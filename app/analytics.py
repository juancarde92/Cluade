"""Minimal file-backed counters for basic usage/conversion tracking.

Not a real analytics platform — just enough to answer "is anyone using
this and are they paying?" without adding a database or external
service. Counts persist across worker restarts within the same Render
deploy (same container filesystem), but reset on a new deploy, since
Render's free tier disk isn't persisted across deploys.
"""
import json
import os
import threading

STATS_PATH = os.path.join(os.path.dirname(__file__), "data", "stats.json")
_lock = threading.Lock()

DEFAULT_STATS = {
    "visits": 0,
    "analyses": 0,
    "harvard_checkouts_started": 0,
    "harvard_purchases": 0,
    "harvard_revenue_cop": 0,
}


def _load():
    if os.path.exists(STATS_PATH):
        try:
            with open(STATS_PATH) as f:
                data = json.load(f)
            return {**DEFAULT_STATS, **data}
        except Exception:
            pass
    return dict(DEFAULT_STATS)


def _save(stats):
    os.makedirs(os.path.dirname(STATS_PATH), exist_ok=True)
    with open(STATS_PATH, "w") as f:
        json.dump(stats, f)


def increment(key, amount=1):
    with _lock:
        stats = _load()
        stats[key] = stats.get(key, 0) + amount
        _save(stats)


def get_stats():
    with _lock:
        return _load()
