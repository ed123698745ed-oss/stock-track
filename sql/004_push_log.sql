-- 推播紀錄（測試階段外部查核用）：每則 LINE 訊息一筆，訊息裡每個項目一筆。
-- 在 Supabase → SQL Editor 貼上整段執行一次即可；重複執行不會出錯。

create table if not exists push_messages (
  id        bigserial primary key,
  sent_at   timestamptz not null default now(),
  mode      text not null,            -- main 主推播／late 補推／intraday 盤中
  status    int,                      -- LINE 回應碼
  text      text not null
);

create table if not exists push_log (
  id          bigserial primary key,
  message_id  bigint references push_messages(id),
  sent_at     timestamptz not null default now(),
  push_date   date not null,          -- 台北日期（推播當天）
  mode        text not null,
  source      text not null,          -- 策略編號（004、A10…）或板塊（處置股、IPO…）或盯盤
  code        text,
  name        text,
  action      text,                   -- 買進／賣出／放空／回補／申購開始…
  act_date    date,                   -- 要執行的日期
  act_timing  text,                   -- open／close
  line        text                    -- 該項目在訊息裡的原文
);
create index if not exists push_log_date on push_log (push_date);
create index if not exists push_log_source on push_log (source, push_date);

alter table push_messages enable row level security;
alter table push_log enable row level security;
grant select, insert on push_messages, push_log to service_role;
grant usage, select on sequence push_messages_id_seq, push_log_id_seq to service_role;
grant select on push_messages, push_log to authenticated;
drop policy if exists push_read on push_log;
create policy push_read on push_log for select to authenticated using (true);
drop policy if exists push_msg_read on push_messages;
create policy push_msg_read on push_messages for select to authenticated using (true);
