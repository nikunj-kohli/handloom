"""Provider-agnostic LLM access. The only module allowed to talk to a model provider."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from . import config, db, security


@dataclass
class LLMResult:
    ok: bool
    text: str = ""
    provider: str = "offline"
    model: str = ""
    error: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


def status() -> Dict[str, Any]:
    cfg = config.llm_config()
    return {
        "provider": cfg["provider"],
        "model": cfg["model"],
        "configured": cfg["configured"],
        "calls_today": db.llm_calls_today(),
        "daily_call_cap": cfg["daily_call_cap"],
    }


def describe_for_ui() -> str:
    cfg = config.llm_config()
    if not cfg["configured"]:
        return "No model key configured — drafting from evidence with the deterministic rule drafter."
    return "Drafting with %s (%s), then verifying every citation." % (cfg["provider"], cfg["model"])


def _retry_delay(response: httpx.Response) -> float:
    raw = response.headers.get("retry-after", "")
    try:
        return min(max(float(raw), 1.0), 12.0)
    except (TypeError, ValueError):
        return 5.0


def _post(url: str, headers: Dict[str, str], payload: Dict[str, Any], provider: str, model: str) -> LLMResult:
    response: Optional[httpx.Response] = None
    for attempt in range(2):
        try:
            with httpx.Client(timeout=config.LLM_TIMEOUT_SECONDS) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException:
            return LLMResult(False, provider=provider, model=model, error="Model request timed out after %ds." % config.LLM_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            return LLMResult(False, provider=provider, model=model, error="Model request failed: %s" % exc.__class__.__name__)
        # Free tiers throttle tokens per minute; one retry after the advertised delay is
        # enough to clear the second (verifier) call of a generation.
        if response.status_code == 429 and attempt == 0:
            time.sleep(_retry_delay(response))
            continue
        break

    if response is None:
        return LLMResult(False, provider=provider, model=model, error="Model request failed.")

    if response.status_code >= 400:
        detail = ""
        try:
            body = response.json()
            detail = str(body.get("error", {}).get("message") or body.get("error") or "")[:240]
        except ValueError:
            detail = response.text[:240]
        return LLMResult(
            False,
            provider=provider,
            model=model,
            error="%s returned HTTP %d. %s" % (provider, response.status_code, detail),
        )

    try:
        body = response.json()
    except ValueError:
        return LLMResult(False, provider=provider, model=model, error="%s returned non-JSON." % provider)

    if provider == "gemini":
        candidates = body.get("candidates") or []
        parts = (candidates[0].get("content", {}) if candidates else {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
    elif provider in ("openai", "groq", "xai"):
        choices = body.get("choices") or []
        text = (choices[0].get("message", {}) or {}).get("content", "") if choices else ""
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    else:
        blocks = body.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict))

    if not text.strip():
        finish = ""
        try:
            finish = str((body.get("choices") or [{}])[0].get("finish_reason") or "")
        except (AttributeError, IndexError, TypeError):
            finish = ""
        detail = " (finish_reason: %s)" % finish if finish else ""
        return LLMResult(
            False,
            provider=provider,
            model=model,
            error="%s returned an empty message%s." % (provider, detail),
        )
    return LLMResult(True, text=text, provider=provider, model=model)


def complete(system: str, prompt: str, max_tokens: Optional[int] = None) -> LLMResult:
    """One model call, guarded by the daily budget. Never raises."""
    cfg = config.llm_config()
    if not cfg["configured"]:
        return LLMResult(False, provider="offline", model="rule-based-drafter", error="No model key configured.")
    if not db.reserve_llm_call():
        return LLMResult(
            False,
            provider=cfg["provider"],
            model=cfg["model"],
            error="Daily model-call cap reached (%d). Serving the rule-based draft instead." % config.DAILY_LLM_CALL_CAP,
        )

    tokens = max_tokens or config.LLM_MAX_OUTPUT_TOKENS
    provider = cfg["provider"]
    model = cfg["model"]

    if provider == "gemini":
        url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s" % (model, config.GEMINI_API_KEY)
        payload = {
            "systemInstruction": {"role": "system", "parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.15,
                "maxOutputTokens": tokens,
                "responseMimeType": "application/json",
            },
        }
        return _post(url, {"Content-Type": "application/json"}, payload, provider, model)

    if provider in ("openai", "groq", "xai"):
        endpoints = {
            "openai": ("https://api.openai.com/v1/chat/completions", config.OPENAI_API_KEY),
            "groq": ("https://api.groq.com/openai/v1/chat/completions", config.GROQ_API_KEY),
            "xai": ("https://api.x.ai/v1/chat/completions", config.XAI_API_KEY),
        }
        url, api_key = endpoints[provider]
        payload = {
            "model": model,
            "temperature": 0.15,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if provider == "groq":
            # Groq counts reasoning tokens against the completion budget. Without headroom
            # and low reasoning effort a long prompt returns finish_reason=length with no text.
            payload["max_completion_tokens"] = tokens + 600
            if "gpt-oss" in model:
                payload["reasoning_effort"] = "low"
        else:
            payload["max_tokens"] = tokens
        # OpenAI's JSON mode is not implemented identically everywhere; the prompt already
        # demands JSON and parse_json_object recovers fenced output.
        if provider == "openai":
            payload["response_format"] = {"type": "json_object"}
        return _post(
            url,
            {"Authorization": "Bearer %s" % api_key, "Content-Type": "application/json"},
            payload,
            provider,
            model,
        )

    payload = {
        "model": model,
        "max_tokens": tokens,
        "temperature": 0.15,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    return _post(
        "https://api.anthropic.com/v1/messages",
        {
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        payload,
        provider,
        model,
    )


def parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Model JSON is untrusted: strip fences, then parse the outermost object."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    cleaned = cleaned.strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None


def safe_meta(result: LLMResult) -> Dict[str, Any]:
    """Public description of a model attempt — no keys, no prompt text."""
    return {
        "ok": result.ok,
        "provider": result.provider,
        "model": result.model,
        "error": result.error,
        "fingerprint": security.clamp_text(result.error, 200) if result.error else None,
    }
