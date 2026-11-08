"""
Gemini integration for TrafficIQ.

Provides natural-language features over the live traffic/weather state:
- chat: answer free-form questions with live context
- describe_frame: vision caption of the current camera frame
- smart_alert: natural-language high-risk advisory

Graceful degradation: any Gemini call returns None on failure or when no
API key is configured, and callers fall back to static templates.
"""

import os
import time

import requests
from dotenv import load_dotenv

from state import current_stats

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL = "gemini-3.6-flash"
_CHAT_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
_VISION_MODEL = "gemini-3.6-flash"
_VISION_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{_VISION_MODEL}:generateContent"

MAX_TOKENS = 300
_CACHE_TTL = 20
_last_call = {}
_cache = {}
_last_error = None


def enabled():
    return bool(API_KEY)


# ---------------------------------------------------------------- helpers

def _throttled(key, ttl=_CACHE_TTL):
    """Return a previously cached result if within TTL, else None and refresh."""
    now = time.time()
    if key in _cache and now - _last_call.get(key, 0) < ttl:
        return _cache[key]
    _last_call[key] = now
    return None


def _extract_text(resp):
    try:
        cands = resp.json()["candidates"]
        return cands[0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, ValueError):
        return None


def _system_prompt():
    w = current_stats.get("weather") or {}
    risk = current_stats.get("traffic_risk") or {}
    weather_txt = (
        f"{w.get('description')}, {w.get('temperature_c')} C, "
        f"humidity {w.get('humidity_pct')}%, wind {w.get('wind_kmh')} km/h"
        if w.get("available") else "unavailable"
    )
    return (
        "You are TrafficIQ, an intelligent traffic assistant for Cuttack, India. "
        "Answer briefly and helpfully (2-4 sentences). "
        "Use the live data provided and note when data looks stale or zero. "
        "Live context:\n"
        f"- vehicles detected: {current_stats.get('vehicle_count', 0)}\n"
        f"- average speed: {current_stats.get('average_speed', 0)} km/h\n"
        f"- traffic status: {current_stats.get('traffic_status', 'unknown')}\n"
        f"- vehicle types: {current_stats.get('vehicle_types', {})}\n"
        f"- weather: {weather_txt}\n"
        f"- traffic risk: {risk.get('level', 'unknown')} "
        f"(score {risk.get('score', 0)}, advisory: {risk.get('advisory', '')})"
    )


# ---------------------------------------------------------------- public API

def chat(user_message, force=False):
    """Answer a free-form question using live context. Returns text or None."""
    if not enabled() or not user_message or not user_message.strip():
        return None

    cached = None if force else _throttled(user_message)
    if cached is not None:
        return cached

    payload = {
        "contents": [
            {"parts": [{"text": _system_prompt()}]},
            {"parts": [{"text": user_message}]},
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": MAX_TOKENS,
            "topP": 0.9,
        },
    }
    try:
        r = requests.post(
            _CHAT_URL,
            params={"key": API_KEY},
            json=payload,
            timeout=20,
        )
        if r.status_code != 200:
            return None
        text = _extract_text(r)
        if text:
            _cache[user_message] = text
        return text
    except requests.RequestException:
        return None


def describe_frame(image_b64, force=False, prompt=None):
    """Caption the current video frame using Gemini Vision. Returns text or None."""
    if not enabled() or not image_b64:
        return None

    # NOTE: no caching here -- each frame is a different image, so the
    # description must always reflect the current frame.

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt or "Describe what you see in this traffic camera frame. List vehicles and their rough count, road conditions, weather, and any hazards. Be concise but concrete."},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_b64,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 700,
        },
    }
    try:
        r = requests.post(
            _VISION_URL,
            params={"key": API_KEY},
            json=payload,
            timeout=30,
        )
        if r.status_code == 429:
            _set_error("Gemini quota exceeded - please try again later (rate limit)")
        elif r.status_code != 200:
            _set_error(f"Gemini API error ({r.status_code})")
        else:
            _set_error(None)
        if r.status_code != 200:
            return None
        return _extract_text(r)
    except requests.RequestException:
        _set_error("Gemini network error")
        return None


def _set_error(msg):
    global _last_error
    _last_error = msg


def last_error():
    global _last_error
    return _last_error


def smart_alert(level, advisory, force=False):
    """Generate a natural-language high-risk alert. Returns text or None."""
    if not enabled():
        return None

    cached = None if force else _throttled(("alert", level))
    if cached is not None:
        return cached

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            f"The system just escalated to {level} traffic risk. "
                            f"{advisory}. Vehicles: {current_stats.get('vehicle_count', 0)}, "
                            f"status: {current_stats.get('traffic_status', 'unknown')}. "
                            "Write a clear, urgent but not panicked alert for citizens "
                            "in 2-3 sentences."
                        )
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.6,
            "maxOutputTokens": 180,
        },
    }
    try:
        r = requests.post(
            _CHAT_URL,
            params={"key": API_KEY},
            json=payload,
            timeout=20,
        )
        if r.status_code != 200:
            return None
        text = _extract_text(r)
        if text:
            _cache[("alert", level)] = text
        return text
    except requests.RequestException:
        return None
