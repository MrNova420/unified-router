"""Request queue with backpressure for graceful provider outages."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class QueuedRequest:
    request_id: str
    coro_fn: Callable
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())
    enqueued_at: float = field(default_factory=time.time)
    timeout: float = 300.0


class RequestQueue:
    def __init__(self, max_size: int = 100, worker_count: int = 5, request_timeout: float = 300.0):
        self.max_size = max_size
        self.worker_count = worker_count
        self.request_timeout = request_timeout
        self._queue: asyncio.Queue[QueuedRequest | None] = asyncio.Queue(maxsize=max_size)
        self._workers: list[asyncio.Task] = []
        self._active_count: int = 0
        self._total_enqueued: int = 0
        self._total_completed: int = 0
        self._total_timed_out: int = 0
        self._total_rejected: int = 0

    async def start(self):
        for _ in range(self.worker_count):
            t = asyncio.create_task(self._worker())
            self._workers.append(t)

    async def stop(self):
        for _ in self._workers:
            await self._queue.put(None)
        for t in self._workers:
            t.cancel()
        self._workers.clear()

    async def submit(self, request_id: str, coro_fn: Callable, timeout: float | None = None) -> Any:
        if self._queue.full():
            self._total_rejected += 1
            raise Exception("Request queue full — all providers likely rate limited. Try again later.")

        qr = QueuedRequest(
            request_id=request_id,
            coro_fn=coro_fn,
            timeout=timeout or self.request_timeout,
        )
        self._total_enqueued += 1
        await self._queue.put(qr)
        return await asyncio.wait_for(qr.future, timeout=qr.timeout)

    async def _worker(self):
        while True:
            try:
                qr = await self._queue.get()
                if qr is None:
                    break
                self._active_count += 1
                try:
                    result = await qr.coro_fn()
                    qr.future.set_result(result)
                    self._total_completed += 1
                except Exception as e:
                    if not qr.future.done():
                        qr.future.set_exception(e)
                finally:
                    self._active_count -= 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Queue worker error: %s", e)

    def stats(self) -> dict[str, Any]:
        return {
            "queue_size": self._queue.qsize(),
            "max_size": self.max_size,
            "active_workers": self._active_count,
            "total_enqueued": self._total_enqueued,
            "total_completed": self._total_completed,
            "total_timed_out": self._total_timed_out,
            "total_rejected": self._total_rejected,
        }
