-- A03 庫藏股：依可執行策略總表改成「宣布隔日開盤買、第 10 日收盤賣」
-- 原設定是隔日「收盤」買。持有天數（10，含進場日）與出場（收盤）不變。
-- 在 Supabase → SQL Editor 貼上執行一次；重複執行沒關係。

-- 之後新產生的庫藏股訊號
update strategies set entry_timing = 'open', updated_at = now() where code = 'buyback';

-- 還沒到進場日的既有訊號（已進場的不動）
update signals set entry_timing = 'open'
 where strategy_code = 'buyback' and entry_date > (now() at time zone 'Asia/Taipei')::date;

-- 檢查：應該都是 open
select code, entry_offset, entry_timing, holding_days, exit_timing from strategies where code = 'buyback';
