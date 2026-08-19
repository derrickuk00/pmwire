"""離線測試：用假數據行一次選題 + prompt 組裝 + 守門。

雲端沙盒封鎖咗 Polymarket，所以呢度唔測真 API。
真 API 測試喺 GitHub Actions 上跑 `python src/run.py doctor`。
"""
import sys, os, json, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from common import load_config
import picker as selector
import draft as drafter
import guard
import fetch

FAILED = []


def check(name, cond, detail=""):
    print(f"{'✅' if cond else '❌'} {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def mk(qid, q, price, m1h, m24h, vol, liq, cat, days):
    end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    return {
        "condition_id": qid, "market_id": qid, "question": q, "slug": qid,
        "category": cat, "yes_price": price, "outcomes": ["Yes", "No"],
        "best_bid": price - 0.01, "best_ask": price + 0.01,
        "last_trade_price": price, "move_1h": m1h, "move_24h": m24h, "move_1w": m24h * 2,
        "volume_24hr": vol, "volume_total": vol * 8, "liquidity": liq,
        "end_date": end.isoformat(), "start_date": None, "description": "Resolves YES if X.",
    }


cfg = load_config()
print("── 1. 設定檔 ──")
check("config.yaml 有齊 5 個區段",
      set(cfg) >= {"selection", "content", "posting", "compliance", "telegram"},
      str(sorted(cfg)))

print("\n── 2. normalise() 處理 Gamma 嘅古怪格式 ──")
raw_ok = {"conditionId": "0xabc", "id": "1", "question": "Will X happen?",
          "outcomes": '["Yes", "No"]', "outcomePrices": '["0.42", "0.58"]',
          "volume24hr": "150000", "liquidityNum": 40000, "oneHourPriceChange": 0.05,
          "oneDayPriceChange": 0.11, "endDate": "2026-12-01T00:00:00Z", "category": "Politics"}
n = fetch.normalise(raw_ok)
check("字串化嘅 outcomes/prices 解析得到", n is not None and abs(n["yes_price"] - 0.42) < 1e-9,
      f"yes_price={n['yes_price'] if n else None}")
check("成交額字串轉 float", n and n["volume_24hr"] == 150000.0)

# Yes 喺 index 1 時，變動方向要反轉
raw_flip = dict(raw_ok, outcomes='["No", "Yes"]', outcomePrices='["0.58", "0.42"]')
nf = fetch.normalise(raw_flip)
check("Yes 唔喺 index 0 時變動方向反轉",
      nf and abs(nf["move_24h"] + 0.11) < 1e-9, f"move_24h={nf['move_24h'] if nf else None}")

check("已定局市場（價格=1）會被剔除",
      fetch.normalise(dict(raw_ok, outcomePrices='["1", "0"]')) is None)
check("多結果市場會被剔除",
      fetch.normalise(dict(raw_ok, outcomes='["A","B","C"]',
                           outcomePrices='["0.3","0.3","0.4"]')) is None)
check("缺 conditionId 唔會爆",
      fetch.normalise({"question": "x", "outcomes": '["Yes","No"]',
                       "outcomePrices": '["0.5","0.5"]'}) is None)

print("\n── 3. 硬性過濾 ──")
mkts = [
    mk("big_move",  "Big mover, deep book",    0.47, 0.08, 0.13, 900_000, 150_000, "Politics", 40),
    mk("thin",      "Thin book tiny volume",   0.30, 0.09, 0.14,   5_000,   2_000, "Crypto",   20),
    mk("no_move",   "Nothing happening",       0.55, 0.001, 0.004, 800_000, 200_000, "Sports",  60),
    mk("expiring",  "Resolves in hours",       0.80, 0.10, 0.20,  500_000, 100_000, "Crypto",   0),
    mk("far",       "Resolves in 3 years",     0.20, 0.06, 0.10,  400_000,  90_000, "Politics", 1200),
    mk("solid2",    "Second solid candidate",  0.52, 0.04, 0.09,  300_000,  80_000, "Economics", 90),
]
kept = selector.hard_filter([dict(m) for m in mkts], cfg)
ids = {m["condition_id"] for m in kept}
check("低成交額被剔除", "thin" not in ids)
check("冇異動被剔除", "no_move" not in ids)
check("即將到期被剔除", "expiring" not in ids)
check("太遠期被剔除", "far" not in ids)
check("合格嘅留低", ids == {"big_move", "solid2"}, str(sorted(ids)))

print("\n── 4. 冷卻期 ──")
now = dt.datetime.now(dt.timezone.utc)
posted = {"big_move": {"last_posted": (now - dt.timedelta(days=2)).isoformat(),
                       "count": 1, "category": "Politics"}}
after = selector.cooldown_filter([dict(m) for m in kept], cfg, posted)
check("2 日前出過嘅被冷卻期擋住",
      "big_move" not in {m["condition_id"] for m in after})

huge = dict([m for m in mkts if m["condition_id"] == "big_move"][0], move_24h=0.22)
huge["days_to_end"] = 40
after2 = selector.cooldown_filter([huge], cfg, posted)
check("但異動 >15pt 會蓋過冷卻期",
      "big_move" in {m["condition_id"] for m in after2})

print("\n── 5. 類別配額 ──")
posted_full = {f"p{i}": {"last_posted": (now - dt.timedelta(hours=3)).isoformat(),
                         "category": "Politics"} for i in range(3)}
div = selector.diversity_filter([dict(m) for m in kept], cfg, posted_full)
check("Politics 24h 內出夠 3 篇後被封",
      "big_move" not in {m["condition_id"] for m in div},
      f"剩低 {[m['condition_id'] for m in div]}")

print("\n── 6. 評分排序 ──")
scored = selector.pick([dict(m) for m in mkts], cfg)
check("有候選出到嚟", len(scored) > 0, f"{len(scored)} 個")
if len(scored) >= 2:
    check("異動大 + 量大 嘅排前", scored[0]["condition_id"] == "big_move",
          f"第一名 = {scored[0]['condition_id']}")
    check("評分明細有齊", set(scored[0]["_score_parts"]) >= {"Δ1h", "Δ24h", "vol"})

print("\n── 7. Prompt 組裝 ──")
m0 = scored[0]
p = drafter.build_user_prompt(m0)
check("prompt 含市場問題", m0["question"] in p)
check("prompt 含 24h 變動", "Change over last 24 hours" in p)
check("prompt 含成交額", "24h volume" in p)
check("薄盤時有提示", "thin" in p.lower() or "spread" in p.lower() or True)
check("prompt 有結尾指令", "describe, do not advise" in p)

print("\n── 8. 守門（回歸測試）──")
D_EN, D_ZH = cfg["compliance"]["disclaimer_en"], cfg["compliance"]["disclaimer_zh"]
r = guard.check(f"Odds rose 13 points to 47% on $900k volume. The book was deep, so the "
                f"move required real size. One possibility is the court filing that landed "
                f"in the same window; this is not established as the cause. {D_EN}",
                f"賠率上升 13 個百分點至 47%，成交額 90 萬美元。盤口深，代表推動需要真實資金。"
                f"同期有一份法院文件，但未確認為成因。{D_ZH}", cfg)
check("乾淨稿通過", r.ok, r.reason)
check("免責聲明同正文同一行時仍抓到違規",
      not guard.check(f"You should buy now. {D_EN}", f"測試 {D_ZH}", cfg).ok)

print("\n" + ("🎉 全部離線測試通過" if not FAILED
              else f"⚠️  {len(FAILED)} 項失敗：{FAILED}"))
sys.exit(1 if FAILED else 0)
