"""內容生成：由一個市場嘅數據，寫出 200 字中英雙語純分析。

設計要點：
  1. 描述性，唔係處方性。講「發生咗咩」，唔講「應該點做」。
  2. 成因一律標記為假設，唔可以斷言。預測市場異動嘅真正成因
     通常無法從賠率數據推斷 —— 假裝知道就係編故事。
  3. 每篇要有「證偽條件」：講明睇咩就知呢個解讀啱定錯。
     呢一點令內容有真正分析價值，而唔係賠率報時。
  4. 免責聲明由 code 附加，唔靠 LLM 記得寫。
"""
from __future__ import annotations
import json
import re
import requests
from common import log, env

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
TIMEOUT = 90


SYSTEM_PROMPT = """You are a markets data analyst writing short, factual notes about \
prediction-market price movements. You write for an informed audience that wants to \
understand what moved and why it might have moved.

HARD RULES — these are legal constraints, not style preferences:
- NEVER give trading advice, recommendations, or suggestions of any kind.
- NEVER say or imply that a price is cheap, expensive, mispriced, undervalued, \
overvalued, good value, or an opportunity.
- NEVER address the reader in the second person about what to do.
- NEVER state a target price or an entry/exit level.
- NEVER include URLs, links, referral codes, or invitations to sign up or trade.
- NEVER assert a cause for a price move. You may offer candidate explanations, but \
each MUST be explicitly framed as unconfirmed (e.g. "one possibility", "this coincided \
with", "not established as the cause").
- Do not use the words: buy, sell, long, short, position, profit, bet, punt.

WHAT TO WRITE (200 words, four short paragraphs, no headings, no bullet points, \
no hashtags, no emoji):
1. The move: the market question in plain language, the price before and after, the \
timeframe, and the size of the move in percentage points.
2. The context: 24h volume and liquidity, and what that implies about how much \
conviction is behind the move (thin book = a small amount of money can move the price \
a lot; deep book = the move required real size).
3. Candidate explanations: two or three things that occurred in or around the same \
window that COULD be connected — each explicitly flagged as unconfirmed.
4. What would settle it: the specific, observable thing that would confirm or kill \
each explanation. Be concrete.

TONE: dry, precise, slightly sceptical. Like a Reuters market wrap, not a newsletter. \
Short sentences. No hype. If the data does not support a confident reading, say so.

CHINESE OUTPUT — READ CAREFULLY:
Write the "zh" field in STANDARD WRITTEN CHINESE (書面語 / Modern Standard Chinese), \
in Traditional characters. This is the register used by newspapers, wire copy and \
research notes across Hong Kong, Taiwan and the overseas Chinese readership.

DO NOT write Cantonese vernacular. Specifically, never use: 嘅 係 唔 冇 咗 喺 佢哋(as 佢) \
睇 邊個 點解 咁 嘢 乜 攞 傾 諗 郁 好似 而家 依家 一齊 分分鐘 梗係 唔使 冇乜 淨係 成日 \
返嚟 落去 開頭 尾二 咪 囉 啦 喎 嘞 㗎 嘅話.
Use instead: 的 是 不 沒有 了 在 他們 看 哪個 為什麼 這樣 東西 什麼 取得 討論 認為 \
變動 似乎 現在 一起 當然 不需要 只是 經常.

The Chinese should read as if written by a financial wire journalist, not translated \
from English and not spoken aloud. Around 200 Chinese characters. Convey the same \
substance as the English — it is a parallel version, not a literal translation.

Return ONLY a JSON object with exactly two keys: "en" (the 200-word English note) and \
"zh" (the standard-written-Chinese version). No markdown fences."""


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def build_user_prompt(m: dict) -> str:
    """將市場數據整理成 LLM 嘅輸入。"""
    lines = [
        f"MARKET QUESTION: {m['question']}",
        f"CATEGORY: {m['category']}",
        "",
        f"Current YES price (implied probability): {_fmt_pct(m['yes_price'])}",
        f"Change over last 1 hour:  {m['move_1h'] * 100:+.1f} percentage points",
        f"Change over last 24 hours: {m['move_24h'] * 100:+.1f} percentage points",
        f"Change over last 7 days:   {m['move_1w'] * 100:+.1f} percentage points",
        "",
        f"24h volume: ${m['volume_24hr']:,.0f}",
        f"Total volume to date: ${m['volume_total']:,.0f}",
        f"Order book liquidity: ${m['liquidity']:,.0f}",
        f"Best bid / best ask: {m['best_bid']:.3f} / {m['best_ask']:.3f}",
        f"Days until resolution: {m.get('days_to_end', 0):.0f}",
    ]

    # 由數據推導出嘅提示，幫 LLM 講得準啲
    spread = max(m["best_ask"] - m["best_bid"], 0.0)
    if spread > 0.03:
        lines.append(f"NOTE: the bid-ask spread is wide ({spread:.3f}) — the book is thin.")
    depth_ratio = m["volume_24hr"] / max(m["liquidity"], 1.0)
    if depth_ratio > 5:
        lines.append("NOTE: 24h volume is large relative to resting liquidity — "
                     "turnover was high for the depth available.")
    elif depth_ratio < 0.5:
        lines.append("NOTE: 24h volume is small relative to resting liquidity — "
                     "the move happened on limited trading.")

    if m.get("description"):
        lines += ["", "RESOLUTION CRITERIA (for your understanding — do not quote "
                      "verbatim at length):", m["description"][:900]]

    lines += [
        "",
        "Write the note now. Remember: describe, do not advise. "
        "Frame every causal claim as unconfirmed.",
    ]
    return "\n".join(lines)


def _strip_fences(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def generate(m: dict, cfg: dict, model: str = "gpt-4o-mini",
             extra_instruction: str = "") -> tuple[str, str]:
    """回傳 (english_text, chinese_text)，已附加免責聲明。"""
    api_key = env("OPENAI_API_KEY")

    user = build_user_prompt(m)
    if extra_instruction:
        user += f"\n\nADDITIONAL REQUIREMENT (a previous draft was rejected):\n{extra_instruction}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "temperature": 0.5,
        "response_format": {"type": "json_object"},
    }

    r = requests.post(
        OPENAI_URL,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json=payload, timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"LLM 呼叫失敗 HTTP {r.status_code}: {r.text[:300]}")

    content = r.json()["choices"][0]["message"]["content"]
    try:
        obj = json.loads(_strip_fences(content))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM 回應唔係合法 JSON：{e}\n原文：{content[:400]}")

    en = (obj.get("en") or "").strip()
    zh = (obj.get("zh") or "").strip()
    if not en:
        raise RuntimeError("LLM 冇回英文內容")

    c = cfg["compliance"]
    if c["disclaimer_en"] not in en:
        en = f"{en}\n\n{c['disclaimer_en']}"
    if zh and c["disclaimer_zh"] not in zh:
        zh = f"{zh}\n\n{c['disclaimer_zh']}"

    return en, zh


def generate_compliant(m: dict, cfg: dict, guard_check, model: str = "gpt-4o-mini",
                       max_attempts: int = 3, tier: str = "move"):
    """生成 → 守門 → 發現度檢查 → 唔過就帶住原因重寫。

    兩道關順序係有意嘅：
      1. guard（合規）—— 唔過就一定要改，冇得妥協
      2. seo（發現度）—— 唔過都要改，但屬於品質問題唔係法律問題

    回傳 (en, zh, guard_result, seo_result)，全部失敗回傳 (None, None, ..., ...)。
    """
    import seo as seo_mod

    extra = ""
    last_g = last_s = None
    for attempt in range(1, max_attempts + 1):
        try:
            en, zh = generate(m, cfg, model=model, extra_instruction=extra)
        except RuntimeError as e:
            log(f"  第 {attempt} 次生成出錯：{e}")
            if attempt == max_attempts:
                return None, None, None, None
            continue

        res = guard_check(en, zh, cfg)
        last_g = res
        if not res.ok:
            log(f"  第 {attempt} 次被守門打回：{res.reason}")
            extra = ("Your previous draft was rejected by an automated compliance "
                     f"filter. Reason: {res.reason}. Rewrite it completely, removing "
                     "every trace of the offending language. Stay purely descriptive.")
            continue

        sres = seo_mod.analyse(en, zh, m, tier=tier)
        last_s = sres
        if sres.ok:
            log(f"  第 {attempt} 次通過守門 + 發現度檢查"
                + (f"（{sres.summary}）" if sres.entities else ""))
            if res.flags:
                log(f"     ⚑ 待你留意：{', '.join(res.flags)}")
            for h in sres.hints:
                log(f"     💡 {h}")
            return en, zh, res, sres

        log(f"  第 {attempt} 次發現度唔合格：{'；'.join(sres.problems)}")
        extra = seo_mod.rewrite_instruction(sres)

    log(f"  ✗ 試咗 {max_attempts} 次都過唔到，放棄呢個題目")
    return None, None, last_g, last_s
