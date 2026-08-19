"""監管合規守門。

呢個模組係整條 pipeline 最重要嘅一環。佢唔係「內容質素檢查」，
係一道法律防線 —— 見 docs/監管紅線.md。

設計原則：
  1. 硬拒絕係 code，唔係 prompt。LLM 會唔聽指示，正則表達式唔會。
  2. 寧枉毋縱。假陽性只係重寫一次（成本 ~$0.002），假陰性可能係監管問題。
  3. 每次拒絕都記低原因，方便你調整 prompt。
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

URL_RE = re.compile(r"(https?://|www\.|\b[\w-]+\.(com|org|net|io|xyz|co)\b)", re.I)


@dataclass
class GuardResult:
    ok: bool
    hard_hits: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    structural: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        bits = []
        if self.hard_hits:
            bits.append("硬拒絕字眼：" + ", ".join(f"「{h}」" for h in self.hard_hits))
        if self.structural:
            bits.append("結構問題：" + "；".join(self.structural))
        return " / ".join(bits) if bits else "通過"


def _scannable(text: str, exempt: list[str]) -> str:
    """移除豁免字串後嘅可掃描文本。

    注意：只剪走豁免字串本身，唔係成行。
    （之前用「成行豁免」有 bug：免責聲明同正文同一行時，
      成行連違規字眼都會被跳過。）
    """
    out = text
    for e in exempt:
        out = out.replace(e, " ")
    return out


def check(text_en: str, text_zh: str, cfg: dict) -> GuardResult:
    c = cfg["compliance"]
    exempt = c.get("exempt_lines_containing", [])

    scan_en = _scannable(text_en, exempt).lower()
    scan_zh = _scannable(text_zh, exempt)
    full = f"{text_en}\n{text_zh}"

    hard: list[str] = []
    for phrase in c["hard_reject"]["en"]:
        if phrase.lower() in scan_en:
            hard.append(phrase)
    for phrase in c["hard_reject"]["zh"]:
        if phrase in scan_zh:
            hard.append(phrase)

    # 正則式硬拒絕：捕捉「對一個具體標的落判斷」嘅句式。
    # 類別層面嘅統計陳述（「政治冷門系統性被高估」）唔會中招。
    for pat in c.get("hard_reject_patterns", []):
        try:
            if re.search(pat, scan_en) or re.search(pat, scan_zh):
                hard.append(f"句式:{pat[:40]}")
        except re.error:
            pass

    flags: list[str] = []
    for phrase in c.get("flag_for_review", {}).get("en", []):
        # 兩邊都要字界，否則 "long " 會喺 "longshots" 度誤中
        if re.search(r"\b" + re.escape(phrase.strip()) + r"\b", scan_en):
            flags.append(phrase.strip())
    for phrase in c.get("flag_for_review", {}).get("zh", []):
        if phrase in scan_zh:
            flags.append(phrase)

    structural: list[str] = []
    if c.get("require_disclaimer", True):
        if c["disclaimer_en"] not in text_en:
            structural.append("英文免責聲明缺失")
        if text_zh and c["disclaimer_zh"] not in text_zh:
            structural.append("中文免責聲明缺失")
    if c.get("forbid_urls", True) and URL_RE.search(full):
        structural.append("含 URL（X API 每篇會由 $0.015 跳到 $0.20）")
    # 中文語域：必須係書面語，唔可以係廣東話口語。
    # 廣東話口語受眾遠細過書面語，而書面語同時覆蓋港台星馬同海外華人。
    if text_zh and cfg.get("content", {}).get("chinese_register") == "written":
        hits = [mk for mk in cfg["content"].get("cantonese_markers", [])
                if mk in text_zh]
        if hits:
            structural.append("中文用咗廣東話口語：" + "、".join(hits[:8])
                              + ("…" if len(hits) > 8 else ""))

    maxlen = c.get("max_chars_per_post", 4000)
    if len(text_en) > maxlen:
        structural.append(f"英文超長 {len(text_en)}>{maxlen}")
    if len(text_zh) > maxlen:
        structural.append(f"中文超長 {len(text_zh)}>{maxlen}")
    # 第二人稱祈使句 —— 「勸人做嘢」嘅最強訊號
    if re.search(r"\byou (should|must|need to|ought to|want to)\b", scan_en):
        hard.append("second-person imperative")

    return GuardResult(
        ok=(not hard and not structural),
        hard_hits=sorted(set(hard)),
        flags=sorted(set(flags)),
        structural=structural,
    )
