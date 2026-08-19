"""Telegram 人手審批閘 —— 非阻塞佇列式。

點解唔用「發完等你撳」嘅阻塞式做法：
  GitHub Actions 一個 job 最多行 6 小時，而且等緊嘅時候一樣燒緊分鐘數。
  阻塞式即係你唔喺電話旁邊，條 workflow 就吊死。

改為佇列式：
  - 草稿 job：生成 → 送去 Telegram → 寫入 queue.json（狀態 pending）→ 收工
  - 發布 job（每 10 分鐘）：讀 Telegram 有冇新決定 → 更新 queue → 發已批准嘅
  你幾時撳都得，撳完最多 10 分鐘內出街。唔撳就永遠唔會出街。
"""
from __future__ import annotations
import requests
from common import log, env, load_tg_offset, save_tg_offset

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 30


def _call(method: str, payload: dict | None = None, token: str | None = None):
    token = token or env("TELEGRAM_BOT_TOKEN")
    r = requests.post(API.format(token=token, method=method),
                      json=payload or {}, timeout=TIMEOUT)
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"Telegram {method} 回應唔係 JSON：{r.text[:200]}")
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} 失敗：{data.get('description')}")
    return data.get("result")


def _preview(item: dict) -> str:
    """組成審批訊息。用 HTML parse mode。"""
    def esc(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    m = item["market"]
    head = (
        f"<b>{esc(m['question'][:180])}</b>\n"
        f"<code>{m['yes_price']*100:.0f}%  "
        f"Δ1h {m['move_1h']*100:+.1f}pt  "
        f"Δ24h {m['move_24h']*100:+.1f}pt</code>\n"
        f"<code>24h量 ${m['volume_24hr']:,.0f}  流動性 ${m['liquidity']:,.0f}</code>\n"
        f"<i>{esc(m['category'])} · {m.get('days_to_end', 0):.0f} 日後結算 · "
        f"評分 {m.get('_score', 0):.0f}</i>\n"
    )
    if item.get("flags"):
        head += f"⚑ <b>待你留意嘅字眼：</b> {esc(', '.join(item['flags']))}\n"
    body = f"\n<b>EN</b>\n{esc(item['text_en'])}\n"
    if item.get("text_zh"):
        body += f"\n<b>中文</b>\n{esc(item['text_zh'])}\n"
    tail = f"\n<code>#{item['id']}</code>"
    msg = head + body + tail
    return msg[:4000]  # Telegram 訊息上限 4096


def send_for_approval(item: dict) -> int | None:
    """送一個草稿去審批，回傳 Telegram message_id。"""
    chat_id = env("TELEGRAM_CHAT_ID")
    kb = {"inline_keyboard": [[
        {"text": "✅ 批准", "callback_data": f"ok:{item['id']}"},
        {"text": "🔁 重寫", "callback_data": f"redo:{item['id']}"},
        {"text": "🗑 丟棄", "callback_data": f"kill:{item['id']}"},
    ]]}
    res = _call("sendMessage", {
        "chat_id": chat_id,
        "text": _preview(item),
        "parse_mode": "HTML",
        "reply_markup": kb,
        "disable_web_page_preview": True,
    })
    mid = res.get("message_id") if isinstance(res, dict) else None
    log(f"  已送去 Telegram 審批（訊息 {mid}）")
    return mid


def notify(text: str) -> None:
    """一般通知（無按鈕）。失敗唔中斷主流程。"""
    try:
        _call("sendMessage", {
            "chat_id": env("TELEGRAM_CHAT_ID"),
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
    except (RuntimeError, requests.RequestException) as e:
        log(f"WARN Telegram 通知失敗：{e}")


def poll_decisions() -> dict[str, str]:
    """讀取自上次之後嘅所有按鈕點擊。

    回傳 {queue_item_id: "ok" | "redo" | "kill"}。
    同一項目多次點擊，以最後一次為準。
    """
    offset = load_tg_offset()
    decisions: dict[str, str] = {}
    try:
        updates = _call("getUpdates", {"offset": offset + 1, "timeout": 0, "limit": 100})
    except (RuntimeError, requests.RequestException) as e:
        log(f"WARN 讀取 Telegram 決定失敗：{e}")
        return {}

    if not updates:
        return {}

    max_id = offset
    for u in updates:
        max_id = max(max_id, u.get("update_id", 0))
        cq = u.get("callback_query")
        if not cq:
            continue
        data = cq.get("data", "")
        if ":" not in data:
            continue
        action, item_id = data.split(":", 1)
        if action in ("ok", "redo", "kill"):
            decisions[item_id] = action
        # 熄咗個 loading 圈，並喺按鈕上方顯示結果
        try:
            label = {"ok": "已批准", "redo": "已排重寫", "kill": "已丟棄"}[action]
            _call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": label})
        except (RuntimeError, requests.RequestException, KeyError):
            pass

    save_tg_offset(max_id)
    if decisions:
        log(f"收到 {len(decisions)} 個審批決定：{decisions}")
    return decisions


def mark_result(message_id: int | None, suffix: str) -> None:
    """喺原訊息尾加一行結果，並移除按鈕。"""
    if not message_id:
        return
    try:
        _call("editMessageReplyMarkup", {
            "chat_id": env("TELEGRAM_CHAT_ID"),
            "message_id": message_id,
            "reply_markup": {"inline_keyboard": []},
        })
    except (RuntimeError, requests.RequestException):
        pass
    notify(suffix)
