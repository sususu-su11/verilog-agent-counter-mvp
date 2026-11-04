"""OpenAI-compatible client for Vultr Serverless Inference + offline mock mode."""
from __future__ import annotations

import json
import os
import re

import httpx

from . import mock, budget

BASE_URL = os.environ.get("VULTR_INFERENCE_BASE_URL", "https://api.vultrinference.com/v1").rstrip("/")
MODEL = os.environ.get("MODEL", "deepseek-v4.1-flash-1017")


def api_key() -> str:
    return os.environ.get("VULTR_INFERENCE_API_KEY", "").strip()


def mock_mode() -> bool:
    return os.environ.get("MOCK_LLM", "").lower() in ("1", "true", "yes") or not api_key()


def chat(messages, request_text: str, attempt: int):
    if mock_mode():
        return mock.answer(request_text, attempt), {"model": "mock", "mock": True}
    # Each request is reserved durably BEFORE network I/O, including retries.
    # A numerical call budget is NOT a monetary hard-stop: see CREDIT_SAFETY.md.
    budget.consume_one()
    r = httpx.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {api_key()}"},
        json={"model": MODEL, "messages": messages, "temperature": 0.2,
              "max_completion_tokens": 4000},
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"]["content"] or ""
    return text, {"model": data.get("model", MODEL), "usage": data.get("usage"),
                  "mock": False, "inference_response_received": True}


def parse_dut(text: str) -> dict:
    """Extract JSON with rtl (+ optional notes). Reject any testbench field usage."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model reply contained no JSON object")
    obj = json.loads(t[start:end + 1])
    if not isinstance(obj.get("rtl"), str) or not obj["rtl"].strip():
        raise ValueError("model reply missing 'rtl'")
    if "testbench" in obj:
        raise ValueError("model must not emit a testbench — host owns verification")
    if not isinstance(obj.get('notes', ''), str):
        raise ValueError('notes must be a string')
    if len(obj['rtl'].encode('utf-8')) > 16384:
        raise ValueError('rtl is too large')
    obj.setdefault("notes", "")
    obj["notes"] = obj["notes"][:2000]
    obj["top"] = "dut"
    return obj
