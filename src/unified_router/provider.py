from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from .circuit_breaker import CircuitBreaker, CircuitState

logger = logging.getLogger(__name__)


class RouteError(Exception):
    pass


class RateLimitError(RouteError):
    def __init__(self, message: str = "Rate limited", *, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderError(RouteError):
    def __init__(self, message: str = "Provider error", *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AuthError(ProviderError):
    pass


class ModelNotFoundError(ProviderError):
    pass


class BaseProvider(ABC):
    name: str = ""
    requires_account_id: bool = False
    max_concurrency: int = 10

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.api_key = config.get("api_key", "")
        self.account_id = config.get("account_id", "")
        self.base_url = config.get("base_url", "")
        self._models_cache: list[dict] | None = None
        self._models_ts: float = 0
        self._rate_limited_until: float = 0
        self.consecutive_failures: int = 0
        self.latency_ema: float = 0.0
        self.request_count: int = 0
        self.error_count: int = 0
        self.token_count: int = 0
        self.circuit_breaker = CircuitBreaker(
            name=self.name or "unknown",
            failure_threshold=config.get("circuit_failure_threshold", 5),
            recovery_timeout=config.get("circuit_recovery_timeout", 60.0),
            half_open_max_calls=config.get("circuit_half_open_max", 3),
        )
        self._semaphore = asyncio.Semaphore(config.get("max_concurrency", self.max_concurrency))

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def is_rate_limited(self) -> bool:
        return time.time() < self._rate_limited_until

    @property
    def circuit_open(self) -> bool:
        return self.circuit_breaker.is_open

    @property
    def is_available(self) -> bool:
        return self.is_configured and not self.is_rate_limited and not self.circuit_open

    def mark_rate_limited(self, retry_after: int = 60):
        self._rate_limited_until = time.time() + retry_after
        self.consecutive_failures += 1

    def mark_success(self, latency: float = 0.0, tokens: int = 0):
        self.consecutive_failures = 0
        self.request_count += 1
        if latency > 0:
            if self.latency_ema == 0:
                self.latency_ema = latency
            else:
                self.latency_ema = 0.7 * self.latency_ema + 0.3 * latency
        self.token_count += tokens

    def mark_error(self):
        self.error_count += 1

    def mask_api_key(self) -> str:
        if not self.api_key or len(self.api_key) < 8:
            return "***"
        return self.api_key[:4] + "****" + self.api_key[-4:]

    @abstractmethod
    async def fetch_models(self, client: Any) -> list[dict]:
        ...

    @abstractmethod
    async def chat(
        self, client: Any, model: str, messages: list, **kwargs
    ) -> dict:
        ...

    async def stream(
        self, client: Any, model: str, messages: list, **kwargs
    ) -> AsyncIterator[bytes]:
        result = await self.chat(client, model, messages, **kwargs)
        import json
        chunk = {
            "id": result.get("id", "chatcmpl-unknown"),
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "content": result["choices"][0]["message"]["content"],
                },
                "finish_reason": None,
            }],
        }
        yield (f"data: {json.dumps(chunk)}\n\n").encode()
        done_chunk = {
            "id": result.get("id", "chatcmpl-unknown"),
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield (f"data: {json.dumps(done_chunk)}\n\n").encode()
        yield b"data: [DONE]\n\n"

    def get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def health_status(self) -> dict[str, Any]:
        cb = self.circuit_breaker
        return {
            "name": self.name,
            "configured": self.is_configured,
            "available": self.is_available,
            "rate_limited": self.is_rate_limited,
            "circuit_state": cb.state.name,
            "circuit_failures": cb.failure_count,
            "consecutive_failures": self.consecutive_failures,
            "requests": self.request_count,
            "errors": self.error_count,
            "tokens": self.token_count,
            "latency_ema_ms": round(self.latency_ema * 1000, 1) if self.latency_ema else 0,
            "api_key_masked": self.mask_api_key(),
        }
