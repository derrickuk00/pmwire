"""由題目文字 parse 出 deadline。

⚠️ 呢個模組存在嘅原因（實戰教訓，唔好刪）：
    Gamma 嘅 `endDate` metadata 唔可信。已知實例：
      - market 677273：endDate 寫 2025-12-31，但題目講 2026
      - market 1323083：endDate 寫 2026-03-31，但題目講 Dec 31
    階梯單調性掃描如果信 endDate，會出假違規。一律以題目文字為準。

⚠️ 第二個陷阱：「by」唔一定係 deadline。
    "Will NVIDIA be the largest company by market cap?" —— 呢個 by 係
    「按…計算」，唔係「喺…之前」。實測會做成 gap=0.246 嘅假陽性。
    下面 NON_DEADLINE_BY 就係用嚟擋呢類。
"""
from __future__ import annotations
import re
import datetime as dt

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}

# 「by」後面跟住呢啲字 = 唔係時間 deadline，係「按…計算/衡量」
NON_DEADLINE_BY = re.compile(
    r"\bby\s+(market\s*cap|marketcap|market\s*capitalisation|market\s*capitalization|"
    r"revenue|volume|population|gdp|sales|users|downloads|assets|aum|"
    r"a\s+margin|margin|points?|votes?|score|the\s+end\s+of\s+the\s+(?:day|game)|"
    r"then|far|comparison|default|law|number|any\s+measure)\b",
    re.I,
)

# 真 deadline 嘅語法標記
#
# ⚠️ `through` 一定要有。「US ceasefire continues **through** September 30」
#    呢類 persistence 型階梯冇 by／before，只有 through ——
#    漏咗嘅話 DK 最重要嗰個伊朗停火家族喺階梯掃描度完全隱形。
#    （2026-08-20 測試捉到，而且原本仲係「假通過」：兩腳都被過濾走，
#      得出空清單啱好符合「零違規」嘅預期。）
DEADLINE_CUE = re.compile(
    r"\b(by|before|on or before|prior to|no later than|until|through|"
    r"as of|at the end of)\b", re.I)


def has_deadline_cue(title: str) -> bool:
    """題目有冇時間 deadline 語法（同時排除『by market cap』類假陽性）。"""
    if not DEADLINE_CUE.search(title):
        return False
    # 如果所有 "by" 都係非時間用法，就當冇 deadline
    if re.search(r"\bby\b", title, re.I) and NON_DEADLINE_BY.search(title):
        # 睇下除咗假 by 之外仲有冇真 cue
        stripped = NON_DEADLINE_BY.sub(" ", title)
        if not DEADLINE_CUE.search(stripped):
            return False
    return True


def _mk(y: int, m: int, d: int):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_deadline(title: str, default_year: int | None = None):
    """由題目文字抽出 deadline 日期。抽唔到回傳 None。

    支援：
      "by December 31, 2026" / "before Dec 31 2026" / "by 31 December 2026"
      "by end of 2026" / "by Q3 2026" / "by March 2026"（當月尾）
      "by 2026-12-31" / "by 12/31/2026"
    """
    if not title or not has_deadline_cue(title):
        return None

    t = NON_DEADLINE_BY.sub(" ", title)  # 剪走假 by，避免誤配
    default_year = default_year or dt.date.today().year
    low = t.lower()

    # ISO: 2026-12-31
    m = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", t)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3]))

    # US: 12/31/2026 或 12/31/26
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2}|\d{2})\b", t)
    if m:
        y = int(m[3])
        y = y + 2000 if y < 100 else y
        return _mk(y, int(m[1]), int(m[2]))

    mon_alt = "|".join(sorted(MONTHS, key=len, reverse=True))

    # "December 31, 2026" / "Dec 31 2026"
    m = re.search(rf"\b({mon_alt})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(20\d{{2}})?\b", low)
    if m:
        mon = MONTHS[m[1]]
        day = int(m[2])
        year = int(m[3]) if m[3] else default_year
        d = _mk(year, mon, day)
        if d:
            return d

    # "31 December 2026"
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({mon_alt})\.?,?\s*(20\d{{2}})?\b", low)
    if m:
        mon = MONTHS[m[2]]
        day = int(m[1])
        year = int(m[3]) if m[3] else default_year
        d = _mk(year, mon, day)
        if d:
            return d

    # "by end of 2026" / "by the end of 2026" / "in 2026"
    m = re.search(r"\bend of (?:the\s+)?(20\d{2})\b", low)
    if m:
        return _mk(int(m[1]), 12, 31)

    # "by Q3 2026"
    m = re.search(r"\bq([1-4])\s*(?:of\s*)?(20\d{2})\b", low)
    if m:
        mm, dd = QUARTER_END[int(m[1])]
        return _mk(int(m[2]), mm, dd)

    # "by March 2026"（冇日 → 當月尾）
    m = re.search(rf"\b({mon_alt})\.?\s+(20\d{{2}})\b", low)
    if m:
        mon = MONTHS[m[1]]
        year = int(m[2])
        nxt = _mk(year + (mon == 12), (mon % 12) + 1, 1)
        return (nxt - dt.timedelta(days=1)) if nxt else None

    # "by 2026"（淨係年份）
    m = re.search(r"\b(?:by|before)\s+(20\d{2})\b", low)
    if m:
        return _mk(int(m[1]), 12, 31)

    return None


def family_key(title: str) -> str:
    """同一「階梯家族」嘅辨識鍵。

    「Will X happen by June 30 2026?」同「Will X happen by Dec 31 2026?」
    應該歸同一家族 —— 剪走日期同 deadline 語法之後，剩低嘅文字要一樣。
    """
    t = title.lower()
    t = NON_DEADLINE_BY.sub(" ", t)
    mon_alt = "|".join(sorted(MONTHS, key=len, reverse=True))
    t = re.sub(r"(20\d{2})-(\d{1,2})-(\d{1,2})", " ", t)
    t = re.sub(r"\b\d{1,2}/\d{1,2}/(20\d{2}|\d{2})\b", " ", t)
    t = re.sub(rf"\b({mon_alt})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*(20\d{{2}})?\b", " ", t)
    t = re.sub(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+({mon_alt})\.?,?\s*(20\d{{2}})?\b", " ", t)
    t = re.sub(r"\bend of (?:the\s+)?20\d{2}\b", " ", t)
    t = re.sub(r"\bq[1-4]\s*(?:of\s*)?20\d{2}\b", " ", t)
    t = re.sub(rf"\b({mon_alt})\.?\s+20\d{{2}}\b", " ", t)
    t = re.sub(r"\b20\d{2}\b", " ", t)
    t = re.sub(r"\b(by|before|on or before|prior to|no later than|until|in|"
               r"through|as of|at the end of)\b", " ", t)
    # 數值區間都要剪走 —— 否則「post 200-219 tweets」同「post 220-239 tweets」
    # 會當成兩個唔同家族。2026-08-19 第五輪實測。
    t = re.sub(r"\b\d[\d,]*\s*(?:[-–—]|to)\s*\d[\d,]*\b", " ", t)
    t = re.sub(r"\b\d[\d,]*(\.\d+)?\+?\b", " ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()
