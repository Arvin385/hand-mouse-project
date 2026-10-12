"""LLM client using an OpenAI-compatible REST API.

Usage
-----
    from voice.src.llm.llm import generate

    tokens = generate("Hello, world!")
    # tokens is a list[str]: cleaned word-level tokens from the response

Environment variables
---------------------
LLM_API_BASE   Base URL of the OpenAI-compatible API
               e.g. http://localhost:11434/v1  (Ollama)
               e.g. http://localhost:1234/v1   (lmstudio)
               Default: http://localhost:11434/v1
LLM_API_KEY    API key (ignored by most local servers; required by OpenAI)
               Default: ""
LLM_MODEL      Model name to use
               Default: "llama3"
"""

import json
import os
import re
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = os.environ.get("LLM_API_BASE", "http://localhost:11434/v1")
API_KEY = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "llama3")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[^\s]+", re.UNICODE)


def _generate(prompt: str) -> str:
    """Call the LLM API and return the raw text response.

    Raises ``RuntimeError`` on HTTP errors or unexpected response format.
    """
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=data,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"LLM API HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM API connection failed: {exc.reason}") from exc

    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as inner:
        raise RuntimeError(
            f"Unexpected LLM response format: {body}"
        ) from inner


def _clean_tokens(raw: str) -> list[str]:
    """Split raw LLM output into cleaned tokens.

    Drops empty entries; returns remaining substrings.
    """
    return [t for t in _TOKEN_RE.findall(raw) if t]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate(prompt: str) -> list[str]:
    """Generate a response to *prompt* and return cleaned tokens.

    Parameters
    ----------
    prompt:
        The user-facing prompt to send to the LLM.

    Returns
    -------
    list[str]:
        A flat list of cleaned, whitespace-stripped tokens extracted from
        the LLM's reply.  Empty lists are returned only when the model
        produces no text content.

    Raises
    ------
    RuntimeError:
        If the API call fails or the response is malformed.
    """
    raw = _generate(prompt)
    return _clean_tokens(raw)
