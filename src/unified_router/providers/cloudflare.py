from __future__ import annotations

from typing import Any
from ..provider import BaseProvider, RateLimitError, ProviderError


class CloudflareProvider(BaseProvider):
    name = "cloudflare"
    requires_account_id = True

    def get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def fetch_models(self, client: Any) -> list[dict]:
        acct = self.account_id or self.config.get("account_id", "")
        if not acct:
            return []
        url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/models/search?per_page=100"
        resp = await client.get(url, headers=self.get_headers(), timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        models = data.get("result", [])
        return [
            {"id": m["id"], "name": m.get("name", m["id"]), "provider": self.name}
            for m in models if "text" in m.get("task", {}).get("type", "").lower()
        ]

    async def chat(
        self, client: Any, model: str, messages: list, **kwargs
    ) -> dict:
        if self.is_rate_limited:
            raise RateLimitError("Cloudflare is rate limited")

        acct = self.account_id or self.config.get("account_id", "")
        if not acct:
            raise ProviderError("Cloudflare account_id not configured")

        system_text = None
        cf_messages = []
        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")
            if isinstance(content, list):
                text = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
            else:
                text = content
            if role == "system":
                system_text = text
            else:
                cf_messages.append({"role": role, "content": text})

        body: dict[str, Any] = {"messages": cf_messages}
        if system_text:
            body["system_prompt"] = system_text
        if kwargs.get("max_tokens"):
            body["max_tokens"] = kwargs["max_tokens"]
        if kwargs.get("temperature"):
            body["temperature"] = kwargs["temperature"]

        url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/v1/chat/completions"
        resp = await client.post(url, headers=self.get_headers(), json=body, timeout=120)

        if resp.status_code == 429:
            self.mark_rate_limited()
            raise RateLimitError("Cloudflare rate limited")
        if resp.status_code != 200:
            raise ProviderError(f"Cloudflare error {resp.status_code}: {resp.text[:500]}")

        self.mark_success()
        return resp.json()
