from __future__ import annotations

import json
import os
import secrets
import subprocess
from pathlib import Path
from typing import Any

import yaml
import re


ROUTER_KEY_FILE = Path.home() / ".config" / "unified-router" / ".router_key"


def generate_router_key() -> str:
    key = f"ur-sk-{secrets.token_hex(24)}"
    ROUTER_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    ROUTER_KEY_FILE.write_text(key, encoding="utf-8")
    os.chmod(ROUTER_KEY_FILE, 0o600)
    return key


def get_router_key() -> str:
    if ROUTER_KEY_FILE.exists():
        key = ROUTER_KEY_FILE.read_text(encoding="utf-8").strip()
        if key.startswith("ur-sk-"):
            return key
    return generate_router_key()

def _get_windows_home() -> Path | None:
    """On WSL, return Path to Windows home directory (e.g. /mnt/c/Users/kayde)."""
    if not os.environ.get("WSL_DISTRO_NAME"):
        return None
    try:
        result = subprocess.run(
            ["cmd.exe", "/c", "echo", "%USERPROFILE%"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            win_path = result.stdout.strip()
            if win_path and "\\" in win_path:
                drive = win_path[0].lower()
                rest = win_path[2:].replace("\\", "/")
                win_home = Path(f"/mnt/{drive}{rest}")
                if win_home.exists():
                    return win_home
    except Exception:
        pass
    return None


def _clean_jsonc(raw: str) -> str:
    result = raw
    # 1. Strip BOM
    result = result.lstrip("\ufeff")
    # 2. Remove control characters (keep \n, \r, \t)
    result = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", result)
    # 3. Strip // comments (handle URLs with // by only stripping when preceded by non-colon)
    result = re.sub(r"(?<!:)\s*//.*", "", result)
    # 4. Strip /* */ block comments
    result = re.sub(r"/\*[\s\S]*?\*/", "", result)
    # 5. Strip trailing commas before ] or } — repeat for nested cases
    for _ in range(5):
        prev = result
        result = re.sub(r",\s*([\]}])", r"\1", result)
        if result == prev:
            break
    return result


def _write_opencode_cfg(opencode_cfg: Path, base_url: str, router_key: str = ""):
    opencode_cfg.parent.mkdir(parents=True, exist_ok=True)

    if not opencode_cfg.exists():
        initial_data = {
            "$schema": "https://opencode.ai/config.json",
            "provider": {}
        }
        opencode_cfg.write_text(json.dumps(initial_data, indent=2), encoding="utf-8")

    content = opencode_cfg.read_text(encoding="utf-8")
    json_content = _clean_jsonc(content)
    data = json.loads(json_content)

    api_key = router_key or get_router_key()

    providers = data.setdefault("provider", {})
    providers["unified-router"] = {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Unified Router",
        "options": {
            "baseURL": base_url,
            "apiKey": api_key
        }
    }

    opencode_cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")


def configure_opencode(base_url: str = "http://localhost:3333/v1", router_key: str = ""):
    try:
        key = router_key or get_router_key()

        linux_cfg = Path.home() / ".config" / "opencode" / "opencode.jsonc"
        _write_opencode_cfg(linux_cfg, base_url, key)

        win_home = _get_windows_home()
        if win_home:
            win_cfg = win_home / ".config" / "opencode" / "opencode.jsonc"
            _write_opencode_cfg(win_cfg, base_url, key)

        return True, "Successfully configured OpenCode"
    except Exception as e:
        return False, str(e)

from .registry import load_registry

CONFIG_DIR = Path.home() / ".config" / "unified-router"
CONFIG_FILE = CONFIG_DIR / "config.yml"
AUTH_FILE = Path.home() / ".local" / "share" / "opencode" / "auth.json"
ENV_FILE = Path.home() / ".config" / "unified-router" / ".env"


def _load_dotenv(path: Path | None = None):
    p = path or ENV_FILE
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


DEFAULT_PRIORITY = [
    "openrouter",   # 1: most free models, no phone/card
    "nvidia",       # 2: 40 RPM no daily cap, phone verify
    "gemini",       # 3: Google's generous free tier
    "opencode_zen", # 4: OpenCode's own free models
    "xai",          # 5: Grok credits ($25 + $150/mo)
    "groq",         # 6: fastest inference, generous limits
    "cerebras",     # 7: fast inference, good limits
    "deepseek",     # 8: very cheap paid models
    "mistral",      # 9: 1B tokens/mo, phone verify
    "codestral",    # 10: coding model, phone verify
    "together",     # 11: $1 trial
    "fireworks",    # 12: $1 trial
    "deepinfra",    # 13: cheap paid
    "github_models",# 14: free with copilot
    "cohere",       # 15: 1000 req/mo, no phone
    "huggingface",  # 16: $0.10/mo, no phone
    "cloudflare",   # 17: 10k neurons/day
    "ai302",        # 18
    "nebius",       # 19
    "novita",       # 20
    "hyperbolic",   # 21
    "sambanova",    # 22
    "scaleway",     # 23
    "venice",       # 24
    "baseten",      # 25
    "gmi_cloud",    # 26
    "io_net",       # 27
    "cortecs",      # 28
    "frogbot",      # 29
    "minimax",      # 30
    "moonshot",     # 31
    "ai21",         # 32
    "upstage",      # 33
    "nlp_cloud",    # 34
    "alibaba",      # 35
    "digitalocean", # 36
    "ovhcloud",     # 37
    "stackit",      # 38
    "sap_ai",       # 39
    "snowflake",    # 40
    "ollama_cloud", # 41
    "vercel_gateway", # 42
    "modal",        # 43
    "inference_net",# 44
]


def _build_default_config() -> dict[str, Any]:
    registry = load_registry()
    providers: dict[str, dict[str, Any]] = {}

    all_registered = {}
    all_registered.update(registry.get("openai_compatible", {}))
    all_registered.update(registry.get("custom", {}))

    for name, reg in all_registered.items():
        entry: dict[str, Any] = {
            "base_url": reg.get("base_url", ""),
            "env_key": reg.get("env_key", ""),
        }
        if reg.get("alt_env_keys"):
            entry["alt_env_keys"] = reg["alt_env_keys"]
        if reg.get("env_account_id"):
            entry["env_account_id"] = reg["env_account_id"]
        providers[name] = entry

    priority = [p for p in DEFAULT_PRIORITY if p in providers]
    for name in providers:
        if name not in priority:
            priority.append(name)

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


def get_provider_type(name: str) -> str:
    info = get_provider_info(name)
    return info.get("type", "free")


PROVIDER_TYPE_BADGES = {
    "free": "[Easy]",
    "phone": "[Phone]",
    "credits": "[Credits]",
    "paid": "[Paid]",
}

PROVIDER_TYPE_COLORS = {
    "free": "green",
    "phone": "yellow",
    "credits": "blue",
    "paid": "dim",
}


def resolve_env(value: str) -> str:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


def _read_auth_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return None


AUTH_KEY_MAP = {
    "nvidia": "nvidia",
    "openrouter": "openrouter",
    "opencode": "opencode",
    "opencode-go": "opencode_zen",
    "groq": "groq",
    "google": "gemini",
}


def _match_auth_key(auth: dict, provider_name: str) -> str | None:
    for k, v in auth.items():
        mapped = AUTH_KEY_MAP.get(k.lower())
        if mapped == provider_name:
            if isinstance(v, str):
                return v
            if isinstance(v, dict) and "key" in v:
                return v["key"]
    return None


def detect_api_key(pcfg: dict) -> str | None:
    key = os.environ.get(pcfg.get("env_key", ""))
    if key:
        return key
    for alt in pcfg.get("alt_env_keys", []):
        key = os.environ.get(alt)
        if key:
            return key

    provider_name = pcfg.get("env_key", "").replace("_API_KEY", "").replace("_TOKEN", "").lower()

    auth_paths = [AUTH_FILE]
    win_home = _get_windows_home()
    if win_home:
        auth_paths.append(win_home / ".local" / "share" / "opencode" / "auth.json")

    for auth_path in auth_paths:
        auth = _read_auth_json(auth_path)
        if auth:
            matched = _match_auth_key(auth, provider_name)
            if matched:
                return matched

    return None


def detect_account_id(pcfg: dict) -> str | None:
    env_var = pcfg.get("env_account_id")
    if env_var:
        return os.environ.get(env_var)
    return None


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    _load_dotenv()
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
