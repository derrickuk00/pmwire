"""X (Twitter) 發布模組。

成本現實（2026年8月核實）：
  - X API 2026年2月6日轉為按用量計費，免費層對新申請者關閉
  - 純文字貼文：每篇約 $0.015
  - 含 URL 貼文：每篇約 $0.20  ← 貴 13 倍
  所以：貼文一律唔放連結，連結淨係放 bio。守門模組會強制執行。

  預算：15 篇/日 × 100 日 = 1,500 篇純文字 ≈ $22.50
        如果每篇加中文自回覆 = 3,000 次呼叫 ≈ $45

長度：200 字英文約 1,100–1,300 字元，超出免費 280 字元上限。
      需要 X Premium（長貼文）。Premium 約 $8/月。

認證用 OAuth 1.0a user context（consumer key/secret + access token/secret）。
好處：唔會過期，唔使 refresh token。
"""
from __future__ import annotations
import os
import requests
from requests_oauthlib import OAuth1
from common import log, env

TWEETS_URL = "https://api.x.com/2/tweets"
TIMEOUT = 45


def _auth() -> OAuth1:
    return OAuth1(
        env("X_API_KEY"),
        client_secret=env("X_API_SECRET"),
        resource_owner_key=env("X_ACCESS_TOKEN"),
        resource_owner_secret=env("X_ACCESS_SECRET"),
    )


def post(text: str, reply_to: str | None = None, dry_run: bool = False) -> str | None:
    """發一篇貼文。回傳 tweet id，失敗回傳 None。

    dry_run=True 只印出唔真發，用嚟試跑。
    """
    if dry_run:
        log(f"  [DRY RUN] 唔會真發。{len(text)} 字元"
            + (f"，回覆 {reply_to}" if reply_to else ""))
        log("  ---8<---\n" + text + "\n  --->8---")
        return f"dryrun-{abs(hash(text)) % 10**10}"

    payload: dict = {"text": text}
    if reply_to:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to}

    try:
        r = requests.post(TWEETS_URL, auth=_auth(), json=payload, timeout=TIMEOUT)
    except requests.RequestException as e:
        log(f"  ✗ 發文網絡錯誤：{e}")
        return None

    if r.status_code in (200, 201):
        tid = r.json().get("data", {}).get("id")
        log(f"  ✓ 已發布，tweet id {tid}")
        return tid

    # 常見錯誤逐個講清楚，唔好淨係吐 raw error
    body = r.text[:400]
    if r.status_code == 401:
        log("  ✗ 401 認證失敗 —— 檢查 4 個 X secret 有冇貼錯，"
            "同埋 app 權限係咪設咗 Read and write")
    elif r.status_code == 403:
        log(f"  ✗ 403 被拒 —— 通常係 app 權限唔夠（要 Read and write），"
            f"或者內容違規。回應：{body}")
    elif r.status_code == 429:
        log("  ✗ 429 超出速率限制 —— 今次跳過，下次再試")
    elif r.status_code == 402 or "payment" in body.lower() or "credit" in body.lower():
        log(f"  ✗ 402/額度問題 —— X 開發者帳戶可能冇 credit。回應：{body}")
    else:
        log(f"  ✗ 發文失敗 HTTP {r.status_code}：{body}")
    return None


def post_pair(text_en: str, text_zh: str, mode: str = "reply",
              dry_run: bool = False) -> tuple[str | None, str | None]:
    """發英文主帖 + 中文。

    mode:
      reply — 英文主帖，中文做自回覆（推薦：兩個語言演算法分開餵，各自唔拖累對方）
      main  — 中英合併喺同一篇（觸及最差，唔建議）
      off   — 淨係發英文
    """
    if mode == "main" and text_zh:
        tid = post(f"{text_en}\n\n———\n\n{text_zh}", dry_run=dry_run)
        return tid, None

    tid_en = post(text_en, dry_run=dry_run)
    if tid_en is None:
        return None, None

    tid_zh = None
    if mode == "reply" and text_zh:
        tid_zh = post(text_zh, reply_to=tid_en, dry_run=dry_run)
        if tid_zh is None:
            log("  ⚠ 英文已出但中文回覆失敗 —— 唔會重發英文")
    return tid_en, tid_zh


def shape_check() -> list[str]:
    """唔洩露數值咁檢查 4 個 X secret 嘅格式。

    401 最常見嘅原因唔係「值錯」，而係「貼錯格」——
    X 個 Keys & Tokens 頁面同時顯示 Bearer Token、Client ID、
    Client Secret（OAuth 2.0），好易攞錯咗嚟當 OAuth 1.0a 用。

    以下係 X OAuth 1.0a 各值嘅典型格式（用嚟提示，唔會硬性失敗）：
      Consumer Key        約 25 字元，純英數
      Consumer Secret     約 50 字元，純英數
      Access Token        `<數字user id>-<英數>`，**一定有連字號**
      Access Token Secret 約 45 字元，純英數
    """
    problems: list[str] = []

    vals = {
        "X_API_KEY": os.environ.get("X_API_KEY", ""),
        "X_API_SECRET": os.environ.get("X_API_SECRET", ""),
        "X_ACCESS_TOKEN": os.environ.get("X_ACCESS_TOKEN", ""),
        "X_ACCESS_SECRET": os.environ.get("X_ACCESS_SECRET", ""),
    }

    for name, v in vals.items():
        if not v:
            continue
        if v != v.strip():
            problems.append(f"{name} 前後有空白／換行 —— 貼嗰陣帶咗多餘字元")
        s = v.strip()
        if s.startswith("AAAA"):
            problems.append(f"{name} 睇落似 **Bearer Token**（App-Only 嗰個），"
                            f"唔係 OAuth 1.0a 嘅值")

    ak = vals["X_ACCESS_TOKEN"].strip()
    if ak and "-" not in ak:
        problems.append("X_ACCESS_TOKEN 冇連字號 —— OAuth 1.0a 嘅 Access Token "
                        "一定係 `<數字>-<英數>` 格式。你可能貼咗 Consumer Key "
                        "或者 OAuth 2.0 嘅 Client ID")
    if ak and "-" in ak and not ak.split("-")[0].isdigit():
        problems.append("X_ACCESS_TOKEN 連字號前面唔係純數字 —— 通常應該係你嘅 user id")

    ck = vals["X_API_KEY"].strip()
    if ck and "-" in ck:
        problems.append("X_API_KEY 有連字號 —— 你可能把 Access Token 貼咗入 "
                        "X_API_KEY 呢一格（兩格調轉咗？）")

    # 長度提示（唔硬性失敗，X 有可能改格式）
    for name, lo, hi in (("X_API_KEY", 20, 30), ("X_API_SECRET", 40, 60),
                         ("X_ACCESS_SECRET", 40, 52)):
        s = vals[name].strip()
        if s and not (lo <= len(s) <= hi):
            problems.append(f"{name} 長度 {len(s)}，一般係 {lo}–{hi} —— 值得再核對")

    if vals["X_API_KEY"].strip() and \
            vals["X_API_KEY"].strip() == vals["X_API_SECRET"].strip():
        problems.append("X_API_KEY 同 X_API_SECRET 一模一樣 —— 貼重複咗")

    return problems


def delete(tweet_id: str) -> bool:
    """刪一篇貼文。DELETE /2/tweets/:id 支援 OAuth 1.0a。"""
    try:
        r = requests.delete(f"{TWEETS_URL}/{tweet_id}", auth=_auth(), timeout=TIMEOUT)
    except requests.RequestException as e:
        log(f"  刪文網絡錯誤：{e}")
        return False
    if r.status_code == 200 and r.json().get("data", {}).get("deleted"):
        return True
    log(f"  刪文失敗 HTTP {r.status_code}：{r.text[:200]}")
    return False


def verify_credentials(dry_run: bool = False) -> bool:
    """盡力驗證憑證。

    ⚠️ 呢度冇一個完美嘅唯讀檢查。X 官方文檔列明
       `GET /2/users/me` 只支援 OAuth 2.0 同 Bearer Token，
       **唔支援 OAuth 1.0a** —— 用佢驗 OAuth 1.0a 憑證必定 401，
       而嗰個 401 唔代表憑證有問題。（我最初就係咁搞錯咗。）

    所以改為試 v1.1 嘅 verify_credentials（本身就係為 OAuth 1.0a 而設）。
    如果你嘅存取層唔畀用 v1.1，就會回「無法確認」——**唔當失敗**，
    因為唯一確定嘅測試係真發一篇，見 `run.py testpost`。
    """
    if dry_run:
        log("[DRY RUN] 跳過 X 憑證檢查")
        return True
    try:
        r = requests.get("https://api.x.com/1.1/account/verify_credentials.json",
                         auth=_auth(), timeout=TIMEOUT)
    except requests.RequestException as e:
        log(f"X 憑證檢查網絡錯誤：{e}")
        return True  # 網絡問題唔算憑證問題
    if r.status_code == 200:
        try:
            u = r.json()
            log(f"✓ X 憑證 OK —— 帳戶 @{u.get('screen_name')}")
        except ValueError:
            log("✓ X 憑證 OK")
        return True
    if r.status_code == 401:
        log(f"✗ X 憑證被拒（v1.1 回 401）—— 四個值其中一個唔啱")
        return False
    log(f"⚠ 無法用 v1.1 確認憑證（HTTP {r.status_code}）—— "
        f"你嘅存取層可能唔開放 v1.1。呢個唔代表憑證有問題。")
    log(f"  唯一確定嘅測試：喺本機或 Actions 跑 `python src/run.py testpost`")
    return True


def test_roundtrip() -> bool:
    """真發一篇極短貼文，成功之後即刻刪返。

    呢個係唯一可靠嘅測試 —— 同時驗證認證同寫入權限，
    而且唔會喺你個 timeline 留低任何嘢。
    """
    text = "setup test — deleting this immediately"
    log("發一篇測試貼文（成功後會自動刪除）…")
    tid = post(text)
    if not tid:
        log("✗ 發文失敗 —— 上面有具體原因")
        return False
    log(f"✓ 發文成功（id {tid}）—— 認證同寫入權限都正常")
    if delete(tid):
        log("✓ 已自動刪除，timeline 冇留低任何嘢")
    else:
        log(f"⚠️ 自動刪除失敗 —— 請自己去 timeline 刪咗 id {tid} 嗰篇")
    return True
