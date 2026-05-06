"""
AFV Tracker - Gate routes

Uses the Africana VA database for gate definitions and writes directly to the
gates.afv_pilot_id column to track pilot reservations — no separate reservation
table needed.

A gate is unavailable when EITHER:
  - gates.aircraft_reg IS NOT NULL  (real aircraft physically parked there), OR
  - gates.afv_pilot_id IS NOT NULL  (an AFV pilot has reserved it)

Gate/aircraft size categories (from the DB ENUM):
  Light | Medium | Heavy | Jumbo
These are used directly throughout — no translation layer.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from database import get_db, Gate, Aircraft
from models import GateResponse, GateAssignmentResponse
from websocket_manager import broadcast_sync

router = APIRouter(prefix="/api/gates", tags=["gates"])

# ── Size helpers ───────────────────────────────────────────────────────────────

# Maps aircraft ICAO type → DB size category (fallback when not in the aircrafts table)
AIRCRAFT_TYPE_SIZE: dict[str, str] = {
    # Light (turboprops / small piston)
    "AT76": "Light", "AT75": "Light", "DH8D": "Light", "DH8C": "Light",
    "DH8B": "Light", "DH8A": "Light",
    "E145": "Light", "E135": "Light", "SF34": "Light",
    "C208": "Light", "C207": "Light", "C182": "Light",
    "PC12": "Light", "TBM9": "Light", "BE9L": "Light", "BE20": "Light",
    # Medium (narrowbody)
    "B737": "Medium", "B738": "Medium", "B739": "Medium", "B73G": "Medium",
    "B733": "Medium", "B734": "Medium", "B735": "Medium",
    "B752": "Medium", "B753": "Medium",
    "A318": "Medium", "A319": "Medium", "A320": "Medium", "A321": "Medium",
    "E170": "Medium", "E190": "Medium", "E195": "Medium",
    "E75L": "Medium", "E75S": "Medium",
    "CRJ9": "Medium", "CRJ7": "Medium",
    # Heavy (widebody)
    "B787": "Heavy", "B788": "Heavy", "B789": "Heavy", "B78X": "Heavy",
    "B763": "Heavy", "B764": "Heavy", "B762": "Heavy",
    "A330": "Heavy", "A332": "Heavy", "A333": "Heavy", "A339": "Heavy",
    "A350": "Heavy", "A359": "Heavy", "A35K": "Heavy",
    "A342": "Heavy", "A343": "Heavy", "A346": "Heavy",
    "B77W": "Heavy", "B773": "Heavy", "B772": "Heavy",
    "MD11": "Heavy",
    # Jumbo
    "B744": "Jumbo", "B74S": "Jumbo", "B74D": "Jumbo",
    "A388": "Jumbo", "A380": "Jumbo",
    "A124": "Jumbo", "C17":  "Jumbo",
}

# Ordered smallest → largest; used for compatibility fallback logic
SIZE_ORDER = {"Light": 0, "Medium": 1, "Heavy": 2, "Jumbo": 3}


def _get_aircraft_size(aircraft_type: str, db: Session) -> str:
    """Return the DB size category for an aircraft type.
    Prefers the aircrafts table; falls back to the static map; defaults to Medium."""
    ac = db.query(Aircraft).filter(
        Aircraft.aircraft_type == aircraft_type.upper()
    ).first()
    if ac and ac.aircraft_category in SIZE_ORDER:
        return ac.aircraft_category
    return AIRCRAFT_TYPE_SIZE.get(aircraft_type.upper(), "Medium")


def _compatible_sizes(aircraft_size: str) -> list[str]:
    """Return all gate size categories that can accommodate this aircraft
    (i.e. same size or larger)."""
    idx = SIZE_ORDER.get(aircraft_size, 1)
    return [s for s, i in SIZE_ORDER.items() if i >= idx]


def _gate_available(gate: Gate) -> bool:
    """Gate is free if neither physically occupied nor AFV-reserved."""
    return gate.aircraft_reg is None and gate.afv_pilot_id is None


def _gate_to_response(gate: Gate) -> GateResponse:
    return GateResponse(
        id=None,
        airport_icao=gate.airport_icao,
        gate_number=gate.gate_name,
        terminal=gate.flight_type or "",
        gate_size=gate.size_category,
        is_available=_gate_available(gate),
    )


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/{airport_icao}", response_model=List[GateResponse])
def list_gates(airport_icao: str, db: Session = Depends(get_db)):
    icao = airport_icao.upper()
    gates = db.query(Gate).filter(
        Gate.airport_icao == icao
    ).order_by(Gate.gate_name).all()

    if not gates:
        raise HTTPException(
            status_code=404,
            detail=f"No gates found for {icao}."
        )

    return [_gate_to_response(g) for g in gates]


@router.get("/{airport_icao}/assign", response_model=GateAssignmentResponse)
def assign_gate(
    airport_icao:  str,
    aircraft_type: str = Query(...),
    pilot_id:      str = Query(default=""),
    pilot_name:    str = Query(default=""),
    aircraft_reg:  str = Query(default=""),
    db: Session = Depends(get_db),
):
    icao     = airport_icao.upper()
    ac_type  = aircraft_type.upper()
    ac_size  = _get_aircraft_size(ac_type, db)

    # Check if this pilot already has a gate here — return it if still usable
    if pilot_id:
        existing = db.query(Gate).filter(
            Gate.airport_icao == icao,
            Gate.afv_pilot_id == pilot_id,
        ).first()
        if existing:
            my_reg = aircraft_reg.strip().upper() if aircraft_reg else None
            physically_clear = (existing.aircraft_reg is None
                                or existing.aircraft_reg == my_reg)
            if physically_clear:
                return GateAssignmentResponse(
                    airport_icao=icao,
                    gate_number=existing.gate_name,
                    terminal=existing.flight_type or "",
                    gate_size=existing.size_category,
                    fallback=False,
                    message="Previously assigned gate.",
                )
            # Physical aircraft blocking our old gate — clear and find a new one
            existing.afv_pilot_id = None
            db.commit()

    all_gates = db.query(Gate).filter(Gate.airport_icao == icao).all()

    # Try exact size first
    gate = next(
        (g for g in all_gates
         if g.size_category == ac_size and _gate_available(g)),
        None
    )

    fallback = False
    if not gate:
        compat = _compatible_sizes(ac_size)
        gate = next(
            (g for g in all_gates
             if g.size_category in compat and _gate_available(g)),
            None
        )
        if gate:
            fallback = True

    if not gate:
        return GateAssignmentResponse(
            airport_icao=icao,
            gate_number="CONTACT GROUND",
            terminal="",
            gate_size=ac_size,
            fallback=True,
            message="No gates available. Park at own discretion and advise on Discord.",
        )

    # Lock the gate
    reg   = aircraft_reg.strip().upper() if aircraft_reg else None
    _lock = pilot_id.strip() if pilot_id else None
    gate.afv_pilot_id = _lock or reg or f"LOCK:{icao}:{gate.gate_name}"

    if reg:
        ac_in_db = db.query(Aircraft).filter(Aircraft.aircraft_reg == reg).first()
        if ac_in_db:
            gate.aircraft_reg = reg
        else:
            import logging
            logging.getLogger(__name__).warning(
                "Reg %s not in aircrafts table — gate locked via afv_pilot_id only", reg
            )

    db.commit()

    msg = (f"No {ac_size} gate available; assigned {gate.size_category} gate instead."
           if fallback else None)

    try:
        broadcast_sync({
            "event": "gate_assigned",
            "data": {
                "airport":     icao,
                "gate_number": gate.gate_name,
                "terminal":    gate.flight_type or "",
                "gate_size":   gate.size_category,
                "pilot_id":    pilot_id,
                "pilot_name":  pilot_name or pilot_id,
            },
        })
    except Exception:
        pass

    return GateAssignmentResponse(
        airport_icao=icao,
        gate_number=gate.gate_name,
        terminal=gate.flight_type or "",
        gate_size=gate.size_category,
        fallback=fallback,
        message=msg,
    )


@router.post("/{airport_icao}/{gate_name}/release")
def release_gate(
    airport_icao: str,
    gate_name: str,
    db: Session = Depends(get_db),
):
    gate = db.query(Gate).filter(
        Gate.airport_icao == airport_icao.upper(),
        Gate.gate_name    == gate_name,
    ).first()

    if not gate or gate.afv_pilot_id is None:
        raise HTTPException(status_code=404,
                            detail="No AFV reservation found for this gate.")

    gate.afv_pilot_id = None
    gate.aircraft_reg = None
    db.commit()

    try:
        broadcast_sync({
            "event": "gate_released",
            "data": {"airport": airport_icao.upper(), "gate_number": gate_name},
        })
    except Exception:
        pass
    return {"status": "released", "gate_number": gate_name}
