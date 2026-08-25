"""The sole LiteLLM import point. Nothing outside this module imports `litellm`.

`service.py` calls exactly two functions here — `stream_text` and `parse_structured` — and
never sees a provider name, an SDK object, or a credential. Which model answers, and which
provider serves it, is `settings.llm_model` alone (an `EAUDIT_LLM_MODEL` env var, e.g.
`"anthropic/claude-opus-5"` or `"openai/gpt-4o"`): change that string and every feature moves
to the new model with no other edit, anywhere.

The two Anthropic-specific extras the app relies on — `thinking` (extended reasoning) and
`cache_control` (prompt-caching breakpoints already embedded in the message-block dicts
`service.py` builds) — are applied or stripped here, based on which provider the configured
model targets, so `service.py` never has to know either exists.
"""
from __future__ import annotations

import os
from typing import Any

import litellm
from pydantic import BaseModel

from ..config import settings

MODEL = settings.llm_model
_PROVIDER = litellm.get_llm_provider(MODEL)[1]  # e.g. "anthropic", "openai", "ollama"

# Credential env vars this app knows to check per provider. Only providers actually expected
# to be demoed need an entry — LiteLLM itself resolves credentials for every provider it
# supports; this map only backs the `no-credentials` branch of availability().
_CRED_ENV_VARS: dict[str, list[str]] = {
    "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"],
    "openai": ["OPENAI_API_KEY"],
    "azure": ["AZURE_API_KEY"],
    "gemini": ["GEMINI_API_KEY"],
    "ollama": [],  # local, no credential needed
}


def has_credentials() -> bool:
    names = _CRED_ENV_VARS.get(_PROVIDER)
    if names is None:
        # An unlisted provider: don't hard-block it, just don't pretend to gate it either —
        # let the call itself fail (and degrade to fallback) if credentials are missing.
        return True
    if not names:
        return True
    return any(os.getenv(n) for n in names)


def is_public_endpoint() -> bool:
    # No override configured => the provider's default hosted endpoint, which is public.
    # An operator who sets EAUDIT_LLM_BASE_URL is explicitly opting into a private/in-VPC one.
    return not settings.llm_base_url


def _provider_extras() -> dict[str, Any]:
    if _PROVIDER == "anthropic":
        return {"thinking": {"type": "adaptive"}}
    return {}


def _sanitize_blocks(blocks: list[dict]) -> list[dict]:
    """Strip `cache_control` from content blocks when the target isn't Anthropic — it's an
    Anthropic-specific prompt-caching marker embedded by service.py's block builders, and it
    is not this module's job to make service.py provider-aware just to omit it there."""
    if _PROVIDER == "anthropic":
        return blocks
    return [{k: v for k, v in b.items() if k != "cache_control"} for b in blocks]


def _messages(system_blocks: list[dict] | None, user_content: list[dict]) -> list[dict]:
    msgs = []
    if system_blocks:
        msgs.append({"role": "system", "content": _sanitize_blocks(system_blocks)})
    msgs.append({"role": "user", "content": _sanitize_blocks(user_content)})
    return msgs


def _refusal(resp) -> bool:
    # LiteLLM normalizes `finish_reason` to the OpenAI vocabulary, which has no "refusal"
    # value — the raw Anthropic stop_reason (when present) is the only reliable signal, so it
    # is checked first and finish_reason is never trusted alone for this.
    msg = resp.choices[0].message
    raw = getattr(msg, "provider_specific_fields", None) or {}
    if isinstance(raw, dict) and raw.get("stop_reason") == "refusal":
        return True
    return getattr(resp.choices[0], "finish_reason", None) == "content_filter"


def stream_text(*, system_blocks: list[dict] | None, user_content: list[dict],
                 max_tokens: int) -> tuple[str, str | None]:
    try:
        stream = litellm.completion(
            model=MODEL, max_tokens=max_tokens, stream=True,
            base_url=settings.llm_base_url or None,
            messages=_messages(system_blocks, user_content),
            **_provider_extras(),
        )
        parts = []
        finish_reason = None
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                parts.append(delta)
            finish_reason = chunk.choices[0].finish_reason or finish_reason
        # Streaming chunks don't carry the raw provider stop_reason (only the final
        # non-streaming response does, checked in parse_structured's _refusal); the
        # normalized finish_reason is the only signal available here.
        if finish_reason == "content_filter":
            return "", "blocked-refusal"
        raw = "".join(parts)
    except Exception:
        return "", "api-error"
    return raw, None


def parse_structured(*, system_blocks: list[dict] | None, user_content: list[dict],
                      max_tokens: int, output_model: type[BaseModel]
                      ) -> tuple[BaseModel | None, str | None]:
    try:
        resp = litellm.completion(
            model=MODEL, max_tokens=max_tokens,
            base_url=settings.llm_base_url or None,
            messages=_messages(system_blocks, user_content),
            response_format=output_model,
            **_provider_extras(),
        )
        if _refusal(resp):
            return None, "blocked-refusal"
        msg = resp.choices[0].message
        for attr in ("parsed", "parsed_output", "output_parsed"):
            obj = getattr(msg, attr, None)
            if isinstance(obj, output_model):
                return obj, None
            if isinstance(obj, dict):
                return output_model.model_validate(obj), None
        return output_model.model_validate_json(msg.content), None
    except Exception:
        return None, "api-error"
