"""
AFV Tracker - Gate routes

Uses the Africana VA database for gate definitions and writes directly to the
gates.afv_pilot_id column to track pilot reservations — no separate reservation
table needed.

A gate is unavailable when EITHER:
  - gates.aircraft_reg IS NOT NULL  (real aircraft physically parked there), OR
  - gates.afv_pilot_id IS NOT NULL  (an AFV pilot has reserved it)

Size mapping (their enum -> our S/M/L/H):
  Light  -> S  |  Medium -> M  |  Heavy -> L  |  Jumbo -> H
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from database import get_db, Gate, Aircraft
from models import GateResponse, GateAssignmentResponse
from websocket_manager import broadcast_sync

router = APIRouter(prefix="/api/gates", tags=["gates"])

# ── Size helpers ───────────────────────────────────────────────────────────────

THEIR_TO_OURS = {"Light": "S", "Medium": "M", "Heavy": "L", "Jumbo": "H"}
OURS_TO_THEIRS = {v: k for k, v in THEIR_TO_OURS.items()}

AIRCRAFT_TYPE_SIZE: dict[str, str] = {
    "AT76": "S", "AT75": "S", "DH8D": "S", "DH8C": "S",
    "E145": "S", "E135": "S", "SF34": "S", "C208": "S", "C207": "S",
    "B737": "M", "B738": "M", "B739": "M", "B73G": "M",
    "A318": "M", "A319": "M", "A320": "M", "A321": "M",
    "E190": "M", "E195": "M", "CRJ9": "M", "CRJ7": "M",
    "B752": "M", "B753": "M",
    "MD11": "L", "B787": "L", "B788": "L", "B789": "L", "B78X": "L",
    "B763": "L", "B764": "L", "B762": "L",
    "A330": "L", "A332": "L", "A333": "L", "A339": "L",
    "A350": "L", "A359": "L", "A35K": "L", "A346": "L",
    "B77W": "L", "B773": "L", "B772": "L",
    "B744": "H", "B74S": "H", "A388": "H", "A380": "H",
}

SIZE_ORDER = {"S": 0, "M": 1, "L": 2, "H": 3}


def _get_aircraft_size(aircraft_type: str, db: Session) -> str:
    ac = db.query(Aircraft).filter(
        Aircraft.aircraft_type == aircraft_type.upper()
    ).first()
    if ac:
        return THEIR_TO_OURS.get(ac.aircraft_category, "M")
    return AIRCRAFT_TYPE_SIZE.get(aircraft_type.upper(), "M")


def _compatible_their_sizes(our_size: str) -> list[str]:
    idx = SIZE_ORDER.get(our_size, 1)
    return [OURS_TO_THEIRS[s] for s, i in SIZE_ORDER.items()
            if i >= idx and s in OURS_TO_THEIRS]


def _gate_available(gate: Gate) -> bool:
    """Gate is free if neither physically occupied nor AFV-reserved."""
    return gate.aircraft_reg is None and gate.afv_pilot_id is None


def _gate_to_response(gate: Gate) -> GateResponse:
    return GateResponse(
        id=None,
        airport_icao=gate.airport_icao,
        gate_number=gate.gate_name,
        terminal=gate.flight_type or "",
        gate_size=THEIR_TO_OURS.get(gate.size_category, "M"),
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
    pilot_id:      str = Query(default=""),   # VATSIM CID
    pilot_name:    str = Query(default=""),
    aircraft_reg:  str = Query(default=""),   # registration from SimBrief (e.g. C9-AIA)
    db: Session = Depends(get_db),
):
    icao     = airport_icao.upper()
    ac_type  = aircraft_type.upper()
    our_size = _get_aircraft_size(ac_type, db)

    # Check if this pilot already has a gate here — return it
    if pilot_id:
        existing = db.query(Gate).filter(
            Gate.airport_icao == icao,
            Gate.afv_pilot_id == pilot_id,
        ).first()
        if existing:
            return GateAssignmentResponse(
                airport_icao=icao,
                gate_number=existing.gate_name,
                terminal=existing.flight_type or "",
                gate_size=THEIR_TO_OURS.get(existing.size_category, "M"),
                fallback=False,
                message="Previously assigned gate.",
            )

    # Get all gates at this airport
    all_gates = db.query(Gate).filter(Gate.airport_icao == icao).all()

    # Try exact size first
    their_exact = OURS_TO_THEIRS.get(our_size, "Medium")
    gate = next(
        (g for g in all_gates
         if g.size_category == their_exact and _gate_available(g)),
        None
    )

    fallback = False
    if not gate:
        compat = _compatible_their_sizes(our_size)
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
            gate_size=our_size,
            fallback=True,
            message="No gates available. Contact ground for manual assignment.",
        )

    # Lock the gate.
    # Preferred: write aircraft_reg to gates.aircraft_reg so the existing
    # virtual `occupied` column (aircraft_reg IS NOT NULL) reflects it immediately.
    # Fallback: use afv_pilot_id only (if the registration isn't in the aircrafts table).
    gate.afv_pilot_id = pilot_id or None

    reg = aircraft_reg.strip().upper() if aircraft_reg else None
    if reg:
        ac_in_db = db.query(Aircraft).filter(Aircraft.aircraft_reg == reg).first()
        if ac_in_db:
            gate.aircraft_reg = reg   # locks via the virtual occupied column
        else:
            import logging
            logging.getLogger(__name__).warning(
                "Reg %s not in aircrafts table — gate locked via afv_pilot_id only", reg
            )

    db.commit()

    msg = (f"No {their_exact} gate available; assigned {gate.size_category} gate instead."
           if fallback else None)

    try:
        broadcast_sync({
            "event": "gate_assigned",
            "data": {
                "airport":     icao,
                "gate_number": gate.gate_name,
                "terminal":    gate.flight_type or "",
                "gate_size":   THEIR_TO_OURS.get(gate.size_category, "M"),
                "pilot_id":    pilot_id,
                "pilot_name":  pilot_name or pilot_id,
            },
        })
    except Exception:
        pass  # broadcast failure must never break the gate assignment

    return GateAssignmentResponse(
        airport_icao=icao,
        gate_number=gate.gate_name,
        terminal=gate.flight_type or "",
        gate_size=THEIR_TO_OURS.get(gate.size_category, "M"),
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

    # Clear both the AFV reservation tag and the physical aircraft_reg lock
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
