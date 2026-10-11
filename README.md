# stock-track

交易提醒：每天告訴你下一個交易日要對哪些股票進出場、是哪個策略觸發的。

- 網站／App：https://ed123698745ed-oss.github.io/stock-track/
- 資料：Supabase；抓取與推播：GitHub Actions（`.github/workflows/`）

## 安裝成 App（手機、電腦都可以）

- **iPhone**：用 Safari 開網站 → 分享 → 「加入主畫面」
- **Android**：用 Chrome 開網站 → 右上選單 → 「安裝應用程式」
- **電腦**：用 Chrome／Edge 開網站 → 網址列右側的「安裝」圖示

裝好後是獨立視窗、有自己的圖示。App 的儲存空間和瀏覽器分開，第一次開要重新貼一次 key、登入一次。

## 每日推播（`每日訊號推播` workflow）

週一到週五台北 21:07：先更新日曆型策略訊號，再把「明天要做的事」推到 LINE。

第一次設定：

1. Supabase → SQL Editor，貼上 `sql/001_strategy_actions.sql` 執行一次（重複執行沒關係）。
2. 這個 repo 的 Settings → Secrets and variables → Actions，新增
   `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_USER_ID`（和 panhou-zhushou 用的同一組）。
3. Actions → 每日訊號推播 → Run workflow，`dry_run` 填 `1` 先看訊息內容，沒問題再填 `0` 實際推一次。

## 日曆型策略（`scripts/calendar_signals.py`）

只靠交易日曆就能算出日期的策略：A01 開紅盤、A09 上中下旬（7 組）、A10 航空股（2 組）、
009 產業旺季（5 檔）、021 台積電法說會前後。

- 交易日 = 平日且不在 `holidays` 表；某年的休市日還沒公布，那一年的訊號就不產生。
- 021 的法說日要手動填在 `config/manual_events.json`。
- A10：長榮航冬季＝開盤買、開盤賣；華航夏季＝開盤買、收盤賣（依 Ed 提供的最佳組合）。

## 事件型策略（第 2 階段，`scripts/event_signals.py`）

資料來源：`scripts/market.py` 每晚抓上市＋上櫃普通股的收盤、漲跌停、融資餘額，存進 `market_days`（一天一列）。

| 策略 | 觸發 | 進出場 |
|---|---|---|
| A08 大盤-5% | 加權指數單日 ≤ −5% | 當日收盤買進 → 第 5 個交易日收盤賣出 |
| 014 跌停群聚 | 上市＋上櫃普通股收跌停 ≥ 100 家，且不在前一事件起算 40 交易日內 | 當日收盤買進 → 持有 5 日／15 日收盤賣出 |
| 010 連續漲停開板 | 連續 ≥ 4 天收漲停後，第一天沒收漲停 | 當日收盤放空 → 下一交易日收盤回補 |
| 020 融資大減（E-Test 候選） | 二次群聚日（定義見程式註解，依策略包 V01/R04） | 下一交易日開盤等權買進 → 群聚日後第 20 個交易日收盤賣出 |

A08、014、010 是「當天收盤」進場，晚上推播來不及，靠 **盤中提醒**（`scripts/intraday.py`，13:05、13:15）：
接近門檻才推，沒事不推；同一天同一件事只推一次。最後是否成立以收盤為準，晚上會記錄並產生出場提醒。

第一次設定：

1. Supabase SQL Editor 執行 `sql/002_market_days.sql`。
2. Actions → **回補歷史行情** → Run workflow（預設 160 個交易日，約 30～40 分鐘；020 需要 120 日以上的融資歷史）。
3. cron-job.org 新增兩個排程，在台北 **13:05、13:15**（週一到週五）呼叫「盤中提醒」的 workflow_dispatch，
   做法和處置股、庫藏股一樣。GitHub 自己的排程常延遲，只當備援；超過 13:27 程式會自動略過。

晚上 22:37 會再跑一次：融資餘額公布較晚，若重抓後出現新訊號（例如 020）才補推。
