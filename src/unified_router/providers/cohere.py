from __future__ import annotations

from typing import Any

from ..provider import BaseProvider, RateLimitError, ProviderError


class CohereProvider(BaseProvider):
    name = "cohere"

    async def fetch_models(self, client: Any) -> list[dict]:
        resp = await client.get(
            f"{self.base_url}/models",
            headers=self.get_headers(),
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        models = data.get("models", [])
        return [
            {"id": m["id"], "name": m.get("name", m["id"]), "provider": self.name}
            for m in models
        ]

    async def chat(
        self, client: Any, model: str, messages: list, **kwargs
    ) -> dict:
        if self.is_rate_limited:
            raise RateLimitError(f"{self.name} is rate limited")

        system = ""
        chat_history: list[dict] = []
        for msg in messages[:-1]:
            role = msg["role"]
            content = msg.get("content", "")
            if isinstance(content, list):
                text = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
            else:
                text = str(content)
            if role == "system":
                system = text
            else:
                chat_history.append({"role": role, "message": text})

        user_msg = messages[-1]
        user_content = user_msg.get("content", "")
        if isinstance(user_content, list):
            user_text = " ".join(p.get("text", "") for p in user_content if p.get("type") == "text")
        else:
            user_text = str(user_content)

        body: dict[str, Any] = {
            "model": model,
            "message": user_text,
            "chat_history": chat_history,
        }
        if system:
            body["preamble"] = system
        if kwargs.get("max_tokens"):
            body["max_tokens"] = kwargs["max_tokens"]
        if kwargs.get("temperature"):
            body["temperature"] = kwargs["temperature"]
        if kwargs.get("top_p"):
            body["p"] = kwargs["top_p"]

        resp = await client.post(
            f"{self.base_url}/chat",
            headers=self.get_headers(),
            json=body,
            timeout=120,
        )

        if resp.status_code == 429:
            self.mark_rate_limited()
            raise RateLimitError(f"{self.name} rate limited")
        if resp.status_code == 401:
            raise ProviderError(f"{self.name} unauthorized: check API key")
        if resp.status_code != 200:
            raise ProviderError(f"{self.name} error {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        self.mark_success()

        return {
            "id": data.get("generation_id", ""),
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": data.get("text", ""),
                },
                "finish_reason": data.get("finish_reason", "complete"),
            }],
            "usage": {
                "prompt_tokens": data.get("meta", {}).get("billed_units", {}).get("input_tokens", 0),
                "completion_tokens": data.get("meta", {}).get("billed_units", {}).get("output_tokens", 0),
            },
            "model": model,
        }

    def get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
