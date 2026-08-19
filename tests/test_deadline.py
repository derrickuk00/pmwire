"""deadline.py 測試 —— 重點係 DK 實戰踩過嘅兩個陷阱。"""
import sys, os, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from deadline import parse_deadline, has_deadline_cue, family_key

FAILED = []
def check(name, cond, detail=""):
    print(f"{'✅' if cond else '❌'} {name}" + (f"  {detail}" if detail else ""))
    if not cond: FAILED.append(name)

D = dt.date

print("── 1. 陷阱一：『by market cap』唔係 deadline ──")
traps = [
    "Will NVIDIA be the largest company by market cap in 2026?",
    "Will Tesla be top 5 by market capitalization?",
    "Will India pass Japan by GDP?",
    "Who wins by a margin of 5 points?",
    "Will X be #1 by revenue?",
]
for t in traps:
    check(f"排除：{t[:48]}", not has_deadline_cue(t),
          f"cue={has_deadline_cue(t)} parsed={parse_deadline(t)}")

print("\n── 2. 但真 deadline 要照抽到 ──")
cases = [
    ("Will X happen by December 31, 2026?",       D(2026, 12, 31)),
    ("Will X happen by Dec 31 2026?",             D(2026, 12, 31)),
    ("Will X occur before 31 December 2026?",     D(2026, 12, 31)),
    ("Will X happen by end of 2026?",             D(2026, 12, 31)),
    ("Will X happen by Q3 2026?",                 D(2026, 9, 30)),
    ("Will X happen by Q1 2027?",                 D(2027, 3, 31)),
    ("Will X happen by March 2026?",              D(2026, 3, 31)),
    ("Will X happen by February 2028?",           D(2028, 2, 29)),   # 閏年
    ("Will X happen by 2026-06-30?",              D(2026, 6, 30)),
    ("Will X happen by 6/30/2026?",               D(2026, 6, 30)),
    ("Will X be resolved no later than June 30, 2026?", D(2026, 6, 30)),
    ("Will X happen by 2027?",                    D(2027, 12, 31)),
]
for t, want in cases:
    got = parse_deadline(t)
    check(f"{t[:50]:52s}", got == want, f"得 {got}，應為 {want}")

print("\n── 3. 混合情況：題目同時有假 by 同真 deadline ──")
t = "Will NVIDIA be largest by market cap by December 31, 2026?"
check("仍然抽到真 deadline", parse_deadline(t) == D(2026, 12, 31), str(parse_deadline(t)))

print("\n── 4. 陷阱二：唔信 endDate，一律用題目 ──")
# 模擬 DK 實測嘅兩個壞 metadata
bad = [
    ("Will X happen by June 30, 2026?", "2025-12-31T00:00:00Z", D(2026, 6, 30)),   # 677273 型
    ("Will Y happen by December 31, 2026?", "2026-03-31T00:00:00Z", D(2026, 12, 31)),  # 1323083 型
]
for title, bad_end, want in bad:
    got = parse_deadline(title)
    check(f"題目勝過壞 endDate({bad_end[:10]})", got == want, f"得 {got}")

print("\n── 5. 家族歸類（階梯掃描核心）──")
fam = [
    "Will Iran close the Strait of Hormuz by June 30, 2026?",
    "Will Iran close the Strait of Hormuz by September 30, 2026?",
    "Will Iran close the Strait of Hormuz by December 31, 2026?",
]
keys = {family_key(t) for t in fam}
check("三個唔同 deadline 歸同一家族", len(keys) == 1, str(keys))

other = family_key("Will Iran restart enrichment by December 31, 2026?")
check("唔同題材唔會誤歸同一家族", other not in keys, f"{other!r} vs {keys}")

fam2 = {family_key("Will BTC hit 200k by Q1 2027?"),
        family_key("Will BTC hit 200k by Q3 2027?")}
check("Q 格式都歸得埋", len(fam2) == 1, str(fam2))

print("\n── 6. 冇 deadline 嘅唔應該亂估 ──")
for t in ["Who will win the 2026 World Cup?", "Will BTC close above 100k?",
          "Will there be a recession?"]:
    check(f"唔亂估：{t[:40]}", parse_deadline(t) is None, str(parse_deadline(t)))

print("\n" + ("🎉 deadline 全部通過" if not FAILED else f"⚠️  {len(FAILED)} 項失敗：{FAILED}"))
sys.exit(1 if FAILED else 0)
