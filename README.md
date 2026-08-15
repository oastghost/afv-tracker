# Africana Virtual Airways — Flight Tracker

Desktop companion app for AFV pilots flying in Microsoft Flight Simulator 2020/2024: live telemetry tracking, automatic gate assignment, and full phpVMS crew-centre integration (PIREP filing, ACARS position reports) — all from a system-tray app that opens itself the moment MSFS launches.

## Features

- **Auto-launch** — sits in the system tray, detects MSFS 2020/2024 starting, and opens itself
- **Live MSFS telemetry** via SimConnect — position, altitude, speed, fuel, engines, flaps, gear, autopilot, polled every 5s
- **Automatic flight-phase detection** — PRE-FLIGHT → TAXI OUT → TAKEOFF → CLIMB → CRUISE → DESCENT → APPROACH → LANDING → TAXI IN → PARKED
- **Automatic gate assignment** — assigned the moment you drop below 10,000 ft within 50 nm of your destination, across 85 gates at 13 AFV hub airports
- **Live pilot roster & map** — MapLibre GL live map of every connected AFV pilot, backed by a WebSocket feed
- **phpVMS crew-centre login** — sign in with your normal AFV crew-centre email + password; a manual API-key option is also available if you prefer it
- **Full PIREP lifecycle** — prefiles, ACARS position reports, phase/status updates, and PIREP filing all synced to phpVMS automatically
- **Offline-safe** — failed phpVMS writes queue locally and retry automatically once connectivity returns, so flight data never silently drops
- **Discord Rich Presence** — shows your current flight on your Discord profile
- **Sound cues** — short audio cues for takeoff, landing, and gate assignment
- **In-app update checks** — notifies you in the tray when a new version is published
- **AFV dark theme** — red/black/white cockpit-styled UI

---

## For Pilots — Installing

Grab the latest release from the [Releases page](https://github.com/oastghost/afv-tracker/releases):

- **`AFV-Tracker-Setup-x.y.z.exe`** (recommended) — installer, no admin rights required, installs to your user profile, adds Start Menu / Desktop shortcuts
- **`AFV-Tracker-x.y.z-portable.zip`** — no installer, just unzip and run `AFV Tracker.exe`

> **Windows may show a blue "Windows protected your PC" screen on first run.** That's SmartScreen flagging the app as unrecognized because it isn't code-signed yet (a paid certificate we don't have) — it doesn't mean anything is actually wrong. Click **More info**, then **Run anyway**.

On first launch you'll be asked to sign in with your AFV crew-centre **email and password** — the same credentials you use on the VA website. Your password is never stored, only the API key it resolves to. If you'd rather not use email/password, click "Use API key instead" and paste your key from the crew centre's Profile page.

Once signed in, the app lives in your system tray and opens itself automatically whenever MSFS starts. Right-click the tray icon for options (open/hide tracker, run at startup, check for updates).

---

## For Developers — Running from Source

**Requirements:** Python 3.11+, Microsoft Flight Simulator 2020/2024 (for the SimConnect DLL)

```bash
git clone https://github.com/oastghost/afv-tracker.git
cd afv-tracker
pip install -r requirements.txt
```

Run the whole app (tray launcher + embedded server) exactly as pilots get it:

```bash
python client/launcher.py
```

This spawns the FastAPI/SQLite server as a background subprocess on `127.0.0.1:8765`, seeds gate data on first run, then opens the tray icon and tracker window.

To work on the server API by itself instead:

```bash
cd server
uvicorn main:app --reload --port 8765
```

Interactive API docs at `http://localhost:8765/docs`.

By default the server uses a local SQLite DB at `~/.afv_tracker/afv_tracker.db`. To point it at a shared MySQL/PostgreSQL database instead, copy `server/.env.example` to `server/.env` and set `DATABASE_URL` — never commit `.env`.

---

## Building a Release

Requires the repo's `.venv` (with PyInstaller) and [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`):

```powershell
.\build_release.ps1
```

This runs PyInstaller (`AFV_Tracker.spec`, onedir) → Inno Setup (`installer.iss`) → portable zip, and drops everything in `dist\installer\`. Version is single-sourced from `client/version.py` — bump it before building.

**The in-app updater only checks GitHub Releases**, not tags or commits — after building, you still need to publish an actual Release on GitHub with a matching version tag (e.g. `v1.2.0`) for pilots' tray "update available" notice to fire. This also requires the repo (or at least its Releases) to be publicly visible, since the client checks the GitHub API unauthenticated.

---

## Configuration

Per-pilot config lives at `~/.afv_tracker/config.json`, created automatically on first run:

| Key | Default | Description |
|-----|---------|-------------|
| `vatsim_cid` | `""` | VATSIM CID — primary pilot identifier sent to the server |
| `simbrief_id` | `""` | SimBrief username or numeric pilot ID |
| `pilot_name` | `""` | Display name |
| `discord` | `""` | Discord handle |
| `server_url` | `http://localhost:8765` | Embedded/local tracker server URL |
| `VA_URL` | `https://africanava.ddns.net` | AFV crew-centre base URL |
| `Pilot_Key` | `""` | phpVMS API key, resolved automatically at login — don't edit by hand |
| `simconnect_poll_interval` | `5` | SimConnect poll interval, in seconds |
| `weight_unit` | `LBS` | `LBS` or `KG` |
| `theme` | `dark` | UI theme |
| `sound_enabled` | `true` | Audio cues on/off |
| `discord_rpc_enabled` | `true` | Discord Rich Presence on/off |
| `discord_client_id` | *(shared)* | AFV's Discord Application ID — set VA-wide, not per pilot |

---

## Architecture

```
┌────────────────────────────────┐
│   MSFS 2020/2024 (SimConnect)  │
└────────────────┬────────────────┘
                 │ SimVars, polled every 5s
┌────────────────▼─────────────────────────────────────────┐
│  AFV Tracker.exe  (single process, system tray)           │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐ │
│  │ SimConnect  │  │   Flight     │  │   phpVMS Sync      │ │
│  │  Worker     │  │   Tracker    │  │   Worker (FIFO)    │ │
│  └─────────────┘  └──────────────┘  └───────────────────┘ │
│  ┌────────────────────────────────────────────────────┐   │
│  │  MainWindow (QWebEngineView)                        │   │
│  │  client/web — HTML/CSS/JS + MapLibre GL live map     │   │
│  │  ↕ QWebChannel bridge (web_bridge.py)                │   │
│  └────────────────────────────────────────────────────┘   │
└──────────┬───────────────────────────────┬─────────────────┘
           │ HTTP + WebSocket              │ HTTPS
┌──────────▼───────────────────┐  ┌────────▼──────────────────┐
│ Embedded server                │  │ phpVMS crew centre         │
│ FastAPI + SQLite                │  │ africanava.ddns.net        │
│ 127.0.0.1:8765 (subprocess)    │  │ login · PIREPs · ACARS     │
│ gates · roster · telemetry     │  └─────────────────────────────┘
└─────────────────────────────────┘
```

The embedded server is local per pilot (gate contention, live roster) — it is **not** shared VA state. Crew-centre data (PIREPs, bids, pilot profile) goes through the real phpVMS server instead.

---

## API Reference (embedded server)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/health` | Health check + count of pilots online |
| `WS`   | `/ws/{vatsim_cid}` | Live roster sync — telemetry + gate events |
| `POST` | `/api/flights/track` | Receive a telemetry ping |
| `POST` | `/api/flights/complete` | Log a completed flight |
| `GET`  | `/api/flights/{vatsim_cid}` | Flight history |
| `GET`  | `/api/gates/{icao}` | List gates at an airport |
| `GET`  | `/api/gates/{icao}/assign?aircraft_type=B738` | Request a gate |
| `POST` | `/api/gates/{icao}/{gate_name}/release` | Release a gate |
| `POST` | `/api/pilots/register` | Create/update pilot record |
| `GET`  | `/api/pilots/online` | Currently connected pilots |
| `GET`  | `/api/pilots/{vatsim_cid}` | Pilot profile |

---

## Gate Coverage

85 gates across 13 AFV hub airports:

| ICAO | Airport |
|------|---------|
| FTTG | N'Djamena International |
| FACT | Cape Town International |
| FAOR | O.R. Tambo International, Johannesburg |
| FMMI | Ivato International, Antananarivo |
| HTDA | Julius Nyerere International, Dar es Salaam |
| FQMA | Maputo International |
| FALA | Lanseria International |
| HAAB | Addis Ababa Bole International |
| DNMM | Murtala Muhammed International, Lagos |
| HKJK | Jomo Kenyatta International, Nairobi |
| DTTA | Tunis-Carthage International |
| HECA | Cairo International |
| GOBD | Blaise Diagne International, Dakar |

Gate sizes: **Light** (turboprop) · **Medium** (narrowbody) · **Heavy** (widebody) · **Jumbo**

---

## Flight Phase Detection

| Phase | Trigger |
|-------|---------|
| PRE-FLIGHT | On ground, engines off |
| TAXI OUT | On ground, engines on, groundspeed < 30 kts |
| TAKEOFF | On ground, groundspeed ≥ 30 kts |
| CLIMB | Airborne, vertical speed > +300 fpm |
| CRUISE | Airborne, altitude stable within ±500 ft for 60s |
| DESCENT | Airborne, vertical speed < -300 fpm |
| APPROACH | Airborne, below 10,000 ft and within 50 nm of destination |
| LANDING | Transition from airborne to on-ground |
| TAXI IN | On ground, engines on, groundspeed < 30 kts (post-landing) |
| PARKED | On ground, engines off, parking brake set |

---

## Troubleshooting

**Blue "Windows protected your PC" screen on install** — the app isn't code-signed yet. Click **More info** → **Run anyway**. See [Installing](#for-pilots--installing).

**"SimConnect library not found" / can't connect to MSFS** — SimConnect installs with MSFS itself. Make sure MSFS is running and you're loaded into a flight, not sitting at the main menu. The app retries automatically every 10 seconds.

**Login fails / "Invalid email or password"** — use your AFV crew-centre credentials, not SimBrief or Discord. If crew-centre login keeps failing, switch to "Use API key instead" on the login screen and paste your key from the crew centre's Profile page.

**Gate not assigned** — the embedded local server may not have started; check `~/afv_server.log` and `~/.afv_tracker/afv_tracker.log`. Restarting the app restarts the server.

**Flight data not appearing on phpVMS** — check your internet connection. Failed writes queue locally (`~/.afv_tracker/outbox.db`) and retry automatically rather than getting dropped.

---

## Credits

phpVMS crew-centre integration built in collaboration with Beni Esteve.
