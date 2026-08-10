"""
llm_client.py - Single entry point for all AI calls, backed by LiteLLM.

Model strings select the provider:
    "ollama/qwen2.5-coder:14b"      -> local/remote Ollama
    "anthropic/claude-sonnet-4-5"   -> Anthropic API (Claude)
    "openai/gpt-4o"                 -> OpenAI API

litellm is imported lazily so the rest of the app works without it
installed (AI features simply report unavailable).
"""

from __future__ import annotations

from typing import Optional


class LLMError(Exception):
    """Raised for LLM call failures with a user-friendly message."""


class LLMClient:
    """Thin wrapper over litellm.completion."""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ):
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def model(self) -> str:
        return self._model

    def generate(
        self, system_prompt: str, user_prompt: str, json_mode: bool = False
    ) -> str:
        """Send a prompt and return the model's text response."""
        try:
            import litellm
        except ImportError as e:
            raise LLMError(
                "litellm is not installed. Run: pip install litellm"
            ) from e

        litellm.suppress_debug_info = True  # hide "Give Feedback" console banner

        kwargs: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "num_retries": 2,
            "timeout": 120,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = litellm.completion(**kwargs)
        except Exception as e:
            raise LLMError(self._friendly_error(e)) from e

        try:
            content = resp.choices[0].message.content
        except (AttributeError, IndexError) as e:
            raise LLMError("LLM returned an empty or malformed response.") from e
        if not content:
            raise LLMError("LLM returned an empty response.")
        return content

    def is_available(self) -> tuple[bool, str]:
        """Cheap connectivity/credential check. Returns (ok, message)."""
        try:
            reply = self.generate("Reply with the single word: OK", "ping")
            return True, f"Connected. Model replied: {reply.strip()[:60]}"
        except LLMError as e:
            return False, str(e)

    def _friendly_error(self, e: Exception) -> str:
        name = type(e).__name__
        text = str(e)
        if "AuthenticationError" in name or "401" in text:
            return (
                f"Authentication failed for {self._model}. "
                "Check your API key in AI Settings."
            )
        if "APIConnectionError" in name or "Connection" in text:
            if self._model.startswith("ollama/"):
                base = self._api_base or "http://localhost:11434"
                if "llama-server process has terminated" in text or "error" in text.lower():
                    return (
                        f"Ollama at {base} responded with a server-side error: "
                        f"{text[:300]}\n"
                        "The Ollama server itself may have crashed loading the "
                        "model - check/restart Ollama on that machine."
                    )
                return (
                    f"Cannot reach Ollama at {base}. "
                    "Make sure Ollama is running (ollama serve)."
                )
            return f"Cannot reach the AI provider for {self._model}: {text[:200]}"
        if "RateLimitError" in name or "429" in text:
            return "AI provider rate limit hit. Wait a moment and retry."
        if "NotFoundError" in name or "404" in text:
            return (
                f"Model '{self._model}' not found. "
                "For Ollama, pull it first: ollama pull <model>."
            )
        return f"AI call failed ({name}): {text[:300]}"
