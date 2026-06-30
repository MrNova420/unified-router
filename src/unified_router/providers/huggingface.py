from __future__ import annotations

from typing import Any

from ..provider import BaseProvider, RateLimitError, ProviderError
from .openai_compat import OpenAICompatibleProvider


class HuggingFaceProvider(OpenAICompatibleProvider):
    name = "huggingface"

    async def fetch_models(self, client: Any) -> list[dict]:
        resp = await client.get(
            f"{self.base_url}/models",
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
        return [{"id": m["id"], "provider": self.name} for m in models]

    def get_headers(self) -> dict[str, str]:
        h = super().get_headers()
        h["x-use-cache"] = "false"
        return h
