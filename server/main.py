"""
AFV Tracker - FastAPI Backend Server
Run: uvicorn main:app --reload --port 8000

Environment variables (put in .env or set in your hosting platform):
  DATABASE_URL   — database connection string (see database.py for examples)
  PORT           — port to listen on (Railway sets this automatically)
"""

import asyncio
import json
import logging
import os

# Load .env file if present (local dev convenience)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database import init_db, get_dialect, _DATABASE_URL, SessionLocal, Gate
from seed_data import seed
from routes import flights, gates, pilots
from websocket_manager import manager, broadcast_sync

log = logging.getLogger(__name__)

app = FastAPI(
    title="Africana Virtual Airways — Flight Tracker API",
    description="Backend API for the AFV Flight Tracker desktop app.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(flights.router)
app.include_router(gates.router)
app.include_router(pilots.router)


@app.on_event("startup")
async def on_startup():
    init_db()
    seed()
    manager.loop = asyncio.get_event_loop()
    dialect = get_dialect()
    # Mask password in log output
    safe_url = _DATABASE_URL.split("@")[-1] if "@" in _DATABASE_URL else _DATABASE_URL
    print(f"  AFV Tracker API ready")
    print(f"  DB: {dialect.upper()} -> {safe_url}")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "AFV Tracker API",
        "pilots_online": manager.get_connection_count(),
    }


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

@app.websocket("/ws/{pilot_id}")
async def websocket_endpoint(ws: WebSocket, pilot_id: str):
    await manager.connect(pilot_id, ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event = msg.get("event")
            data  = msg.get("data", {})

            if event == "ping":
                await ws.send_json({"event": "pong"})

            elif event == "pilot_update":
                # Enforce server-side pilot_id (can't spoof someone else)
                data["pilot_id"] = pilot_id
                manager.update_roster(pilot_id, data)
                # Broadcast to everyone except the sender
                await manager.broadcast(
                    {"event": "pilot_update", "data": data},
                    exclude=pilot_id,
                )

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("WS error for %s: %s", pilot_id, exc)
    finally:
        await manager.disconnect(pilot_id)
        await manager.broadcast(
            {"event": "pilot_offline", "data": {"pilot_id": pilot_id}}
        )
        # Auto-release any gate reservations held by this pilot
        _release_pilot_gates(pilot_id)
        log.info("WS session ended for %s", pilot_id)


def _release_pilot_gates(vatsim_cid: str):
    """Release all gate reservations for a pilot and broadcast each release."""
    db = SessionLocal()
    try:
        reserved_gates = (
            db.query(Gate)
            .filter(Gate.afv_pilot_id == vatsim_cid)
            .all()
        )
        for gate in reserved_gates:
            icao = gate.airport_icao
            name = gate.gate_name
            gate.afv_pilot_id = None
            gate.aircraft_reg = None   # clear the physical lock too
            broadcast_sync({
                "event": "gate_released",
                "data": {"airport": icao, "gate_number": name},
            })
            log.info("Auto-released gate %s/%s for disconnected pilot %s",
                     icao, name, vatsim_cid)
        db.commit()
    except Exception as exc:
        log.warning("Failed to auto-release gates for %s: %s", vatsim_cid, exc)
        db.rollback()
    finally:
        db.close()
