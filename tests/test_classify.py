"""classify.py 測試 —— 全部用 2026-08-19 實跑見到嘅真題目。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from classify import classify

FAILED = []
def check(q, want):
    got = classify(q)
    ok = got == want
    print(f"{'✅' if ok else '❌'} {want:12s} ← {q[:58]}" + ("" if ok else f"　（得 {got}）"))
    if not ok: FAILED.append(q[:40])

print("── 實跑當日真實題目（全部應為 sports，之前被判 Uncategorised）──")
for q in [
    "Arizona Diamondbacks vs. Boston Red Sox",
    "Miami Marlins vs. Philadelphia Phillies",
    "New York Yankees vs. Baltimore Orioles",
    "Cancun: Otto Virtanen vs Moez Echargui",
    "Cincinnati Open: Nuno Borges vs Brandon Nakashima",
]:
    check(q, "sports")

print("\n── 實跑當日真實題目（crypto）──")
for q in [
    "Will the price of Ethereum be above $2,200 on August 21?",
    "Will Bitcoin reach $72,500 in August?",
    "Will Bitcoin reach $72,000 August 17-23?",
    "Will Ethereum reach $2,250 by December 31, 2026?",
    "Will Bitcoin dip to $62,500 in August?",
]:
    check(q, "crypto")

print("\n── 宏觀 ──")
for q in [
    "Fed Decision in September?",
    "Will the FOMC cut rates by 25 bps?",
    "Core CPI MoM - August 2026",
    "Will the US enter a recession in 2026?",
    "Will the Bank of England hold rates in November?",
]:
    check(q, "macro")

print("\n── 地緣政治 ──")
for q in [
    "Will Iran close the Strait of Hormuz by June 30, 2026?",
    "Will there be a ceasefire in Ukraine before December 31?",
    "Will Israel and Hamas agree a peace deal in 2026?",
    "Will NATO invoke Article 5 in 2026?",
]:
    check(q, "geopolitics")

print("\n── 選舉政治 ──")
for q in [
    "Who will win the 2028 presidential election?",
    "Will the Senate confirm the nominee by March?",
    "Will the Prime Minister resign in 2026?",
    "Will Republicans hold the House in the midterms?",
]:
    check(q, "politics")

print("\n── 科技 ──")
for q in [
    "Will OpenAI release GPT-6 before July?",
    "Will NVIDIA announce a stock split in 2026?",
    "Will SpaceX Starship reach orbit by Q4?",
]:
    check(q, "tech")

print("\n── 2026-08-19 實跑漏網（回歸測試）──")
check("US announces end of Iranian blockade by September 30?", "geopolitics")
check("Clarity Act (H.R.3633) signed into law in 2026", "politics")
check("Will the President veto the bill before July?", "politics")
check("Will Russia capture all of Kostyantynivka by December 31?", "geopolitics")
check("Will the US impose an embargo on Venezuela?", "geopolitics")
check("Will an executive order on tariffs be issued in Q1?", "politics")

print("\n── 邊界情況 ──")
check("Will the Supreme Court rule on the case by June?", "politics")
check("Will the lawsuit Smith vs. Jones settle in 2026?", "other")   # vs 但係法律
check("Will a hurricane make landfall in Florida in September?", "weather")
check("Will the film win Best Picture at the Oscars?", "culture")
check("Something entirely unclassifiable happens", "other")

print("\n── 優先次序：crypto 提到 Fed 應該點判 ──")
# 「Fed」同「Bitcoin」都出現 —— sports 唔中，crypto 排喺 macro 前，應為 crypto
check("Will Bitcoin rise after the Fed decision?", "crypto")

print("\n── 描述做後備 ──")
got = classify("Market A", "This market resolves YES if the Federal Reserve cuts rates.")
print(f"{'✅' if got == 'macro' else '❌'} 題目無線索時用 description　（得 {got}）")
if got != "macro": FAILED.append("description fallback")

print("\n── 主體偵測（同一件事唔好一日出七篇）──")
from classify import subject
def chks(q, want):
    got = subject(q)
    ok = got == want
    print(f"{'✅' if ok else '❌'} {want or '(無)':<12} ← {q[:54]}" + ("" if ok else f"　（得 {got!r}）"))
    if not ok: FAILED.append("subject:" + q[:32])

# 2026-08-19 實跑頭 10 名：七個都應該歸做 iran
for q in [
    "US ceasefire against Iran continues through September 30?",
    "Strait of Hormuz traffic returns to normal by September 30?",
    "US ceasefire against Iran continues through August 31?",
    "Iran-Oman Hormuz Agreement by September 30?",
    "US announces end of Iranian blockade by September 15?",
]:
    chks(q, "iran")

chks("Will United Russia (ER) gain the most seats in the next Duma election?", "russia")
chks("Will Russia capture all of Kostyantynivka by December 31?", "russia")
chks("Will Zelenskyy remain president through 2026?", "ukraine")
chks("Will the IDF withdraw from Gaza by March?", "israel")
chks("Will Taiwan hold a snap election in 2026?", "china")
chks("Fed Decision in September?", "us_fed")
chks("Clarity Act (H.R.3633) signed into law in 2026", "us_congress")
chks("Will the Bank of England hold rates in November?", "uk")
chks("Will OpenAI release GPT-6 before July?", "openai")
chks("Will it rain in Paris on Tuesday?", "")

print("\n── 機械式市場：價格階梯 + 計數桶 ──")
from classify import is_mechanical
for q, want in [
    # 價格階梯
    ("Will the price of Ethereum be above $2,200 on August 21?", True),
    ("Will Bitcoin reach $72,500 in August?", True),
    ("Will Bitcoin dip to $62,500 in August?", True),
    # 計數桶（2026-08-19 第五輪實測漏網）
    ("Will Elon Musk post 200-219 tweets from August 15-22?", True),
    ("Will Elon Musk post 220-239 tweets from August 15-22?", True),
    ("How many tweets will Elon Musk post this week?", True),
    ("Will the account gain more than 5000 followers in August?", True),
    # 應保留：低頻離散事件有真實討論價值
    ("How many Fed rate cuts in 2026?", False),
    ("How many seats will Labour win?", False),
    ("Will the SEC approve a spot Solana ETF in 2026?", False),
    ("US ceasefire against Iran continues through September 30?", False),
    ("Will United Russia (ER) gain the most seats in the next Duma election?", False),
]:
    got = is_mechanical(q)
    ok = got == want
    print(f"{'✅' if ok else '❌'} {'剔走' if want else '保留'} ← {q[:56]}")
    if not ok: FAILED.append("mech:" + q[:32])

chks("Will Elon Musk post 200-219 tweets from August 15-22?", "musk")
chks("Will Tesla deliver 500k vehicles in Q3?", "musk")

print("\n── 家族鍵要剪走數值區間 ──")
from deadline import family_key
_ks = {family_key(q) for q in [
    "Will Elon Musk post 200-219 tweets from August 15-22?",
    "Will Elon Musk post 220-239 tweets from August 15-22?",
    "Will Elon Musk post 240-259 tweets from August 15-22?"]}
_ok = len(_ks) == 1
print(f"{'✅' if _ok else '❌'} 三個推文桶歸同一家族  {_ks}")
if not _ok: FAILED.append("family:musk buckets")

print("\n" + ("🎉 classify 全部通過" if not FAILED else f"⚠️  {len(FAILED)} 項失敗：{FAILED}"))
sys.exit(1 if FAILED else 0)
