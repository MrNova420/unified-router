from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

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

    def _build_body(self, model: str, messages: list, **kwargs) -> dict:
        body = {
            "model": model,
            "messages": messages,
        }
        stream = kwargs.pop("stream", False)
        for k, v in kwargs.items():
            if v is not None:
                body[k] = v
        if stream:
            body["stream"] = True
        return body

    async def chat(
        self, client: Any, model: str, messages: list, **kwargs
    ) -> dict:
        if self.is_rate_limited:
            raise RateLimitError(f"{self.name} is rate limited")

        kwargs.pop("stream", None)
        body = self._build_body(model, messages, **kwargs)

        start = time.time()
        resp = await client.post(
            f"{self.base_url}/chat/completions",
            headers=self.get_headers(),
            json=body,
            timeout=120,
        )

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", "60"))
            self.mark_rate_limited(retry_after)
            self.mark_error()
            raise RateLimitError(f"{self.name} rate limited: {resp.text}", retry_after=retry_after)

        if resp.status_code == 401:
            self.mark_error()
            raise ProviderError(f"{self.name} unauthorized: check API key")

        if resp.status_code != 200:
            self.mark_error()
            raise ProviderError(
                f"{self.name} returned {resp.status_code}: {resp.text[:500]}"
            )

        data = resp.json()
        usage = data.get("usage", {})
        tokens = usage.get("total_tokens", 0)
        self.mark_success(time.time() - start, tokens)
        return data

    async def stream(
        self, client: Any, model: str, messages: list, **kwargs
    ) -> AsyncIterator[bytes]:
        if self.is_rate_limited:
            raise RateLimitError(f"{self.name} is rate limited")

        body = self._build_body(model, messages, stream=True, **kwargs)

        start = time.time()
        async with client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self.get_headers(),
            json=body,
            timeout=120,
        ) as resp:
            if resp.status_code == 429:
                self.mark_rate_limited()
                self.mark_error()
                raise RateLimitError(f"{self.name} rate limited")
            if resp.status_code == 401:
                self.mark_error()
                raise ProviderError(f"{self.name} unauthorized")
            if resp.status_code != 200:
                text = await resp.aread()
                self.mark_error()
                raise ProviderError(f"{self.name} {resp.status_code}: {text[:300]}")

            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    yield (line + "\n\n").encode()
                elif line == "data: [DONE]":
                    yield b"data: [DONE]\n\n"

        self.mark_success(time.time() - start)
