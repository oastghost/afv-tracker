-- ============================================================
-- AFV Tracker — Database restructure (corrected)
-- Current state: afv_pilots already renamed to pilots
--                afv_flight_logs / afv_telemetry / afv_gate_reservations still exist
-- ============================================================


-- ── 1. Drop afv_flight_logs first ────────────────────────────────────────────
-- It has a FK pointing to pilots.pilot_id which blocks the column rename.
-- Table is empty — server will recreate it as flight_logs on next startup.
DROP TABLE afv_flight_logs;


-- ── 2. Restructure pilots ─────────────────────────────────────────────────────
ALTER TABLE pilots
    CHANGE COLUMN pilot_id   vatsim_cid   VARCHAR(20)  NOT NULL,
    ADD    COLUMN simbrief_id              VARCHAR(64)  NULL     AFTER vatsim_cid,
    ADD    COLUMN discord                  VARCHAR(128) NULL     AFTER name,
    DROP   COLUMN email,
    DROP   COLUMN hub_icao;


-- ── 3. telemetry (was afv_telemetry) ─────────────────────────────────────────
RENAME TABLE afv_telemetry TO telemetry;

ALTER TABLE telemetry
    CHANGE COLUMN pilot_id  vatsim_cid  VARCHAR(20)  NOT NULL;


-- ── 4. Drop gate_reservations ─────────────────────────────────────────────────
DROP TABLE afv_gate_reservations;


-- ── 5. Add afv_pilot_id to gates for AFV reservations ────────────────────────
ALTER TABLE gates
    ADD COLUMN afv_pilot_id VARCHAR(20) NULL DEFAULT NULL AFTER aircraft_reg;
