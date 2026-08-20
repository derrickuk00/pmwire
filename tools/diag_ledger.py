#!/usr/bin/env python3
"""診斷：點解帳本持倉查唔到價。

唔洩露任何秘密，只係打幾個公開 API 然後印出實情。

    python tools/diag_ledger.py
"""
from __future__ import annotations
import sys, json, pathlib, requests

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
import ledger  # noqa: E402

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = {"User-Agent": "pmwire/1.0 (diag)"}
BAR = "─" * 66


def show(label, r):
    body = r.text[:300].replace("\n", " ")
    n = "?"
    try:
        d = r.json()
        n = len(d) if isinstance(d, list) else ("dict" if isinstance(d, dict) else "?")
    except ValueError:
        pass
    print(f"  {label:38s} HTTP {r.status_code}  回 {n} 項")
    if r.status_code != 200 or n in (0, "?"):
        print(f"      {body}")


def main() -> int:
    rows = ledger.read_all()
    pend = [r for r in rows if r.get("status") == "pending"]
    if not pend:
        print("帳本冇未結算條目")
        return 1

    print(f"{BAR}\n  帳本 {len(rows)} 筆，未結算 {len(pend)}\n{BAR}")

    ids = [r["market_id"] for r in pend]
    lens = sorted({len(i) for i in ids})
    print(f"market_id 長度分佈：{lens}")
    print(f"（真正嘅 Polymarket conditionId 係 66 字元：0x + 64 hex）")
    print(f"頭三個完整值：")
    for i in ids[:3]:
        print(f"  {i}   ← {len(i)} 字元")

    cid = ids[0]
    print(f"\n{BAR}\n  用第一個 id 試各種查法\n{BAR}")

    tries = [
        ("Gamma condition_ids（開市）",
         lambda: requests.get(f"{GAMMA}/markets", headers=UA, timeout=25,
                              params={"condition_ids": cid, "closed": "false"})),
        ("Gamma condition_ids（已結算）",
         lambda: requests.get(f"{GAMMA}/markets", headers=UA, timeout=25,
                              params={"condition_ids": cid, "closed": "true"})),
        ("Gamma condition_ids（唔指定 closed）",
         lambda: requests.get(f"{GAMMA}/markets", headers=UA, timeout=25,
                              params={"condition_ids": cid})),
        ("Gamma condition_id（單數）",
         lambda: requests.get(f"{GAMMA}/markets", headers=UA, timeout=25,
                              params={"condition_id": cid})),
        ("CLOB /markets/<cid>",
         lambda: requests.get(f"{CLOB}/markets/{cid}", headers=UA, timeout=25)),
    ]
    for label, fn in tries:
        try:
            show(label, fn())
        except requests.RequestException as e:
            print(f"  {label:38s} 網絡錯誤：{e}")

    # 反向驗證：由今日大掃描攞個真 id，睇下同一查法通唔通
    print(f"\n{BAR}\n  反向對照：用今日大掃描攞到嘅真 id 試同一查法\n{BAR}")
    try:
        r = requests.get(f"{GAMMA}/markets", headers=UA, timeout=25,
                         params={"limit": 1, "closed": "false", "active": "true",
                                 "order": "volume24hr", "ascending": "false"})
        live = r.json()[0]
        live_cid = live.get("conditionId")
        print(f"  真 id：{live_cid}   ← {len(str(live_cid))} 字元")
        rr = requests.get(f"{GAMMA}/markets", headers=UA, timeout=25,
                          params={"condition_ids": live_cid, "closed": "false"})
        show("Gamma condition_ids（用真 id）", rr)
        print("\n  → 如果呢個通而你帳本嗰個唔通，即係帳本 id 格式唔啱。")
        print("     如果兩個都唔通，即係 condition_ids 呢個參數用法唔啱。")
    except (requests.RequestException, ValueError, IndexError, KeyError) as e:
        print(f"  反向對照失敗：{e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
