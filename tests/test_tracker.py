"""tracker.py 測試：回訪日計算、到期偵測、往績統計、日誌摘要。"""
import sys, os, datetime as dt, tempfile, pathlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import common
TMP = tempfile.mkdtemp()
common.STATE_DIR = pathlib.Path(TMP)

import tracker
tracker.STATE_DIR = common.STATE_DIR
tracker.LOG_PATH = common.STATE_DIR / "post_log.csv"

FAILED = []
def check(name, cond, detail=""):
    print(f"{'✅' if cond else '❌'} {name}" + (f"  {detail}" if detail else ""))
    if not cond: FAILED.append(name)

TODAY = dt.date.today()

print("── 1. 回訪日按類型計算 ──")
cases = [
    ("anchor",     None,           ""),                                  # 唔需要回訪
    ("method",     None,           ""),
    ("basket",     None,           (TODAY + dt.timedelta(days=7)).isoformat()),
    ("violation",  None,           (TODAY + dt.timedelta(days=3)).isoformat()),
    ("move",       None,           (TODAY + dt.timedelta(days=5)).isoformat()),
    ("discussion", "2026-09-16",   "2026-09-16"),                        # 回訪 = 結算日
]
for tier, res, want in cases:
    got = tracker.compute_revisit(tier, TODAY, res)
    check(f"{tier:11s} → {want or '不需要':12s}", got == want, f"得 {got!r}")

print("\n── 1b. 回訪日唔可以遲過結算日（實測 bug）──")
soon = (TODAY + dt.timedelta(days=2)).isoformat()
got = tracker.compute_revisit("move", TODAY, soon)      # move 正常隔 5 日
check("move 遇上 2 日後結算 → 改用結算日", got == soon, f"得 {got}")
far = (TODAY + dt.timedelta(days=90)).isoformat()
check("結算日遠過計劃回訪日 → 用計劃日",
      tracker.compute_revisit("move", TODAY, far)
      == (TODAY + dt.timedelta(days=5)).isoformat())
check("anchor 有結算日都唔回訪", tracker.compute_revisit("anchor", TODAY, soon) == "")
check("壞日期字串唔會爆",
      tracker.compute_revisit("move", TODAY, "not-a-date")
      == (TODAY + dt.timedelta(days=5)).isoformat())

print("\n── 2. 記錄 + 讀返 ──")
tracker.log_post(post_id="p1", tier="discussion",
                 question="Fed Decision in September?",
                 claim="Board sums to 102.8; hike priced 29 vs cut 1",
                 condition_id="0xfed", price_at_post=0.29,
                 resolution_date="2026-09-16", tweet_id="tw1")
tracker.log_post(post_id="p2", tier="anchor", question="",
                 claim="Sum-ask median 1.02, zero breaches", tweet_id="tw2")
rows = tracker.read_all()
check("兩行都寫入咗", len(rows) == 2, f"{len(rows)} 行")
check("價格格式化正確", rows[0]["price_at_post"] == "0.2900", rows[0]["price_at_post"])
check("anchor 冇回訪日", rows[1]["revisit_date"] == "", repr(rows[1]["revisit_date"]))
check("discussion 回訪日 = 結算日", rows[0]["revisit_date"] == "2026-09-16")
check("初始狀態 open", all(r["status"] == "open" for r in rows))

print("\n── 3. 到期偵測 ──")
# 加一個 3 日前出、已到回訪期嘅 violation
tracker.log_post(post_id="p3", tier="violation", question="Ladder gap on X",
                 claim="3.1pt inversion between Jun and Dec legs")
rows = tracker.read_all()
for r in rows:
    if r["post_id"] == "p3":
        r["revisit_date"] = (TODAY - dt.timedelta(days=1)).isoformat()
tracker._write_all(rows)

due = tracker.due_revisits(TODAY)
check("捉到過期未回訪嘅", {r["post_id"] for r in due} == {"p3"},
      str([r["post_id"] for r in due]))

check("未到期嘅唔會出現", "p1" not in {r["post_id"] for r in due})

res_due = tracker.due_resolutions(dt.date(2026, 9, 16))
check("結算日到就捉到", "p1" in {r["post_id"] for r in res_due},
      str([r["post_id"] for r in res_due]))
res_early = tracker.due_resolutions(dt.date(2026, 9, 15))
check("結算日前一日唔會捉", "p1" not in {r["post_id"] for r in res_early})

print("\n── 4. 標記狀態 ──")
check("標記存在嘅 id 成功", tracker.mark("p3", status="revisited", outcome="correct",
                                    notes="gap closed in 26h"))
check("標記唔存在嘅 id 回 False", not tracker.mark("nope", status="resolved"))
r3 = [r for r in tracker.read_all() if r["post_id"] == "p3"][0]
check("狀態已更新", r3["status"] == "revisited", r3["status"])
check("回訪日期有記低", r3["revisited_at"] == TODAY.isoformat(), r3["revisited_at"])
check("備註有加到", "gap closed" in r3["notes"], r3["notes"])
check("已回訪嘅唔會再列為到期",
      "p3" not in {r["post_id"] for r in tracker.due_revisits(TODAY)})

print("\n── 5. 往績統計（唔可以揀啱嗰啲）──")
tracker.mark("p1", status="resolved", outcome="wrong")
tracker.mark("p2", status="resolved", outcome="correct")
t = tracker.tally()
check("總數啱", t["total_posts"] == 3, str(t["total_posts"]))
check("已結算 2", t["resolved"] == 2, str(t["resolved"]))
check("中 1 錯 1 —— 兩邊都計", t["correct"] == 1 and t["wrong"] == 1, str(t))
check("按類型分類有齊", set(t["by_tier"]) == {"discussion", "anchor", "violation"},
      str(t["by_tier"]))

print("\n── 6. 每日摘要 ──")
d = tracker.digest(TODAY)
check("摘要含今日已出", "今日已出" in d)
check("摘要含往績行", "往績" in d and "已結 2" in d, d.split("\n")[-1][:60])
check("摘要係 HTML（Telegram 用）", "<b>" in d)
check("空 log 唔會爆", isinstance(tracker.digest(dt.date(2020, 1, 1)), str))

import shutil; shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("🎉 tracker 全部通過" if not FAILED else f"⚠️  {len(FAILED)} 項失敗：{FAILED}"))
sys.exit(1 if FAILED else 0)
