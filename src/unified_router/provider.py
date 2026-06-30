from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any


class RouteError(Exception):
    pass


class RateLimitError(RouteError):
    pass


class ProviderError(RouteError):
    pass


class BaseProvider(ABC):
    name: str = ""
    requires_account_id: bool = False

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.api_key = config.get("api_key", "")
        self.account_id = config.get("account_id", "")
        self.base_url = config.get("base_url", "")
        self._models_cache: list[dict] | None = None
        self._models_ts: float = 0
        self._rate_limited_until: float = 0
        self.consecutive_failures: int = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def is_rate_limited(self) -> bool:
        return time.time() < self._rate_limited_until

    def mark_rate_limited(self, retry_after: int = 60):
        self._rate_limited_until = time.time() + retry_after
        self.consecutive_failures += 1

    def mark_success(self):
        self.consecutive_failures = 0

    @abstractmethod
    async def fetch_models(self, client: Any) -> list[dict]:
        ...

    @abstractmethod
    async def chat(
        self, client: Any, model: str, messages: list, **kwargs
    ) -> dict:
        ...

    def get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
