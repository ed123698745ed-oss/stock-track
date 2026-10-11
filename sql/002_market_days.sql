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

-- v_strategy_actions 用 a.* 展開欄位，新增欄位後要重建才看得到 notified_at
drop view if exists v_strategy_actions;
create view v_strategy_actions with (security_invoker = true) as
with t as (
  select (now() at time zone 'Asia/Taipei')::date as today
), nxt as (
  select min(d::date) as next_day
  from t, generate_series(t.today + 1, t.today + 20, interval '1 day') d
  where extract(isodow from d) < 6
    and not exists (select 1 from holidays h where h.market_date = d::date)
)
select a.*,
       case when a.act_date < t.today then '未處理'
            when a.act_date = t.today then '今天'
            else '明天' end as due_label,
       case when a.role = 'entry' and a.side = 'long'  then '買進'
            when a.role = 'exit'  and a.side = 'long'  then '賣出'
            when a.role = 'entry' and a.side = 'short' then '放空'
            else '回補' end as action,
       case when (a.role = 'entry') = (a.side = 'long') then 'buy' else 'sell' end as act_kind
from strategy_actions a, t, nxt
where not a.ignored
  and a.act_date <= nxt.next_day
  and (a.act_date >= t.today or (not a.checked and a.act_date >= t.today - 14));
grant select on v_strategy_actions to service_role, authenticated;

-- 盤中提醒去重：同一天同一件事只推一次
create table if not exists intraday_alerts (
  d          date not null,
  key        text not null,
  created_at timestamptz not null default now(),
  primary key (d, key)
);
alter table intraday_alerts enable row level security;
grant select, insert on intraday_alerts to service_role;
