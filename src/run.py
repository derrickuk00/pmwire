"""主程式。兩個模式：

  python src/run.py draft     抓數據 → 選題 → 生成 → 守門 → 送去 Telegram 審批
  python src/run.py publish   讀取審批決定 → 發布已批准嘅 → 更新狀態
  python src/run.py doctor    自檢：憑證、設定、狀態檔
  python src/run.py testpost  真發一篇測試貼再自動刪 —— 唯一可靠嘅寫入測試
  python src/run.py scan      跑齊三個結構性掃描（anchor / basket / violation 貼嘅數據）
  python src/run.py settle <market_id> YES|NO   記錄一筆帳本結算

環境變數（全部由 GitHub Secrets 注入）：
  OPENAI_API_KEY        內容生成
  TELEGRAM_BOT_TOKEN    審批機械人
  TELEGRAM_CHAT_ID      你嘅 Telegram user id
  X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_SECRET
  DRY_RUN=1             （可選）唔真發，只印出嚟睇
"""
from __future__ import annotations
import os
import sys
import uuid
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (log, load_config, load_queue, save_queue, load_posted,
                    save_posted, utcnow, iso, parse_iso)
import fetch
import picker as selector
import draft as drafter
import guard
import telegram_gate as tg
import post_x
import tracker
import scans
import ledger

DRY = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")
MODEL = os.environ.get("LLM_MODEL", "").strip() or None
PROVIDER = os.environ.get("LLM_PROVIDER", "").strip() or None


# ────────────────────────── 草稿模式 ──────────────────────────

def cmd_draft() -> int:
    cfg = load_config()
    queue = load_queue()

    # 已經喺佇列度等緊嘅市場，今次唔好再揀（避免同一題目重複出現喺審批清單）
    live_ids = {q["market"]["condition_id"] for q in queue
                if q["status"] in ("pending", "approved")}

    markets = fetch.fetch_normalised()
    if not markets:
        log("抓唔到市場數據，今次收工")
        return 0

    candidates = selector.pick(markets, cfg, exclude_ids=live_ids)
    if not candidates:
        log("冇合適題目 —— 呢個係正常嘅（市場靜嘅時候就應該唔出稿）")
        return 0

    want = cfg["selection"]["drafts_per_run"]
    made = 0

    for m in candidates:
        if made >= want:
            break
        log(f"起草：{m['question'][:70]}")
        en, zh, res, sres = drafter.generate_compliant(
            m, cfg, guard.check, model=MODEL, provider=PROVIDER,
            max_attempts=3, tier="move",
        )
        if not en:
            log("  跳過，試下一個候選")
            continue

        item = {
            "id": uuid.uuid4().hex[:8],
            "created": iso(utcnow()),
            "status": "pending",
            "market": {k: v for k, v in m.items() if not k.startswith("_")}
                      | {"_score": round(m.get("_score", 0), 1)},
            "text_en": en,
            "text_zh": zh,
            "tier": "move",
            "family": m.get("_family", ""),
            "flags": res.flags if res else [],
            "entities": sres.entities if sres else [],
            "redo_count": 0,
        }
        try:
            item["tg_message_id"] = tg.send_for_approval(item)
        except Exception as e:  # noqa: BLE001 — Telegram 掛咗唔應該搞死成個 run
            log(f"  ✗ 送 Telegram 失敗：{e}（草稿仍會入佇列）")
            item["tg_message_id"] = None

        queue.append(item)
        made += 1

    save_queue(queue)
    log(f"完成：新增 {made} 個待審草稿，佇列現有 "
        f"{sum(1 for q in queue if q['status'] == 'pending')} 個 pending")
    return 0


# ────────────────────────── 發布模式 ──────────────────────────

def _posts_today(queue: list) -> int:
    today = utcnow().date()
    n = 0
    for q in queue:
        if q["status"] == "posted":
            d = parse_iso(q.get("posted_at"))
            if d and d.date() == today:
                n += 1
    return n


def _last_post_time(queue: list):
    times = [parse_iso(q.get("posted_at")) for q in queue if q["status"] == "posted"]
    times = [t for t in times if t]
    return max(times) if times else None


def cmd_publish() -> int:
    cfg = load_config()
    queue = load_queue()
    posted_store = load_posted()

    # 1) 收 Telegram 決定
    decisions = tg.poll_decisions()
    by_id = {q["id"]: q for q in queue}
    for item_id, action in decisions.items():
        q = by_id.get(item_id)
        if not q:
            log(f"  收到未知項目 {item_id} 嘅決定，忽略")
            continue
        if q["status"] not in ("pending",):
            log(f"  項目 {item_id} 狀態係 {q['status']}，忽略重複決定")
            continue
        if action == "ok":
            q["status"] = "approved"
            q["approved_at"] = iso(utcnow())
        elif action == "kill":
            q["status"] = "killed"
            tg.mark_result(q.get("tg_message_id"), f"🗑 已丟棄 <code>#{item_id}</code>")
        elif action == "redo":
            q["status"] = "redo"
            tg.mark_result(q.get("tg_message_id"),
                           f"🔁 <code>#{item_id}</code> 已排入重寫，下次草稿時處理")

    # 2) 發布已批准嘅（受每日上限同間隔限制）
    p = cfg["posting"]
    max_day = p["max_posts_per_day"]
    gap = dt.timedelta(minutes=p["min_minutes_between_posts"])
    mode = cfg["content"]["chinese_mode"]

    done_today = _posts_today(queue)
    if done_today >= max_day:
        log(f"今日已發 {done_today}/{max_day} 篇，達上限")
    else:
        last = _last_post_time(queue)
        if last and (utcnow() - last) < gap:
            wait = (gap - (utcnow() - last)).total_seconds() / 60
            log(f"距離上一篇未夠 {p['min_minutes_between_posts']} 分鐘（仲有 {wait:.0f} 分鐘），今次唔發")
        else:
            approved = [q for q in queue if q["status"] == "approved"]
            approved.sort(key=lambda q: q.get("approved_at") or q["created"])
            if not approved:
                log("冇已批准待發嘅項目")
            else:
                q = approved[0]
                log(f"發布 #{q['id']}：{q['market']['question'][:60]}")
                tid_en, tid_zh = post_x.post_pair(
                    q["text_en"], q.get("text_zh", ""), mode=mode, dry_run=DRY)
                if tid_en:
                    q["status"] = "posted"
                    q["posted_at"] = iso(utcnow())
                    q["tweet_id"] = tid_en
                    q["tweet_id_zh"] = tid_zh
                    cid = q["market"]["condition_id"]
                    rec = posted_store.get(cid, {"count": 0})
                    rec.update({
                        "last_posted": q["posted_at"],
                        "count": rec.get("count", 0) + 1,
                        "category": q["market"].get("category", "other"),
                        # 家族／主體用嚟做 24h 去重（見 picker.diversity_filter）
                        "family": q.get("family", ""),
                        "subject": q["market"].get("subject", ""),
                        "question": q["market"].get("question", "")[:120],
                    })
                    posted_store[cid] = rec

                    # 記入回訪追蹤：呢個先係把散貨變成往績鏈嘅一步
                    mk = q["market"]
                    tracker.log_post(
                        post_id=q["id"],
                        tier=q.get("tier", "move"),
                        question=mk.get("question", ""),
                        claim=q.get("claim", "")
                              or q["text_en"].split("\n")[0][:200],
                        condition_id=mk.get("condition_id", ""),
                        price_at_post=mk.get("yes_price"),
                        resolution_date=mk.get("end_date"),
                        tweet_id=tid_en or "",
                    )

                    tg.mark_result(q.get("tg_message_id"),
                                   f"✅ 已發布 <code>#{q['id']}</code>")
                else:
                    q["retry_count"] = q.get("retry_count", 0) + 1
                    if q["retry_count"] >= 5:
                        q["status"] = "failed"
                        tg.notify(f"⚠️ <code>#{q['id']}</code> 發布失敗 5 次，已放棄。"
                                  f"請檢查 X API 憑證同額度。")
                    log(f"  發布失敗（第 {q['retry_count']} 次），會再試")

    # 3) 清走 30 日前嘅已完成項目，唔好等 queue.json 無限膨脹
    cutoff = utcnow() - dt.timedelta(days=30)
    before = len(queue)
    queue = [q for q in queue
             if q["status"] in ("pending", "approved", "redo")
             or (parse_iso(q.get("posted_at") or q.get("created")) or utcnow()) > cutoff]
    if before != len(queue):
        log(f"清理咗 {before - len(queue)} 個舊項目")

    save_queue(queue)
    save_posted(posted_store)

    pend = sum(1 for q in queue if q["status"] == "pending")
    appr = sum(1 for q in queue if q["status"] == "approved")
    log(f"完成：{pend} 待審、{appr} 待發、今日已發 {_posts_today(queue)}/{max_day}")
    return 0


# ────────────────────────── 自檢模式 ──────────────────────────

def cmd_doctor() -> int:
    log("=== 自檢 ===")
    ok = True

    try:
        cfg = load_config()
        log(f"✓ config.yaml 讀得到（{len(cfg)} 個區段）")
    except Exception as e:  # noqa: BLE001
        log(f"✗ config.yaml 有問題：{e}")
        return 1

    cfg_provider = (PROVIDER or cfg.get("content", {}).get("llm_provider", "openai")).lower()
    need_llm_key = "ANTHROPIC_API_KEY" if cfg_provider == "claude" else "OPENAI_API_KEY"
    log(f"內容生成供應商：{cfg_provider} → 需要 {need_llm_key}")

    for name in (need_llm_key, "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                 "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"):
        if os.environ.get(name, "").strip():
            log(f"✓ {name} 已設定")
        else:
            log(f"✗ {name} 冇設定")
            ok = False

    log("--- Polymarket API ---")
    try:
        ms = fetch.fetch_normalised()
        log(f"{'✓' if ms else '✗'} 抓到 {len(ms)} 個可用市場")
        if ms:
            cands = selector.pick(ms, cfg)
            log(f"{'✓' if cands else '⚠'} 過到篩選嘅候選：{len(cands)} 個")
        else:
            ok = False
    except Exception as e:  # noqa: BLE001
        log(f"✗ Polymarket 抓取失敗：{e}")
        ok = False

    log("--- X 憑證 ---")
    shape_problems = post_x.shape_check()
    for pr in shape_problems:
        log(f"  ⚠ {pr}")
    if not post_x.verify_credentials(dry_run=DRY):
        ok = False
        if not shape_problems:
            log("  格式檢查冇發現異常，但 v1.1 明確回 401 —— "
                "四個值其中一個貼錯咗另一個欄位嘅內容。")
        log("  修法：X Developer Portal → Keys and tokens →")
        log("    1) Regenerate Consumer Key（連 Secret 一齊即刻抄低）")
        log("    2) 然後先 Regenerate Access Token（順序倒轉要重做）")
        log("    3) 確認新 Access Token 顯示 Read and write")

    log("--- Telegram ---")
    try:
        tg.notify("🔧 pmwire 自檢：Telegram 通道正常。")
        log("✓ Telegram 已發出測試訊息")
    except Exception as e:  # noqa: BLE001
        log(f"✗ Telegram 失敗：{e}")
        ok = False

    log("=== 自檢 " + ("全部通過" if ok else "有問題，見上") + " ===")
    return 0 if ok else 1


# ────────────────────────── 日誌摘要模式 ──────────────────────────

def cmd_scan() -> int:
    """跑齊三個結構性掃描，印出 anchor／basket／violation 貼所需嘅數字。

    ⚠️ 呢個係內容核心。`move` 異動註記只係填數量，
       真正冇人有嘅係下面三組數。
    """
    cfg = load_config()
    log("═══ 結構性掃描 ═══")

    markets = fetch.fetch_normalised()
    if not markets:
        log("抓唔到市場數據")
        return 1

    # ── C：negRisk 盤面效率（anchor 貼）──
    log("\n── C  negRisk 盤面效率 ──")
    boards = scans.fetch_negrisk_boards()
    scored = scans.score_boards(boards)
    rep = scans.board_report(scored)
    if rep["n_boards"]:
        log(f"  掃描 {rep['n_boards']} 個盤面")
        log(f"  Σask 中位數 {rep['median_ask']}　（最低 {rep['min_ask']}）")
        log(f"  Σbid 中位數 {rep['median_bid']}　（最高 {rep['max_bid']}）")
        log(f"  違規：{rep['n_violations']} 個")
        for v in rep["violations"][:5]:
            log(f"    · {v['kind']}  Σask={v['sum_ask']:.4f} Σbid={v['sum_bid']:.4f}"
                f"  深度 ${v['min_depth']:,.0f}  {v['title'][:56]}")
    else:
        log("  ⚠ 取唔到任何完整盤面報價")

    # ── B：日期階梯（violation 貼）──
    log("\n── B  日期階梯單調性 ──")
    viol = scans.ladder_scan(markets)
    for v in viol[:5]:
        log(f"  · 差 {v['gap']*100:.1f}pt（{v['polarity']}）")
        log(f"      早 {v['early']['deadline']} @ {v['early']['price']:.0%}"
            f"  {v['early']['question'][:52]}")
        log(f"      遲 {v['late']['deadline']} @ {v['late']['price']:.0%}"
            f"  {v['late']['question'][:52]}")
    if not viol:
        log("  零違規 —— 呢個本身就係結論")

    # ── A：政治冷門籃子（basket 貼）──
    log("\n── A  政治冷門籃子 ──")
    cands = scans.basket_candidates(markets)
    log(f"  符合條件嘅市場：{len(cands)} 個")
    added = ledger.add_candidates(cands)
    mtm = ledger.mark_to_market(markets)
    st = ledger.stats()
    log(f"  帳本：{st['total']} 筆　未結算 {st['pending']}　已結算 {st['settled']}"
        + (f"（YES {st['settled_yes']} / NO {st['settled_no']}）" if st["settled"] else ""))
    if st["mean_entry"] is not None:
        log(f"  籃內均價：入場 {st['mean_entry']:.4f} → 今日 {st['mean_current']:.4f}"
            + (f"　漂移 {st['drift_pts']:+.1f}pt" if st["drift_pts"] is not None else ""))
    if st["roi_pct"] is not None:
        log(f"  已結算 ROI：{st['roi_pct']:+.1f}%（{st['settled']} 筆，樣本細，唔好過度解讀）")
    due = ledger.due_settlement()
    if due:
        log(f"  ⚠ {len(due)} 筆已過結算日仲係 pending —— 去查結果再用 "
            f"`run.py settle <market_id> YES|NO` 記低")
        for r in due[:5]:
            log(f"      {r['market_id'][:24]}  {r['question'][:50]}")

    log("\n═══ 掃描完成 ═══")
    return 0


def cmd_settle() -> int:
    """記錄一筆結算結果：run.py settle <market_id> YES|NO"""
    if len(sys.argv) < 4:
        print("用法：python src/run.py settle <market_id> YES|NO")
        return 2
    mid, outcome = sys.argv[2], sys.argv[3].upper()
    if outcome not in ("YES", "NO"):
        print("結果只可以係 YES 或 NO")
        return 2
    if ledger.settle(mid, outcome):
        st = ledger.stats()
        log(f"✓ 已記錄 {mid} = {outcome}")
        log(f"  帳本：已結算 {st['settled']} 筆"
            f"（YES {st['settled_yes']} / NO {st['settled_no']}）"
            f"　ROI {st['roi_pct']:+.1f}%")
        return 0
    log(f"✗ 帳本入面搵唔到 {mid}（或者已經結算咗）")
    return 1


def cmd_digest() -> int:
    """每日送一次：今日寫過乜、邊啲到期回訪、邊啲應該有結果。"""
    text = tracker.digest()
    print(text.replace("<b>", "").replace("</b>", ""))
    if not DRY:
        tg.notify(text)
    due = tracker.due_resolutions()
    if due:
        log(f"⚠️ 有 {len(due)} 個市場已到結算日，記得出結算貼並用 "
            f"`mark` 記低結果")
    return 0


def cmd_testpost() -> int:
    """真發一篇極短貼文再即刻刪返 —— 唯一可靠嘅寫入權限測試。"""
    if DRY:
        log("DRY_RUN 開緊，testpost 冇意義。除咗 DRY_RUN 再跑。")
        return 1
    log("=== X 寫入權限測試 ===")
    for pr in post_x.shape_check():
        log(f"  ⚠ {pr}")
    return 0 if post_x.test_roundtrip() else 1


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if DRY:
        log("⚠️  DRY_RUN 開啟 —— 唔會真係發文")
    if mode == "draft":
        return cmd_draft()
    if mode == "publish":
        return cmd_publish()
    if mode == "digest":
        return cmd_digest()
    if mode == "doctor":
        return cmd_doctor()
    if mode == "testpost":
        return cmd_testpost()
    if mode == "scan":
        return cmd_scan()
    if mode == "settle":
        return cmd_settle()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
