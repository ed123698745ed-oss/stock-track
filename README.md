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
