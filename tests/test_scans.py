"""scans.py + ledger.py 測試 —— 重點係階梯方向性同帳本只增不改。"""
import sys, os, datetime as dt, tempfile, pathlib
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "..", "src"))

import common
TMP = tempfile.mkdtemp()
common.STATE_DIR = pathlib.Path(TMP)

import scans, ledger, classify
ledger.LEDGER_PATH = common.STATE_DIR / "pm_paper_ledger.csv"

FAILED = []
def check(name, cond, detail=""):
    print(f"{'✅' if cond else '❌'} {name}" + (f"  {detail}" if detail else ""))
    if not cond: FAILED.append(name)


def mk(q, price, vol=200000, cat=None, days=60, cid=None):
    end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    return {"condition_id": cid or q[:30], "question": q,
            "category": cat or classify.classify(q),
            "price_ladder": classify.is_mechanical(q),
            "yes_price": price, "volume_24hr": vol, "volume_total": vol * 6,
            "end_date": end.isoformat()}


print("── 1. 階梯方向性（v4 最大陷阱）──")
# 「by」型：時間越長越易發生 → 價格應遞增
check("『by』型判為 increasing",
      scans.ladder_polarity("Will Iran close the Strait of Hormuz by June 30, 2026?") == "increasing")
# 「continues through」型：維持越耐越難 → 價格應遞減
for q in ["US ceasefire against Iran continues through September 30?",
          "Will the Prime Minister remain in office through December 31?",
          "Will the truce hold through August 31?",
          "Will BTC stay above 60k through Q4?"]:
    check(f"persistence 判為 decreasing：{q[:44]}",
          scans.ladder_polarity(q) == "decreasing")

print("\n── 2. 『by』型階梯 ──")
ok_by = [mk("Will X happen by June 30, 2026?", 0.30),
         mk("Will X happen by September 30, 2026?", 0.42),
         mk("Will X happen by December 31, 2026?", 0.55)]
check("正常遞增 → 零違規", scans.ladder_scan(ok_by) == [])

bad_by = [mk("Will Y happen by June 30, 2026?", 0.40),
          mk("Will Y happen by December 31, 2026?", 0.31)]
v = scans.ladder_scan(bad_by)
check("遲 deadline 反而低 → 捉到", len(v) == 1, str(len(v)))
if v:
    check("差距計啱", abs(v[0]["gap"] - 0.09) < 1e-9, str(v[0]["gap"]))
    check("方向標記啱", v[0]["polarity"] == "increasing")

print("\n── 3. persistence 型階梯（DK 真數據）──")
# 90% (Aug 31) → 70% (Sep 30)：遞減，係**正常**
real = [mk("US ceasefire against Iran continues through August 31?", 0.90, 134024),
        mk("US ceasefire against Iran continues through September 30?", 0.70, 111463)]
check("真實遞減 → 唔應該報違規", scans.ladder_scan(real) == [],
      str(scans.ladder_scan(real)))
# 如果當成 increasing 就會報 0.20 嘅假違規
check("（對照）當成 increasing 就會出假違規",
      scans.ladder_polarity(real[0]["question"]) != "increasing")

# 反過來：persistence 型但遲嗰個反而高 = 真違規
bad_p = [mk("Truce continues through August 31?", 0.60),
         mk("Truce continues through December 31?", 0.75)]
check("persistence 型遲嗰個更高 → 捉到", len(scans.ladder_scan(bad_p)) == 1)

print("\n── 4. 階梯掃描其他過濾 ──")
check("單腳家族唔檢查",
      scans.ladder_scan([mk("Will Z happen by June 30, 2026?", 0.4)]) == [])
check("成交額太低唔檢查",
      scans.ladder_scan([mk("Will W happen by June 30, 2026?", 0.40, 5000),
                         mk("Will W happen by December 31, 2026?", 0.31, 5000)]) == [])
check("『by market cap』唔會被當成階梯",
      scans.ladder_scan([mk("Will NVIDIA be largest by market cap?", 0.40),
                         mk("Will NVIDIA be largest by revenue?", 0.31)]) == [])

print("\n── 5. 籃子候選 ──")
pool = [
    mk("Will the Senate confirm the nominee by March?", 0.22, cat="politics"),
    mk("Will Iran close the Strait of Hormuz by December 31, 2026?", 0.18, cat="geopolitics"),
    mk("Will the Senate act?", 0.60, cat="politics"),          # 太貴
    mk("Will X happen?", 0.05, cat="politics"),                # 太平
    mk("Will Bitcoin reach $72,500 in August?", 0.25),          # crypto + 機械式
]
c = scans.basket_candidates(pool)
check("只揀政治／地緣 0.10–0.35", len(c) == 2, f"{len(c)} 個")
check("剔走機械式市場",
      all(not x.get("price_ladder") for x in c))

print("\n── 6. 帳本：只增不改 ──")
added = ledger.add_candidates(c)
check("兩個入籃", len(added) == 2, str(len(added)))
check("重複加唔會double", len(ledger.add_candidates(c)) == 0)
check("入場價記低咗", all(float(r["entry_p"]) > 0 for r in ledger.read_all()))

print("\n── 7. mark-to-market ──")
moved = [dict(x, yes_price=x["yes_price"] - 0.05) for x in c]
res = ledger.mark_to_market(moved)
check("兩個都 mark 咗", res["marked"] == 2, str(res))
rows = ledger.read_all()
check("入場價冇被改",
      all(abs(float(r["entry_p"]) - float(r["current_p"])) > 0.04 for r in rows),
      str([(r["entry_p"], r["current_p"]) for r in rows]))
st = ledger.stats()
check("籃子漂移計到", st["drift_pts"] is not None and st["drift_pts"] < 0,
      f"drift={st['drift_pts']}")

print("\n── 8. 結算 ──")
mid = rows[0]["market_id"]
check("結算成功", ledger.settle(mid, "NO"))
st = ledger.stats()
check("已結算 1", st["settled"] == 1, str(st["settled"]))
check("NO 記低咗", st["settled_no"] == 1)
check("蝕咗嘅照計入 ROI", st["roi_pct"] is not None and st["roi_pct"] < 0,
      f"roi={st['roi_pct']}%")
check("未結算剩 1", st["pending"] == 1)

print("\n── 9. 到期提醒 ──")
rows = ledger.read_all()
for r in rows:
    if r["status"] == "pending":
        r["end_date"] = (dt.date.today() - dt.timedelta(days=1)).isoformat()
ledger._write_all(rows)
check("捉到過咗結算日仲 pending 嘅", len(ledger.due_settlement()) == 1)

print("\n── 10. 盤面彙總 ──")
scored = [
    {"event_id": "1", "title": "A", "sum_ask": 1.02, "sum_bid": 0.99,
     "min_depth": 500, "n_legs": 4, "legs": []},
    {"event_id": "2", "title": "B", "sum_ask": 1.03, "sum_bid": 0.98,
     "min_depth": 500, "n_legs": 5, "legs": []},
    {"event_id": "3", "title": "C 紙面矛盾但冇深度", "sum_ask": 0.94,
     "sum_bid": 0.90, "min_depth": 3, "n_legs": 3, "legs": []},
    {"event_id": "4", "title": "D 真矛盾", "sum_ask": 0.95, "sum_bid": 0.92,
     "min_depth": 800, "n_legs": 3, "legs": []},
]
rep = scans.board_report(scored)
import statistics as _st
want = round(_st.median([b["sum_ask"] for b in scored]), 4)
check("中位數計啱", rep["median_ask"] == want, f'{rep["median_ask"]} vs {want}')
check("深度不足嘅唔算違規", all(v["event_id"] != "3" for v in rep["violations"]))
check("有深度嘅真矛盾捉到", any(v["event_id"] == "4" for v in rep["violations"]))
check("違規數啱", rep["n_violations"] == 1, str(rep["n_violations"]))
check("空輸入唔會爆", scans.board_report([])["n_boards"] == 0)

import shutil; shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("🎉 scans + ledger 全部通過" if not FAILED
              else f"⚠️  {len(FAILED)} 項失敗：{FAILED}"))
sys.exit(1 if FAILED else 0)
