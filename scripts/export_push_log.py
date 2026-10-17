"""匯出推播週報：讀 push_messages 原文，交 push_report.render 依執行日分章、去重。
DAYS=7（預設）。報告印在 ===BEGIN=== / ===END=== 之間；RAW=1 另印原文 JSON。
GitHub Actions 會把 report.md、raw.json 推到暫存分支 tmp-push-export，給連不到 Actions 日誌的環境取用。"""
import datetime as dt
import json
import os

from calendar_signals import supa
from push_report import TPE, render

now = dt.datetime.now(TPE)
today = now.date()
days = int(os.environ.get("DAYS") or 7)
start = today - dt.timedelta(days=days)
since = dt.datetime.combine(start, dt.time(0), TPE).astimezone(dt.timezone.utc).isoformat().replace("+", "%2B")
msgs = supa(f"push_messages?select=id,sent_at,mode,status,text&sent_at=gte.{since}&order=sent_at") or []
report = render(msgs, start, today, now)
open("report.md", "w", encoding="utf-8").write(report)
print("===BEGIN===")
print(report)
print("===END===")
if os.environ.get("RAW") == "1":
    json.dump({"messages": msgs}, open("raw.json", "w", encoding="utf-8"), ensure_ascii=False)
