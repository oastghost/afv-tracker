"""
AFV Tracker - Simulator Backend Factory
Picks which telemetry worker to construct based on the user's configured
sim_type. This is the only place in the app that knows both SimConnectWorker
(MSFS) and XPlaneWorker (X-Plane) exist — gui_web.py just asks for "a sim
worker" and gets back whichever QThread it should wire up, since both speak
the same signal contract (see simconnect_client.Telemetry and the four
telemetry_update/connected/disconnected/error signals both workers expose).

Defaults to MSFS/SimConnect so any config.json predating this feature — i.e.
every existing install — keeps behaving exactly as it did before.
"""

from simconnect_client import SimConnectWorker
from xplane_client import XPlaneWorker

SIM_LABELS = {
    "msfs": "MSFS",
    "xplane": "X-Plane",
    "fsx": "FSX",
    "p3d": "Prepar3D",
}


def build_sim_worker(cfg: dict, poll_interval: int, parent):
    sim_type = cfg.get("sim_type", "msfs")
    if sim_type == "xplane":
        return XPlaneWorker(
            poll_interval, parent,
            host=cfg.get("xplane_host", ""),
            port=cfg.get("xplane_port", 49000),
        )
    # msfs / fsx / p3d all speak SimConnect — same worker, auto-detects which
    # one is actually running (see simconnect_client.detect_sim_version).
    return SimConnectWorker(poll_interval, parent)
