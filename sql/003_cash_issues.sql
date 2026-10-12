-- 現增公告解析結果（004 寫入、017 查詢每仟股認購股數）
-- 在 Supabase → SQL Editor 貼上整段執行一次即可；重複執行不會出錯。

create table if not exists cash_issues (
  company_code  text not null,
  cycle         text not null,      -- 認股基準日（沒有時用繳款截止日）
  company_name  text,
  ratio         numeric,            -- 每仟股認購股數
  ratio_src     text,               -- 公告／原股東認購股數÷已發行股數
  pay_start     date,
  pay_end       date,               -- 原股東繳款截止日（004 的 D）
  announced_on  date,
  updated_at    timestamptz not null default now(),
  primary key (company_code, cycle)
);
alter table cash_issues enable row level security;
grant select, insert, update on cash_issues to service_role;
