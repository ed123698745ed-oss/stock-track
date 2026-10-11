-- 第 2 階段：每日行情（事件型策略的資料來源）
-- 在 Supabase → SQL Editor 貼上整段執行一次即可；重複執行不會出錯。

create table if not exists market_days (
  d                date primary key,
  taiex            numeric,          -- 加權指數收盤
  taiex_pct        numeric,          -- 加權指數漲跌幅 %
  ld_twse          int,              -- 上市普通股收跌停家數（自行計算）
  ld_tpex          int,              -- 上櫃普通股收跌停家數（自行計算；上櫃抓取失敗為 null）
  ld_twse_official int,              -- 證交所公告「股票」跌停家數，對帳用
  lu_twse_official int,
  has_otc          boolean not null default false,
  has_margin       boolean not null default false,  -- 上市＋上櫃融資餘額都有抓到
  stocks           jsonb not null,   -- {代號: {n 名稱, m L/O, c 收盤, lu 收漲停, ld 收跌停,
                                     --        v 有效行情日, mb 融資今日餘額(張), mp 融資前日餘額(張)}}
  fetched_at       timestamptz not null default now()
);

alter table market_days enable row level security;
grant select, insert, update on market_days to service_role;

-- 推播去重：晚間第二次執行時，只推第一次還沒推過的新訊號
alter table strategy_actions add column if not exists notified_at timestamptz;
