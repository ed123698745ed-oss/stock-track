-- 策略訊號（日曆型策略起步，之後的新策略也寫這張表）
-- 在 Supabase → SQL Editor 貼上整段執行一次即可；重複執行不會出錯。
-- 不動到既有的 signals / v_tomorrow，兩邊在網頁與推播端合併顯示。

create table if not exists strategy_actions (
  id            bigint generated always as identity primary key,
  strategy_id   text not null,               -- A01 / A09 / 009 ...（對照策略總表編號）
  strategy_name text not null,
  variant       text not null default '',    -- 十二月下旬 / 雄獅2731 ...
  company_code  text not null,               -- 個股代號；大盤用 TAIEX
  company_name  text not null,
  cycle         text not null,               -- 第幾輪（通常是年份）；日期改了也能原地更新
  role          text not null check (role in ('entry', 'exit')),
  side          text not null check (side in ('long', 'short')),
  act_date      date not null,
  act_timing    text check (act_timing in ('open', 'close')),  -- null = 原表未註明
  pair_date     date,                        -- 進場列放出場日、出場列放進場日
  pair_timing   text check (pair_timing in ('open', 'close')),
  detail        text,
  checked       boolean not null default false,
  ignored       boolean not null default false,
  note          text,
  updated_at    timestamptz not null default now(),
  unique (strategy_id, variant, company_code, cycle, role)
);

create index if not exists strategy_actions_date on strategy_actions (act_date);

alter table strategy_actions enable row level security;
drop policy if exists "auth read strategy_actions" on strategy_actions;
create policy "auth read strategy_actions" on strategy_actions
  for select to authenticated using (true);
drop policy if exists "auth update strategy_actions" on strategy_actions;
create policy "auth update strategy_actions" on strategy_actions
  for update to authenticated using (true) with check (true);

-- 下面的 view 以登入者身分執行（security_invoker），需要能讀 holidays。
-- 只新增一條「登入者可讀」的規則，不改動 holidays 既有設定。
drop policy if exists "auth read holidays" on holidays;
create policy "auth read holidays" on holidays
  for select to authenticated using (true);

-- 待辦：過期未勾（14 天內）＋今天＋下一個交易日。欄位比照 v_tomorrow，網頁直接合併。
create or replace view v_strategy_actions with (security_invoker = true) as
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
       -- 紅＝買方向（買進、回補），綠＝賣方向（賣出、放空）
       case when (a.role = 'entry') = (a.side = 'long') then 'buy' else 'sell' end as act_kind
from strategy_actions a, t, nxt
where not a.ignored
  and a.act_date <= nxt.next_day
  and (a.act_date >= t.today or (not a.checked and a.act_date >= t.today - 14));

-- 權限：Supabase 新表預設不開放給 API 角色，要明確授權。
-- service_role = GitHub Actions 寫入／讀取；authenticated = 登入後的網站。
grant select, insert, update on strategy_actions to service_role;
grant select on v_strategy_actions to service_role, authenticated;
grant select, update on strategy_actions to authenticated;
grant select on holidays to authenticated;
