"""
app_config.py - Application configuration persistence for UIATools.

Stores settings in %APPDATA%/UIATools/config.json. API keys are NOT
stored here - they live in Windows Credential Manager via keyring.
"""

from __future__ import annotations

import json
import os
from typing import Any

_APP_NAME = "UIATools"
_KEYRING_SERVICE = "UIATools"

DEFAULT_CONFIG: dict[str, Any] = {
    "last_repository": "",
    "capture_max_depth": 100,
    "recorder": {
        "pause_hotkey": "Ctrl+Shift+F12",
    },
    "llm": {
        "model": "ollama/qwen2.5-coder:14b",
        "api_base": None,
        "temperature": 0.2,
        "max_tokens": 4096,
    },
}


def _config_dir() -> str:
    base = os.environ.get("APPDATA", os.path.expanduser("~"))
    return os.path.join(base, _APP_NAME)


def _config_path() -> str:
    return os.path.join(_config_dir(), "config.json")


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    """Load config.json, merged over defaults. Missing file -> defaults."""
    try:
        with open(_config_path(), encoding="utf-8") as f:
            user_cfg = json.load(f)
        return _deep_merge(DEFAULT_CONFIG, user_cfg)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(config: dict[str, Any]):
    """Write config to %APPDATA%/UIATools/config.json."""
    os.makedirs(_config_dir(), exist_ok=True)
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


# ── API key storage (Windows Credential Manager via keyring) ──


def get_api_key(provider: str) -> str | None:
    """Read an API key from the credential store, env-var fallback."""
    try:
        import keyring

        key = keyring.get_password(_KEYRING_SERVICE, f"{provider}_api_key")
        if key:
            return key
    except Exception:
        pass
    env_names = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    env_var = env_names.get(provider.lower())
    return os.environ.get(env_var) if env_var else None


def set_api_key(provider: str, key: str):
    """Store an API key in the credential store."""
    import keyring

    keyring.set_password(_KEYRING_SERVICE, f"{provider}_api_key", key)


def delete_api_key(provider: str):
    """Remove a stored API key."""
    try:
        import keyring

        keyring.delete_password(_KEYRING_SERVICE, f"{provider}_api_key")
    except Exception:
        pass
