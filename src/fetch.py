"""由 Polymarket Gamma API 抓取活躍市場。

Gamma 係公開唯讀 API，唔需要 API key。
速率限制：/markets 300 req/10s，/events 500 req/10s —— 我哋每次 run 用 <10 個請求。
文檔：https://docs.polymarket.com/api-reference/markets/list-markets
"""
from __future__ import annotations
import json
import requests
from common import log

GAMMA = "https://gamma-api.polymarket.com"
UA = {"User-Agent": "pmwire/1.0 (research; contact via GitHub)"}
TIMEOUT = 25


def _as_float(v, default=0.0) -> float:
    """Gamma 有啲數值欄位係字串，有啲係 null。統一轉 float。"""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (ValueError, AttributeError):
        return default


def _as_list(v):
    """outcomes / outcomePrices 有時係 JSON 字串，有時係真 list。"""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def fetch_markets(pages: int = 12, per_page: int = 100) -> list[dict]:
    """按 24 小時成交額由大到小抓活躍未平倉市場。

    ⚠️ Gamma 嘅 `limit` 上限係 100 —— 傳 250 佢一樣只回 100。
       之前寫 per_page=250，結果第一頁攞到 100 < 250 就當「冇更多」跳出，
       總共只抓到 100 個市場。實測（2026-08-19）先發現。
       而家 12 頁 × 100 = 最多 1,200 個。
    """
    out: list[dict] = []
    for page in range(pages):
        params = {
            "limit": per_page,
            "offset": page * per_page,
            "closed": "false",
            "active": "true",
            "order": "volume24hr",
            "ascending": "false",
        }
        try:
            r = requests.get(f"{GAMMA}/markets", params=params,
                             headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            batch = r.json()
        except requests.RequestException as e:
            log(f"WARN 抓第 {page+1} 頁失敗：{e}")
            break
        except json.JSONDecodeError as e:
            log(f"WARN 第 {page+1} 頁回應唔係 JSON：{e}")
            break

        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        if len(batch) < per_page:
            break

    log(f"抓到 {len(out)} 個活躍市場")
    return out


def normalise(m: dict) -> dict | None:
    """將 Gamma 嘅原始 market 物件轉成我哋用嘅精簡結構。

    唔合用嘅（例如唔係二元市場、冇賠率）回傳 None。
    """
    outcomes = _as_list(m.get("outcomes"))
    prices = [_as_float(p, -1.0) for p in _as_list(m.get("outcomePrices"))]

    # 只處理二元市場（Yes/No）。多結果市場嘅「賠率變動」語意唔同，另外處理。
    if len(outcomes) != 2 or len(prices) != 2:
        return None
    if any(p < 0 for p in prices):
        return None

    # 慣例：outcomes[0] 係 "Yes"
    yes_idx = 0
    for i, o in enumerate(outcomes):
        if isinstance(o, str) and o.strip().lower() == "yes":
            yes_idx = i
            break
    yes_price = prices[yes_idx]

    if not (0.0 < yes_price < 1.0):
        return None  # 已經定局嘅盤（0 或 1）冇分析價值

    cond = m.get("conditionId") or m.get("condition_id") or m.get("id")
    if not cond:
        return None

    # 變動欄位嘅正負係相對 outcomes[0]；如果 Yes 唔係 index 0 要反轉
    flip = -1.0 if yes_idx != 0 else 1.0

    question = (m.get("question") or "").strip()
    description = (m.get("description") or "")[:1500]

    # ⚠️ Gamma 個 `category` 欄位實測係空嘅（2026-08-19，100/100 全空）。
    #    一律由題目文字推斷，唔靠 metadata。詳見 classify.py。
    import classify as _classify
    category = _classify.classify(question, description)
    # 機械式市場 = 價格階梯 + 計數桶（見 classify.is_mechanical）
    price_ladder = _classify.is_mechanical(question)

    return {
        "condition_id": str(cond),
        "market_id": str(m.get("id", "")),
        "question": question,
        "slug": m.get("slug") or "",
        "category": category,
        "category_raw": (m.get("category") or "").strip(),
        "price_ladder": price_ladder,
        "subject": _classify.subject(question),
        "yes_price": yes_price,
        "outcomes": outcomes,
        "best_bid": _as_float(m.get("bestBid")),
        "best_ask": _as_float(m.get("bestAsk")),
        "last_trade_price": _as_float(m.get("lastTradePrice")),
        "move_1h": _as_float(m.get("oneHourPriceChange")) * flip,
        "move_24h": _as_float(m.get("oneDayPriceChange")) * flip,
        "move_1w": _as_float(m.get("oneWeekPriceChange")) * flip,
        "volume_24hr": _as_float(m.get("volume24hr")),
        "volume_total": _as_float(m.get("volumeNum") or m.get("volume")),
        "liquidity": _as_float(m.get("liquidityNum") or m.get("liquidity")),
        "end_date": m.get("endDate"),
        "start_date": m.get("startDate"),
        "description": description,
    }


def fetch_states_by_condition(condition_ids: list[str],
                              batch: int = 40) -> dict[str, dict]:
    """按 condition_id 查現況。回傳 {cid: {yes_price, closed, outcome}}。

    ⚠️ 三個一齊搞掂嘅陷阱（2026-08-20 實測：48/48 全部攞唔到）：

      1. Gamma `/markets` 預設 `closed=false` —— 已結算嘅持倉
         唔會回，所以要分兩趟（開市 + 已結算）。
      2. `normalise()` 會剔走價格 0 或 1 嘅市場（當佢定局），
         但帳本正正需要嗰啲 —— 所以呢度唔用 normalise，直接抽價。
      3. 已結算嘅唔應該只係「查唔到價」，而應該自動入帳。
         回傳 outcome 畀 ledger 自動 settle。
    """
    out: dict[str, dict] = {}
    ids = [c for c in condition_ids if c]
    if not ids:
        return out

    def absorb(m: dict) -> None:
        cid = str(m.get("conditionId") or m.get("condition_id") or "")
        if not cid:
            return
        outs = _as_list(m.get("outcomes"))
        prices = [_as_float(p, -1.0) for p in _as_list(m.get("outcomePrices"))]
        if len(outs) != 2 or len(prices) != 2 or any(p < 0 for p in prices):
            return
        yes_i = 0
        for i, o in enumerate(outs):
            if isinstance(o, str) and o.strip().lower() == "yes":
                yes_i = i
                break
        yp = prices[yes_i]
        closed = bool(m.get("closed"))
        outcome = ""
        if closed or yp >= 0.999 or yp <= 0.001:
            outcome = "YES" if yp >= 0.5 else "NO"
        out[cid] = {"yes_price": yp, "closed": closed, "outcome": outcome}

    for closed_flag in ("false", "true"):
        remaining = [c for c in ids if c not in out]
        if not remaining:
            break
        for i in range(0, len(remaining), batch):
            chunk = remaining[i:i + batch]
            try:
                r = requests.get(f"{GAMMA}/markets", headers=UA, timeout=TIMEOUT,
                                 params=[("condition_ids", c) for c in chunk]
                                        + [("limit", len(chunk)),
                                           ("closed", closed_flag)])
                r.raise_for_status()
                data = r.json()
            except (requests.RequestException, json.JSONDecodeError) as e:
                log(f"WARN 查價失敗（closed={closed_flag} 第 {i//batch + 1} 批）：{e}")
                continue
            if isinstance(data, list):
                for m in data:
                    absorb(m)

    n_closed = sum(1 for v in out.values() if v["outcome"])
    log(f"  直接查價：{len(out)}/{len(ids)} 個攞到"
        + (f"，其中 {n_closed} 個已結算" if n_closed else ""))
    return out


def fetch_normalised() -> list[dict]:
    raw = fetch_markets()
    out = []
    for m in raw:
        n = normalise(m)
        if n and n["question"]:
            out.append(n)
    log(f"其中 {len(out)} 個係可用嘅二元市場")
    return out


if __name__ == "__main__":
    ms = fetch_normalised()
    for m in ms[:5]:
        print(f"{m['yes_price']:.3f}  Δ1h={m['move_1h']:+.3f}  "
              f"Δ24h={m['move_24h']:+.3f}  ${m['volume_24hr']:,.0f}  {m['question'][:70]}")
