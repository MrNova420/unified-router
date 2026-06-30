from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml

from .provider import BaseProvider
from .providers.openai_compat import OpenAICompatibleProvider

REGISTRY_PATH = Path(__file__).parent / "registry.yaml"

_registry_cache: dict[str, Any] | None = None


def load_registry() -> dict[str, Any]:
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        _registry_cache = yaml.safe_load(f)
    return _registry_cache


def _get_provider_class(adapter: str | None) -> type[BaseProvider]:
    if adapter is None:
        return OpenAICompatibleProvider
    mod_path = f"unified_router.providers.{adapter}"
    mod = importlib.import_module(mod_path)
    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if isinstance(attr, type) and issubclass(attr, BaseProvider) and attr is not BaseProvider:
            return attr
    raise ValueError(f"No provider class found in module {mod_path}")


def build_providers(config: dict[str, Any]) -> dict[str, BaseProvider]:
    registry = load_registry()
    providers: dict[str, BaseProvider] = {}
    pconfigs = config.get("providers", {})

    for name, reg in registry.get("openai_compatible", {}).items():
        if name not in pconfigs:
            continue
        pcfg = pconfigs[name]
        if not pcfg.get("api_key"):
            continue
        instance = OpenAICompatibleProvider(pcfg)
        instance.name = reg.get("name", name)
        if not instance.base_url:
            instance.base_url = pcfg.get("base_url", reg.get("base_url", ""))
        providers[name] = instance

    for name, reg in registry.get("custom", {}).items():
        if name not in pconfigs:
            continue
        pcfg = pconfigs[name]
        if not pcfg.get("api_key"):
            continue
        adapter_name = reg.get("adapter", "")
        cls = _get_provider_class(adapter_name)
        if cls.requires_account_id and not pcfg.get("account_id") and not reg.get("env_account_id"):
            continue
        instance = cls(pcfg)
        instance.name = reg.get("name", name)
        if not instance.base_url:
            instance.base_url = pcfg.get("base_url", reg.get("base_url", ""))
        providers[name] = instance

    return providers
