import os
import json
import yaml
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "unified-router"
CONFIG_FILE = CONFIG_DIR / "config.yml"
AUTH_FILE = Path.home() / ".local" / "share" / "opencode" / "auth.json"

DEFAULT_CONFIG = {
    "server": {
        "host": "127.0.0.1",
        "port": 3333,
        "log_level": "info",
    },
    "priority": [
        "openrouter",
        "groq",
        "cerebras",
        "cloudflare",
        "nvidia",
        "gemini",
        "mistral",
        "cohere",
        "huggingface",
        "deepseek",
        "github_models",
    ],
    "providers": {
        "openrouter": {
            "base_url": "https://openrouter.ai/api/v1",
            "env_key": "OPENROUTER_API_KEY",
        },
        "groq": {
            "base_url": "https://api.groq.com/openai/v1",
            "env_key": "GROQ_API_KEY",
        },
        "cerebras": {
            "base_url": "https://api.cerebras.ai/v1",
            "env_key": "CEREBRAS_API_KEY",
        },
        "cloudflare": {
            "base_url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
            "env_account_id": "CLOUDFLARE_ACCOUNT_ID",
            "env_key": "CLOUDFLARE_API_TOKEN",
        },
        "nvidia": {
            "base_url": "https://integrate.api.nvidia.com/v1",
            "env_key": "NVIDIA_API_KEY",
        },
        "gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "env_key": "GEMINI_API_KEY",
            "alt_env_keys": ["GOOGLE_API_KEY"],
        },
        "mistral": {
            "base_url": "https://api.mistral.ai/v1",
            "env_key": "MISTRAL_API_KEY",
        },
        "cohere": {
            "base_url": "https://api.cohere.ai/v1",
            "env_key": "COHERE_API_KEY",
        },
        "huggingface": {
            "base_url": "https://router.huggingface.co/hf-inference/v1",
            "env_key": "HF_TOKEN",
            "alt_env_keys": ["HUGGINGFACE_TOKEN"],
        },
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "env_key": "DEEPSEEK_API_KEY",
        },
        "github_models": {
            "base_url": "https://models.inference.ai.azure.com/v1",
            "env_key": "GITHUB_TOKEN",
            "alt_env_keys": ["GITHUB_API_KEY"],
        },
    },
}

PROVIDER_NAMES = {
    "openrouter": "OpenRouter",
    "groq": "Groq",
    "cerebras": "Cerebras",
    "cloudflare": "Cloudflare Workers AI",
    "nvidia": "NVIDIA NIM",
    "gemini": "Google Gemini",
    "mistral": "Mistral AI",
    "cohere": "Cohere",
    "huggingface": "HuggingFace",
    "deepseek": "DeepSeek",
    "github_models": "GitHub Models",
}

PROVIDER_SIGNUP_URLS = {
    "openrouter": "https://openrouter.ai/settings/keys",
    "groq": "https://console.groq.com/keys",
    "cerebras": "https://inference.cerebras.ai/",
    "cloudflare": "https://dash.cloudflare.com/?to=/:account/workers/ai",
    "nvidia": "https://build.nvidia.com",
    "gemini": "https://aistudio.google.com/app/apikey",
    "mistral": "https://console.mistral.ai/api-keys/",
    "cohere": "https://dashboard.cohere.com/api-keys",
    "huggingface": "https://huggingface.co/settings/tokens",
    "deepseek": "https://platform.deepseek.com/api_keys",
    "github_models": "https://github.com/settings/tokens",
}


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
    config["providers"] = {k: dict(v) for k, v in config["providers"].items()}

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
