"""
Persistence layer for TrafficIQ.

Tries Supabase first (if credentials are real) and transparently falls back
to a local SQLite database so logging + historical trends work with zero setup.

Table/columns (both backends):
    traffic_logs: id, vehicle_count, status, avg_speed, timestamp
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traffic_iq.db")

_sqlite_lock = threading.Lock()
_conn = None


def _usable_supabase():
    return SUPABASE_URL and SUPABASE_KEY and "your-project" not in SUPABASE_URL


# ---------------------------------------------------------------- sqlite

def _get_sqlite():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS traffic_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_count INTEGER,
                status TEXT,
                avg_speed REAL,
                timestamp TEXT
            )
            """
        )
        _conn.commit()
    return _conn


# ---------------------------------------------------------------- write

def save_traffic_log(vehicle_count, status, avg_speed=0.0):
    """Persist a traffic sample. Returns backend name used or None."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Try Supabase first (only if real creds present)
    if _usable_supabase():
        try:
            from supabase import create_client
            client = create_client(SUPABASE_URL, SUPABASE_KEY)
            client.table("traffic_logs").insert({
                "vehicle_count": vehicle_count,
                "status": status,
                "avg_speed": avg_speed,
                "timestamp": ts,
            }).execute()
            return "supabase"
        except Exception as e:
            print(f"[db] Supabase write failed, falling back to SQLite: {e}")

    # SQLite fallback
    try:
        with _sqlite_lock:
            conn = _get_sqlite()
            conn.execute(
                "INSERT INTO traffic_logs (vehicle_count, status, avg_speed, timestamp) VALUES (?,?,?,?)",
                (vehicle_count, status, avg_speed, ts),
            )
            conn.commit()
        return "sqlite"
    except Exception as e:
        print(f"[db] SQLite write failed: {e}")
        return None


# ---------------------------------------------------------------- history

def get_history(hours=8, granularity=None):
    """
    Return recent traffic samples bucketed for charting.
    - hours: window to look back
    - granularity: bucket size in minutes (e.g. 10); defaults to auto = hours*60/48
    """
    conn = _get_sqlite()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")

    sql = (
        "SELECT vehicle_count, status, timestamp FROM traffic_logs "
        "WHERE timestamp >= ? ORDER BY timestamp ASC"
    )
    rows = []
    try:
        with _sqlite_lock:
            cur = conn.execute(sql, (cutoff,))
            rows = cur.fetchall()
    except Exception as e:
        print(f"[db] history query failed: {e}")
        return {"bucket_minutes": 0, "points": []}

    if not rows:
        return {"bucket_minutes": 0, "points": []}

    granularity = granularity or max(5, int((hours * 60) / 48))
    buckets = {}
    for count, status, ts in rows:
        try:
            t = datetime.fromisoformat(ts)
        except ValueError:
            continue
        # bucket by floor to granularity minutes within the hour
        minute_floor = (t.minute // granularity) * granularity
        key = (t.hour, minute_floor)
        b = buckets.setdefault(key, {"t": t.replace(minute=minute_floor, second=0, microsecond=0), "counts": [], "statuses": {}})
        b["counts"].append(count)
        b["statuses"][status] = b["statuses"].get(status, 0) + 1

    points = []
    for key in sorted(buckets):
        b = buckets[key]
        avg_count = round(sum(b["counts"]) / len(b["counts"]), 1)
        dominant = max(b["statuses"], key=b["statuses"].get)
        local_t = b["t"].astimezone()
        points.append({
            "time": local_t.strftime("%H:%M"),
            "vehicle_count": avg_count,
            "status": dominant,
        })

    return {"bucket_minutes": granularity, "points": points}


def get_raw_history(hours=24):
    """Return a flat list of raw rows: [{vehicle_count, status, avg_speed, timestamp}]."""
    conn = _get_sqlite()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    try:
        with _sqlite_lock:
            cur = conn.execute(
                "SELECT vehicle_count, status, avg_speed, timestamp FROM traffic_logs "
                "WHERE timestamp >= ? ORDER BY timestamp ASC",
                (cutoff,),
            )
            rows = cur.fetchall()
    except Exception as e:
        print(f"[db] raw history failed: {e}")
        return []
    return [
        {"vehicle_count": c, "status": s, "avg_speed": sp, "timestamp": ts}
        for c, s, sp, ts in rows
    ]


def get_aggregate_since(day_start_iso):
    """Total samples and peak stats since a given UTC iso timestamp."""
    conn = _get_sqlite()
    try:
        with _sqlite_lock:
            cur = conn.execute(
                "SELECT vehicle_count, status FROM traffic_logs WHERE timestamp >= ?",
                (day_start_iso,),
            )
            rows = cur.fetchall()
    except Exception:
        return {"total_samples": 0, "avg_vehicles": 0, "peak_vehicles": 0, "peak_time": None}

    peak = 0
    total = 0
    peak_time = None
    for count, status in rows:
        total += count
        peak = max(peak, count)
    avg = round(total / len(rows), 1) if rows else 0
    return {"total_samples": len(rows), "avg_vehicles": avg, "peak_vehicles": peak, "peak_time": peak_time}
