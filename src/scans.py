"""三個結構性掃描 —— 由 DK 2026-08-19 v4 移植上雲端。

  A  籃子    政治／地緣冷門（0.10–0.35）記入公開帳本，每日 mark-to-market
  B  階梯    同一問題唔同截止日，檢查單調性
  C  盤面    negRisk board 訂單簿加總（Σask / Σbid）

呢三個先係項目嘅內容核心 —— `move` 異動註記只係填數量。

⚠️ 已知陷阱（v4 實戰得出，全部已編碼）：
   · Gamma `endDate` 唔可信 → 一律由題目 parse（deadline.py）
   · 「by market cap」唔係 deadline → 已排除（deadline.py）
   · Gamma `limit` 上限 100 → 分頁（fetch.py）
   · 訂單簿要批量取，逐個打會幾百個請求
"""
from __future__ import annotations
import json
import re
import statistics
import requests
from common import log
from deadline import parse_deadline, family_key, has_deadline_cue

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = {"User-Agent": "pmwire/1.0 (research)"}
TIMEOUT = 30
BOOK_BATCH = 120          # v4 實測可行嘅批量


# ══════════════════════════════════════════════════════════════
#  C — negRisk 盤面效率
# ══════════════════════════════════════════════════════════════

def _as_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            p = json.loads(v)
            return p if isinstance(p, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def fetch_negrisk_boards(pages: int = 8, per_page: int = 100,
                         min_markets: int = 3, max_markets: int = 25) -> list[dict]:
    """抓 negRisk event（結果互斥且窮盡，機率理應加總為 1）。

    少過 min_markets 冇嘢好檢查；多過 max_markets 盤口太薄，加總冇意義。
    """
    boards: list[dict] = []
    seen = set()
    for page in range(pages):
        try:
            r = requests.get(f"{GAMMA}/events", headers=UA, timeout=TIMEOUT, params={
                "limit": per_page, "offset": page * per_page,
                "closed": "false", "active": "true",
                "order": "volume24hr", "ascending": "false",
            })
            r.raise_for_status()
            batch = r.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            log(f"WARN 抓 events 第 {page+1} 頁失敗：{e}")
            break
        if not isinstance(batch, list) or not batch:
            break

        for ev in batch:
            if not ev.get("negRisk"):
                continue
            # ⚠️ 剔走體育。2026-08-20 實測：唯一「違規」係一場足球賽
            #    （OFI vs PFK CSKA Sofia，深度得 $23）。單場賽事盤口
            #    又薄又多，會拉歪 Σask 中位數 —— 實測含體育 1.051，
            #    而 v4 唔含體育係 1.02。要同你嘅內容主題一致。
            import classify as _cl
            title_cat = _cl.classify(ev.get("title") or "")
            if title_cat in ("sports", "weather", "culture"):
                continue
            eid = str(ev.get("id", ""))
            if eid in seen:
                continue
            mkts = ev.get("markets") or []
            if not (min_markets <= len(mkts) <= max_markets):
                continue

            legs = []
            for m in mkts:
                toks = _as_list(m.get("clobTokenIds"))
                outs = _as_list(m.get("outcomes"))
                if len(toks) != 2 or len(outs) != 2:
                    continue
                # 取 YES 嗰邊嘅 token
                yes_i = 0
                for i, o in enumerate(outs):
                    if isinstance(o, str) and o.strip().lower() == "yes":
                        yes_i = i
                        break
                legs.append({"token": str(toks[yes_i]),
                             "question": (m.get("question") or "")[:120]})
            if len(legs) < min_markets:
                continue

            seen.add(eid)
            boards.append({
                "event_id": eid,
                "title": (ev.get("title") or "")[:140],
                "volume_24hr": _f(ev.get("volume24hr")),
                "legs": legs,
            })
        if len(batch) < per_page:
            break

    log(f"negRisk 盤面：{len(boards)} 個（{min_markets}–{max_markets} 個成分）")
    return boards


def fetch_books(token_ids: list[str]) -> dict[str, dict]:
    """批量取訂單簿。回傳 {token_id: {best_bid, best_ask, depth}}。

    主路用 POST /books（v4 實測 120 個一批）。
    失敗就 fallback 去逐個 GET /book —— 慢但可靠。
    """
    out: dict[str, dict] = {}

    def absorb(ob: dict) -> None:
        tid = str(ob.get("asset_id") or ob.get("token_id") or "")
        if not tid:
            return
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        # ⚠️ 唔好靠陣列次序攞最佳價 —— Polymarket 兩邊排序方向唔同，
        #    而且文檔冇保證。直接攞極值最穩陣。
        bp = [_f(b.get("price"), -1) for b in bids]
        ap = [_f(a.get("price"), -1) for a in asks]
        bp = [p for p in bp if 0 <= p <= 1]
        ap = [p for p in ap if 0 <= p <= 1]
        best_bid = max(bp) if bp else 0.0
        best_ask = min(ap) if ap else 0.0
        # 深度 = 最佳價嗰一檔嘅金額（用嚟過濾「紙面矛盾但根本冇單」）
        depth = 0.0
        for a in asks:
            if abs(_f(a.get("price"), -1) - best_ask) < 1e-9:
                depth = max(depth, _f(a.get("size")) * best_ask)
        out[tid] = {"best_bid": best_bid, "best_ask": best_ask, "depth": depth}

    for i in range(0, len(token_ids), BOOK_BATCH):
        chunk = token_ids[i:i + BOOK_BATCH]
        try:
            r = requests.post(f"{CLOB}/books", headers=UA, timeout=TIMEOUT,
                              json=[{"token_id": t} for t in chunk])
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for ob in data:
                        absorb(ob)
                    continue
            log(f"WARN 批量 /books 回 {r.status_code}，改用逐個 GET")
        except (requests.RequestException, json.JSONDecodeError) as e:
            log(f"WARN 批量 /books 出錯（{e}），改用逐個 GET")

        for t in chunk:
            try:
                r = requests.get(f"{CLOB}/book", headers=UA, timeout=TIMEOUT,
                                 params={"token_id": t})
                if r.status_code == 200:
                    absorb(r.json())
            except (requests.RequestException, json.JSONDecodeError):
                continue

    return out


def score_boards(boards: list[dict], min_depth_usd: float = 20.0) -> list[dict]:
    """計每個盤面嘅 Σask / Σbid。冇齊報價嘅盤面剔走。"""
    tokens = [leg["token"] for b in boards for leg in b["legs"]]
    if not tokens:
        return []
    log(f"取 {len(tokens)} 個 token 嘅訂單簿…")
    books = fetch_books(tokens)

    scored = []
    for b in boards:
        asks, bids, depths = [], [], []
        for leg in b["legs"]:
            ob = books.get(leg["token"])
            if not ob or ob["best_ask"] <= 0 or ob["best_bid"] <= 0:
                asks = []
                break
            asks.append(ob["best_ask"])
            bids.append(ob["best_bid"])
            depths.append(ob["depth"])
        if not asks:
            continue
        scored.append(dict(b,
                           sum_ask=sum(asks), sum_bid=sum(bids),
                           min_depth=min(depths), n_legs=len(asks)))
    log(f"取到完整報價嘅盤面：{len(scored)} / {len(boards)}")
    return scored


def board_report(scored: list[dict], ask_floor: float = 1.00,
                 bid_ceiling: float = 1.00, min_depth_usd: float = 250.0) -> dict:
    """彙總成一篇 anchor 貼所需嘅數字。

    Σask < 1.00 或 Σbid > 1.00 = 內部矛盾。
    但要求最小深度 —— 紙面矛盾而只得幾蚊掛住，唔算真矛盾，只係空。

    ⚠️ 門檻由 $20 提高到 $250。2026-08-20 實測，$20 會放行一個
       深度得 $23 嘅「違規」—— 嗰個係噪音唔係訊號。
    """
    if not scored:
        return {"n_boards": 0, "median_ask": None, "median_bid": None,
                "violations": [], "n_violations": 0}

    asks = [b["sum_ask"] for b in scored]
    bids = [b["sum_bid"] for b in scored]
    viol = []
    for b in scored:
        if b["min_depth"] < min_depth_usd:
            continue
        if b["sum_ask"] < ask_floor:
            viol.append(dict(b, kind="ask_sum_below_1"))
        elif b["sum_bid"] > bid_ceiling:
            viol.append(dict(b, kind="bid_sum_above_1"))

    return {
        "n_boards": len(scored),
        "median_ask": round(statistics.median(asks), 4),
        "median_bid": round(statistics.median(bids), 4),
        "min_ask": round(min(asks), 4),
        "max_bid": round(max(bids), 4),
        "violations": viol,
        "n_violations": len(viol),
    }


# ══════════════════════════════════════════════════════════════
#  B — 日期階梯單調性
# ══════════════════════════════════════════════════════════════

# ⚠️ 方向性：唔係所有階梯都「越遲越高」。
#    「Will X happen BY <date>」  → 時間越長越易發生 → 價格應該遞增
#    「X CONTINUES THROUGH <date>」→ 要維持得越耐越難 → 價格應該遞減
#    DK 個 Iran ceasefire 家族正正係第二種（90% Aug 31 → 70% Sep 30），
#    當成第一種就會報一大堆假違規。
PERSISTENCE = re.compile(
    r"\b(continue|continues|continuing|remain|remains|stay|stays|"
    r"hold|holds|still|persist|persists|survive|survives|"
    r"in (office|power)|avoid|avoids|without)\b", re.I)


def ladder_polarity(question: str) -> str:
    """回傳 'increasing'（by 型）或 'decreasing'（persistence 型）。"""
    return "decreasing" if PERSISTENCE.search(question or "") else "increasing"


def ladder_scan(markets: list[dict], threshold: float = 0.015,
                min_volume: float = 20000.0) -> list[dict]:
    """搵同一家族入面違反單調性嘅組合。"""
    fams: dict[str, list[dict]] = {}
    for m in markets:
        q = m.get("question", "")
        if m.get("volume_24hr", 0) < min_volume:
            continue
        if not has_deadline_cue(q):
            continue
        d = parse_deadline(q)
        if not d:
            continue
        fams.setdefault(family_key(q), []).append(dict(m, _deadline=d))

    violations = []
    checked = 0
    for fam, legs in fams.items():
        if len(legs) < 2:
            continue
        # 同一 deadline 嘅重複腳去掉，只留成交額最大嗰個
        by_date: dict = {}
        for lg in legs:
            k = lg["_deadline"]
            if k not in by_date or lg["volume_24hr"] > by_date[k]["volume_24hr"]:
                by_date[k] = lg
        legs = sorted(by_date.values(), key=lambda x: x["_deadline"])
        if len(legs) < 2:
            continue
        checked += 1

        pol = ladder_polarity(legs[0]["question"])
        for i in range(len(legs) - 1):
            a, b = legs[i], legs[i + 1]        # a 較早，b 較遲
            gap = (a["yes_price"] - b["yes_price"]) if pol == "increasing" \
                else (b["yes_price"] - a["yes_price"])
            if gap > threshold:
                violations.append({
                    "family": fam, "polarity": pol, "gap": round(gap, 4),
                    "early": {"question": a["question"], "deadline": a["_deadline"].isoformat(),
                              "price": a["yes_price"], "volume_24hr": a["volume_24hr"]},
                    "late": {"question": b["question"], "deadline": b["_deadline"].isoformat(),
                             "price": b["yes_price"], "volume_24hr": b["volume_24hr"]},
                })

    log(f"階梯掃描：{checked} 個多腳家族，{len(violations)} 個違規"
        f"（門檻 {threshold:.3f}）")
    return sorted(violations, key=lambda v: -v["gap"])


# ══════════════════════════════════════════════════════════════
#  A — 政治冷門籃子
# ══════════════════════════════════════════════════════════════

BASKET_CATEGORIES = {"politics", "geopolitics"}


def basket_candidates(markets: list[dict], lo: float = 0.10, hi: float = 0.35,
                      min_volume_total: float = 100_000.0,
                      max_new: int | None = None) -> list[dict]:
    """符合籃子條件嘅市場。

    政治／地緣 + 價格 0.10–0.35 + 累計成交額 ≥ 10 萬。
    呢個組合正正係文獻指出校準最差嘅角落（政治斜率 1.31）——
    所以佢係一個**測量儀器**，唔係選股器。
    """
    out = []
    for m in markets:
        if m.get("category") not in BASKET_CATEGORIES:
            continue
        if m.get("price_ladder"):
            continue
        if not (lo <= m.get("yes_price", 0) <= hi):
            continue
        if m.get("volume_total", 0) < min_volume_total:
            continue
        out.append(m)

    # 每日入籃上限：超額就按累計成交額排序，只留最大嗰批。
    # 冇呢個上限，籃子會變成拖網而唔係受控實驗。
    out.sort(key=lambda m: -m.get("volume_total", 0))
    if max_new is not None and len(out) > max_new:
        log(f"籃子候選 {len(out)} 個，按每日上限只取成交額最大嘅 {max_new} 個")
        out = out[:max_new]
    return out
