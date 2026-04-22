"""
AFV Tracker - Flight routes
POST /api/flights/track      — receive telemetry
POST /api/flights/complete   — log a completed flight
GET  /api/flights/{vatsim_cid} — flight history
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone

from database import get_db, FlightLog, TelemetryRecord, Pilot
from models import TelemetryUpdate, FlightCompleteRequest, FlightLogResponse

router = APIRouter(prefix="/api/flights", tags=["flights"])


@router.post("/track", status_code=202)
def track_telemetry(update: TelemetryUpdate, db: Session = Depends(get_db)):
    """Receive a live telemetry ping from the client."""
    record = TelemetryRecord(
        vatsim_cid=update.vatsim_cid,
        flight_number=update.flight_number,
        phase=update.phase,
        latitude=update.latitude,
        longitude=update.longitude,
        altitude_ft=update.altitude_ft,
        heading_mag=update.heading_mag,
        pitch_deg=update.pitch_deg,
        bank_deg=update.bank_deg,
        groundspeed_kts=update.groundspeed_kts,
        ias_kts=update.ias_kts,
        tas_kts=update.tas_kts,
        mach=update.mach,
        vertical_speed_fpm=update.vertical_speed_fpm,
        eng1_on=update.eng1_on,
        eng2_on=update.eng2_on,
        eng3_on=update.eng3_on,
        eng4_on=update.eng4_on,
        eng1_n1=update.eng1_n1,
        eng2_n1=update.eng2_n1,
        eng3_n1=update.eng3_n1,
        eng4_n1=update.eng4_n1,
        fuel_lbs=update.fuel_lbs,
        fuel_qty_gal=update.fuel_qty_gal,
        autopilot_on=update.autopilot_on,
        autopilot_alt_ft=update.autopilot_alt_ft,
        autopilot_hdg=update.autopilot_hdg,
        flaps_pct=update.flaps_pct,
        gear_down=update.gear_down,
        transponder=update.transponder,
        parking_brake=update.parking_brake,
        lights_strobe=update.lights_strobe,
        lights_landing=update.lights_landing,
        wind_speed_kts=update.wind_speed_kts,
        wind_dir_deg=update.wind_dir_deg,
        oat_celsius=update.oat_celsius,
        qnh_mb=update.qnh_mb,
    )
    db.add(record)
    db.commit()
    return {"status": "recorded"}


@router.post("/complete", response_model=FlightLogResponse, status_code=201)
def complete_flight(req: FlightCompleteRequest, db: Session = Depends(get_db)):
    """Save a completed flight log."""
    # Auto-register pilot if not found
    pilot = db.query(Pilot).filter(Pilot.vatsim_cid == req.vatsim_cid).first()
    if not pilot:
        pilot = Pilot(
            vatsim_cid=req.vatsim_cid,
            name=req.pilot_name or req.vatsim_cid,
        )
        db.add(pilot)
        db.flush()

    def _epoch_to_dt(epoch: float | None) -> datetime | None:
        if epoch is None:
            return None
        return datetime.fromtimestamp(epoch, tz=timezone.utc)

    log = FlightLog(
        vatsim_cid=req.vatsim_cid,
        callsign=req.callsign,
        flight_number=req.flight_number,
        origin=req.origin,
        destination=req.destination,
        aircraft_type=req.aircraft_type,
        departure_time=_epoch_to_dt(req.departure_time),
        arrival_time=_epoch_to_dt(req.arrival_time),
        flight_time_min=req.flight_time_sec / 60.0,
        fuel_used_lbs=req.fuel_used_lbs,
        distance_nm=req.distance_flown_nm,
        landing_rate_fpm=req.landing_rate_fpm,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    return _log_to_response(log)


@router.get("/{vatsim_cid}", response_model=List[FlightLogResponse])
def get_flight_history(
    vatsim_cid: str,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    logs = (
        db.query(FlightLog)
        .filter(FlightLog.vatsim_cid == vatsim_cid)
        .order_by(FlightLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_log_to_response(lg) for lg in logs]


def _log_to_response(lg: FlightLog) -> FlightLogResponse:
    return FlightLogResponse(
        id=lg.id,
        vatsim_cid=lg.vatsim_cid,
        flight_number=lg.flight_number,
        origin=lg.origin,
        destination=lg.destination,
        aircraft_type=lg.aircraft_type,
        departure_time=lg.departure_time,
        arrival_time=lg.arrival_time,
        flight_time_min=round(lg.flight_time_min, 2),
        fuel_used_lbs=round(lg.fuel_used_lbs, 0),
        distance_nm=round(lg.distance_nm, 1),
        landing_rate_fpm=lg.landing_rate_fpm,
    )
