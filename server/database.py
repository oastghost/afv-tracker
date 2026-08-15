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
    ForeignKey, create_engine, PrimaryKeyConstraint, text, inspect,
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
    phase           = Column(String(20), default="UNKNOWN")
    # Position
    latitude        = Column(Float, default=0.0)
    longitude       = Column(Float, default=0.0)
    altitude_ft     = Column(Float, default=0.0)
    # Attitude
    heading_mag     = Column(Float, nullable=True)
    pitch_deg       = Column(Float, nullable=True)
    bank_deg        = Column(Float, nullable=True)
    # Speed
    groundspeed_kts = Column(Float, default=0.0)
    ias_kts         = Column(Float, nullable=True)
    tas_kts         = Column(Float, nullable=True)
    mach            = Column(Float, nullable=True)
    vertical_speed_fpm = Column(Float, nullable=True)
    # Engines
    eng1_on         = Column(Float, nullable=True)   # 0/1 stored as Float for portability
    eng2_on         = Column(Float, nullable=True)
    eng3_on         = Column(Float, nullable=True)
    eng4_on         = Column(Float, nullable=True)
    eng1_n1         = Column(Float, nullable=True)
    eng2_n1         = Column(Float, nullable=True)
    eng3_n1         = Column(Float, nullable=True)
    eng4_n1         = Column(Float, nullable=True)
    # Fuel
    fuel_lbs        = Column(Float, default=0.0)
    fuel_qty_gal    = Column(Float, nullable=True)
    # Systems
    autopilot_on    = Column(Float, nullable=True)
    autopilot_alt_ft = Column(Float, nullable=True)
    autopilot_hdg   = Column(Float, nullable=True)
    flaps_pct       = Column(Float, nullable=True)
    gear_down       = Column(Float, nullable=True)
    transponder     = Column(Integer, nullable=True)
    parking_brake   = Column(Float, nullable=True)
    # Lights
    lights_strobe   = Column(Float, nullable=True)
    lights_landing  = Column(Float, nullable=True)
    # Ambient
    wind_speed_kts  = Column(Float, nullable=True)
    wind_dir_deg    = Column(Float, nullable=True)
    oat_celsius     = Column(Float, nullable=True)
    qnh_mb          = Column(Float, nullable=True)
    recorded_at     = Column(DateTime,
                             default=lambda: datetime.now(timezone.utc))


# ── Init ───────────────────────────────────────────────────────────────────────

# Tables we OWN and auto-create — never touch the friend's gates/aircrafts
_OWN_TABLES = [Pilot, FlightLog, TelemetryRecord]


def _table_exists(name: str) -> bool:
    """True if a table with this name exists in the connected DB."""
    return inspect(engine).has_table(name)


def _ensure_gates_afv_column():
    """Add afv_pilot_id to the shared gates table if it doesn't exist yet."""
    # Migration helper for an existing gates table only — on a fresh local DB
    # the table is created (with the column already present) by init_db, so
    # there is nothing to migrate.
    if not _table_exists("gates"):
        return
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


_TELEMETRY_NEW_COLUMNS = [
    ("heading_mag", "FLOAT"), ("pitch_deg", "FLOAT"), ("bank_deg", "FLOAT"),
    ("ias_kts", "FLOAT"), ("tas_kts", "FLOAT"), ("mach", "FLOAT"),
    ("vertical_speed_fpm", "FLOAT"),
    ("eng1_on", "FLOAT"), ("eng2_on", "FLOAT"), ("eng3_on", "FLOAT"), ("eng4_on", "FLOAT"),
    ("eng1_n1", "FLOAT"), ("eng2_n1", "FLOAT"), ("eng3_n1", "FLOAT"), ("eng4_n1", "FLOAT"),
    ("fuel_qty_gal", "FLOAT"),
    ("autopilot_on", "FLOAT"), ("autopilot_alt_ft", "FLOAT"), ("autopilot_hdg", "FLOAT"),
    ("flaps_pct", "FLOAT"), ("gear_down", "FLOAT"), ("transponder", "INTEGER"),
    ("parking_brake", "FLOAT"),
    ("lights_strobe", "FLOAT"), ("lights_landing", "FLOAT"),
    ("wind_speed_kts", "FLOAT"), ("wind_dir_deg", "FLOAT"),
    ("oat_celsius", "FLOAT"), ("qnh_mb", "FLOAT"),
]


def _ensure_telemetry_columns():
    """Add new telemetry columns to existing telemetry table if absent."""
    if not _table_exists("telemetry"):
        return
    dialect = get_dialect()
    with engine.connect() as conn:
        if dialect == "sqlite":
            result = conn.execute(text("PRAGMA table_info(telemetry)"))
            existing = {row[1] for row in result}
        else:
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'telemetry'"
            ))
            existing = {row[0] for row in result}

        for col_name, col_type in _TELEMETRY_NEW_COLUMNS:
            if col_name not in existing:
                try:
                    conn.execute(text(
                        f"ALTER TABLE telemetry ADD COLUMN {col_name} {col_type}"
                    ))
                    conn.commit()
                except Exception:
                    pass


def init_db():
    """
    Create AFV Tracker's own tables, then run column migrations.

    On a hosted DB (MySQL/Postgres) the friend's gates/aircrafts tables
    already exist and must not be recreated — only _OWN_TABLES are created.
    On a local SQLite DB (the bundled exe) nobody else provides those tables,
    so we create the full schema, including gates/aircrafts, so seed() can
    populate them and the gate/network features work offline.
    """
    for model in _OWN_TABLES:
        model.__table__.create(bind=engine, checkfirst=True)
    if get_dialect() == "sqlite":
        Base.metadata.create_all(bind=engine, checkfirst=True)
    _ensure_gates_afv_column()
    _ensure_telemetry_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
