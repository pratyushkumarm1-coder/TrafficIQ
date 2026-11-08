"""
TrafficIQ feature modules: snapshots, incidents, anomaly detection, forecast.
Centralizes state and helpers used by the API, map and alerts.
"""

import base64
import json
import os
import threading
import time
from datetime import datetime

from state import current_stats

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_DIR = os.path.join(_BASE_DIR, "snapshots")
INCIDENTS_PATH = os.path.join(_BASE_DIR, "incidents.json")

os.makedirs(SNAPSHOT_DIR, exist_ok=True)

_state_lock = threading.Lock()
_incidents = []


def load_incidents():
    global _incidents
    try:
        with open(INCIDENTS_PATH, "r", encoding="utf-8") as f:
            _incidents = json.load(f)
    except (OSError, ValueError):
        _incidents = []


load_incidents()


# ---------------------------------------------------------------- snapshots

def capture_snapshot(save_to_disk=True):
    """
    Grab the latest analyzed frame from the CV engine, persist it as a JPEG
    "evidence" file, and return metadata + base64 bytes for the frontend.
    """
    from cv_engine import get_latest_frame_b64
    frame_b64 = get_latest_frame_b64()
    if frame_b64 is None:
        return None

    ts = datetime.now()
    ts_str = ts.strftime("%Y%m%d_%H%M%S")
    filename = f"snapshot_{ts_str}.jpg"
    meta = {
        "filename": filename,
        "captured_at": ts.isoformat(timespec="seconds"),
        "vehicles": current_stats.get("vehicle_count", 0),
        "status": current_stats.get("traffic_status", "Normal"),
    }
    if save_to_disk:
        try:
            raw = base64.b64decode(frame_b64)
            with open(os.path.join(SNAPSHOT_DIR, filename), "wb") as f:
                f.write(raw)
            meta["saved"] = True
        except Exception as e:
            meta["saved"] = False
            meta["error"] = str(e)
    return {**meta, "image_b64": frame_b64}


def list_snapshots(limit=20):
    files = []
    try:
        names = sorted(os.listdir(SNAPSHOT_DIR), reverse=True)
    except FileNotFoundError:
        return files
    for name in names[:limit]:
        if name.lower().endswith(".jpg"):
            full = os.path.join(SNAPSHOT_DIR, name)
            files.append({
                "filename": name,
                "mtime": datetime.fromtimestamp(os.path.getmtime(full)).isoformat(timespec="seconds"),
            })
    return files


# ---------------------------------------------------------------- incidents

def add_incident(lat, lng, label="Reported incident", risk_level=None):
    global _incidents
    veh = current_stats.get("vehicle_count", 0)
    entry = {
        "id": int(time.time() * 1000),
        "lat": lat,
        "lng": lng,
        "label": label,
        "risk_level": risk_level or current_stats.get("traffic_risk", {}).get("level", "LOW"),
        "vehicles": veh,
        "reported_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _state_lock:
        _incidents.insert(0, entry)
        _incidents = _incidents[:100]
        try:
            with open(INCIDENTS_PATH, "w", encoding="utf-8") as f:
                json.dump(_incidents, f, indent=2)
        except OSError:
            pass
    return entry


def list_incidents():
    with _state_lock:
        return list(_incidents)


# ---------------------------------------------------------------- anomalies

_anomaly_state = {
    "baseline_count": None,
    "last_sample": None,
    "last_alert": 0,
    "last_jam_alert": 0,
}

ANOMALY_COOLDOWN = 120            # seconds between anomaly alerts
JAM_SPEED_THRESHOLD_KMH = 3.0     # near-zero speed in a busy feed -> jam


def evaluate_anomalies(force=False):
    """
    Look at current_stats for two conditions:
      1. Volume surge        : count >> smoothed baseline (e.g. > 2x with min delta)
      2. Possible jam        : many vehicles but speed near zero
    Returns a string description of any condition, else None.
    Emits in-process alerts via telegram_bot.
    """
    count = current_stats.get("vehicle_count", 0)
    speed = current_stats.get("average_speed", 0.0)
    now = time.time()
    a = _anomaly_state

    message = None
    key = None

    # Volume surge detection
    if a["baseline_count"] is None:
        a["baseline_count"] = count
    else:
        a["baseline_count"] = 0.9 * a["baseline_count"] + 0.1 * count
        if (
            count > 12
            and a["baseline_count"] > 4
            and count > 2.0 * a["baseline_count"]
            and (now - a["last_alert"]) > ANOMALY_COOLDOWN
        ):
            a["last_alert"] = now
            key = "surge"
            message = (
                f"<b>[TRAFFIC SURGE]</b> Vehicle count jumped to {count} "
                f"(baseline ~{round(a['baseline_count'])}) at "
                f"{current_stats.get('traffic_status', 'normal')} conditions."
            )

    # Possible jam detection
    if (
        count >= 6
        and 0 < speed <= JAM_SPEED_THRESHOLD_KMH
        and (now - a["last_jam_alert"]) > ANOMALY_COOLDOWN
    ):
        a["last_jam_alert"] = now
        key = "jam"
        message = (
            f"<b>[POSSIBLE JAM]</b> {count} vehicles detected but speed is only "
            f"{speed} km/h near Link Road - likely congestion or stopped traffic."
        )

    if message and not force:
        try:
            import telegram_bot
            telegram_bot.send_message(message)
        except Exception:
            pass

    return message


# ---------------------------------------------------------------- forecast

def forecast_map_nodes(nodes):
    """
    Enrich map nodes with a short (next 30/60 min) congestion outlook derived
    from the simulated rush-hour curve.
    """
    from map_nodes import _rush_hour_factor, STATUS_POINTS
    now_hour = time.localtime()
    f_t0 = _rush_hour_factor(now_hour)
    # Project ~+30 min
    future = time.localtime(time.time() + 1800)
    f_30 = _rush_hour_factor(future)
    future_60 = time.localtime(time.time() + 3600)
    f_60 = _rush_hour_factor(future_60)

    trend = (f_30 - f_t0) + 0.5 * (f_60 - f_t0)
    direction = "rising" if trend > 0.03 else ("falling" if trend < -0.03 else "stable")

    seeded = {}
    for node in nodes:
        idx = seeded.setdefault(f_30, 0) + 1
        seeded[f_30] = idx
        base = 4 + 18 * f_30 * ((idx * 37) % 10 + 1) / 10
        if base > 15:
            outlook = "Congested"
        elif base > 7:
            outlook = "Heavy"
        else:
            outlook = "Normal"
        node["forecast_30m"] = outlook
        node["forecast_trend"] = direction
    return nodes
