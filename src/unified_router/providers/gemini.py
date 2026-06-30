from __future__ import annotations

from typing import Any
from ..provider import BaseProvider, RateLimitError, ProviderError


class GeminiProvider(BaseProvider):
    name = "gemini"

    async def fetch_models(self, client: Any) -> list[dict]:
        url = (
            f"{self.base_url.rstrip('/openai')}/models"
            f"?key={self.api_key}"
        )
        resp = await client.get(url, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        models = data.get("models", [])
        result = []
        for m in models:
            name = m.get("name", "").replace("models/", "")
            result.append({
                "id": name,
                "name": m.get("displayName", name),
                "provider": self.name,
            })
        return result

    async def chat(
        self, client: Any, model: str, messages: list, **kwargs
    ) -> dict:
        if self.is_rate_limited:
            raise RateLimitError("Gemini is rate limited")

        gemini_messages = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                role = "user"
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                content = "\n".join(text_parts)
            gemini_messages.append({"role": role, "parts": [{"text": content}]})

        system_instruction = None
        for msg in messages:
            if msg["role"] == "system":
                text = msg.get("content", "")
                if isinstance(text, list):
                    text = " ".join(p.get("text", "") for p in text if p.get("type") == "text")
                system_instruction = {"parts": [{"text": text}]}
                break

        body: dict[str, Any] = {
            "contents": gemini_messages,
        }
        if system_instruction:
            body["system_instruction"] = system_instruction

        generation_config = {}
        if kwargs.get("temperature") is not None:
            generation_config["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens") is not None:
            generation_config["maxOutputTokens"] = kwargs["max_tokens"]
        if kwargs.get("top_p") is not None:
            generation_config["topP"] = kwargs["top_p"]
        if generation_config:
            body["generationConfig"] = generation_config

        url = (
            f"{self.base_url.rstrip('/openai')}/models/{model}:generateContent"
            f"?key={self.api_key}"
        )

        resp = await client.post(url, json=body, timeout=120)

        if resp.status_code == 429:
            self.mark_rate_limited()
            raise RateLimitError("Gemini rate limited")

        if resp.status_code != 200:
            raise ProviderError(f"Gemini error {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        candidate = data.get("candidates", [{}])[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        text = " ".join(p.get("text", "") for p in parts)
        finish_reason = candidate.get("finishReason", "STOP")

        return {
            "id": data.get("id", ""),
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,
                },
                "finish_reason": finish_reason.lower() if finish_reason else "stop",
            }],
            "usage": data.get("usageMetadata", {}),
            "model": model,
        }

    def get_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}
