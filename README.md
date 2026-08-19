# pmwire

Polymarket 市場異動 → 200 字中英雙語純數據分析 → 人手審批 → X 自動發布。

**開始前先讀兩份嘢：**
1. [`docs/監管紅線.md`](docs/監管紅線.md) — 點解呢個系統唔會叫人落注，以及點解咁重要
2. [`SETUP.md`](SETUP.md) — 由零到第一篇出街，約 60–90 分鐘

## 一句話架構

每 90 分鐘抓 1,000 個活躍市場 → 用 `oneHourPriceChange` / `volume24hr` 揀出最值得寫嗰個
→ LLM 寫 200 字描述性分析 → 硬編碼合規守門（唔過就重寫）→ Telegram 送畀你撳掣
→ 你批准咗先發去 X（英文主帖 + 中文自回覆）。

**設計原則：自動生產，人手把關。你唔撳，就永遠唔會出街。**

## 成本
約 $17–26/月（GitHub Actions、Polymarket API、Telegram 全免費；
OpenAI ~$3、X Premium ~$8、X API 發文 ~$7–14）。

## 測試
```bash
pip install -r requirements.txt
python tests/test_offline.py        # 24 個離線測試，唔使任何憑證
python src/run.py doctor            # 全鏈自檢，需要憑證
```
