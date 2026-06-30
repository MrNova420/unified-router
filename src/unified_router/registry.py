from __future__ import annotations

from typing import Any

from .provider import BaseProvider, RateLimitError, ProviderError
from .providers.openai_compat import OpenAICompatibleProvider
from .providers.gemini import GeminiProvider
from .providers.cloudflare import CloudflareProvider


PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {
    "openrouter": OpenAICompatibleProvider,
    "groq": OpenAICompatibleProvider,
    "cerebras": OpenAICompatibleProvider,
    "nvidia": OpenAICompatibleProvider,
    "mistral": OpenAICompatibleProvider,
    "cohere": OpenAICompatibleProvider,
    "huggingface": OpenAICompatibleProvider,
    "deepseek": OpenAICompatibleProvider,
    "github_models": OpenAICompatibleProvider,
    "gemini": GeminiProvider,
    "cloudflare": CloudflareProvider,
}


def build_providers(config: dict[str, Any]) -> dict[str, BaseProvider]:
    providers: dict[str, BaseProvider] = {}
    pconfigs = config.get("providers", {})
    for name, pcls in PROVIDER_CLASSES.items():
        if name not in pconfigs:
            continue
        pcfg = pconfigs[name]
        if not pcfg.get("api_key"):
            continue
        if pcls.requires_account_id and not pcfg.get("account_id"):
            continue
        instance = pcls(pcfg)
        instance.name = pcfg.get("display_name", instance.name or name)
        if not instance.base_url:
            instance.base_url = pcfg.get("base_url", "")
        providers[name] = instance
    return providers
