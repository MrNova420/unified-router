from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

from .provider import BaseProvider

logger = logging.getLogger(__name__)

PLUGINS_DIR = Path.home() / ".config" / "unified-router" / "plugins"


def discover_plugins() -> dict[str, type[BaseProvider]]:
    result: dict[str, type[BaseProvider]] = {}
    if not PLUGINS_DIR.exists():
        return result
    for py in sorted(PLUGINS_DIR.glob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"ur_plugin_{py.stem}", py)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseProvider) and attr is not BaseProvider:
                    result[py.stem] = attr
                    logger.info("Loaded provider plugin '%s' from %s", attr_name, py.name)
        except Exception as e:
            logger.warning("Failed to load plugin %s: %s", py.name, e)
    return result


def build_plugin_providers(config: dict[str, Any]) -> dict[str, BaseProvider]:
    classes = discover_plugins()
    providers: dict[str, BaseProvider] = {}
    pconfigs = config.get("plugins", {})
    for name, cls in classes.items():
        pcfg = pconfigs.get(name, {})
        if not pcfg.get("api_key"):
            continue
        instance = cls(pcfg)
        if not instance.name:
            instance.name = name
        if not instance.base_url:
            instance.base_url = pcfg.get("base_url", "")
        providers[name] = instance
    return providers