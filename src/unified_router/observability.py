"""Request tracing and structured observability."""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

_trace_ctx: contextvars.ContextVar[TraceSpan | None] = contextvars.ContextVar(
    "unified_router_trace", default=None
)


@dataclass
class TraceSpan:
    request_id: str
    start_time: float = field(default_factory=time.time)
    provider_attempts: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    final_provider: str | None = None
    final_model: str | None = None
    error: str | None = None
    cache_hit: bool = False

    @property
    def elapsed_ms(self) -> float:
        return round((time.time() - self.start_time) * 1000, 1)


def new_trace(model: str | None = None) -> TraceSpan:
    span = TraceSpan(request_id=uuid.uuid4().hex[:12], model=model)
    _trace_ctx.set(span)
    return span


def current_trace() -> TraceSpan | None:
    return _trace_ctx.get()


def record_attempt(provider: str, model: str, status: str, latency_ms: float = 0, error: str | None = None):
    span = current_trace()
    if span:
        span.provider_attempts.append({
            "provider": provider,
            "model": model,
            "status": status,
            "latency_ms": round(latency_ms, 1),
            "error": error,
        })


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        span = current_trace()
        if span:
            return f"[{span.request_id}] {base}"
        return base


def setup_logging(level: str = "info") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root = logging.getLogger("unified_router")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
