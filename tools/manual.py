#!/usr/bin/env python3
"""人手 loop：唔使 LLM API key 都出到稿。

用途：頭一兩星期你本來就手貼，可以用你已經付咗錢嘅 CLI 或者網頁版
      生成，唔使即刻買 API。同時可以先驗證內容質素。

兩步：

  1) 出 prompt（真連 Polymarket 選題，印出可以直接貼落去嘅 prompt）

        python tools/manual.py prompt

     把印出嚟嘅嘢整段貼落你嘅 CLI／網頁版，攞返個 JSON。

  2) 檢查佢寫嘅嘢（貼返嚟，行合規守門 + 發現度檢查）

        python tools/manual.py check

     然後貼上 JSON（或者直接貼英文同中文），Ctrl-D 結束。
     過到關就會印出可以直接貼上 X 嘅最終版本。

⚠️ 呢個係過渡方案，唔係長期架構：
   - 只喺你部機行得，GitHub Actions 呼叫唔到
   - 用消費者訂閱做自動化後端可能違反條款，你自己確認
   - API 100 日全程只係 US$2–24，行到第二三星期就應該轉返 API
"""
from __future__ import annotations
import sys, os, json, re, argparse, pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from common import load_config          # noqa: E402
import fetch, picker, guard, seo, draft  # noqa: E402

BAR = "═" * 70
STATE = HERE.parent / "state" / "manual_last.json"


def cmd_prompt(args) -> int:
    cfg = load_config()
    markets = fetch.fetch_normalised()
    if not markets:
        print("❌ 抓唔到市場數據")
        return 1
    cands = picker.pick(markets, cfg)
    if not cands:
        print("\n⚠️  今次冇市場過到篩選 —— 呢個係正常結果，市場靜就唔應該出稿。")
        return 0

    m = cands[min(args.nth - 1, len(cands) - 1)]

    # 記低揀咗邊個，check 嗰陣可以自動配返
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(
        {k: v for k, v in m.items() if not k.startswith("_")}
        | {"_score": m.get("_score", 0), "_family": m.get("_family", "")},
        ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{BAR}\n  第 {args.nth} 名候選（共 {len(cands)} 個）\n{BAR}")
    print(f"  {m['question']}")
    print(f"  {m['yes_price']:.0%}　Δ1h {m['move_1h']:+.1%}　Δ24h {m['move_24h']:+.1%}"
          f"　${m['volume_24hr']:,.0f}　[{m['category']}]")
    print(f"\n{BAR}\n  ↓↓↓ 由下一行開始整段複製，貼落你嘅 CLI／網頁版 ↓↓↓\n{BAR}\n")

    print(draft.SYSTEM_PROMPT)
    print("\n---\n")
    print(draft.build_user_prompt(m))

    print(f"\n{BAR}\n  ↑↑↑ 複製到呢度為止 ↑↑↑")
    print(f"{BAR}\n")
    print("攞到回覆之後跑：  python tools/manual.py check")
    return 0


def _extract(raw: str) -> tuple[str, str]:
    """由貼返嚟嘅嘢抽出英文同中文。

    接受三種格式：純 JSON、包住 ``` 圍欄嘅 JSON、或者
    「英文段落 + 空行 + 中文段落」。
    """
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)

    # 先試 JSON
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return (obj.get("en") or "").strip(), (obj.get("zh") or "").strip()
    except json.JSONDecodeError:
        pass

    # 試搵埋喺文字入面嘅 JSON 物件
    mm = re.search(r"\{.*\}", s, re.S)
    if mm:
        try:
            obj = json.loads(mm.group(0))
            if isinstance(obj, dict):
                return (obj.get("en") or "").strip(), (obj.get("zh") or "").strip()
        except json.JSONDecodeError:
            pass

    # 最後：按有冇中日韓字元切開
    lines = s.split("\n")
    cjk = re.compile(r"[一-鿿]")
    split_at = next((i for i, ln in enumerate(lines) if cjk.search(ln)), None)
    if split_at is None:
        return s, ""
    return "\n".join(lines[:split_at]).strip(), "\n".join(lines[split_at:]).strip()


def cmd_check(args) -> int:
    cfg = load_config()
    c = cfg["compliance"]

    print("貼上 LLM 嘅回覆（JSON 或者英文+中文都得），完咗撳 Ctrl-D：\n")
    raw = sys.stdin.read()
    if not raw.strip():
        print("❌ 冇輸入")
        return 1

    en, zh = _extract(raw)
    # 收走段落內嘅硬換行 —— 由 CLI／網頁版複製返嚟最易帶住
    en, zh = draft.normalise_for_x(en), draft.normalise_for_x(zh)
    if not en:
        print("❌ 抽唔到英文內容")
        return 1

    # 免責聲明由 code 補，唔靠 LLM 記得
    if c["disclaimer_en"] not in en:
        en = f"{en}\n\n{c['disclaimer_en']}"
    if zh and c["disclaimer_zh"] not in zh:
        zh = f"{zh}\n\n{c['disclaimer_zh']}"

    m = {}
    if STATE.exists():
        try:
            m = json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    g = guard.check(en, zh, cfg)
    s = seo.analyse(en, zh, m, tier="move")

    print(f"\n{BAR}")
    print(f"合規　 {'✅ 通過' if g.ok else '❌ 拒絕'}　{g.reason}")
    if g.flags:
        print(f"  ⚑ 待你留意嘅字眼：{', '.join(g.flags)}")
    print(f"發現度 {'✅ 通過' if s.ok else '❌ 唔合格'}"
          f"　實體：{'、'.join(s.entities) or '無'}")
    for p in s.problems:
        print(f"  ✗ {p}")
    for h in s.hints:
        print(f"  💡 {h}")
    print(BAR)

    if not (g.ok and s.ok):
        print("\n唔好貼呢篇。把上面嘅問題貼返畀 LLM 叫佢重寫，然後再 check 一次。")
        return 1

    print(f"\n✅ 可以貼。英文 {len(en.split())} 字 / {len(en)} 字元"
          f"　中文 {len(zh)} 字元\n")
    print(BAR + "\n  英文主帖\n" + BAR)
    print(en)
    if zh:
        print("\n" + BAR + "\n  中文（貼做英文帖嘅自回覆）\n" + BAR)
        print(zh)
    print()

    if m.get("question"):
        print(f"📓 記得手動記入 state/post_log.csv：")
        print(f"   市場 {m['question'][:60]}")
        print(f"   價格 {m.get('yes_price', 0):.4f}　結算 "
              f"{(m.get('end_date') or '')[:10]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p1 = sub.add_parser("prompt", help="選題並印出可貼嘅 prompt")
    p1.add_argument("--nth", type=int, default=1, help="揀第幾名候選（預設 1）")
    p1.set_defaults(fn=cmd_prompt)
    p2 = sub.add_parser("check", help="貼返 LLM 回覆，行守門同發現度檢查")
    p2.set_defaults(fn=cmd_check)
    args = ap.parse_args()
    if not getattr(args, "fn", None):
        ap.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
