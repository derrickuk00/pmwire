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


def verify_credentials(dry_run: bool = False) -> bool:
    """開波前自檢：確認 4 個 secret 啱同埋有寫入權限。"""
    if dry_run:
        log("[DRY RUN] 跳過 X 憑證檢查")
        return True
    try:
        r = requests.get("https://api.x.com/2/users/me", auth=_auth(), timeout=TIMEOUT)
    except requests.RequestException as e:
        log(f"X 憑證檢查網絡錯誤：{e}")
        return False
    if r.status_code == 200:
        u = r.json().get("data", {})
        log(f"X 憑證 OK —— 帳戶 @{u.get('username')} ({u.get('name')})")
        return True
    log(f"X 憑證檢查失敗 HTTP {r.status_code}：{r.text[:250]}")
    return False
