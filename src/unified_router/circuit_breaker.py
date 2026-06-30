"""Circuit breaker pattern for resilient provider calls."""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum, auto
from typing import Callable

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = auto()    # Normal operation, requests flow through
    OPEN = auto()      # Failing fast, no requests allowed
    HALF_OPEN = auto() # Testing if provider recovered


class CircuitBreaker:
    """Production-grade circuit breaker per provider."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.half_open_calls = 0
        self._lock = asyncio.Lock()

    def _record_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.half_open_calls = 0

    def _record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker OPEN for %s (failures: %d)",
                self.name, self.failure_count,
            )

    async def call(self, coro_fn: Callable):
        async with self._lock:
            if self.state == CircuitState.OPEN:
                if self.last_failure_time and (time.time() - self.last_failure_time) > self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    logger.info("Circuit breaker HALF-OPEN for %s", self.name)
                else:
                    raise Exception(f"Circuit breaker OPEN for {self.name}")

            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.half_open_max_calls:
                    self.state = CircuitState.OPEN
                    raise Exception(f"Circuit breaker OPEN for {self.name}")
                self.half_open_calls += 1

        try:
            # Always call the function and await its result
            result = await coro_fn()
            async with self._lock:
                self._record_success()
            return result
        except Exception:
            async with self._lock:
                self._record_failure()
            raise

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN