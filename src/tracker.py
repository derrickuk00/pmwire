"""回訪追蹤：記低每日寫過乜、幾時要回訪、幾時應該有結果、結果係咩。

點解要有呢個模組：
    冇佢，一堆貼文就係散貨 —— 出咗就冇下文，讀者冇理由追你，
    你自己亦唔會知邊個判斷啱過。
    有佢，同一堆貼文就變成一條可審計嘅往績鏈。

    最重要係：**逐次記低，唔可以揀啱嗰啲先講。**
    講中嘅同講錯嘅都喺同一個 CSV 入面，任何人可以自己數。

格式用 CSV 唔用 JSON，理由：
    你可以直接喺 Excel / Google Sheets 打開、排序、做圖表，
    而且 git diff 睇得明（JSON 改一個欄位成個檔案都變）。
"""
from __future__ import annotations
import csv
import datetime as dt
from pathlib import Path
from common import STATE_DIR, log, utcnow, parse_iso

LOG_PATH = STATE_DIR / "post_log.csv"

FIELDS = [
    "post_date",        # 出稿日 YYYY-MM-DD
    "post_id",          # 佇列 id
    "tier",             # anchor / basket / violation / method / discussion / move
    "condition_id",     # Polymarket 市場 id（可空，例如 anchor 貼）
    "question",         # 市場問題（截短）
    "claim",            # 這篇實際講咗咩（一句，用嚟日後對數）
    "price_at_post",    # 出稿時 YES 價（可空）
    "resolution_date",  # 預期結算日 YYYY-MM-DD（可空）
    "revisit_date",     # 應該回訪日 YYYY-MM-DD（可空）
    "status",           # open / revisited / resolved / void
    "outcome",          # YES / NO / correct / wrong / partial / n_a
    "revisited_at",     # 實際回訪日
    "tweet_id",
    "notes",
]

# 每種內容類型隔幾多日回訪。None = 唔需要回訪（例如每日錨定貼）。
REVISIT_DAYS = {
    "anchor": None,       # 每日效率讀數 —— 本身就係連續系列
    "method": None,       # 方法論 —— 冇嘢好回訪
    "basket": 7,          # 籃子追蹤 —— 每週對數
    "violation": 3,       # 階梯／board 違規 —— 3 日後睇下收窄咗未
    "move": 5,            # 異動註記 —— 5 日後睇下係咪真訊號
    "discussion": None,   # 討論型 —— 回訪日 = 結算日（下面特別處理）
}


def _ensure() -> None:
    if not LOG_PATH.exists():
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def read_all() -> list[dict]:
    _ensure()
    with open(LOG_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_all(rows: list[dict]) -> None:
    tmp = LOG_PATH.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    tmp.replace(LOG_PATH)


def _d(x) -> str:
    if isinstance(x, dt.datetime):
        return x.date().isoformat()
    if isinstance(x, dt.date):
        return x.isoformat()
    if isinstance(x, str) and x:
        p = parse_iso(x)
        if p:
            return p.date().isoformat()
        return x[:10]
    return ""


def compute_revisit(tier: str, post_date: dt.date,
                    resolution_date: str | None) -> str:
    """按內容類型算出回訪日。

    ⚠️ 回訪日唔可以遲過結算日。
       2026-08-19 實測捉到：一個 8-21 結算嘅市場，move 型別排咗
       8-24 回訪 —— 即係等市場結咗兩日先「覆查」，冇意義。
       結算日較早就以結算日為準。
    """
    res = _d(resolution_date)

    if tier == "discussion":
        # 討論型：結算日就係回訪日（承諾咗「無論點樣都會出結算」）
        return res

    days = REVISIT_DAYS.get(tier)
    if days is None:
        return ""
    planned = post_date + dt.timedelta(days=days)

    if res:
        try:
            res_d = dt.date.fromisoformat(res)
            if res_d < planned:
                return res_d.isoformat()
        except ValueError:
            pass
    return planned.isoformat()


def log_post(*, post_id: str, tier: str, question: str, claim: str,
             condition_id: str = "", price_at_post: float | None = None,
             resolution_date: str | None = None, tweet_id: str = "",
             notes: str = "") -> dict:
    """出稿之後即刻記低一行。append-only。"""
    _ensure()
    today = utcnow().date()
    row = {
        "post_date": today.isoformat(),
        "post_id": post_id,
        "tier": tier,
        "condition_id": condition_id,
        "question": (question or "")[:150],
        "claim": (claim or "")[:300],
        "price_at_post": f"{price_at_post:.4f}" if price_at_post is not None else "",
        "resolution_date": _d(resolution_date),
        "revisit_date": compute_revisit(tier, today, resolution_date),
        "status": "open",
        "outcome": "",
        "revisited_at": "",
        "tweet_id": tweet_id,
        "notes": notes,
    }
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow(row)
    log(f"  📓 已記入 post_log：{tier} / 回訪 {row['revisit_date'] or '不需要'}")
    return row


def due_revisits(today: dt.date | None = None) -> list[dict]:
    """今日（或之前）應該回訪、但仲未回訪嘅。"""
    today = today or utcnow().date()
    out = []
    for r in read_all():
        if r.get("status") != "open":
            continue
        rv = r.get("revisit_date", "")
        if not rv:
            continue
        try:
            if dt.date.fromisoformat(rv) <= today:
                out.append(r)
        except ValueError:
            continue
    return out


def due_resolutions(today: dt.date | None = None) -> list[dict]:
    """結算日已到、但仲未記結果嘅。"""
    today = today or utcnow().date()
    out = []
    for r in read_all():
        if r.get("status") == "resolved":
            continue
        rd = r.get("resolution_date", "")
        if not rd:
            continue
        try:
            if dt.date.fromisoformat(rd) <= today:
                out.append(r)
        except ValueError:
            continue
    return out


def mark(post_id: str, *, status: str, outcome: str = "",
         notes: str = "") -> bool:
    """更新一行嘅狀態／結果。只改 status/outcome/revisited_at/notes。"""
    rows = read_all()
    hit = False
    for r in rows:
        if r.get("post_id") == post_id:
            r["status"] = status
            if outcome:
                r["outcome"] = outcome
            if status in ("revisited", "resolved"):
                r["revisited_at"] = utcnow().date().isoformat()
            if notes:
                r["notes"] = (r.get("notes", "") + " | " + notes).strip(" |")
            hit = True
    if hit:
        _write_all(rows)
    return hit


def tally() -> dict:
    """往績統計。呢個數字要照出，唔可以揀。"""
    rows = read_all()
    resolved = [r for r in rows if r.get("status") == "resolved"]
    correct = sum(1 for r in resolved if r.get("outcome") in ("correct", "YES"))
    wrong = sum(1 for r in resolved if r.get("outcome") in ("wrong", "NO"))
    return {
        "total_posts": len(rows),
        "open": sum(1 for r in rows if r.get("status") == "open"),
        "resolved": len(resolved),
        "correct": correct,
        "wrong": wrong,
        "by_tier": {t: sum(1 for r in rows if r.get("tier") == t)
                    for t in sorted({r.get("tier", "") for r in rows} - {""})},
    }


def digest(today: dt.date | None = None) -> str:
    """每日 Telegram 摘要：今日寫過乜、邊啲到期回訪、邊啲應有結果。"""
    today = today or utcnow().date()
    rows = read_all()
    today_posts = [r for r in rows if r.get("post_date") == today.isoformat()]
    rev = due_revisits(today)
    res = due_resolutions(today)
    t = tally()

    lines = [f"📓 <b>{today.isoformat()} 內容日誌</b>", ""]

    if today_posts:
        lines.append(f"<b>今日已出 {len(today_posts)} 篇</b>")
        for r in today_posts:
            q = r["question"][:52] or "—"
            lines.append(f"  · [{r['tier']}] {q}")
    else:
        lines.append("今日未出稿")
    lines.append("")

    if rev:
        lines.append(f"🔁 <b>到期回訪 {len(rev)} 宗</b>")
        for r in rev[:10]:
            lines.append(f"  · {r['post_date']} [{r['tier']}] {r['question'][:46]}")
            if r.get("claim"):
                lines.append(f"     當時講：{r['claim'][:70]}")
    else:
        lines.append("🔁 今日冇到期回訪")
    lines.append("")

    if res:
        lines.append(f"🎯 <b>應有結果 {len(res)} 宗 —— 記得出結算貼</b>")
        for r in res[:10]:
            price = f" @ {float(r['price_at_post']):.0%}" if r.get("price_at_post") else ""
            lines.append(f"  · {r['question'][:46]}{price}")
    else:
        lines.append("🎯 今日冇市場到期")
    lines.append("")

    lines.append(f"<b>往績</b>　累計 {t['total_posts']} 篇 · "
                 f"未結 {t['open']} · 已結 {t['resolved']}"
                 + (f"（中 {t['correct']} / 錯 {t['wrong']}）" if t["resolved"] else ""))
    return "\n".join(lines)
