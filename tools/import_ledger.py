#!/usr/bin/env python3
"""把 v4 嘅 pm_paper_ledger.csv 導入 pmwire 格式。

用法：
    python tools/import_ledger.py <你原本個 CSV 路徑>

只補欄位，唔改任何已有數值。已結算嘅條目原樣保留。
"""
from __future__ import annotations
import sys, csv, pathlib, datetime as dt

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
import ledger  # noqa: E402
import classify  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = pathlib.Path(sys.argv[1]).expanduser()
    if not src.exists():
        print(f"✗ 搵唔到 {src}")
        return 1

    with open(src, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("✗ 個檔案冇資料")
        return 1

    today = dt.date.today().isoformat()
    out = []
    for r in rows:
        entry = (r.get("entry_p") or "").strip()
        q = (r.get("question") or "").strip()
        status = (r.get("status") or "pending").strip()
        outcome = (r.get("outcome") or "").strip().upper()
        # 已結算嘅：current_p 反映結果；未結算嘅：初值 = entry_p
        if status == "settled" and outcome in ("YES", "NO"):
            cur = "1.0000" if outcome == "YES" else "0.0000"
        else:
            cur = entry
        out.append({
            "recorded_at": (r.get("recorded_at") or "")[:10],
            "market_id": (r.get("market_id") or "").strip(),
            "question": q[:150],
            "entry_p": entry,
            "current_p": cur,
            "marked_at": (r.get("recorded_at") or today)[:10],
            "end_date": (r.get("end_date") or "")[:10],
            "category": r.get("category") or classify.classify(q),
            "strategy": r.get("strategy") or ledger.STRATEGY,
            "status": status,
            "outcome": outcome,
            "pnl": (r.get("pnl") or "").strip(),
        })

    ledger._write_all(out)
    st = ledger.stats()
    print(f"✓ 導入 {len(out)} 筆 → {ledger.LEDGER_PATH}")
    print(f"  未結算 {st['pending']}　已結算 {st['settled']}"
          f"（YES {st['settled_yes']} / NO {st['settled_no']}）")
    if st["roi_pct"] is not None:
        print(f"  已結算 ROI {st['roi_pct']:+.1f}%")
    print("\n跟住跑：python src/run.py scan   （攞今日價 mark-to-market）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
