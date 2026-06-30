from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from .registry import load_registry

CONFIG_DIR = Path.home() / ".config" / "unified-router"
CONFIG_FILE = CONFIG_DIR / "config.yml"
AUTH_FILE = Path.home() / ".local" / "share" / "opencode" / "auth.json"


def _build_default_config() -> dict[str, Any]:
    registry = load_registry()
    priority: list[str] = []
    providers: dict[str, dict[str, Any]] = {}

    for name, reg in registry.get("openai_compatible", {}).items():
        priority.append(name)
        entry: dict[str, Any] = {
            "base_url": reg.get("base_url", ""),
            "env_key": reg.get("env_key", ""),
        }
        if reg.get("alt_env_keys"):
            entry["alt_env_keys"] = reg["alt_env_keys"]
        providers[name] = entry

    for name, reg in registry.get("custom", {}).items():
        priority.append(name)
        entry = {
            "base_url": reg.get("base_url", ""),
            "env_key": reg.get("env_key", ""),
        }
        if reg.get("alt_env_keys"):
            entry["alt_env_keys"] = reg["alt_env_keys"]
        if reg.get("env_account_id"):
            entry["env_account_id"] = reg["env_account_id"]
        providers[name] = entry

    return {
        "server": {
            "host": "127.0.0.1",
            "port": 3333,
            "log_level": "info",
        },
        "priority": priority,
        "providers": providers,
    }


DEFAULT_CONFIG = _build_default_config()


def get_provider_info(name: str) -> dict[str, Any]:
    registry = load_registry()
    for section in ("openai_compatible", "custom"):
        reg = registry.get(section, {}).get(name)
        if reg:
            return reg
    return {}


def resolve_env(value: str) -> str:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


def detect_api_key(pcfg: dict) -> str | None:
    key = os.environ.get(pcfg.get("env_key", ""))
    if key:
        return key
    for alt in pcfg.get("alt_env_keys", []):
        key = os.environ.get(alt)
        if key:
            return key

    if AUTH_FILE.exists():
        try:
            auth = json.loads(AUTH_FILE.read_text())
            provider_name = pcfg.get("env_key", "").replace("_API_KEY", "").replace("_TOKEN", "").lower()
            for k, v in auth.items():
                if provider_name in k.lower() and isinstance(v, str):
                    return v
        except Exception:
            pass

    return None


def detect_account_id(pcfg: dict) -> str | None:
    env_var = pcfg.get("env_account_id")
    if env_var:
        return os.environ.get(env_var)
    return None


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else CONFIG_FILE

    config = DEFAULT_CONFIG.copy()
    config["priority"] = list(DEFAULT_CONFIG["priority"])
    config["providers"] = {k: dict(v) for k, v in DEFAULT_CONFIG["providers"].items()}

    if cfg_path.exists():
        raw = yaml.safe_load(cfg_path.read_text())
        if raw:
            if "priority" in raw:
                config["priority"] = raw["priority"]
            if "server" in raw:
                config["server"].update(raw["server"])
            if "providers" in raw:
                for name, pcfg in raw["providers"].items():
                    if name in config["providers"]:
                        config["providers"][name].update(pcfg)
                    else:
                        config["providers"][name] = dict(pcfg)

    for name, pcfg in config["providers"].items():
        raw_key = pcfg.get("api_key", "")
        if raw_key:
            pcfg["api_key"] = resolve_env(raw_key)
        else:
            detected = detect_api_key(pcfg)
            if detected:
                pcfg["api_key"] = detected

        raw_acct = pcfg.get("account_id", "")
        if raw_acct:
            pcfg["account_id"] = resolve_env(raw_acct)
        else:
            detected = detect_account_id(pcfg)
            if detected:
                pcfg["account_id"] = detected

    return config
