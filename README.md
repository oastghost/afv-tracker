# Africana Virtual Airways — Flight Tracker

Desktop flight tracking application for AFV pilots flying in Microsoft Flight Simulator 2024.

## Features

- **SimBrief integration** — fetches your latest OFP automatically
- **Live MSFS telemetry** via SimConnect — altitude, speed, fuel, flight phase
- **Automatic flight phase detection** — Pre-flight → Taxi → Climb → Cruise → Approach → Landing → Parked
- **Gate assignment** — assigned automatically when you enter APPROACH phase
- **Flight logging** — every completed flight is saved locally and synced to the backend
- **Dark aviation UI** — AFV red, black, and white theme; cockpit-style layout

---

## Requirements

- Python 3.11+
- Microsoft Flight Simulator 2024 (for SimConnect)
- SimConnect SDK (installed with MSFS)

---

## Setup

### 1. Clone / download the project

```
afv-tracker/
├── client/
├── server/
├── requirements.txt
└── README.md
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `SimConnect` (pip package) requires the SimConnect SDK DLL present on the system.  
> It is installed automatically with MSFS 2020/2024. If you get a DLL error, ensure MSFS is installed.

### 3. Start the backend server

```bash
cd server
uvicorn main:app --reload --port 8000
```

On first run this will:
- Create the SQLite database at `~/.afv_tracker/afv_tracker.db`
- Seed gate data for all AFV hub airports

### 4. Start the client

```bash
cd client
python main.py
```

On first launch, a **Pilot Setup** dialog will appear. Enter your:
- **SimBrief Pilot ID** (username or numeric ID)
- **Your name**

These are saved to `~/.afv_tracker/config.json` and reloaded on future launches.

---

## Usage

1. Open the app — it auto-fetches your latest SimBrief OFP
2. Load MSFS and start your flight
3. Click **START TRACKING** — the app connects to MSFS via SimConnect
4. Fly your route — watch altitude, speed, phase, and fuel update every 5 seconds
5. As you descend through **10,000 ft within 50 nm of your destination**, the gate banner appears
6. Park with engines off and parking brake set — the flight is logged automatically

---

## Configuration

Config file: `~/.afv_tracker/config.json`

| Key | Default | Description |
|-----|---------|-------------|
| `pilot_id` | `""` | SimBrief pilot ID / username |
| `pilot_name` | `""` | Your display name |
| `server_url` | `http://localhost:8000` | Backend API URL |
| `simconnect_poll_interval` | `5` | SimConnect poll interval in seconds |

---

## Airport Gate Coverage

| ICAO | Airport | Gates |
|------|---------|-------|
| FTTG | N'Djamena | 7 |
| FACT | Cape Town | 10 |
| FAOR | O.R. Tambo, Johannesburg | 13 |
| FMMI | Antananarivo | 5 |
| HTDA | Dar es Salaam | 7 |
| FQMA | Maputo | 5 |
| FALA | Lanseria | 5 |
| HAAB | Addis Ababa | 7 |
| DNMM | Lagos | 6 |
| HKJK | Nairobi | 6 |
| DTTA | Tunis | 4 |
| HECA | Cairo | 6 |
| GOBD | Dakar | 4 |

Gate sizes: **S** = Small (turboprop), **M** = Medium (narrowbody), **L** = Large (widebody), **H** = Heavy

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/flights/track` | Receive telemetry ping |
| `POST` | `/api/flights/complete` | Log completed flight |
| `GET` | `/api/flights/{pilot_id}` | Flight history |
| `GET` | `/api/gates/{icao}/assign?aircraft_type=B738` | Request gate |
| `GET` | `/api/gates/{icao}` | List all gates |
| `POST` | `/api/pilots/register` | Register pilot |
| `GET` | `/api/pilots/{pilot_id}` | Pilot profile |
| `GET` | `/health` | Health check |

Full interactive docs: `http://localhost:8000/docs`

---

## Architecture

```
┌────────────────────────────────────────┐
│          MSFS 2024 (SimConnect)         │
└────────────────────┬───────────────────┘
                     │ SimVars (poll 5s)
┌────────────────────▼───────────────────┐
│   AFV Client (PyQt6 Desktop App)        │
│  ┌──────────┐ ┌──────────┐ ┌────────┐  │
│  │ SimBrief │ │ SimConn  │ │ Flight │  │
│  │  Fetch   │ │  Worker  │ │Tracker │  │
│  └──────────┘ └──────────┘ └────────┘  │
│         GUI (MainWindow + Panels)       │
└────────────────────┬───────────────────┘
                     │ HTTP (requests)
┌────────────────────▼───────────────────┐
│   AFV Server (FastAPI + SQLite)         │
│  /api/flights  /api/gates  /api/pilots  │
└────────────────────────────────────────┘
```

---

## Phase Detection Logic

| Phase | Conditions |
|-------|-----------|
| PRE-FLIGHT | On ground, engines off |
| TAXI OUT | On ground, engines on, GS < 30 kts |
| TAKEOFF | On ground, GS ≥ 30 kts |
| CLIMB | Airborne, VS > +100 fpm |
| CRUISE | Airborne, altitude stable ±500 ft for 60 sec |
| DESCENT | Airborne, VS < -100 fpm |
| APPROACH | Airborne, alt < 10,000 ft, within 50 nm of destination |
| LANDING | Transition from airborne to on ground |
| TAXI IN | On ground, engines on, GS < 30 kts (post-landing) |
| PARKED | On ground, engines off, parking brake set |

---

## Troubleshooting

**"SimConnect library not found"**  
Run `pip install SimConnect`. Ensure MSFS is installed.

**"Cannot connect to MSFS"**  
MSFS must be running and loaded into a flight (not the main menu). The app retries automatically every 10 seconds.

**"SimBrief pilot ID not found"**  
Double-check your SimBrief username at [simbrief.com](https://www.simbrief.com). Numeric IDs and usernames both work.

**Gate not assigned**  
If the server is unreachable, you'll see "CONTACT GROUND FOR GATE ASSIGNMENT". Start the server with `uvicorn main:app --port 8000`.
