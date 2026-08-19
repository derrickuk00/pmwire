"""由題目文字分類市場主題。

⚠️ 呢個模組存在嘅原因（2026-08-19 實測發現）：
    Gamma `/markets` 回應嘅 `category` 欄位**實際上係空嘅** ——
    100 個市場全部歸做 "Uncategorised"。

    後果好嚴重：picker 嘅類別多樣性配額（每類 24 小時最多 3 篇）
    會把所有嘢當成同一類，出夠 3 篇之後就再冇稿出得到。
    呢個 bug 喺上線第一日就會爆。

    所以類別一律由題目文字推斷，唔靠 metadata。
    （同 deadline.py 一樣嘅教訓：metadata 係一個說法，唔係事實。）
"""
from __future__ import annotations
import re

# 判斷順序有意義：由最specific到最general，第一個命中就採用。
RULES: list[tuple[str, re.Pattern]] = [
    # ── 體育（要最先判，因為佢量最大而且最易辨認）──
    ("sports", re.compile(
        r"(\bvs\.?\b|\bv\.\b)"                       # "A vs. B" —— 最強訊號
        r"|\b(mlb|nba|nfl|nhl|mls|ncaa|epl|uefa|fifa|atp|wta|pga|f1|ufc)\b"
        r"|\b(yankees|dodgers|red sox|mets|cubs|braves|phillies|marlins|"
        r"orioles|astros|padres|giants|angels|mariners|rangers|guardians|"
        r"diamondbacks|rockies|brewers|cardinals|pirates|reds|tigers|twins|"
        r"royals|athletics|白襪|nationals|blue jays|rays|white sox)\b"
        r"|\b(lakers|celtics|warriors|knicks|heat|bucks|nuggets|suns)\b"
        r"|\b(arsenal|chelsea|liverpool|man city|manchester|tottenham|"
        r"real madrid|barcelona|bayern|psg|juventus|inter milan)\b"
        r"|\b(open|championship|cup|masters|grand prix|playoffs?|"
        r"world series|super bowl|finals?)\b\s*:"    # "Cincinnati Open: A vs B"
        r"|\b(win the (game|match|series|title|championship))\b"
        r"|\bscore\b.{0,20}\b(goals?|points?|runs?)\b",
        re.I)),

    # ── 加密貨幣 ──
    ("crypto", re.compile(
        r"\b(bitcoin|btc|ethereum|eth|solana|sol|xrp|ripple|dogecoin|doge|"
        r"cardano|ada|avalanche|avax|polygon|matic|chainlink|link|"
        r"crypto|stablecoin|usdt|usdc|altcoin|memecoin|satoshi|"
        r"binance|coinbase|halving|etf)\b", re.I)),

    # ── 宏觀經濟／央行 ──
    ("macro", re.compile(
        r"\b(fed|fomc|federal reserve|powell|ecb|lagarde|bank of england|boe|"
        r"boj|pboc|rate (cut|hike|decision)|basis points?|bps\b|"
        r"cpi|inflation|pce|gdp|recession|unemployment|nonfarm|payrolls|nfp|"
        r"jobs report|yield curve|treasury|debt ceiling|s&p 500|nasdaq|"
        r"dow jones)\b", re.I)),

    # ── 地緣政治／衝突 ──
    ("geopolitics", re.compile(
        r"\b(war|ceasefire|cease-fire|invade|invasion|airstrike|air strike|"
        r"missile|nuclear|sanctions?|treaty|armistice|hostage|"
        r"peace (deal|talks|agreement)|troops?|military (action|strike)|"
        r"nato|united nations|un security council|opec|"
        # ⚠️ blockade / iranian 係 2026-08-19 實測漏網（"US announces end of
        #    Iranian blockade" 被判 other，攞唔到地緣政治加分）
        r"blockade|embargo|annex(ation)?|coup|insurgency|"
        r"airspace|drone strike|no-fly zone|border (clash|conflict|incursion)|"
        r"ukraine|russia|israel|palestin|gaza|irans?|iranian|north korea|taiwan|"
        r"strait of hormuz|red sea|houthi|hezbollah|hamas)\b", re.I)),

    # ── 選舉／政治 ──
    # ⚠️ 記住加 s? —— "Republicans" 唔會 match "republican\b"（複數 s 破壞字界）。
    #    2026-08-19 測試捉到。
    ("politics", re.compile(
        r"\b(elections?|elected|presidents?|presidential|senate|senators?|"
        r"congress|congressional|parliament|prime ministers?|governors?|mayors?|"
        r"impeach(ed|ment)?|nominations?|nominees?|midterms?|"
        r"primary|primaries|caucus|ballots?|electoral|cabinet|"
        r"resign(s|ed|ation)?|supreme court|scotus|justices?|"
        r"republicans?|democrats?|democratic party|gop|tories|tory|"
        r"labour party|referendums?|coalitions?|"
        # ⚠️ 立法類係 2026-08-19 實測漏網（"Clarity Act (H.R.3633) signed into
        #    law" 被判 other）
        r"signed into law|becomes? law|enacted|legislation|"
        # \d+ 唔可以寫 \d —— "H.R.3633" 嘅 \b 會落喺 3 同 6 之間而失敗
        r"\bbills?\b|h\.?r\.?\s?\d+|s\.?\s?\d{3,}|"
        r"vetoe?d?|filibuster|executive orders?|"
        r"house of (representatives|commons|lords)|the house|the senate)\b",
        re.I)),

    # ── 科技／AI ──
    ("tech", re.compile(
        r"\b(openai|anthropic|claude|chatgpt|gpt-?\d|gemini|llama|deepseek|"
        r"grok|nvidia|apple|microsoft|google|alphabet|meta|amazon|tesla|"
        r"spacex|starship|ipo|acquisition|antitrust|"
        r"agi|artificial intelligence|large language model)\b", re.I)),

    # ── 娛樂／文化 ──
    ("culture", re.compile(
        r"\b(oscar|academy award|grammy|emmy|golden globe|box office|"
        r"rotten tomatoes|billboard|album|movie|film|netflix|"
        r"time person of the year|nobel|eurovision)\b", re.I)),

    # ── 天氣／災害 ──
    ("weather", re.compile(
        r"\b(hurricane|typhoon|earthquake|wildfire|tornado|flood|"
        r"temperature|snowfall|drought|el ni[nñ]o)\b", re.I)),
]

# 兩個字以上嘅「X vs Y」但唔喺體育詞庫入面（例如辯論、法律訴訟）
DEBATE_VS = re.compile(r"\b(debate|lawsuit|case|trial|court)\b", re.I)


# ── 價格階梯市場偵測 ──────────────────────────────────────────
#
# ⚠️ 2026-08-19 實測發現：篩選後 43 個候選入面有 27 個係 crypto，
#    而且絕大部分係「Will the price of X be above $Y on <日期>」呢類。
#
#    點解要剔走：呢類市場嘅結果係一個**連續可觀察公開價格嘅確定性函數**。
#    「點解佢郁咗 66 點？」答案永遠係「因為現貨價郁咗」——冇分析空間，
#    冇成因之謎，冇可證偽嘅解讀。寫十篇都係同一個故事。
#
#    而且 Polymarket 每日／每小時開一批，數量極多，唔剔就會霸晒名單。
#
#    注意：呢個唔係「排除加密貨幣」。「Will the SEC approve a spot ETF」
#    或者「Will Coinbase be delisted」照樣通過 —— 嗰啲有真實嘅不確定性。
PRICE_LADDER = re.compile(
    r"\bprice of\b.{0,40}\b(above|below|between)\b.{0,20}[\$£€]"
    r"|\b(above|below)\s+[\$£€][\d,\.]+\s*(on|at|by)\b"
    r"|\breach\s+[\$£€][\d,\.]+"
    r"|\bhit\s+[\$£€][\d,\.]+"
    r"|\bdip to\s+[\$£€][\d,\.]+"
    r"|\bdrop to\s+[\$£€][\d,\.]+"
    r"|\btouch\s+[\$£€][\d,\.]+"
    r"|\bclose (above|below)\s+[\$£€][\d,\.]+"
    r"|\bwhat price will\b"
    r"|\bprice on (january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b",
    re.I,
)


# ── 計數桶市場 ────────────────────────────────────────────────
#
# ⚠️ 2026-08-19 實測第五輪：主體配額騰出嚟嘅位，畀三個
#    「Will Elon Musk post 200-219 / 220-239 / 240-259 tweets」填咗。
#
#    呢個同價格階梯係**同一個 bug 類別**：結果係一個連續機械計數器
#    嘅確定性函數。「點解 200-219 嗰格郁咗 28 點？」答案永遠係
#    「因為佢今日發多咗幾條」——冇成因之謎，冇可證偽解讀。
#
#    只堵高頻機械計數（推文、貼文、追蹤者、觀看次數…）。
#    低頻離散事件照樣通過：「How many Fed rate cuts in 2026」
#    係真有討論價值嘅，因為每次減息都係一個獨立決策。
HIGH_FREQ_COUNTER = (
    r"(tweets?|posts?|xeets?|followers?|subscribers?|views?|likes?|"
    r"retweets?|replies|messages?|mentions?|streams?|downloads?)"
)

COUNT_BUCKET = re.compile(
    # "post 200-219 tweets" / "220 to 239 posts"
    rf"\b\d[\d,]*\s*(?:[-–—]|to)\s*\d[\d,]*\s+{HIGH_FREQ_COUNTER}\b"
    # "how many tweets will …"
    rf"|\bhow many\s+{HIGH_FREQ_COUNTER}\b"
    # "number of tweets between … and …"
    rf"|\bnumber of\s+{HIGH_FREQ_COUNTER}\b"
    # "post 200+ tweets" / "more than 200 tweets"
    rf"|\b(post|make|send)\s+\d[\d,]*\+?\s+{HIGH_FREQ_COUNTER}\b"
    rf"|\b(more|fewer|less) than\s+\d[\d,]*\s+{HIGH_FREQ_COUNTER}\b",
    re.I,
)


def is_count_bucket(question: str) -> bool:
    """係咪「某個高頻計數器落喺邊個區間」呢類機械式市場。"""
    return bool(COUNT_BUCKET.search(question or ""))


def is_price_ladder(question: str) -> bool:
    """係咪「資產價格穿唔穿某個水平」呢類機械式市場。

    呢類市場嘅「異動成因」永遠係「現貨價郁咗」，冇內容價值。
    """
    return bool(PRICE_LADDER.search(question or ""))


def is_mechanical(question: str) -> bool:
    """機械式市場總稱：結果由一個連續可觀察嘅公開計數器決定。

    價格階梯 + 計數桶。兩者嘅共同點係「點解郁咗」有一個
    冇資訊量嘅答案，所以寫幾多篇都係同一個故事。
    """
    return is_price_ladder(question) or is_count_bucket(question)


# ── 主體（真實世界當事人）偵測 ────────────────────────────────
#
# ⚠️ 2026-08-19 實測第四輪發現：家族去重之後，頭 10 名仍然有 7 個
#    講緊同一件事（伊朗停火 ×2、荷姆茲通航、伊朗-阿曼協議、伊朗封鎖 ×2）。
#    佢哋家族鍵各自唔同（真係唔同問題），所以家族層捉唔到 ——
#    要多一層「主體」配額：同一個真實世界當事人，24 小時內最多幾篇。
#
# 順序 = 優先次序。第一個命中就當主體。
SUBJECTS: list[tuple[str, re.Pattern]] = [
    ("iran",        re.compile(r"\b(iran|iranian|hormuz|tehran|irgc)\b", re.I)),
    ("russia",      re.compile(r"\b(russia|russian|putin|kremlin|moscow|"
                               r"united russia|duma)\b", re.I)),
    ("ukraine",     re.compile(r"\b(ukrain\w*|zelensk\w*|kyiv|donbas|"
                               r"kostyantynivka|bakhmut)\b", re.I)),
    ("israel",      re.compile(r"\b(israel\w*|netanyahu|idf|gaza|"
                               r"palestin\w*|hamas|hezbollah|west bank)\b", re.I)),
    ("china",       re.compile(r"\b(china|chinese|beijing|xi jinping|ccp|"
                               r"taiwan|pla)\b", re.I)),
    ("north_korea", re.compile(r"\b(north korea|dprk|kim jong)\b", re.I)),
    ("venezuela",   re.compile(r"\b(venezuela\w*|maduro|caracas)\b", re.I)),
    ("us_fed",      re.compile(r"\b(fed|fomc|federal reserve|powell)\b", re.I)),
    ("us_congress", re.compile(r"\b(congress|senate|house of representatives|"
                               r"h\.?r\.?\s?\d+|filibuster)\b", re.I)),
    ("us_exec",     re.compile(r"\b(white house|president|executive order|"
                               r"cabinet|potus)\b", re.I)),
    ("uk",          re.compile(r"\b(uk|britain|british|downing street|"
                               r"westminster|bank of england)\b", re.I)),
    ("eu",          re.compile(r"\b(eu|european union|brussels|ecb|"
                               r"european commission)\b", re.I)),
    ("bitcoin",     re.compile(r"\b(bitcoin|btc)\b", re.I)),
    ("ethereum",    re.compile(r"\b(ethereum|eth)\b", re.I)),
    ("openai",      re.compile(r"\b(openai|chatgpt|gpt-?\d|sam altman)\b", re.I)),
    # ⚠️ musk 係 2026-08-19 第五輪漏網（三個推文計數市場歸做 other，
    #    攞唔到主體配額嘅約束）
    ("musk",        re.compile(r"\b(elon musk|elon|musk|tesla|spacex|"
                               r"neuralink|starlink)\b", re.I)),
]


def subject(question: str) -> str:
    """回傳題目講緊嘅主要真實世界當事人。搵唔到回傳空字串。

    用嚟做「同一件事唔好一日出七篇」嘅配額。
    """
    q = question or ""
    for name, pat in SUBJECTS:
        if pat.search(q):
            return name
    return ""


def classify(question: str, description: str = "") -> str:
    """回傳主題代號。搵唔到回傳 'other'。

    只用題目為主，description 做次要參考（description 常有樣板文字，
    太依賴會誤判）。
    """
    q = question or ""
    for name, pat in RULES:
        if pat.search(q):
            # "vs" 喺法律／辯論語境唔算體育
            if name == "sports" and DEBATE_VS.search(q):
                continue
            return name
    # 題目搵唔到就試下 description 嘅頭 300 字
    if description:
        head = description[:300]
        for name, pat in RULES:
            if pat.search(head):
                if name == "sports" and DEBATE_VS.search(head):
                    continue
                return name
    return "other"
