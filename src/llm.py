"""LLM 供應商抽象層：OpenAI 或 Claude，config 一行切換。

點解要有呢層：
    「用邊個模型」唔應該由我（或者你）憑感覺決定。呢個任務有兩個
    好具體嘅硬要求 —— 遵守否定式指令（永不建議）同書面中文語域 ——
    而邊個模型做得好啲，**用你自己嘅真數據試一次就知**。
    所以我唔寫死，寫成可切換 + 可 A/B 對比。

兩邊都要回一個 JSON 物件 {"en": ..., "zh": ...}：
    OpenAI 用 response_format={"type":"json_object"}
    Claude  用 assistant prefill（開頭餵佢一個 "{"），最穩陣而且唔使 tool
"""
from __future__ import annotations
import json
import re
import requests
from common import log, env

TIMEOUT = 90

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class LLMError(RuntimeError):
    pass


def _strip_fences(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _parse(raw: str, who: str) -> dict:
    try:
        obj = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise LLMError(f"{who} 回應唔係合法 JSON：{e}\n原文前 300 字：{raw[:300]}")
    if not isinstance(obj, dict):
        raise LLMError(f"{who} 回咗 JSON 但唔係物件：{type(obj).__name__}")
    return obj


# ────────────────────────── OpenAI ──────────────────────────

def _openai(system: str, user: str, model: str, temperature: float) -> dict:
    r = requests.post(
        OPENAI_URL,
        headers={"Authorization": f"Bearer {env('OPENAI_API_KEY')}",
                 "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        },
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise LLMError(f"OpenAI HTTP {r.status_code}：{r.text[:300]}")
    return _parse(r.json()["choices"][0]["message"]["content"], "OpenAI")


# ────────────────────────── Claude ──────────────────────────

def _claude(system: str, user: str, model: str, temperature: float) -> dict:
    # Prefill：預先餵一個 "{"，逼佢由 JSON 物件開始，唔會寫開場白。
    # 回應要自己補返個 "{"。
    r = requests.post(
        ANTHROPIC_URL,
        headers={"x-api-key": env("ANTHROPIC_API_KEY"),
                 "anthropic-version": ANTHROPIC_VERSION,
                 "content-type": "application/json"},
        json={
            "model": model,
            "max_tokens": 2000,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user},
                         {"role": "assistant", "content": "{"}],
        },
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise LLMError(f"Claude HTTP {r.status_code}：{r.text[:300]}")
    body = r.json()
    parts = [b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"]
    return _parse("{" + "".join(parts), "Claude")


# ────────────────────────── 對外 ──────────────────────────

PROVIDERS = {"openai": _openai, "claude": _claude}

# 預設模型 ID。⚠️ 供應商改型號名嘅時候呢度要更新 ——
# 喺各自嘅 console 睇實際 API 識別碼，唔好靠營銷名（例如
# 「GPT-5.6 Luna」係營銷名，API 字串未必一樣）。
DEFAULT_MODELS = {
    "openai": "gpt-5.6-luna",
    "claude": "claude-haiku-4-5",
}


def complete(system: str, user: str, *, provider: str = "openai",
             model: str | None = None, temperature: float = 0.5) -> dict:
    """叫一次 LLM，回傳解析好嘅 JSON 物件。"""
    provider = (provider or "openai").strip().lower()
    fn = PROVIDERS.get(provider)
    if fn is None:
        raise LLMError(f"唔識嘅供應商 {provider!r}，得 {sorted(PROVIDERS)}")
    model = model or DEFAULT_MODELS[provider]
    return fn(system, user, model, temperature)


def describe(provider: str, model: str | None = None) -> str:
    provider = (provider or "openai").strip().lower()
    return f"{provider}/{model or DEFAULT_MODELS.get(provider, '?')}"
