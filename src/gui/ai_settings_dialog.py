"""
ai_settings_dialog.py - Settings dialog for the AI provider (LiteLLM).

Provider switching is just a model-string change:
    ollama/<model>       local or remote Ollama (api_base override)
    anthropic/<model>    Claude via API key
    openai/<model>       OpenAI via API key

API keys are stored in Windows Credential Manager via keyring - never in
the config file.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Optional

from src.utils import app_config

_PROVIDER_PRESETS = {
    "Ollama (local/remote)": ("ollama/", "qwen2.5-coder:14b"),
    "Anthropic (Claude)": ("anthropic/", "claude-sonnet-4-5"),
    "OpenAI": ("openai/", "gpt-4o"),
    "Custom (raw model string)": ("", ""),
}


def _provider_from_model(model: str) -> str:
    if model.startswith("ollama/"):
        return "Ollama (local/remote)"
    if model.startswith("anthropic/"):
        return "Anthropic (Claude)"
    if model.startswith("openai/"):
        return "OpenAI"
    return "Custom (raw model string)"


def _keyring_provider(model: str) -> str:
    """Map a model string to the keyring provider slot."""
    if model.startswith("anthropic/"):
        return "anthropic"
    if model.startswith("openai/"):
        return "openai"
    return "custom"


class AISettingsDialog(tk.Toplevel):
    """Modal dialog to configure the LLM provider."""

    def __init__(
        self,
        parent: tk.Widget,
        config: dict,
        on_saved: Optional[Callable[[dict], None]] = None,
    ):
        super().__init__(parent)
        self.title("AI Settings")
        self.geometry("520x340")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.resizable(False, False)

        self._config = config
        self._on_saved = on_saved

        llm_cfg = config.get("llm", {})
        model = llm_cfg.get("model", "ollama/qwen2.5-coder:14b")

        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(1, weight=1)

        # Provider
        ttk.Label(body, text="Provider:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self._provider_var = tk.StringVar(value=_provider_from_model(model))
        provider_cb = ttk.Combobox(
            body,
            textvariable=self._provider_var,
            values=list(_PROVIDER_PRESETS.keys()),
            state="readonly",
        )
        provider_cb.grid(row=0, column=1, sticky=tk.EW, pady=4)
        provider_cb.bind("<<ComboboxSelected>>", self._on_provider_changed)

        # Model
        ttk.Label(body, text="Model:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self._model_var = tk.StringVar(value=model)
        ttk.Entry(body, textvariable=self._model_var).grid(
            row=1, column=1, sticky=tk.EW, pady=4
        )
        ttk.Label(
            body,
            text="e.g. ollama/qwen2.5-coder:14b or anthropic/claude-sonnet-4-5",
            foreground="gray",
        ).grid(row=2, column=1, sticky=tk.W)

        # API base (Ollama host override)
        ttk.Label(body, text="API Base URL:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self._api_base_var = tk.StringVar(value=llm_cfg.get("api_base") or "")
        ttk.Entry(body, textvariable=self._api_base_var).grid(
            row=3, column=1, sticky=tk.EW, pady=4
        )
        ttk.Label(
            body,
            text="Optional. e.g. http://192.168.1.50:11434 for remote Ollama",
            foreground="gray",
        ).grid(row=4, column=1, sticky=tk.W)

        # API key
        ttk.Label(body, text="API Key:").grid(row=5, column=0, sticky=tk.W, pady=4)
        self._api_key_var = tk.StringVar(value="")
        self._api_key_entry = ttk.Entry(body, textvariable=self._api_key_var, show="•")
        self._api_key_entry.grid(row=5, column=1, sticky=tk.EW, pady=4)
        ttk.Label(
            body,
            text="Stored in Windows Credential Manager. Leave blank to keep existing.",
            foreground="gray",
        ).grid(row=6, column=1, sticky=tk.W)

        # Buttons
        btn_row = ttk.Frame(body)
        btn_row.grid(row=7, column=0, columnspan=2, sticky=tk.EW, pady=(12, 0))

        self._test_btn = ttk.Button(
            btn_row, text="🔌 Test Connection", command=self._test_connection
        )
        self._test_btn.pack(side=tk.LEFT)

        ttk.Button(btn_row, text="Save", command=self._save).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(
            side=tk.RIGHT, padx=2
        )

        # Test result (own row, wrapped so long errors are readable)
        self._test_var = tk.StringVar(value="")
        self._test_label = ttk.Label(
            body, textvariable=self._test_var, foreground="gray",
            wraplength=480, justify=tk.LEFT,
        )
        self._test_label.grid(row=8, column=0, columnspan=2, sticky=tk.EW, pady=(8, 0))

    def _on_provider_changed(self, _event=None):
        prefix, default_model = _PROVIDER_PRESETS[self._provider_var.get()]
        if prefix:
            self._model_var.set(prefix + default_model)

    def _build_client(self):
        from src.ai.llm_client import LLMClient

        model = self._model_var.get().strip()
        api_base = self._api_base_var.get().strip() or None
        api_key = self._api_key_var.get().strip() or app_config.get_api_key(
            _keyring_provider(model)
        )
        llm_cfg = self._config.get("llm", {})
        return LLMClient(
            model=model,
            api_key=api_key,
            api_base=api_base,
            temperature=float(llm_cfg.get("temperature", 0.2)),
            max_tokens=int(llm_cfg.get("max_tokens", 4096)),
        )

    def _test_connection(self):
        model = self._model_var.get().strip()
        if not model:
            messagebox.showwarning("AI Settings", "Enter a model string first.", parent=self)
            return
        self._test_btn.config(state=tk.DISABLED)
        self._test_var.set("Testing...")
        client = self._build_client()

        def _do_test():
            ok, msg = client.is_available()

            def _done():
                self._test_btn.config(state=tk.NORMAL)
                self._test_var.set(("✅ " if ok else "❌ ") + msg)
                self._test_label.config(foreground="#006600" if ok else "#aa0000")
                if not ok:
                    messagebox.showerror("Test Connection", msg, parent=self)

            self.after(0, _done)

        threading.Thread(target=_do_test, daemon=True).start()

    def _save(self):
        model = self._model_var.get().strip()
        if not model:
            messagebox.showwarning("AI Settings", "Model string cannot be empty.", parent=self)
            return

        # Store API key in credential manager if entered
        api_key = self._api_key_var.get().strip()
        if api_key:
            try:
                app_config.set_api_key(_keyring_provider(model), api_key)
            except Exception as e:
                messagebox.showerror(
                    "AI Settings", f"Failed to store API key securely:\n{e}", parent=self
                )
                return

        self._config.setdefault("llm", {})
        self._config["llm"]["model"] = model
        self._config["llm"]["api_base"] = self._api_base_var.get().strip() or None
        try:
            app_config.save_config(self._config)
        except Exception as e:
            messagebox.showerror("AI Settings", f"Failed to save config:\n{e}", parent=self)
            return

        if self._on_saved:
            self._on_saved(self._config)
        self.destroy()
