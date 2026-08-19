#!/usr/bin/env python3
"""本機試跑 —— 零憑證，唔會發任何嘢。

用途：喺你部 Mac 上行一次完整流程，親眼睇住成件事點運作。

    cd pmwire
    pip install -r requirements.txt
    python tools/dryrun.py

會做嘅事：
    1. 真連 Polymarket Gamma API（你部機通，Anthropic 雲端沙盒唔通）
    2. 真跑選題引擎，印出頭 10 名候選同評分明細
    3. 用內建假稿（唔使 OpenAI key）行一次守門 + 發現度檢查
    4. 模擬「已發布」，寫入回訪追蹤，印出每日日誌
    全程唔會連 X、唔會連 Telegram、唔會用任何 API key。

如果你有 OpenAI key，加 --live-llm 就會真係生成一篇：
    OPENAI_API_KEY=sk-... python tools/dryrun.py --live-llm
"""
from __future__ import annotations
import sys, os, argparse, tempfile, pathlib, datetime as dt

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import common
# 試跑用暫存狀態，唔好污染真 state/
_TMP = tempfile.mkdtemp(prefix="pmwire-dryrun-")
common.STATE_DIR = pathlib.Path(_TMP)
common.QUEUE_PATH = common.STATE_DIR / "queue.json"
common.POSTED_PATH = common.STATE_DIR / "posted.json"

from common import load_config, log            # noqa: E402
import fetch, picker, guard, seo, tracker      # noqa: E402
tracker.LOG_PATH = common.STATE_DIR / "post_log.csv"

BAR = "─" * 66


def hr(title: str) -> None:
    print(f"\n{BAR}\n  {title}\n{BAR}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-llm", action="store_true",
                    help="真係叫 OpenAI 生成（需要 OPENAI_API_KEY）")
    ap.add_argument("--top", type=int, default=10, help="印幾多個候選")
    args = ap.parse_args()

    cfg = load_config()
    print(f"試跑狀態目錄：{_TMP}")

    # ── 1. 抓數據 ──
    hr("1 / 5　連 Polymarket Gamma API")
    try:
        markets = fetch.fetch_normalised()
    except Exception as e:                                    # noqa: BLE001
        print(f"\n❌ 抓取失敗：{e}")
        print("   如果你係喺公司網絡／VPN 後面，試下轉網絡。")
        print("   Gamma 係公開 API，唔需要任何 key。")
        return 1
    if not markets:
        print("❌ 抓唔到市場。API 可能暫時有事，等陣再試。")
        return 1
    print(f"✅ 取得 {len(markets)} 個可用二元市場")

    # ── 2. 選題 ──
    hr("2 / 5　選題引擎")
    cands = picker.pick(markets, cfg)
    if not cands:
        print("\n⚠️  今次冇市場過到篩選。")
        print("   呢個係正常結果，唔係錯誤 —— 市場靜嘅時候就應該唔出稿。")
        print("   想睇多啲候選，可以喺 config.yaml 調低：")
        print("     selection.min_volume_24hr  （而家 "
              f"{cfg['selection']['min_volume_24hr']:,}）")
        print("     selection.min_abs_move_24hr（而家 "
              f"{cfg['selection']['min_abs_move_24hr']}）")
        return 0

    # 主題分佈 —— 一眼睇到有冇某類霸晒
    from collections import Counter
    dist = Counter(m["category"] for m in markets)
    print("\n全部市場主題分佈：" +
          "　".join(f"{k} {v}" for k, v in dist.most_common()))
    dist2 = Counter(m["category"] for m in cands)
    print("過到篩選之後　　：" +
          ("　".join(f"{k} {v}" for k, v in dist2.most_common()) or "（無）"))

    print(f"\n{'分數':>6}  {'YES':>5}  {'Δ1h':>7}  {'Δ24h':>7}  {'24h成交':>12}  "
          f"{'主題':<12} 題目")
    for m in cands[:args.top]:
        flag = " ⚠" if m.get("_move_1h_uncorroborated") else ""
        print(f"{m['_score']:6.1f}  {m['yes_price']:5.0%}  "
              f"{m['move_1h']:+7.1%}  {m['move_24h']:+7.1%}  "
              f"${m['volume_24hr']:>11,.0f}  {m['category']:<12} "
              f"{m['question'][:46]}{flag}")

    top = cands[0]
    print(f"\n選中：{top['question']}")
    print(f"評分明細：{top['_score_parts']}")

    # ── 3. 生成 ──
    hr("3 / 5　內容生成")
    if args.live_llm:
        if not os.environ.get("OPENAI_API_KEY"):
            print("❌ --live-llm 需要 OPENAI_API_KEY 環境變數")
            return 1
        import draft
        en, zh, gres, sres = draft.generate_compliant(
            top, cfg, guard.check, max_attempts=3, tier="move")
        if not en:
            print("❌ 三次都過唔到關卡。呢個係系統正常運作 —— "
                  "寧願唔出，都好過出一篇違規嘅。")
            return 0
    else:
        print("（用內建假稿。加 --live-llm 就會真係叫 OpenAI）")
        d = cfg["compliance"]
        ratio = top["volume_24hr"] / max(top["liquidity"], 1.0)
        depth_line = ("Volume ran well above resting depth, so the move consumed "
                      "the book rather than sitting alongside it."
                      if ratio > 2 else
                      "Volume and resting depth were comparable, so the move did "
                      "not obviously exhaust the book.")
        en = (f"This one moved {abs(top['move_24h'])*100:.1f} points in 24 hours.\n\n"
              f"{top['question']} now trades at {top['yes_price']*100:.0f}c on "
              f"Polymarket, on ${top['volume_24hr']:,.0f} of volume against "
              f"${top['liquidity']:,.0f} of resting liquidity.\n\n"
              f"{depth_line} "
              "That ratio is the part worth pausing on.\n\n"
              "Two things could explain a move of this shape. One is that new "
              "information arrived and the price is now correct. The other is that "
              "the book was thin enough that the print says more about liquidity "
              "than about anyone's view. Neither is established here.\n\n"
              "What settles it is whether the level holds once depth rebuilds. "
              "I will check back in five days and post what happened.\n\n"
              f"{d['disclaimer_en']}")
        zh_depth = ("成交額明顯高於掛出深度，代表變動是吃掉了訂單簿，"
                    "而非與之並存。" if ratio > 2 else
                    "成交額與掛出深度相若，變動並未明顯消耗訂單簿。")
        zh = (f"這個市場 24 小時內變動 {abs(top['move_24h'])*100:.1f} 個百分點。\n\n"
              f"現報 {top['yes_price']*100:.0f} 仙，同期成交額 "
              f"{top['volume_24hr']:,.0f} 美元，掛出的流動性為 "
              f"{top['liquidity']:,.0f} 美元。\n\n"
              f"{zh_depth}值得留意的正是這個比率。\n\n"
              "這種形態有兩種可能解釋。其一是新資訊出現，價格現已正確。"
              "其二是訂單簿夠薄，成交紀錄反映的是流動性狀況，而非任何人的看法。"
              "兩者在此均未確立。\n\n"
              "關鍵在於深度重建之後，該水平能否守住。我會在五日後覆查並發布結果。\n\n"
              f"{d['disclaimer_zh']}")

        gres = guard.check(en, zh, cfg)
        sres = seo.analyse(en, zh, top, tier="move")

    print(f"\n【英文】{len(en.split())} 字 / {len(en)} 字元")
    print(en)
    print(f"\n【中文】{len(zh)} 字元")
    print(zh)

    # ── 4. 兩道關 ──
    hr("4 / 5　合規守門 + 發現度檢查")
    print(f"合規：{'✅ 通過' if gres.ok else '❌ 拒絕'}　{gres.reason}")
    if gres.flags:
        print(f"  ⚑ 待人手留意：{', '.join(gres.flags)}")
    print(f"發現度：{'✅ 通過' if sres.ok else '❌ 唔合格'}")
    if sres.entities:
        print(f"  認到實體：{'、'.join(sres.entities)}")
    else:
        print("  ⚠️ 認唔到已知實體 —— 語意模型可能放唔準你入主題群")
    for p in sres.problems:
        print(f"  ✗ {p}")
    for h in sres.hints:
        print(f"  💡 {h}")

    if not (gres.ok and sres.ok):
        print("\n真實運作時，呢個時候會帶住上面嘅原因重寫，最多三次。")

    # ── 5. 追蹤 ──
    hr("5 / 5　回訪追蹤")
    tracker.log_post(
        post_id="dryrun01", tier="move",
        question=top["question"], claim=en.split("\n")[0][:150],
        condition_id=top["condition_id"], price_at_post=top["yes_price"],
        resolution_date=top.get("end_date"), tweet_id="(試跑)",
    )
    row = tracker.read_all()[0]
    print(f"已寫入 post_log.csv：")
    print(f"  類型 {row['tier']}　出稿日 {row['post_date']}")
    print(f"  應回訪 {row['revisit_date'] or '不需要'}"
          f"　預期結算 {row['resolution_date'] or '未知'}")
    print("\n每日日誌會係咁樣：\n")
    print(tracker.digest().replace("<b>", "").replace("</b>", ""))

    hr("試跑完成")
    print("以上全部係真數據（除咗稿件本身，除非你加咗 --live-llm）。")
    print("冇連過 X、冇連過 Telegram、冇發任何嘢。")
    print(f"\n下一步：跟 SETUP.md 貼好 7 個 GitHub Secrets，"
          f"然後喺 Actions 跑 doctor。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(_TMP, ignore_errors=True)
