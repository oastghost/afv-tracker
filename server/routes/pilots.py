"""
AFV Tracker - Pilot routes
POST /api/pilots/register
GET  /api/pilots/online     ← must be before /{vatsim_cid} to avoid route shadowing
GET  /api/pilots/{vatsim_cid}
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db, Pilot, FlightLog
from models import PilotRegisterRequest, PilotResponse
from websocket_manager import manager

router = APIRouter(prefix="/api/pilots", tags=["pilots"])


@router.post("/register", response_model=PilotResponse, status_code=200)
def register_pilot(req: PilotRegisterRequest, db: Session = Depends(get_db)):
    """Create or update a pilot record (upsert)."""
    pilot = db.query(Pilot).filter(Pilot.vatsim_cid == req.vatsim_cid).first()
    if pilot:
        pilot.simbrief_id = req.simbrief_id
        pilot.name        = req.name
        pilot.discord     = req.discord
    else:
        pilot = Pilot(
            vatsim_cid=req.vatsim_cid,
            simbrief_id=req.simbrief_id,
            name=req.name,
            discord=req.discord,
        )
        db.add(pilot)
    db.commit()
    db.refresh(pilot)
    return _to_response(pilot, db)


@router.get("/online")
def get_online_pilots():
    """Returns all pilots currently connected via WebSocket."""
    return {
        "count": manager.get_connection_count(),
        "pilots": manager.get_online_pilots(),
    }


@router.get("/{vatsim_cid}", response_model=PilotResponse)
def get_pilot(vatsim_cid: str, db: Session = Depends(get_db)):
    pilot = db.query(Pilot).filter(Pilot.vatsim_cid == vatsim_cid).first()
    if not pilot:
        raise HTTPException(status_code=404, detail="Pilot not found.")
    return _to_response(pilot, db)


def _to_response(pilot: Pilot, db: Session) -> PilotResponse:
    logs = db.query(FlightLog).filter(FlightLog.vatsim_cid == pilot.vatsim_cid).all()
    total_hours = sum(lg.flight_time_min for lg in logs) / 60.0
    return PilotResponse(
        id=pilot.id,
        vatsim_cid=pilot.vatsim_cid,
        simbrief_id=pilot.simbrief_id,
        name=pilot.name,
        discord=pilot.discord,
        total_flights=len(logs),
        total_hours=round(total_hours, 1),
        created_at=pilot.created_at,
    )
