"""
One-shot script: clears aircraft_reg and afv_pilot_id from all gates,
leaving the gate records themselves intact.

Run from the server/ directory:
    python clear_gate_occupancy.py
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from database import SessionLocal, engine
from sqlalchemy import text

def main():
    with engine.connect() as conn:
        result = conn.execute(
            text("UPDATE gates SET aircraft_reg = NULL, afv_pilot_id = NULL")
        )
        conn.commit()
        print(f"Cleared {result.rowcount} gate(s). Gates themselves are untouched.")

if __name__ == "__main__":
    main()
