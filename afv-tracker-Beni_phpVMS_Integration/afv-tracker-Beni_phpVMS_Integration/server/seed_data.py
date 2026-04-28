"""
AFV Tracker - Database seeding
Populates gate data for AFV hub airports.
Run directly: python seed_data.py
"""

from database import SessionLocal, init_db, Gate

# Gate definitions: (airport_icao, gate_number, terminal, size)
# Size: S=small, M=medium, L=large, H=heavy

GATES = [
    # ── FTTG — N'Djamena International ────────────────────────────────────────
    ("FTTG", "A1", "A", "M"),
    ("FTTG", "A2", "A", "M"),
    ("FTTG", "A3", "A", "S"),
    ("FTTG", "A4", "A", "S"),
    ("FTTG", "B1", "B", "L"),
    ("FTTG", "B2", "B", "M"),
    ("FTTG", "C1", "Cargo", "H"),

    # ── FACT — Cape Town International ────────────────────────────────────────
    ("FACT", "A1", "A", "M"),
    ("FACT", "A2", "A", "M"),
    ("FACT", "A3", "A", "M"),
    ("FACT", "A4", "A", "L"),
    ("FACT", "A5", "A", "L"),
    ("FACT", "B1", "B", "S"),
    ("FACT", "B2", "B", "S"),
    ("FACT", "B3", "B", "M"),
    ("FACT", "C1", "C", "H"),
    ("FACT", "C2", "C", "L"),

    # ── FAOR — O.R. Tambo International, Johannesburg ──────────────────────────
    ("FAOR", "A1", "A", "H"),
    ("FAOR", "A2", "A", "H"),
    ("FAOR", "A3", "A", "L"),
    ("FAOR", "A4", "A", "L"),
    ("FAOR", "B1", "B", "L"),
    ("FAOR", "B2", "B", "L"),
    ("FAOR", "B3", "B", "M"),
    ("FAOR", "B4", "B", "M"),
    ("FAOR", "C1", "C", "M"),
    ("FAOR", "C2", "C", "M"),
    ("FAOR", "C3", "C", "S"),
    ("FAOR", "C4", "C", "S"),
    ("FAOR", "D1", "D", "H"),

    # ── FMMI — Ivato International, Antananarivo ───────────────────────────────
    ("FMMI", "1",  "Main", "L"),
    ("FMMI", "2",  "Main", "M"),
    ("FMMI", "3",  "Main", "M"),
    ("FMMI", "4",  "Main", "S"),
    ("FMMI", "5",  "Main", "S"),

    # ── HTDA — Julius Nyerere International, Dar es Salaam ────────────────────
    ("HTDA", "A1", "A", "L"),
    ("HTDA", "A2", "A", "L"),
    ("HTDA", "A3", "A", "M"),
    ("HTDA", "A4", "A", "M"),
    ("HTDA", "B1", "B", "M"),
    ("HTDA", "B2", "B", "S"),
    ("HTDA", "B3", "B", "S"),

    # ── FQMA — Maputo International ───────────────────────────────────────────
    ("FQMA", "1",  "Main", "M"),
    ("FQMA", "2",  "Main", "M"),
    ("FQMA", "3",  "Main", "L"),
    ("FQMA", "4",  "Main", "S"),
    ("FQMA", "5",  "Main", "S"),

    # ── FALA — Lanseria International ─────────────────────────────────────────
    ("FALA", "A1", "A", "M"),
    ("FALA", "A2", "A", "M"),
    ("FALA", "A3", "A", "S"),
    ("FALA", "B1", "B", "L"),
    ("FALA", "B2", "B", "M"),

    # ── HAAB — Addis Ababa Bole International ─────────────────────────────────
    ("HAAB", "T1-1", "T1", "H"),
    ("HAAB", "T1-2", "T1", "H"),
    ("HAAB", "T1-3", "T1", "L"),
    ("HAAB", "T1-4", "T1", "L"),
    ("HAAB", "T2-1", "T2", "M"),
    ("HAAB", "T2-2", "T2", "M"),
    ("HAAB", "T2-3", "T2", "S"),

    # ── DNMM — Murtala Muhammed International, Lagos ──────────────────────────
    ("DNMM", "A1", "A", "H"),
    ("DNMM", "A2", "A", "L"),
    ("DNMM", "A3", "A", "L"),
    ("DNMM", "B1", "B", "M"),
    ("DNMM", "B2", "B", "M"),
    ("DNMM", "B3", "B", "S"),

    # ── HKJK — Jomo Kenyatta International, Nairobi ───────────────────────────
    ("HKJK", "1A", "1", "H"),
    ("HKJK", "1B", "1", "L"),
    ("HKJK", "2A", "2", "M"),
    ("HKJK", "2B", "2", "M"),
    ("HKJK", "3A", "3", "S"),
    ("HKJK", "3B", "3", "S"),

    # ── DTTA — Tunis-Carthage International ───────────────────────────────────
    ("DTTA", "A1", "A", "L"),
    ("DTTA", "A2", "A", "M"),
    ("DTTA", "B1", "B", "M"),
    ("DTTA", "B2", "B", "S"),

    # ── HECA — Cairo International ────────────────────────────────────────────
    ("HECA", "T1-A", "T1", "H"),
    ("HECA", "T1-B", "T1", "L"),
    ("HECA", "T2-A", "T2", "M"),
    ("HECA", "T2-B", "T2", "M"),
    ("HECA", "T3-A", "T3", "L"),
    ("HECA", "T3-B", "T3", "M"),

    # ── GOBD — Blaise Diagne International, Dakar ─────────────────────────────
    ("GOBD", "A1", "A", "L"),
    ("GOBD", "A2", "A", "M"),
    ("GOBD", "B1", "B", "M"),
    ("GOBD", "B2", "B", "S"),
]


_SIZE_TO_CATEGORY = {"S": "Light", "M": "Medium", "L": "Heavy", "H": "Jumbo"}


def seed():
    init_db()

    from database import get_dialect
    if get_dialect() != "sqlite":
        # Using the Africana VA hosted database — gate data already exists there
        db = SessionLocal()
        count = db.query(Gate).count()
        db.close()
        print(f"Using hosted DB — {count} gates already present, skipping seed.")
        return

    db = SessionLocal()
    try:
        existing = db.query(Gate).count()
        if existing > 0:
            print(f"Database already has {existing} gates — skipping seed.")
            return

        gates = [
            Gate(
                airport_icao=airport,
                gate_name=gate_num,
                flight_type=terminal,
                size_category=_SIZE_TO_CATEGORY[size],
            )
            for airport, gate_num, terminal, size in GATES
        ]
        db.bulk_save_objects(gates)
        db.commit()
        print(f"Seeded {len(gates)} gates across {len({g[0] for g in GATES})} airports.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
