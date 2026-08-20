"""公開紙上帳本：政治冷門籃子。

⚠️ 呢個檔案就係你 bio 寫住嘅 "Public ledger"，
   同埋置頂貼寫住嘅 "Everything is logged. The wrong ones stay up."
   佢一定要真係喺 public repo 入面，否則兩句都係空話。

設計原則：
  · **只增不改**。新條目 append，已有條目只可以更新
    現價（mark-to-market）同結算結果，唔可以刪、唔可以改入場價。
  · 用 CSV 唔用 JSON —— 你可以直接 Excel 打開，
    而且 git diff 睇得明邊行變咗。
  · 輸咗嘅照留。3/3 全 NO 就係 3/3 全 NO。

欄位：
  recorded_at   入籃日期
  market_id     Polymarket condition id
  question      市場問題
  entry_p       入籃時嘅 YES 價（永不修改）
  current_p     最近一次 mark-to-market 嘅價
  marked_at     最近一次 mark 嘅日期
  end_date      預期結算日
  category      politics / geopolitics
  strategy      入籃原因（預設 cheap_political_yes）
  status        pending / settled
  outcome       YES / NO
  pnl           結算損益（1 單位計）
"""
from __future__ import annotations
import csv
import datetime as dt
from common import STATE_DIR, log, utcnow, parse_iso

LEDGER_PATH = STATE_DIR / "pm_paper_ledger.csv"

FIELDS = ["recorded_at", "market_id", "question", "entry_p", "current_p",
          "marked_at", "end_date", "category", "strategy", "status",
          "outcome", "pnl"]

STRATEGY = "cheap_political_yes"


def _ensure() -> None:
    if not LEDGER_PATH.exists():
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def read_all() -> list[dict]:
    _ensure()
    with open(LEDGER_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_all(rows: list[dict]) -> None:
    tmp = LEDGER_PATH.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    tmp.replace(LEDGER_PATH)


def _f(v, d=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def add_candidates(markets: list[dict]) -> list[dict]:
    """新市場入籃。已經喺帳本嘅唔會重複加。"""
    _ensure()
    existing = {r["market_id"] for r in read_all()}
    today = utcnow().date().isoformat()
    added = []
    with open(LEDGER_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        for m in markets:
            mid = str(m.get("condition_id", ""))
            if not mid or mid in existing:
                continue
            row = {
                "recorded_at": today,
                "market_id": mid,
                "question": (m.get("question") or "")[:150],
                "entry_p": f"{_f(m.get('yes_price')):.4f}",
                "current_p": f"{_f(m.get('yes_price')):.4f}",
                "marked_at": today,
                "end_date": (m.get("end_date") or "")[:10],
                "category": m.get("category", ""),
                "strategy": STRATEGY,
                "status": "pending",
                "outcome": "",
                "pnl": "",
            }
            w.writerow(row)
            added.append(row)
            existing.add(mid)
    if added:
        log(f"📒 {len(added)} 個新市場入籃")
    return added


def mark_to_market(markets: list[dict]) -> dict:
    """用今日嘅價更新所有未結算條目。

    ⚠️ 冇呢一步，你 100 日內學唔到任何嘢 ——
       政治市場幾個月先結算，期間帳本會完全靜止。
       有咗佢，你每日都報告得到「籃內均價由 0.22 跌到 0.19」。
    """
    rows = read_all()
    price = {str(m.get("condition_id")): _f(m.get("yes_price")) for m in markets}
    today = utcnow().date().isoformat()

    marked = missing = 0
    for r in rows:
        if r.get("status") != "pending":
            continue
        p = price.get(r["market_id"])
        if p is None or p <= 0:
            missing += 1
            continue
        r["current_p"] = f"{p:.4f}"
        r["marked_at"] = today
        marked += 1

    if marked:
        _write_all(rows)
    log(f"📒 mark-to-market：更新 {marked} 個"
        + (f"，{missing} 個今日抓唔到報價" if missing else ""))
    return {"marked": marked, "missing": missing}


def settle(market_id: str, outcome: str) -> bool:
    """記錄結算結果。outcome 係 'YES' 或 'NO'。

    1 單位計：YES 賺 (1 - entry_p)，NO 蝕 entry_p。
    """
    rows = read_all()
    hit = False
    for r in rows:
        if r["market_id"] != market_id or r.get("status") == "settled":
            continue
        e = _f(r["entry_p"])
        r["status"] = "settled"
        r["outcome"] = outcome.upper()
        r["pnl"] = f"{(1 - e) if outcome.upper() == 'YES' else -e:.4f}"
        r["marked_at"] = utcnow().date().isoformat()
        r["current_p"] = "1.0000" if outcome.upper() == "YES" else "0.0000"
        hit = True
    if hit:
        _write_all(rows)
    return hit


def stats() -> dict:
    """籃子現況 —— basket 貼所需嘅全部數字。"""
    rows = read_all()
    pend = [r for r in rows if r.get("status") == "pending"]
    sett = [r for r in rows if r.get("status") == "settled"]

    entry = [_f(r["entry_p"]) for r in pend if _f(r["entry_p"]) > 0]
    cur = [_f(r["current_p"]) for r in pend if _f(r["current_p"]) > 0]
    yes = sum(1 for r in sett if r.get("outcome") == "YES")
    no = sum(1 for r in sett if r.get("outcome") == "NO")
    pnl = sum(_f(r["pnl"]) for r in sett)

    return {
        "total": len(rows),
        "pending": len(pend),
        "settled": len(sett),
        "settled_yes": yes,
        "settled_no": no,
        "pnl_units": round(pnl, 4),
        "roi_pct": round(100 * pnl / len(sett), 1) if sett else None,
        "mean_entry": round(sum(entry) / len(entry), 4) if entry else None,
        "mean_current": round(sum(cur) / len(cur), 4) if cur else None,
        "drift_pts": round(100 * (sum(cur) / len(cur) - sum(entry) / len(entry)), 1)
                     if entry and cur and len(entry) == len(cur) else None,
        "last_marked": max((r.get("marked_at", "") for r in pend), default=""),
    }


def due_settlement(today: dt.date | None = None) -> list[dict]:
    """結算日已過但仲係 pending 嘅條目 —— 提你去查結果。"""
    today = today or utcnow().date()
    out = []
    for r in read_all():
        if r.get("status") != "pending":
            continue
        ed = r.get("end_date", "")
        if not ed:
            continue
        try:
            if dt.date.fromisoformat(ed) <= today:
                out.append(r)
        except ValueError:
            continue
    return out
