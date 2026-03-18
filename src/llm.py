from __future__ import annotations

import os
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class LlmResult:
    text: str
    provider: str


class LlmError(RuntimeError):
    pass


def generate_with_ollama(prompt: str, *, model: str = "llama3.2:3b", base_url: str = "http://localhost:11434") -> LlmResult:
    """
    Uses Ollama's local HTTP API.
    """
    url = f"{base_url.rstrip('/')}/api/generate"
    try:
        resp = requests.post(
            url,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=120,
        )
    except requests.RequestException as e:
        raise LlmError(f"Could not reach Ollama at {base_url}. Is Ollama installed and running? ({e})") from e

    if resp.status_code != 200:
        raise LlmError(f"Ollama error {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    return LlmResult(text=data.get("response", "").strip(), provider=f"ollama:{model}")


def generate_with_openrouter(prompt: str, *, model: str, api_key: str | None = None) -> LlmResult:
    """
    Optional: OpenRouter chat completions (internet required).
    """
    api_key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise LlmError("OPENROUTER_API_KEY not set.")

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a precise maintenance assistant. Use citations. If unsure, say what info is missing."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 800,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
    except requests.RequestException as e:
        raise LlmError(f"OpenRouter request failed: {e}") from e

    if resp.status_code != 200:
        raise LlmError(f"OpenRouter error {resp.status_code}: {resp.text[:600]}")

    data = resp.json()
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return LlmResult(text=text.strip(), provider=f"openrouter:{model}")

