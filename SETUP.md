# pmwire 設置指示

由零到第一篇出街，大約 **60–90 分鐘**。全部係網頁操作，唔使寫 code。

> ⚠️ **開始之前先讀 [`docs/監管紅線.md`](docs/監管紅線.md)。**
> 呢個項目最大嘅風險唔係技術，係監管。5 分鐘，值得。

---

## 步驟 0 — 推上 GitHub（5 分鐘）

`.github/workflows/` 已經喺 zip 入面整好，唔使再手動建 —— git 識處理隱藏資料夾。

喺你部 Mac 開 Terminal：

```bash
cd ~/Downloads/pmwire
git init
git add .
git commit -m "pmwire: initial"
git branch -M main
git remote add origin https://github.com/derrickuk00/pmwire.git
git push -u origin main
```

**推之前確認冇推錯嘢**（`.venv` 有幾百 MB）：

```bash
git status --short | head -30      # 應該見唔到任何 .venv/ 開頭嘅行
```

見到 `.venv/` 嘅話，即係 `.gitignore` 冇生效，停手話我知。

### 認證

GitHub 由 2021 年起唔收密碼，要用 Personal Access Token：

1. GitHub → 右上頭像 → Settings → Developer settings →
   Personal access tokens → **Tokens (classic)** → Generate new token
2. Note 隨便填，Expiration 揀 90 days
3. ⚠️ **兩個 scope 都要勾：`repo` 同 `workflow`**
   - 淨係勾 `repo` 會推到普通檔案，但一撞到 `.github/workflows/`
     就會被拒：*"refusing to allow a Personal Access Token to create or
     update workflow ... without `workflow` scope"*
   - Classic token 事後可以直接加 scope 而 token 值唔變 ——
     撳返個 token 名入去勾多個 `workflow`，撳 Update token 就得，
     唔使重新認證
4. Generate，抄低（**只顯示一次**）
5. `git push` 問 Username 就打你 GitHub 用戶名，問 Password 就貼**個 token**

或者裝 GitHub CLI，一次過搞掂（佢會自己攞齊 scope）：
`brew install gh && gh auth login`

### 如果 push 話 `denied to <另一個帳號名>`

macOS 鑰匙圈快取咗第二個 GitHub 帳號嘅憑證。清走再推：

```bash
printf "protocol=https\nhost=github.com\n\n" | git credential-osxkeychain erase
git remote set-url origin https://<你嘅用戶名>@github.com/<你嘅用戶名>/pmwire.git
git push -u origin main
```

## 步驟 1 — Telegram 機械人（5 分鐘）

1. Telegram 搵 **@BotFather** → `/newbot` → 改個名 → 佢會畀你一串
   **token**（樣子似 `8123456789:AAH...`）→ 抄低，呢個係 `TELEGRAM_BOT_TOKEN`
2. 搵 **@userinfobot** → 撳 Start → 佢會回覆你嘅 numeric ID
   → 抄低，呢個係 `TELEGRAM_CHAT_ID`
3. **重要：去你自己個 bot 度撳一次 `/start`。**
   Telegram 唔准 bot 主動私訊未同佢對話過嘅人，唔撳嘅話所有通知會失敗。

---

## 步驟 2 — X 開發者帳戶（20–30 分鐘，最麻煩嗰步）

1. 去 [developer.x.com](https://developer.x.com) 用你要發文嗰個帳戶登入
2. 申請開發者存取權（會問你用途，照實寫：
   *"Automated posting of factual market-data summaries to my own account. Read and write only to the authenticated account. No scraping, no bulk actions, no engagement automation."*）
3. 建立一個 App
4. **App settings → User authentication settings：**
   - App permissions 設為 **Read and write** ← **呢一步唔做，發文一定 403**
   - Type of App：**Web App / Automated App or Bot**
   - Callback URI 隨便填（例如 `https://example.com`），Website URL 填你 GitHub repo
5. **Keys and tokens** 分頁，攞 4 樣嘢：
   - API Key → `X_API_KEY`
   - API Key Secret → `X_API_SECRET`
   - Access Token → `X_ACCESS_TOKEN`
   - Access Token Secret → `X_ACCESS_SECRET`

   ⚠️ 如果你**改咗權限之後**先發現 token 係舊嘅，要**重新 regenerate Access Token**，
   舊 token 仲係 read-only。呢個係最常見嘅 403 原因。

6. **兩個必須確認嘅嘢：**
   - **X Premium**（英國 £4.67 首兩個月，之後 £9.34，揀 Monthly）——
     200 字英文約 1,100–1,300 字元，超出免費 280 字元上限。
     冇 Premium 就發唔到長文。詳見下面成本表。
   - **API credit** —— 2026年2月6日起免費層對新申請者關閉，改為按用量預付。
     入 Developer Console 睇下你有冇 credit。純文字每篇約 $0.015。

---

## 步驟 3 — LLM API key（5 分鐘）

**OpenAI 定 Claude？100 日全程成本差距最多約 US$22**，所以唔應該用價錢決定。
用你自己嘅真數據試一次：

```bash
OPENAI_API_KEY=sk-... ANTHROPIC_API_KEY=sk-ant-... \
  python tools/dryrun.py --compare
```

同一個市場，兩邊各生成一次，並排印出嚟，連埋守門同發現度結果。
睇兩樣：**要重寫幾多次先過到關**（重寫多 = 唔聽負面指令 = 貴又慢），
同埋**中文係咪真書面語**。揀完改 `config.yaml` 嘅 `content.llm_provider`。

- OpenAI：[platform.openai.com](https://platform.openai.com) → API keys
  → 建立 → 入 Billing 充值 → `OPENAI_API_KEY`
- Claude：[platform.claude.com](https://platform.claude.com) → API keys
  → 建立 → 入 Billing 充值 → `ANTHROPIC_API_KEY`

$10 已經夠用好耐（1,500 篇約 $2–24，睇型號）。

---

## 步驟 4 — 貼 Secrets 落 GitHub（5 分鐘）

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

逐個加呢 7 個：

| 名（要一模一樣） | 來源 |
|---|---|
| `OPENAI_API_KEY` | 步驟 3（用 OpenAI 嘅話）|
| `ANTHROPIC_API_KEY` | 步驟 3（用 Claude 嘅話）|
| `TELEGRAM_BOT_TOKEN` | 步驟 1 @BotFather |
| `TELEGRAM_CHAT_ID` | 步驟 1 @userinfobot |
| `X_API_KEY` | 步驟 2 |
| `X_API_SECRET` | 步驟 2 |
| `X_ACCESS_TOKEN` | 步驟 2 |
| `X_ACCESS_SECRET` | 步驟 2 |

兩個 LLM key **唔使兩個都貼** —— 睇你 `config.yaml` 入面
`content.llm_provider` 設咗邊個。想做 A/B 對比就兩個都貼。

（可選）**Variables** 分頁可以加 `LLM_PROVIDER`（`openai` 或 `claude`）
同 `LLM_MODEL`，會蓋過 config。唔加就跟 config。

---

## 步驟 5 — 自檢（5 分鐘）

Repo → **Actions** → 左邊揀 **doctor** → **Run workflow**

會做四件事：133 個離線測試、憑證檢查、真連 Polymarket API、DRY RUN 試起草一篇。

**全綠先好繼續。** 常見紅字：

| 症狀 | 原因 |
|---|---|
| `✗ X 憑證檢查失敗 HTTP 401` | 4 個 secret 有錯字，或者貼漏咗字尾 |
| `403 被拒` | App permissions 唔係 Read and write，或者改咗權限但冇 regenerate token |
| `Telegram 失敗：Forbidden: bot can't initiate conversation` | 冇去 bot 度撳 `/start`（步驟 1.3） |
| `✗ Polymarket 抓取失敗` | 罕見。Polymarket API 暫時 down，等陣再試 |
| `⚠ 過到篩選嘅候選：0 個` | **唔係錯誤。** 市場靜，冇嘢值得寫。市場一郁就會有 |

---

## 步驟 6 — 試跑（10 分鐘）

1. **Actions → draft → Run workflow**（`dry_run` 留 false）
   → 你部電話應該收到一個 Telegram 訊息，有三個掣
2. 撳 **✅ 批准**
3. **Actions → publish → Run workflow**，`dry_run` **剔 true**
   → 睇 log，會印出「本應發乜」但唔會真發
4. 睇落 OK 的話，再跑一次 publish，`dry_run` 留 false → **第一篇真出街**

---

## 步驟 7 — 開自動排程

Workflow 檔案入面已經寫好 cron，只要 repo 有活動就會自動行。

⚠️ **兩個 GitHub 排程嘅已知限制：**
- 排程 workflow 喺 repo **連續 60 日無活動**之後會自動停用。
  但呢個系統每次 run 都會 commit 狀態，所以正常運作下唔會停。
- GitHub 排程喺繁忙時段會延遲，有時遲 5–20 分鐘。唔影響呢個系統。

---

## ⚠️ 開波節奏 —— 呢個係最容易一次過搞砸帳號嘅位

X 有「冷啟動抑制」：新帳號嘅**頭約 100 篇**係一個評估窗口。
如果呢批貼文互動率太低，帳號會被長期限流，而且要極高互動先翻得到身。

**每日 15 篇 = 唔夠 7 日燒晒個窗口**，而且係喺你零追蹤者、
零互動歷史嘅最差時機燒。呢個係唯一一個「做錯咗好難補救」嘅決定。

| 週 | `max_posts_per_day` | 累計貼文 | 升級條件 |
|---|---|---|---|
| 1 | **3**（預設） | ~20 | 有回覆或轉發出現 |
| 2 | 5 | ~55 | 互動率冇跌 |
| 3 | 8 | ~110 | 互動率冇跌 |
| 4 | 12 | ~195 | 互動率冇跌 |
| 5+ | 15 | — | 到此為止 |

**每級升之前睇實一樣嘢：平均每篇嘅回覆數。** 跌就降返落一級，
唔好硬升。回覆係 X 權重最高嘅訊號 —— 呢個數字先係真指標，
唔係曝光數。

另外：**第一篇出街之前就要買 X Premium。** Premium 對新帳號嘅
起始信任分有實質提升，而且你本來就需要佢先發到長貼文。
唔好等試完先買 —— 頭幾篇冇 Premium 等於白燒。

> 📌 來源品質提醒：上述冷啟動嘅具體數字（-128 起始分、+17 門檻、
> 頭 100 篇、0.5% 互動率）嚟自第三方對 X 演算法嘅逆向分析部落格，
> **唔係 X 官方公佈**。但方向同我核實過嘅一手數據吻合：Buffer 分析
> 1,880 萬條貼文發現免費帳號單條曝光中位數 <100、互動率 0%，
> 而 Premium 帳號係 ~600。所以「慢啟動 + 早買 Premium」呢個結論
> 唔依賴嗰啲未證實嘅數字都成立。

---

## 成本（每月）

| 項目 | 費用 | 備註 |
|---|---|---|
| GitHub Actions（public repo） | **$0** | 無限分鐘 |
| Polymarket Gamma API | **$0** | 公開唯讀，唔使 key |
| Telegram Bot API | **$0** | 官方免費 |
| OpenAI（gpt-4o-mini） | **~$2–4** | 15 篇/日 × 30 日，每篇約 2k token |
| X Premium（英國，月費） | **£4.67 首兩個月，之後 £9.34** | 長貼文必需。**揀 Monthly 唔好揀 Annual** —— 年費 £98 要預繳，而你 Day 60／90 有砍掉條件，唔好用付咗嘅錢綁架自己判斷。全年只慳 £14，Day 90 過關先轉年費。**唔好揀 Premium+（£18.09）** —— 內容未驗證前買 4 倍分發係倒轉做 |
| X API 純文字發文 | **~$7–14** | 15 篇/日 × $0.015，加中文回覆就雙倍 |
| **合計** | **約 $17–26/月** | 遠低於 $100 上限 |

**100 日全程總成本：約 £45–65（X Premium £18.68 + OpenAI 同 X API 發文約 £25–45）。**

⚠️ 買 Premium 之前先確認頁面顯示英鎊。開住 VPN 嘅話會見到其他國家嘅價
（實測見過同一版出巴西雷亞爾同新台幣），用錯區訂閱係 ToS 風險 ——
唔值得用一個你即將起盤生意嘅帳號嚟賭。

⚠️ **絕對唔好喺貼文放連結** —— 含 URL 每篇 $0.20 vs 純文字 $0.015，
15 篇/日 × 100 日就係 **$300 vs $22.50**。守門模組已經硬性禁止，
但如果你手動改 config 記住呢件事。

---

## 之後點調

全部喺 `config.yaml`，改完 commit 就生效，唔使掂 code：

| 想點 | 改邊個 |
|---|---|
| 稿源唔夠 | `min_volume_24hr` 同 `min_liquidity` 調低 |
| 稿太多太雜 | `min_abs_move_24hr` 由 0.03 調高到 0.05 |
| 太多加密貨幣題材 | `max_per_category_24h` 由 3 調低到 2 |
| 同一市場出得太密 | `cooldown_days` 由 14 調高 |
| 唔想出中文 | `chinese_mode` 改做 `off` |
| 中文想同英文同一篇 | `chinese_mode` 改做 `main`（⚠️ 觸及會差，唔建議） |
| 覺得守門太嚴 | 由 `hard_reject` 搬個字去 `flag_for_review`。**三思。** |

---

## 檔案結構

```
config.yaml              全部設定喺呢度
requirements.txt
SETUP.md                 呢份文件
docs/
  監管紅線.md             ← 先讀呢份
  開帳號_首發.md          Bio、介紹貼、頭七日排程
  稿例全集_書面語.md      六種內容類型嘅完整稿例
  v2設計_15篇一日.md      內容供應量計算同分層架構
src/
  common.py              設定／狀態／日誌
  fetch.py               Polymarket Gamma API
  classify.py            主題／機械式市場／主體 判斷
  deadline.py            由題目文字 parse 截止日（唔信 metadata）
  picker.py              選題引擎（過濾、冷卻、四層配額、評分）
  draft.py               內容生成 + 重寫迴圈
  guard.py               合規守門 ← 最重要
  seo.py                 發現度檢查（實體、鈎子、hashtag 紀律）
  tracker.py             回訪追蹤（post_log.csv）
  telegram_gate.py       審批閘
  post_x.py              X 發布
  run.py                 主程式（draft / publish / digest / doctor）
tests/                   133 個測試，六個檔案
tools/dryrun.py          本機零憑證試跑
state/
  queue.json             待審／待發／已發
  posted.json            冷卻期同配額記錄
  post_log.csv           回訪追蹤（可直接用 Excel 開）
.github/workflows/       draft / publish / digest / doctor
```

---

## 附錄 A — 本機試跑（零憑證，2 分鐘）

貼 Secrets 之前，先喺你部 Mac 睇一次成件事點運作：

```bash
cd pmwire
pip install -r requirements.txt
python tools/dryrun.py
```

會做：真連 Polymarket、真跑選題引擎印出頭 10 名候選同評分明細、
用內建假稿行一次合規守門 + 發現度檢查、模擬發布並印出每日日誌。

**全程唔會連 X、唔會連 Telegram、唔使任何 API key、唔會發任何嘢。**

有 OpenAI key 想睇真生成：

```bash
OPENAI_API_KEY=sk-... python tools/dryrun.py --live-llm
```

⚠️ 呢個要喺**你部 Mac** 跑。Anthropic 雲端沙盒封鎖咗 Polymarket、X、
Telegram、OpenAI 全部——所以真連線只可以喺你部機或者 GitHub Actions 上發生。

## 附錄 B — 真發文順序

1. `python tools/dryrun.py` — 本機睇流程（唔使憑證）
2. 跟步驟 1–4 貼好 7 個 Secrets
3. Actions → **doctor** → Run workflow — 全綠先繼續
4. **手動出介紹貼**（`docs/開帳號_首發.md`），設為置頂。
   ⚠️ 第一篇唔好用自動流程 —— 佢係品牌宣言，值得你自己貼同睇住排版
5. Actions → **draft** → Run workflow — Telegram 收到待審
6. 撳 ✅ 批准
7. Actions → **publish** → `dry_run` 剔 **true** — 睇 log 確認內容
8. 再跑 publish，`dry_run` 留 false — **第一篇自動貼出街**
9. Actions → **digest** → Run workflow — 確認日誌通
10. 之後就自動行，你每日淨係要撳批准同睇日誌
