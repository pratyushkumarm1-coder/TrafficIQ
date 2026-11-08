import os
import time
from datetime import datetime, timezone, timedelta
from database import get_history
from state import current_stats
import cv_engine
from map_nodes import get_map_nodes


def jam_cause(b64_image=None):
    """Explain WHY the road is jammed using Gemini vision on a live frame."""
    import gemini
    if not gemini.enabled():
        return {"ok": False, "error": "Gemini not configured"}
    if not b64_image:
        b64_image = cv_engine.get_latest_frame_b64()
    if not b64_image or len(b64_image) < 10000:
        return {"ok": False, "error": "image too small"}
    text = gemini.describe_frame(
        b64_image,
        prompt=("You are a traffic safety analyst. The image is a camera feed from "
                "Cuttack. Tell me in 1-2 sentences the likely CAUSE of congestion: "
                "accident, roadwork, signal problem, emergency vehicle, or just heavy "
                "flow. Be specific and practical."),
    )
    if text is None:
        return {"ok": False, "error": gemini.last_error() or "Gemini API error"}
    return {"ok": True, "text": text}


def _history_points(hours=48):
    """Return a flat list of history points from the DB wrapper."""
    res = get_history(hours=hours)
    if not res:
        return []
    pts = res.get("points", res) if isinstance(res, dict) else res
    if isinstance(pts, dict):
        return pts.get("points", [])
    return pts or []


def risk_patterns(hours=48):
    """Analyze historical logs to surface time-of-day + weather risk insights."""
    rows = _history_points(hours)
    if not rows:
        return {"ok": False, "error": "insufficient history", "insights": []}
    insights = []
    by_hour = {}
    for r in rows:
        ts = r.get("timestamp") or r.get("time") or ""
        try:
            h = int(ts.split(":")[0])
        except Exception:
            continue
        sev = 1 if r.get("status") in ("Heavy", "Congested") else 0
        by_hour.setdefault(h, [0, 0])
        by_hour[h][0] += 1
        by_hour[h][1] += sev
    if not by_hour:
        return {"ok": False, "error": "insufficient history", "insights": []}
    worst_h = max(by_hour, key=lambda h: by_hour[h][1] / by_hour[h][0])
    best_h = min(by_hour, key=lambda h: by_hour[h][1] / by_hour[h][0])
    insights.append({
        "title": "Worst congestion window",
        "detail": f"Most congestion occurs around {worst_h:02d}:00, "
                  f"affecting {round(by_hour[worst_h][1] / by_hour[worst_h][0] * 100)}% of "
                  f"{by_hour[worst_h][0]} samples. Avoid travel then if possible.",
        "icon": "🌧️",
    })
    insights.append({
        "title": "Best travel window",
        "detail": f"Lightest traffic is around {best_h:02d}:00 "
                  f"(only {round(by_hour[best_h][1] / by_hour[best_h][0] * 100)}% congested).",
        "icon": "🚦",
    })
    w = current_stats.get("weather") or {}
    if w.get("description"):
        insights.append({
            "title": "Weather factor",
            "detail": f"Current conditions: {w['description']}, {w.get('temp', '?')}°C. "
                      "Poor weather can raise accident risk and slow speeds.",
            "icon": "🌤️",
        })
    return {"ok": True, "insights": insights}


def route_suggestion(start, end):
    """Suggest the least-congested path between two junctions on the map."""
    res = get_map_nodes(current_stats)
    nodes = res.get("nodes", [])
    if not nodes:
        return {"ok": False, "error": "no map nodes"}
    by_name = {n.get("name", "").lower(): n for n in nodes}
    s = by_name.get(str(start).lower())
    e = by_name.get(str(end).lower())
    if not s or not e:
        names = [n.get("name") for n in nodes][:6]
        return {"ok": False, "error": f"junctions not found. Available: {names}"}
    if s["id"] == e["id"]:
        return {"ok": False, "error": "start and end are the same junction"}
    _rank = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "SEVERE": 3}
    mid = [n for n in nodes if n["id"] not in (s["id"], e["id"])]
    mid.sort(key=lambda n: _rank.get(n.get("risk_level", "LOW"), 0))
    path = [s] + [m for m in mid[:2]] + [e]
    route = [{"lat": n["lat"], "lng": n["lng"], "name": n["name"]} for n in path]
    avg_risk = sum(_rank.get(p.get("risk_level", "LOW"), 0) for p in path) / len(path)
    label = "Light" if avg_risk <= 1 else "Moderate" if avg_risk <= 2 else "Heavy" if avg_risk <= 3 else "Severe"
    return {
        "ok": True,
        "route": route,
        "summary": f"Least-congested route from {s['name']} to {e['name']}: "
                   f"via " + " → ".join(r["name"] for r in route[1:-1]) + f". Estimated load: {label}.",
    }


def build_report():
    """Generate an end-of-day traffic report card as an HTML string."""
    now = datetime.now()
    rows = _history_points(24)
    total = len(rows)
    vals = [r.get("vehicle_count", 0) for r in rows]
    avg_v = round(sum(vals) / total, 1) if total else 0
    max_v = max(vals) if vals else 0
    from collections import Counter
    statuses = Counter(r.get("status", "Normal") for r in rows)
    peak = statuses.most_common(1)[0][0] if statuses else "Normal"
    risk = current_stats.get("traffic_risk") or "LOW"
    w = current_stats.get("weather") or {}
    em = cv_engine.emergency_active()
    html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
    <title>TrafficIQ Daily Report</title>
    <style>
      body{{font-family:Segoe UI,Arial,sans-serif;max-width:720px;margin:40px auto;color:#1f2937;padding:0 20px}}
      h1{{color:#3b82f6}} h2{{color:#111827;border-bottom:2px solid #e5e7eb;padding-bottom:6px}}
      .card{{background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin:12px 0}}
      .big{{font-size:2.2em;font-weight:700;color:#3b82f6}} .grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
      .metric{{background:#eff6ff;border-radius:8px;padding:12px;text-align:center}}
      table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #e5e7eb;padding:8px}}
    </style></head><body>
    <h1>🚦 TrafficIQ Daily Report</h1>
    <p><b>{now.strftime('%A, %d %B %Y %H:%M')}</b> · Cuttack Surveillance</p>
    <h2>Summary</h2>
    <div class='grid'>
      <div class='metric'><div class='big'>{peak}</div><div>Dominant status</div></div>
      <div class='metric'><div class='big'>{avg_v}</div><div>Avg vehicles</div></div>
      <div class='metric'><div class='big'>{max_v}</div><div>Peak vehicles</div></div>
    </div>
    <div class='card'>Risk level: <b>{risk}</b> · Samples: <b>{total}</b> ·
      Weather: {w.get('description', 'n/a')} · Emergency corridor: <b>{'ACTIVE' if em else 'clear'}</b></div>
    <h2>Status breakdown</h2>
    <table><tr><th>Status</th><th>Sample count</th></tr>
    {"".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in statuses.most_common())}
    </table>
    <p><small>Generated automatically by TrafficIQ. Data: local SQLite store.</small></p>
    </body></html>"""
    return html
