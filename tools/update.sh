#!/usr/bin/env bash
# 安全更新：解壓新 zip → commit → push
#
# 用法（喺任何位置都得）：
#     bash <repo>/tools/update.sh
#     bash <repo>/tools/update.sh "自訂 commit 訊息"
#
# ⚠️ 為何唔再寫死 ~/Downloads/pmwire：
#    macOS Safari 嘅「下載後自動打開安全檔案」會叫 Archive Utility
#    自動解壓下載嘅 zip。如果 ~/Downloads/pmwire 已經存在，
#    佢會**整個資料夾取代**，連 .git 同 .venv 一齊清走。
#    （2026-08-20 連續兩次撞到，兩者同時消失。）
#
#    所以：repo 位置由呢個腳本自己嘅路徑推導，
#    而正確做法係把 repo 搬離 ~/Downloads（見 docs 或下面提示）。
#
# 佢會做嘅嘢：
#   1. 搵 ~/Downloads 最新嗰個 pmwire*.zip
#   2. .git 唔見就由 GitHub 還原（唔會掂你啲檔案）
#   3. .venv 唔見就重建
#   4. 解壓入 repo → commit → push
#
# 唔會做嘅嘢：唔會 rm -rf 你個資料夾。

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="https://github.com/derrickuk00/pmwire.git"
MSG="${1:-update}"

say()  { printf "\033[1m▸ %s\033[0m\n" "$1"; }
warn() { printf "\033[33m⚠ %s\033[0m\n" "$1"; }
die()  { printf "\033[31m✗ %s\033[0m\n" "$1" >&2; exit 1; }

say "repo：$REPO_DIR"

case "$REPO_DIR" in
  "$HOME/Downloads"/*)
    warn "個 repo 放咗喺 ~/Downloads 入面。"
    warn "Safari 自動解壓會整個資料夾取代，.git / .venv 會被清走。"
    warn "建議搬走一次過解決："
    warn "    mv \"$REPO_DIR\" ~/pmwire && cd ~/pmwire"
    warn "（或者關閉 Safari → 設定 → 一般 → 下載後自動打開安全檔案）"
    ;;
esac

# ── 1. 搵最新嘅 zip ──
ZIP="$(ls -t "$HOME/Downloads"/pmwire*.zip 2>/dev/null | head -1 || true)"
[ -n "$ZIP" ] || die "喺 ~/Downloads 搵唔到任何 pmwire*.zip"
say "用緊 $(basename "$ZIP")（$(date -r "$ZIP" '+%H:%M:%S') 下載）"

# ── 2. .git 唔見就還原 ──
if [ ! -d "$REPO_DIR/.git" ]; then
  say ".git 唔見咗 —— 由 GitHub 攞返（唔會掂你啲檔案）"
  TMP="$(mktemp -d)"
  git clone --quiet "$REMOTE" "$TMP/repo"
  mv "$TMP/repo/.git" "$REPO_DIR/.git"
  rm -rf "$TMP"
fi

# ── 3. 解壓（zip 根目錄係 pmwire/，抽出嚟蓋落 REPO_DIR）──
say "解壓中…"
TMPX="$(mktemp -d)"
unzip -o -q "$ZIP" -d "$TMPX"
SRC="$TMPX/pmwire"
[ -d "$SRC" ] || SRC="$TMPX"
# -a 保留權限，唔用 rsync 因為唔一定裝咗
(cd "$SRC" && tar cf - .) | (cd "$REPO_DIR" && tar xf -)
rm -rf "$TMPX"

# ── 4. .venv 唔見就重建 ──
if [ ! -x "$REPO_DIR/.venv/bin/python" ]; then
  say ".venv 唔見咗 —— 重建中（約 20 秒）"
  python3 -m venv "$REPO_DIR/.venv"
  "$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt"
  say ".venv 已重建 —— 記住重新 activate：source .venv/bin/activate"
fi

# ── 5. commit + push ──
cd "$REPO_DIR"

CHANGED="$(git status --porcelain | wc -l | tr -d ' ')"
if [ "$CHANGED" = "0" ]; then
  say "冇任何改動 —— 你已經係最新版"
  exit 0
fi

say "有 $CHANGED 個檔案改動"
git status --short | head -20

if git status --porcelain | grep -q '\.venv/'; then
  die ".venv 出現喺改動清單 —— .gitignore 有問題，停手"
fi

git add -A
git commit -q -m "$MSG"
say "推送中…"
git push -q
say "完成 —— $(git rev-parse --short HEAD)"
