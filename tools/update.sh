#!/usr/bin/env bash
# 安全更新：解壓新 zip → commit → push
#
# 用法（喺任何位置都得）：
#     bash ~/Downloads/pmwire/tools/update.sh
#     bash ~/Downloads/pmwire/tools/update.sh "自訂 commit 訊息"
#
# 佢會做嘅嘢：
#   1. 確認 ~/Downloads 有最新嘅 pmwire zip（自動揀最新嗰個，
#      包括 Safari／Chrome 改名成 pmwire-2.zip 呢類）
#   2. 如果 .git 唔見咗，自動由 GitHub clone 返嚟駁上去（唔會掂你啲檔案）
#   3. 解壓、commit、push
#
# 唔會做嘅嘢：唔會 rm -rf 你個資料夾，唔會掂 .venv。

set -euo pipefail

REPO_DIR="$HOME/Downloads/pmwire"
REMOTE="https://github.com/derrickuk00/pmwire.git"
MSG="${1:-update}"

say() { printf "\033[1m▸ %s\033[0m\n" "$1"; }
die() { printf "\033[31m✗ %s\033[0m\n" "$1" >&2; exit 1; }

[ -d "$REPO_DIR" ] || die "搵唔到 $REPO_DIR"

# ── 1. 搵最新嘅 zip ──
ZIP="$(ls -t "$HOME/Downloads"/pmwire*.zip 2>/dev/null | head -1 || true)"
[ -n "$ZIP" ] || die "喺 ~/Downloads 搵唔到任何 pmwire*.zip"
say "用緊 $(basename "$ZIP")（$(date -r "$ZIP" '+%H:%M:%S') 下載）"

# ── 2. .git 唔見就駁返 ──
if [ ! -d "$REPO_DIR/.git" ]; then
  say ".git 唔見咗 —— 由 GitHub 攞返（唔會掂你啲檔案）"
  TMP="$(mktemp -d)"
  git clone --quiet "$REMOTE" "$TMP/repo"
  mv "$TMP/repo/.git" "$REPO_DIR/.git"
  rm -rf "$TMP"
  say ".git 已還原"
fi

# ── 3. 解壓 ──
say "解壓中…"
unzip -o -q "$ZIP" -d "$HOME/Downloads"

# ── 4. commit + push ──
cd "$REPO_DIR"

CHANGED="$(git status --porcelain | wc -l | tr -d ' ')"
if [ "$CHANGED" = "0" ]; then
  say "冇任何改動 —— 你已經係最新版，唔使 push"
  exit 0
fi

say "有 $CHANGED 個檔案改動"
git status --short | head -20

# 安全掣：唔應該出現 .venv
if git status --porcelain | grep -q '\.venv/'; then
  die ".venv 出現喺改動清單 —— .gitignore 有問題，停手"
fi

git add -A
git commit -q -m "$MSG"
say "推送中…"
git push -q
say "完成 —— $(git rev-parse --short HEAD)"
