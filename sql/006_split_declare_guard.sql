-- 分割追蹤：宣告拆股日只能往前改、不會被之後的公告往後蓋（2026-11-03 騰雲 6870 事故）。
-- 起因：資料庫在寫入「宣告拆股」類線索時，會把 split_watch.declare_date 改成該則公告日；
--       強生、仁新、寶雅每天重發的面額變更公告、騰雲的「變更登記完成」都把宣告日一路往後推。
--       程式端已改分類（scripts/split_classify.py），這段是資料庫端的保險，選用。
-- 在 Supabase → SQL Editor 貼上整段執行一次即可；重複執行不會出錯。
-- 要把宣告日改成更晚的日期時（極少見），先執行最後一行註解掉的 drop，改完再重跑本檔。

create or replace function split_watch_keep_declare() returns trigger
language plpgsql as $$
begin
  if old.declare_date is not null and new.declare_date is not null
     and new.declare_date > old.declare_date then
    new.declare_date := old.declare_date;   -- 已有宣告日就保留較早的那天
  end if;
  return new;
end $$;

drop trigger if exists split_watch_keep_declare on split_watch;
create trigger split_watch_keep_declare
  before update on split_watch
  for each row execute function split_watch_keep_declare();

-- drop trigger if exists split_watch_keep_declare on split_watch;
