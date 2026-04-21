"""
AFV Tracker — Gate Import Tool
Imports gate data from your friend's external database into the AFV Tracker schema.

Usage:
  1. Fill in the SOURCE_DATABASE_URL below (your friend's HeidiSQL connection)
  2. Fill in the table/column names that match their schema
  3. Run: python import_gates.py

The script reads from their DB and writes into whichever DB is set in DATABASE_URL
(or local SQLite if not set).
"""

import os
import sys

# ── Configure these to match your friend's database ───────────────────────────

SOURCE_DATABASE_URL = (
    # Example: "mysql+pymysql://user:password@hostname:3306/their_database"
    os.environ.get("SOURCE_DATABASE_URL", "")
)

# Their table and column names — update these to match their actual schema
SOURCE_TABLE   = "gates"           # their table name
COL_AIRPORT    = "airport_icao"    # ICAO code column (e.g. "FAOR")
COL_GATE       = "gate_number"     # gate identifier (e.g. "A1", "B7")
COL_TERMINAL   = "terminal"        # terminal name/number (can be "" if they don't have one)
COL_SIZE       = "gate_size"       # S / M / L / H  (or map from their naming below)

# If their size column uses different values, map them here:
SIZE_MAP = {
    # Their value  →  AFV value
    "small":    "S",
    "medium":   "M",
    "large":    "L",
    "heavy":    "H",
    "S": "S", "M": "M", "L": "L", "H": "H",   # passthrough if already correct
}

# ─────────────────────────────────────────────────────────────────────────────

def run():
    if not SOURCE_DATABASE_URL:
        print("ERROR: Set SOURCE_DATABASE_URL to your friend's connection string.")
        print("  export SOURCE_DATABASE_URL=mysql+pymysql://user:pass@host:3306/dbname")
        sys.exit(1)

    from sqlalchemy import create_engine, text
    from database import SessionLocal, init_db, Gate

    print(f"Connecting to source DB…")
    src_engine = create_engine(SOURCE_DATABASE_URL, pool_pre_ping=True)

    with src_engine.connect() as conn:
        rows = conn.execute(text(f"SELECT * FROM {SOURCE_TABLE}")).mappings().all()
    print(f"  Found {len(rows)} gates in source database.")

    init_db()
    db = SessionLocal()

    imported = 0
    skipped  = 0
    errors   = 0

    for row in rows:
        try:
            airport = str(row[COL_AIRPORT]).upper().strip()
            gate_num = str(row[COL_GATE]).strip()
            terminal = str(row.get(COL_TERMINAL) or "").strip()
            raw_size = str(row.get(COL_SIZE) or "M").strip()
            size = SIZE_MAP.get(raw_size, "M")

            # Skip if this gate already exists
            existing = db.query(Gate).filter(
                Gate.airport_icao == airport,
                Gate.gate_number  == gate_num,
            ).first()

            if existing:
                skipped += 1
                continue

            db.add(Gate(
                airport_icao=airport,
                gate_number=gate_num,
                terminal=terminal,
                gate_size=size,
                is_available=True,
            ))
            imported += 1

        except Exception as e:
            print(f"  ERR row {dict(row)}: {e}")
            errors += 1

    db.commit()
    db.close()

    print(f"\nDone — imported: {imported}  skipped: {skipped}  errors: {errors}")
    total = db.query(Gate).count() if False else imported + skipped
    print(f"Total gates in AFV DB: {imported + skipped}")


if __name__ == "__main__":
    run()
