from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from .provider import RateLimitError, ProviderError, BaseProvider

logger = logging.getLogger(__name__)


class Router:
    def __init__(
        self,
        providers: dict[str, BaseProvider],
        priority: list[str],
    ):
        self.providers = providers
        self.priority = priority
        self._all_models: list[dict] = []
        self._models_last_fetch: float = 0
        self._models_lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            timeout=30,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
        )

    def get_active_providers(self) -> dict[str, BaseProvider]:
        return {
            name: p
            for name, p in self.providers.items()
            if p.is_configured and not p.is_rate_limited
        }

    async def _fetch_from_provider(self, name: str, prov: BaseProvider) -> list[dict]:
        try:
            return await prov.fetch_models(self._http)
        except Exception as e:
            logger.debug("Failed to fetch models from %s: %s", name, e)
            return []

    async def fetch_all_models(self, force: bool = False) -> list[dict]:
        async with self._models_lock:
            now = time.time()
            if not force and self._all_models and (now - self._models_last_fetch) < 120:
                return self._all_models

            tasks = []
            for name, prov in self.providers.items():
                if prov.is_configured:
                    tasks.append(self._fetch_from_provider(name, prov))

            results = await asyncio.gather(*tasks)
            seen = set()
            models = []
            for models_list in results:
                for m in models_list:
                    mid = m.get("id", "")
                    if mid and mid not in seen:
                        seen.add(mid)
                        models.append(m)

            self._all_models = models
            self._models_last_fetch = now
            return models

    def has_model(self, provider_name: str, model: str, available_models: set[str]) -> bool:
        return model in available_models

    async def route(
        self,
        model: str,
        messages: list,
        **kwargs,
    ) -> dict:
        if not self.providers:
            raise ProviderError("No providers configured")

        await self.fetch_all_models(force=False)

        all_models_map: dict[str, set[str]] = {}
        for name, prov in self.providers.items():
            if prov.is_configured:
                try:
                    models = await self._fetch_from_provider(name, prov)
                    all_models_map[name] = {m["id"] for m in models}
                except Exception:
                    all_models_map[name] = set()

        last_error: Exception | None = None
        for pname in self.priority:
            prov = self.providers.get(pname)
            if not prov or not prov.is_configured:
                continue
            if prov.is_rate_limited:
                logger.info("Skipping %s (rate limited until %.0f)", pname, prov._rate_limited_until)
                continue

            provider_models = all_models_map.get(pname, set())
            matches = [m for m in provider_models if model in m]
            if not matches:
                logger.debug("Skipping %s (model %s not found)", pname, model)
                continue

            try:
                logger.info("Routing to %s (model: %s)", pname, model)
                result = await prov.chat(self._http, model, messages, **kwargs)
                return result
            except RateLimitError as e:
                logger.warning("%s hit rate limit: %s", pname, e)
                last_error = e
                continue
            except ProviderError as e:
                logger.warning("%s error: %s", pname, e)
                last_error = e
                continue
            except Exception as e:
                logger.error("%s unexpected error: %s", pname, e)
                last_error = e
                continue

        raise ProviderError(
            f"All providers failed for model '{model}'. Last error: {last_error}"
        )

    async def close(self):
        await self._http.aclose()
