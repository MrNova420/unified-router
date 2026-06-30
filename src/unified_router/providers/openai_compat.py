from __future__ import annotations

from typing import Any
from ..provider import BaseProvider, RateLimitError, ProviderError


class OpenAICompatibleProvider(BaseProvider):
    name: str = ""
    models_endpoint: str = "/models"

    async def fetch_models(self, client: Any) -> list[dict]:
        resp = await client.get(
            f"{self.base_url}{self.models_endpoint}",
            headers=self.get_headers(),
            timeout=15,
        )
        if resp.status_code == 401:
            return []
        if resp.status_code == 429:
            self.mark_rate_limited()
            return []
        if resp.status_code != 200:
            return []
        data = resp.json()
        models = data.get("data", [])
        for m in models:
            if "provider" not in m or not m.get("provider"):
                m["provider"] = self.name or "unknown"
        return models

    async def chat(
        self, client: Any, model: str, messages: list, **kwargs
    ) -> dict:
        if self.is_rate_limited:
            raise RateLimitError(f"{self.name} is rate limited")

        body = {
            "model": model,
            "messages": messages,
            **{k: v for k, v in kwargs.items() if v is not None},
        }

        resp = await client.post(
            f"{self.base_url}/chat/completions",
            headers=self.get_headers(),
            json=body,
            timeout=120,
        )

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", "60"))
            self.mark_rate_limited(retry_after)
            raise RateLimitError(f"{self.name} rate limited: {resp.text}")

        if resp.status_code == 401:
            raise ProviderError(f"{self.name} unauthorized: check API key")

        if resp.status_code != 200:
            raise ProviderError(
                f"{self.name} returned {resp.status_code}: {resp.text[:500]}"
            )

        self.mark_success()
        return resp.json()
