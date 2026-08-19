"""發現度最佳化（X 專用，2026 年機制）。

⚠️ 呢個唔係傳統 SEO。X 喺 2026 年嘅運作方式：

  1. Hashtag 基本上冇用。Musk（2024-12）：「請停止用 hashtag，
     系統唔再需要佢哋。」X 官方文檔上限 2 個；源碼分析顯示
     3 個以上觸發 spam 偵測，觸及約跌 40%。
     → 所以我哋上限 1 個，而且只喺真係有 live event 先用。

  2. Grok 直接讀貼文做語意理解，唔係關鍵字比對。
     Phoenix 用讀者最近 128 條互動貼文同貼文主題做配對。
     → 要贏，係要**用自然語言清楚寫出實體名**（Federal Reserve、
       FOMC、Polymarket、Kalshi），令語意模型放得準你入邊個主題群。

  3. 回覆係權重最高嘅互動訊號，高過 like。「對話驅動觸及」。
     → 每篇要有一個真正值得回應嘅開放問題或可爭論斷言。

  4. 連結觸及最多被壓 80%。
     → 已喺 guard.py 硬性禁止（同時慳 X API 每篇 $0.185）。

  5. 停留時間（dwell time）權重好高。
     → 200 字密集可讀嘅內容係啱嘅方向，唔好寫一行字。

  6. 作者多樣性上限：無論你出幾多，演算法都封頂你嘅位置。
     → 出多唔等於觸及多。質素門檻比數量重要。
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

# 貼文喺 timeline 上「Show more」之前大約睇到嘅字元數。
# 鈎同主要實體必須喺呢個範圍之內，否則等於冇出過。
VISIBLE_CHARS = 280

# 常見預測市場實體嘅正規名同別名。
# 目的：確保貼文用「語意模型認得」嘅寫法至少出現一次。
# 例如淨係寫 "the Fed" 唔夠，最好有一次 "Federal Reserve" 或 "FOMC"。
ENTITY_ALIASES: dict[str, list[str]] = {
    "Federal Reserve": ["fed", "federal reserve", "fomc", "powell"],
    "European Central Bank": ["ecb", "european central bank", "lagarde"],
    "Bank of England": ["boe", "bank of england"],
    "Bitcoin": ["bitcoin", "btc"],
    "Ethereum": ["ethereum", "eth"],
    "Consumer Price Index": ["cpi", "consumer price index", "inflation print"],
    "Nonfarm Payrolls": ["nfp", "nonfarm", "payrolls", "jobs report"],
    "Supreme Court": ["scotus", "supreme court"],
    "OPEC": ["opec"],
    "NATO": ["nato"],
    "United Nations": ["united nations", "un security council"],
    "Polymarket": ["polymarket"],
    "Kalshi": ["kalshi"],
}

# 數字模式：可見範圍內有具體數字係止住滑動嘅最強訊號
NUMBER_RE = re.compile(r"\b\d[\d,]*\.?\d*\s*(%|c\b|bp|bps|cents?|percent|million|billion|k\b)?",
                       re.I)
HASHTAG_RE = re.compile(r"#\w+")

# 回覆鈎：一個真正開放、值得人回應嘅嘢。
#
# ⚠️ 問號要喺後半段任何位置都算，唔可以要求佢喺行尾 ——
#    貼文會自動換行，一句問句嘅問號好容易落喺句中。
#    （呢個 bug 喺介紹貼度真係捉錯過一次。）
REPLY_HOOK_PATTERNS = [
    re.compile(r"\?"),                                       # 任何問號
    re.compile(r"？"),                                        # 全形問號（中文）
    re.compile(r"\beither\b.{0,150}\bor\b", re.I | re.S),     # 兩個互斥解釋
    re.compile(r"\bis it\b.{0,150}\bor is it\b", re.I | re.S),
    re.compile(r"\bone (is|possibility).{0,200}\bthe other\b", re.I | re.S),
    re.compile(r"\b(I will post|I'll post|we find out|I will check back)\b", re.I),
    re.compile(r"\b(more interesting|worth writing down|that is the finding)\b", re.I),
]


@dataclass
class SeoResult:
    ok: bool
    entities: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        bits = []
        if self.entities:
            bits.append("實體：" + "、".join(self.entities))
        if self.problems:
            bits.append("問題：" + "；".join(self.problems))
        return " ｜ ".join(bits) if bits else "無實體"


def detect_entities(*texts: str) -> list[str]:
    """搵出貼文入面出現咗嘅正規實體。"""
    blob = " ".join(t.lower() for t in texts if t)
    found = []
    for canon, aliases in ENTITY_ALIASES.items():
        if any(re.search(r"\b" + re.escape(a) + r"\b", blob) for a in aliases):
            found.append(canon)
    return found


def _visible(text: str) -> str:
    return text[:VISIBLE_CHARS]


def analyse(text_en: str, text_zh: str = "", market: dict | None = None,
            tier: str = "move") -> SeoResult:
    """檢查一篇貼文嘅發現度。回傳問題同建議。

    呢個唔會自動改稿 —— 佢報告問題，由重寫迴圈或者你人手處理。
    """
    problems: list[str] = []
    hints: list[str] = []

    vis = _visible(text_en)
    entities = detect_entities(text_en, market.get("question", "") if market else "")

    # ── 1. 可見範圍必須有主要實體 ──
    # 長貼文喺 timeline 上會截斷。截斷之前見唔到主題 = 語意模型同讀者都捉唔到。
    vis_entities = detect_entities(vis)
    if entities and not vis_entities:
        problems.append(f"首 {VISIBLE_CHARS} 字元冇提到主要實體"
                        f"（{'、'.join(entities[:3])}）—— 截斷後讀者見唔到主題")
    elif not entities:
        hints.append("搵唔到已知實體。如果係人物／機構／國家，"
                     "用返佢哋嘅正式名稱寫一次，語意模型先放得準你入主題群")

    # ── 2. 可見範圍必須有具體數字 ──
    if not NUMBER_RE.search(vis):
        problems.append(f"首 {VISIBLE_CHARS} 字元冇具體數字 —— 數字係止住滑動最強嘅嘢")

    # ── 3. Hashtag 紀律 ──
    tags = HASHTAG_RE.findall(text_en) + HASHTAG_RE.findall(text_zh)
    if len(tags) > 1:
        problems.append(f"用咗 {len(tags)} 個 hashtag。X 官方上限 2，"
                        f"3 個以上觸發 spam 偵測（觸及約 −40%）。呢度上限 1")
    elif len(tags) == 1:
        hints.append(f"用咗 1 個 hashtag（{tags[0]}）。除非係 live event，"
                     f"否則 2026 年嘅 hashtag 對觸及冇幫助，考慮刪走")

    # ── 4. 回覆鈎（回覆係權重最高嘅訊號）──
    tail = text_en[len(text_en) // 2:]          # 後半段
    has_hook = any(p.search(tail) for p in REPLY_HOOK_PATTERNS)
    if not has_hook:
        if tier in ("discussion", "basket", "violation"):
            problems.append("後半段冇回覆鈎。回覆係 X 權重最高嘅互動訊號 —— "
                            "加一個開放問題，或者兩個互斥解釋而唔選邊")
        else:
            hints.append("冇明顯回覆鈎（對 anchor／method 類可以接受）")

    # ── 5. 長度：太短拿唔到停留時間，太長會被摺 ──
    words = len(text_en.split())
    if words < 90:
        problems.append(f"英文只有 {words} 字 —— 停留時間權重高，太短蝕底")
    elif words > 320:
        hints.append(f"英文 {words} 字偏長，讀者可能唔展開")

    # ── 6. 第一行係全篇最重要嘅一行 ──
    first_line = text_en.split("\n")[0].strip()
    if len(first_line) > 200:
        hints.append("第一行過長。開場一句短而突兀效果最好")
    if re.match(r"^(polymarket'?s? |the |a |an |in |on |as )", first_line, re.I) \
            and tier == "discussion":
        hints.append("討論型稿唔好用平淡開場。第一句應該令人「吓？」")

    return SeoResult(
        ok=not problems,
        entities=entities,
        hashtags=tags,
        problems=problems,
        hints=hints,
    )


def rewrite_instruction(res: SeoResult) -> str:
    """把問題轉成畀 LLM 重寫嘅指令。"""
    if not res.problems:
        return ""
    return ("The draft has discoverability problems on X. Fix ALL of these while "
            "keeping every fact and the descriptive, non-advisory tone:\n- "
            + "\n- ".join(res.problems)
            + "\nRemember: the first 280 characters are all most readers will see "
              "before the post is truncated. Put the most arresting concrete number "
              "and the named entity in that window.")
