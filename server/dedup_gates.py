"""
AFV Tracker - Gate deduplication script
---------------------------------------
Finds aircraft registrations that are parked at more than one airport
simultaneously (impossible in reality — stale data) and NULLs them all out
so the gate occupancy can be re-established from the actual sim state.

Works on both the local SQLite dev DB and the hosted MySQL production DB by
introspecting column names at runtime.

Run from the server/ directory:
    python dedup_gates.py           # dry run — shows what would be fixed
    python dedup_gates.py --fix     # apply the changes
"""

import sys
from collections import defaultdict
from database import engine, init_db
from sqlalchemy import text


def _get_columns(conn) -> set[str]:
    """Return the actual column names for the gates table."""
    dialect = engine.dialect.name
    if dialect == "sqlite":
        rows = conn.execute(text("PRAGMA table_info(gates)")).fetchall()
        return {row[1] for row in rows}
    else:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'gates'"
        )).fetchall()
        return {row[0] for row in rows}


def _detect_columns(cols: set[str]) -> tuple[str, str]:
    """
    Return (gate_id_col, reg_col) based on what actually exists in the table.

    SQLite dev DB  : gate_number, occupied_by_flight
    MySQL prod DB  : gate_name,   aircraft_reg
    """
    gate_id_col = "gate_name" if "gate_name" in cols else "gate_number"
    reg_col     = "aircraft_reg" if "aircraft_reg" in cols else "occupied_by_flight"
    return gate_id_col, reg_col


def main():
    dry_run = "--fix" not in sys.argv

    if dry_run:
        print("DRY RUN — pass --fix to apply changes.\n")
    else:
        print("APPLYING FIXES...\n")

    init_db()

    with engine.connect() as conn:
        cols = _get_columns(conn)
        gate_id_col, reg_col = _detect_columns(cols)

        print(f"Schema detected — gate id col: '{gate_id_col}', "
              f"reg col: '{reg_col}'\n")

        # Fetch all gates that have a non-NULL registration
        rows = conn.execute(text(
            f"SELECT airport_icao, {gate_id_col}, {reg_col} "
            f"FROM gates WHERE {reg_col} IS NOT NULL"
        )).fetchall()

        # Group by registration
        by_reg: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for airport_icao, gate_id, reg in rows:
            by_reg[reg].append((airport_icao, gate_id))

        dupes = {reg: locs for reg, locs in by_reg.items() if len(locs) > 1}

        if not dupes:
            print("No duplicate aircraft registrations found. Database is clean.")
            return

        print(f"Found {len(dupes)} registration(s) parked at multiple airports:\n")

        total_gates_affected = 0
        for reg, locations in sorted(dupes.items()):
            airports = ", ".join(f"{icao}/{gate}" for icao, gate in locations)
            print(f"  {reg:10s}  →  {airports}")
            total_gates_affected += len(locations)

            if not dry_run:
                for icao, gate_id in locations:
                    conn.execute(text(
                        f"UPDATE gates SET {reg_col} = NULL, afv_pilot_id = NULL "
                        f"WHERE airport_icao = :icao AND {gate_id_col} = :gate"
                    ), {"icao": icao, "gate": gate_id})

        print(f"\n{total_gates_affected} gate record(s) affected across "
              f"{len(dupes)} registration(s).")

        if dry_run:
            print("\nRe-run with --fix to NULL out all of the above.")
        else:
            conn.commit()
            print("Done. All duplicate gate occupancies have been cleared.")


if __name__ == "__main__":
    main()
