"""共用工具：設定載入、狀態讀寫、日誌。"""
from __future__ import annotations
import json, os, sys, datetime as dt
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(exist_ok=True)

QUEUE_PATH = STATE_DIR / "queue.json"
POSTED_PATH = STATE_DIR / "posted.json"
TG_OFFSET_PATH = STATE_DIR / "tg_offset.json"


def log(msg: str) -> None:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_config() -> dict:
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log(f"WARN 讀 {path.name} 失敗（{e}），用預設值")
        return default


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_queue() -> list:
    return _read_json(QUEUE_PATH, [])


def save_queue(q: list) -> None:
    _write_json(QUEUE_PATH, q)


def load_posted() -> dict:
    """{condition_id: {"last_posted": iso, "count": n, "category": str, "event_id": str}}"""
    return _read_json(POSTED_PATH, {})


def save_posted(p: dict) -> None:
    _write_json(POSTED_PATH, p)


def load_tg_offset() -> int:
    return _read_json(TG_OFFSET_PATH, {"offset": 0}).get("offset", 0)


def save_tg_offset(offset: int) -> None:
    _write_json(TG_OFFSET_PATH, {"offset": offset})


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).isoformat()


def parse_iso(s: str | None):
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d
    except (ValueError, TypeError):
        return None


def env(name: str, required: bool = True) -> str:
    v = os.environ.get(name, "").strip()
    if required and not v:
        log(f"FATAL 缺少環境變數 {name}")
        sys.exit(1)
    return v
