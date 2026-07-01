"""Persistent usage statistics: lifetime tokens, per-provider/model breakdown, request log."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATS_FILE = Path.home() / ".config" / "unified-router" / "usage_stats.json"


class UsageStats:
    def __init__(self, path: Path | None = None):
        self._path = path or STATS_FILE
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {
            "lifetime_tokens": 0,
            "lifetime_requests": 0,
            "lifetime_errors": 0,
            "providers": {},
            "models": {},
            "recent_requests": [],
            "started_at": time.time(),
        }
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._data.update(raw)
            except Exception as e:
                logger.warning("Failed to load usage stats: %s", e)

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to save usage stats: %s", e)

    def record_request(
        self,
        provider: str,
        model: str,
        tokens: int = 0,
        latency_ms: float = 0.0,
        status: str = "ok",
        error: str | None = None,
        request_id: str | None = None,
    ):
        with self._lock:
            self._data["lifetime_requests"] += 1
            self._data["lifetime_tokens"] += tokens
            if status != "ok":
                self._data["lifetime_errors"] += 1

            prov = self._data["providers"].setdefault(provider, {
                "requests": 0, "errors": 0, "tokens": 0, "latency_ms_total": 0.0, "last_used": 0.0,
            })
            prov["requests"] += 1
            prov["tokens"] += tokens
            prov["latency_ms_total"] += latency_ms
            prov["last_used"] = time.time()
            if status != "ok":
                prov["errors"] += 1

            mdl = self._data["models"].setdefault(model, {
                "requests": 0, "errors": 0, "tokens": 0, "providers": {}, "last_used": 0.0,
            })
            mdl["requests"] += 1
            mdl["tokens"] += tokens
            mdl["last_used"] = time.time()
            if status != "ok":
                mdl["errors"] += 1
            prov_for_model = mdl["providers"].setdefault(provider, {"requests": 0, "tokens": 0, "errors": 0})
            prov_for_model["requests"] += 1
            prov_for_model["tokens"] += tokens
            if status != "ok":
                prov_for_model["errors"] += 1

            entry = {
                "time": time.time(),
                "provider": provider,
                "model": model,
                "tokens": tokens,
                "latency_ms": round(latency_ms, 1),
                "status": status,
            }
            if error:
                entry["error"] = error
            if request_id:
                entry["request_id"] = request_id
            self._data["recent_requests"].append(entry)
            if len(self._data["recent_requests"]) > 500:
                self._data["recent_requests"] = self._data["recent_requests"][-500:]

    def flush(self):
        with self._lock:
            self._save()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            data = {
                "lifetime_tokens": self._data["lifetime_tokens"],
                "lifetime_requests": self._data["lifetime_requests"],
                "lifetime_errors": self._data["lifetime_errors"],
                "uptime_seconds": round(now - self._data.get("started_at", now)),
                "providers": dict(self._data["providers"]),
                "models": dict(self._data["models"]),
                "recent_requests": list(self._data["recent_requests"][-100:]),
            }
            for prov_data in data["providers"].values():
                prov_data.setdefault("last_used", 0)
                if prov_data.get("last_used"):
                    prov_data["last_used_ago"] = round(now - prov_data["last_used"])
            for model_data in data["models"].values():
                model_data.setdefault("last_used", 0)
                if model_data.get("last_used"):
                    model_data["last_used_ago"] = round(now - model_data["last_used"])
            return data


_usage_stats: UsageStats | None = None

_LAST_FLUSH: float = 0.0


def get_usage_stats() -> UsageStats:
    global _usage_stats
    if _usage_stats is None:
        _usage_stats = UsageStats()
    return _usage_stats


def periodic_flush():
    global _LAST_FLUSH
    now = time.time()
    if now - _LAST_FLUSH > 30:
        get_usage_stats().flush()
        _LAST_FLUSH = now
