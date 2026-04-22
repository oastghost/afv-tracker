"""
AFV Tracker - Database setup
Connects to the Africana VA MySQL database (hosted via africanava.ddns.net)
or falls back to local SQLite for development.

The Gates and Aircrafts tables are owned by the friend's DB and are NOT
created or seeded by this app — we read/write them as-is.
We do add one column (afv_pilot_id) to gates on first run to track reservations.

Pilots, FlightLogs, and TelemetryRecords are AFV Tracker's own tables
and will be auto-created in the same database on first run.
"""

import os
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Float, DateTime,
    ForeignKey, create_engine, PrimaryKeyConstraint, text,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker, relationship

# ── Connection URL ─────────────────────────────────────────────────────────────

def _build_engine():
    url = os.environ.get("DATABASE_URL", "").strip()

    if not url:
        db_path = Path(os.path.expanduser("~")) / ".afv_tracker" / "afv_tracker.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_path}"

    # Heroku / Railway sometimes export postgres:// — fix it
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)

    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool
        kwargs = {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
    else:
        kwargs = {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_size": 5,
            "max_overflow": 10,
        }

    return create_engine(url, echo=False, **kwargs), url


engine, _DATABASE_URL = _build_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_dialect() -> str:
    return engine.dialect.name


# ── ORM Base ───────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Friend's tables (read/write, never recreated) ──────────────────────────────

class Gate(Base):
    """
    Maps to the existing `gates` table in africana_database.
    Schema (from HeidiSQL):
        airport_icao  VARCHAR(10)
        gate_name     VARCHAR(10)
        size_category ENUM('Light','Medium','Heavy','Jumbo')
        flight_type   ENUM('National','International','Remote')
        aircraft_reg  VARCHAR(10) FK → aircrafts.aircraft_reg  (NULL = gate free)
        occupied      TINYINT(1)  VIRTUAL GENERATED (aircraft_reg IS NOT NULL)
                                  ← we never write this column
        afv_pilot_id  VARCHAR(20) ← added by AFV Tracker; stores VATSIM CID when reserved
    """
    __tablename__ = "gates"
    __table_args__ = (
        PrimaryKeyConstraint("airport_icao", "gate_name"),
        {"extend_existing": True},
    )

    airport_icao  = Column(String(10), nullable=True)
    gate_name     = Column(String(10), nullable=True)
    size_category = Column(String(10), nullable=False)   # Light / Medium / Heavy / Jumbo
    flight_type   = Column(String(20), nullable=True)    # National / International / Remote
    aircraft_reg  = Column(String(10), nullable=True)    # NULL = physically free
    afv_pilot_id  = Column(String(20), nullable=True)    # NULL = AFV-unreserved


class Aircraft(Base):
    """
    Maps to the existing `aircrafts` table.
    aircraft_reg  VARCHAR(10) PK
    aircraft_type VARCHAR(5)  ICAO type code (e.g. B738, A388)
    aircraft_category ENUM('Light','Medium','Heavy','Jumbo')
    """
    __tablename__ = "aircrafts"
    __table_args__ = {"extend_existing": True}

    aircraft_reg      = Column(String(10), primary_key=True)
    aircraft_type     = Column(String(5),  nullable=True)
    aircraft_category = Column(String(10), nullable=False)


# ── AFV Tracker's own tables (auto-created) ───────────────────────────────────

class Pilot(Base):
    __tablename__ = "pilots"

    id          = Column(Integer, primary_key=True, index=True)
    vatsim_cid  = Column(String(20),  unique=True, index=True, nullable=False)
    simbrief_id = Column(String(64),  nullable=True)
    name        = Column(String(128), nullable=False)
    discord     = Column(String(128), nullable=True)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    flights = relationship("FlightLog", back_populates="pilot_rel", lazy="dynamic")


class FlightLog(Base):
    __tablename__ = "flight_logs"

    id               = Column(Integer, primary_key=True, index=True)
    vatsim_cid       = Column(String(20), ForeignKey("pilots.vatsim_cid"),
                              nullable=False, index=True)
    callsign         = Column(String(20),  nullable=True)
    flight_number    = Column(String(20),  nullable=True)
    origin           = Column(String(4),   nullable=False)
    destination      = Column(String(4),   nullable=False)
    aircraft_type    = Column(String(10),  nullable=False)
    aircraft_reg     = Column(String(10),  nullable=True)
    departure_time   = Column(DateTime,    nullable=True)
    arrival_time     = Column(DateTime,    nullable=True)
    flight_time_min  = Column(Float,       default=0.0)
    fuel_used_lbs    = Column(Float,       default=0.0)
    distance_nm      = Column(Float,       default=0.0)
    landing_rate_fpm = Column(Float,       nullable=True)
    gate_assigned    = Column(String(20),  nullable=True)
    created_at       = Column(DateTime,    default=lambda: datetime.now(timezone.utc))

    pilot_rel = relationship("Pilot", back_populates="flights")


class TelemetryRecord(Base):
    __tablename__ = "telemetry"

    id              = Column(Integer, primary_key=True, index=True)
    vatsim_cid      = Column(String(20), index=True, nullable=False)
    flight_number   = Column(String(20), nullable=True)
    latitude        = Column(Float,  default=0.0)
    longitude       = Column(Float,  default=0.0)
    altitude_ft     = Column(Float,  default=0.0)
    groundspeed_kts = Column(Float,  default=0.0)
    fuel_lbs        = Column(Float,  default=0.0)
    phase           = Column(String(20), default="UNKNOWN")
    recorded_at     = Column(DateTime,
                             default=lambda: datetime.now(timezone.utc))


# ── Init ───────────────────────────────────────────────────────────────────────

# Tables we OWN and auto-create — never touch the friend's gates/aircrafts
_OWN_TABLES = [Pilot, FlightLog, TelemetryRecord]


def _ensure_gates_afv_column():
    """Add afv_pilot_id to the shared gates table if it doesn't exist yet."""
    dialect = get_dialect()
    with engine.connect() as conn:
        if dialect == "sqlite":
            result = conn.execute(text("PRAGMA table_info(gates)"))
            columns = [row[1] for row in result]
            if "afv_pilot_id" not in columns:
                conn.execute(text(
                    "ALTER TABLE gates ADD COLUMN afv_pilot_id VARCHAR(20)"
                ))
                conn.commit()
        else:  # MySQL / MariaDB / PostgreSQL
            try:
                conn.execute(text(
                    "ALTER TABLE gates "
                    "ADD COLUMN afv_pilot_id VARCHAR(20) NULL DEFAULT NULL"
                ))
                conn.commit()
            except Exception:
                pass  # Column already exists — fine


def init_db():
    """Create AFV Tracker's own tables. Add afv_pilot_id to gates if absent."""
    for model in _OWN_TABLES:
        model.__table__.create(bind=engine, checkfirst=True)
    _ensure_gates_afv_column()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
