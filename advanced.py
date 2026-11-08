import os
import time
from datetime import datetime, timezone, timedelta

from state import current_stats
from database import get_raw_history
import cv_engine


# ---------- #7 Multi-language labels ----------
LABELS = {
    "en": {"Low": "Low", "Moderate": "Moderate", "High": "High", "Severe": "Severe",
           "Normal": "Normal", "Heavy": "Heavy", "Congested": "Congested"},
    "hi": {"Low": "कम", "Moderate": "मध्यम", "High": "उच्च", "Severe": "गंभीर",
           "Normal": "सामान्य", "Heavy": "भारी", "Congested": "घना"},
    "or": {"Low": "କମ୍", "Moderate": "ମଧ୍ୟମ", "High": "ଉଚ୍ଚ", "Severe": "ଗମ୍ଭୀର",
           "Normal": "ସାଧାରଣ", "Heavy": "ଘନ", "Congested": "ଭିଡ଼"},
}
LANGS = {"en": "English", "hi": "हिन्दी (Hindi)", "or": "ଓଡ଼ିଆ (Odia)"}


def translate_label(label, lang):
    """Translate a risk/status label into the requested language (fallback English)."""
    if not lang or lang not in LABELS:
        return label
    return LABELS[lang].get(label, label)


# ---------- #8 System health ----------
def system_health():
    """Self-diagnostic report for monitoring."""
    health = {"ok": True, "checks": {}}
    # Stream / analyzer health
    try:
        frame = cv_engine.get_latest_frame() is not None
        health["checks"]["video_stream"] = {"status": "ok" if frame else "degraded",
                                            "detail": "live frame available" if frame else "no live frame yet"}
        if not frame:
            health["ok"] = False
    except Exception as e:
        health["checks"]["video_stream"] = {"status": "error", "detail": str(e)}
        health["ok"] = False

    # DB health
    try:
        rows = get_raw_history(24)
        health["checks"]["database"] = {"status": "ok", "detail": f"{len(rows)} samples in last 24h"}
        if not rows:
            health["checks"]["database"]["status"] = "degraded"
    except Exception as e:
        health["checks"]["database"] = {"status": "error", "detail": str(e)}
        health["ok"] = False

    # Gemini health (don't make an API call; just report config + last error)
    try:
        import gemini
        enabled = gemini.enabled()
        last = gemini.last_error() or "none"
        health["checks"]["gemini"] = {"status": "ok" if enabled else "not configured",
                                      "detail": f"enabled={enabled}, last_error={last}"}
        if enabled and last and "quota" in last.lower():
            health["checks"]["gemini"]["status"] = "degraded"
    except Exception as e:
        health["checks"]["gemini"] = {"status": "error", "detail": str(e)}

    # Model load time (cached soft metric)
    mdl = getattr(cv_engine.analyzer, "model", None)
    health["checks"]["yolo_model"] = {"status": "ok" if mdl is not None else "unknown",
                                      "detail": "YOLO model loaded" if mdl else "model not initialized"}

    # Snapshot storage
    import features
    shots = features.list_snapshots()
    health["checks"]["snapshots"] = {"status": "ok", "detail": f"{len(shots)} stored"}

    health["uptime_s"] = round(time.time() - _START_TIME, 1)
    health["live_stats"] = {
        "vehicles": current_stats.get("vehicle_count", 0),
        "status": current_stats.get("traffic_status", "n/a"),
        "risk": (current_stats.get("traffic_risk") or {}).get("level", "n/a"),
    }
    return health


# ---------- #9 Wrong-way detection ----------
def wrong_way():
    """
    Detect vehicles moving against the dominant flow using tracked trajectories.
    Returns detail about the first/most offenders.
    """
    traj = getattr(cv_engine.analyzer, "trajectories", {})
    if not traj:
        return {"ok": True, "wrong_way_count": 0, "offenders": []}

    offenders = []
    # Compute displacement direction for each track with enough history
    vectors = []
    for tid, pts in traj.items():
        if len(pts) >= 4:
            dx = pts[-1][0] - pts[0][0]
            dy = pts[-1][1] - pts[0][1]
            mag = (dx * dx + dy * dy) ** 0.5
            if mag > 4:  # meaningful movement
                vectors.append((tid, dx, dy, mag))

    # Dominant direction = average of all movement vectors
    if not vectors:
        return {"ok": True, "wrong_way_count": 0, "offenders": []}
    avg_dx = sum(v[1] for v in vectors) / len(vectors)
    avg_dy = sum(v[2] for v in vectors) / len(vectors)
    dom_mag = (avg_dx * avg_dx + avg_dy * avg_dy) ** 0.5
    if dom_mag < 1e-3:
        return {"ok": True, "wrong_way_count": 0, "offenders": []}

    # Dot product < deep negative => opposes dominant flow
    for tid, dx, dy, mag in vectors:
        dot = (dx * avg_dx + dy * avg_dy) / (mag * dom_mag + 1e-9)
        if dot < -0.4:  # strongly opposing
            offenders.append({"track_id": tid,
                              "against_flow": round(float(dot), 2),
                              "magnitude": round(float(mag), 1)})

    return {"ok": True, "wrong_way_count": len(offenders), "offenders": offenders[:5],
            "dominant_direction": [round(avg_dx, 2), round(avg_dy, 2)]}


# ---------- #10 Capacity forecast (ML-lite linear regression) ----------
def forecast(hours_back=6, target_minutes=30):
    """
    Simple least-squares linear regression on recent vehicle counts to predict
    the count in `target_minutes` minutes. Returns trend + prediction.
    """
    rows = get_raw_history(hours_back)
    if len(rows) < 5:
        return {"ok": False, "error": f"not enough data ({len(rows)} samples)"}

    # Convert timestamps to seconds since earliest for x-axis
    try:
        t0 = datetime.fromisoformat(rows[0]["timestamp"]).timestamp()
    except Exception:
        return {"ok": False, "error": "bad timestamps"}
    xs = []
    ys = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["timestamp"]).timestamp()
        except Exception:
            continue
        xs.append((ts - t0) / 60.0)  # minutes since start
        ys.append(r["vehicle_count"])

    if len(xs) < 5:
        return {"ok": False, "error": "not enough data"}

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    slope = num / den if den != 0 else 0.0
    intercept = mean_y - slope * mean_x

    last_min = xs[-1]
    pred = slope * (last_min + target_minutes) + intercept
    pred = max(0, round(pred, 1))

    curr = round(mean_y, 1)
    trend = "Rising" if slope > 0.05 else "Falling" if slope < -0.05 else "Steady"
    return {
        "ok": True,
        "current_avg": curr,
        "prediction_minutes": target_minutes,
        "predicted_count": pred,
        "trend": trend,
        "change": round(pred - curr, 1),
        "slope_per_min": round(slope, 3),
        "samples": n,
    }


_START_TIME = time.time()
