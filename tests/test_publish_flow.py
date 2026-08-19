"""整合測試：publish 狀態機。用 mock 代替 Telegram / X，唔使網絡。

測嘅係最容易出錯嗰部分：審批決定 → 狀態轉換 → 發文 → 冷卻期記錄 → 速率限制。
"""
import sys, os, json, datetime as dt, tempfile, shutil
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "..", "src"))

# 將狀態檔重導去暫存目錄，唔好污染真 state/
TMP = tempfile.mkdtemp()
import common
common.STATE_DIR = __import__("pathlib").Path(TMP)
common.QUEUE_PATH = common.STATE_DIR / "queue.json"
common.POSTED_PATH = common.STATE_DIR / "posted.json"
common.TG_OFFSET_PATH = common.STATE_DIR / "tg_offset.json"

import telegram_gate as tg
import post_x
import run as runner

FAILED = []
def check(name, cond, detail=""):
    print(f"{'✅' if cond else '❌'} {name}" + (f"  {detail}" if detail else ""))
    if not cond: FAILED.append(name)

# ── mock 掉所有網絡呼叫 ──
DECISIONS = {}
POSTED_TEXTS = []
NOTIFIES = []

tg.poll_decisions = lambda: dict(DECISIONS)
tg.mark_result = lambda mid, s: NOTIFIES.append(s)
tg.notify = lambda s: NOTIFIES.append(s)

def fake_post_pair(en, zh, mode="reply", dry_run=False):
    POSTED_TEXTS.append((en, zh, mode))
    return f"tw{len(POSTED_TEXTS)}", (f"tw{len(POSTED_TEXTS)}z" if zh and mode == "reply" else None)
post_x.post_pair = fake_post_pair

# run.py 用 `from common import ...`，所以要同步覆寫佢嗰邊嘅引用
runner.load_queue = common.load_queue
runner.save_queue = common.save_queue
runner.load_posted = common.load_posted
runner.save_posted = common.save_posted
runner.tg = tg
runner.post_x = post_x


def mkitem(iid, status="pending", cid=None, cat="Politics", ago_min=None):
    it = {
        "id": iid, "created": common.iso(common.utcnow()), "status": status,
        "market": {"condition_id": cid or f"c_{iid}", "question": f"Question {iid}",
                   "category": cat, "yes_price": 0.5, "move_1h": 0.05, "move_24h": 0.1,
                   "volume_24hr": 500000, "liquidity": 100000, "days_to_end": 30},
        "text_en": f"English body {iid}.", "text_zh": f"中文內容 {iid}。",
        "flags": [], "tg_message_id": 1,
    }
    if ago_min is not None:
        it["posted_at"] = common.iso(common.utcnow() - dt.timedelta(minutes=ago_min))
    return it


print("── 1. 批准 → 發布 ──")
common.save_queue([mkitem("aaa")])
common.save_posted({})
DECISIONS.clear(); DECISIONS["aaa"] = "ok"
POSTED_TEXTS.clear()
runner.cmd_publish()
q = common.load_queue()
check("狀態變成 posted", q[0]["status"] == "posted", q[0]["status"])
check("真係發咗一篇", len(POSTED_TEXTS) == 1, f"{len(POSTED_TEXTS)} 篇")
check("英文內容啱", POSTED_TEXTS and "English body aaa" in POSTED_TEXTS[0][0])
check("中文有一齊發", POSTED_TEXTS and "中文內容 aaa" in POSTED_TEXTS[0][1])
check("tweet id 記低咗", q[0].get("tweet_id") == "tw1")
p = common.load_posted()
check("冷卻期記錄已寫入", "c_aaa" in p and p["c_aaa"]["count"] == 1, json.dumps(p, ensure_ascii=False))
check("記錄有類別（畀配額用）", p.get("c_aaa", {}).get("category") == "Politics")

print("\n── 2. 丟棄唔會發 ──")
common.save_queue([mkitem("bbb")])
DECISIONS.clear(); DECISIONS["bbb"] = "kill"
POSTED_TEXTS.clear()
runner.cmd_publish()
q = common.load_queue()
check("狀態變 killed", q[0]["status"] == "killed", q[0]["status"])
check("冇發任何嘢", len(POSTED_TEXTS) == 0)

print("\n── 3. 未審批唔會發 ──")
common.save_queue([mkitem("ccc")])
DECISIONS.clear()
POSTED_TEXTS.clear()
runner.cmd_publish()
check("pending 保持 pending", common.load_queue()[0]["status"] == "pending")
check("冇發任何嘢", len(POSTED_TEXTS) == 0)

print("\n── 4. 發文間隔限制 ──")
# 剛剛先發完一篇（5 分鐘前），config 要求隔 45 分鐘
common.save_queue([mkitem("ddd", "posted", ago_min=5), mkitem("eee", "approved")])
DECISIONS.clear()
POSTED_TEXTS.clear()
runner.cmd_publish()
check("未夠間隔就唔發", len(POSTED_TEXTS) == 0, f"發咗 {len(POSTED_TEXTS)} 篇")
check("已批准嘅仍然等緊",
      [x for x in common.load_queue() if x["id"] == "eee"][0]["status"] == "approved")

# 隔咗 60 分鐘就應該發
common.save_queue([mkitem("fff", "posted", ago_min=60), mkitem("ggg", "approved")])
POSTED_TEXTS.clear()
runner.cmd_publish()
check("夠間隔就會發", len(POSTED_TEXTS) == 1, f"發咗 {len(POSTED_TEXTS)} 篇")

print("\n── 5. 每日上限 ──")
import yaml
cfg_path = os.path.join(BASE, "..", "config.yaml")
cfg = yaml.safe_load(open(cfg_path, encoding="utf-8"))
maxday = cfg["posting"]["max_posts_per_day"]
today_posts = [mkitem(f"h{i}", "posted", ago_min=60 + i * 10) for i in range(maxday)]
common.save_queue(today_posts + [mkitem("iii", "approved")])
POSTED_TEXTS.clear()
runner.cmd_publish()
check(f"今日已夠 {maxday} 篇就唔再發", len(POSTED_TEXTS) == 0, f"發咗 {len(POSTED_TEXTS)} 篇")

print("\n── 6. 一次 run 最多發一篇（防洗版）──")
common.save_queue([mkitem("j1", "approved"), mkitem("j2", "approved"),
                   mkitem("j3", "approved")])
DECISIONS.clear()
POSTED_TEXTS.clear()
runner.cmd_publish()
check("三篇待發但只發一篇", len(POSTED_TEXTS) == 1, f"發咗 {len(POSTED_TEXTS)} 篇")

print("\n── 7. 重複決定唔會double post ──")
common.save_queue([mkitem("kkk")])
DECISIONS.clear(); DECISIONS["kkk"] = "ok"
POSTED_TEXTS.clear()
runner.cmd_publish()                      # 第一次：批准 + 發
first = len(POSTED_TEXTS)
runner.cmd_publish()                      # 第二次：同樣決定又嚟一次
check("同一決定重播唔會再發", len(POSTED_TEXTS) == first,
      f"第一次 {first} 篇，第二次之後 {len(POSTED_TEXTS)} 篇")

print("\n── 8. 發文失敗會重試，唔會當成功 ──")
post_x.post_pair = lambda en, zh, mode="reply", dry_run=False: (None, None)
common.save_queue([mkitem("lll", "approved")])
DECISIONS.clear()
runner.cmd_publish()
q = common.load_queue()[0]
check("失敗後保持 approved 等重試", q["status"] == "approved", q["status"])
check("有記低失敗次數", q.get("retry_count") == 1, str(q.get("retry_count")))
post_x.post_pair = fake_post_pair

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("🎉 publish 狀態機全部通過" if not FAILED
              else f"⚠️  {len(FAILED)} 項失敗：{FAILED}"))
sys.exit(1 if FAILED else 0)
