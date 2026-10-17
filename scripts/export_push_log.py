"""匯出推播週報與依策略總表。

讀 push_messages 原文（週報、總表都以原文為準），並和 strategy_actions 對帳：
應在本期主推播提醒（執行日的前一個交易日 ∈ 本期，且推播時間已過）卻沒推出的項目列「⚠ 漏推」。
舊板塊（IPO、處置股等 v_tomorrow）沒有獨立的應推清單，只列已推項目。

DAYS=7（預設）。輸出：
  report.md   週報（依執行日）
  ledger.json 依策略排序的總表列（Drive《推播總表》追加用）
  raw.json    RAW=1 時另存原文
GitHub Actions 會把這些檔推到暫存分支 tmp-push-export，給連不到 Actions 日誌的環境取用。
"""
import datetime as dt
import json
import os

from calendar_signals import Cal, supa
from push_report import LEDGER_COLS, TPE, ledger, render

now = dt.datetime.now(TPE)
today = now.date()
days = int(os.environ.get("DAYS") or 7)
start = today - dt.timedelta(days=days)
since = dt.datetime.combine(start, dt.time(0), TPE).astimezone(dt.timezone.utc).isoformat().replace("+", "%2B")
msgs = supa(f"push_messages?select=id,sent_at,mode,status,text&sent_at=gte.{since}&order=sent_at") or []

# 應推清單：主推播在執行日前一個交易日晚上送出
cal = Cal([dt.date.fromisoformat(r["market_date"]) for r in supa("holidays?select=market_date&limit=5000")])
last_push_day = today if now.hour >= 20 else today - dt.timedelta(days=1)
# 推播入庫起日之前沒有紀錄可比對，不列漏推
first = supa("push_messages?select=sent_at&order=sent_at&limit=1") or []
log_start = dt.datetime.fromisoformat(first[0]["sent_at"].replace("Z", "+00:00")).astimezone(TPE).date() if first else today
check_from = max(start, log_start)
upper = cal.shift(last_push_day, 1)
acts = supa(f"strategy_actions?select=strategy_id,company_code,company_name,role,side,act_date,act_timing"
            f"&ignored=eq.false&act_date=gt.{start.isoformat()}&act_date=lte.{upper.isoformat()}") or []
ACT = {("entry", "long"): "買進", ("exit", "long"): "賣出", ("entry", "short"): "放空", ("exit", "short"): "回補"}
expected = []
for a in acts:
    d = dt.date.fromisoformat(a["act_date"])
    push_day = cal.shift(d, -1)
    if check_from <= push_day <= last_push_day:
        expected.append(dict(a, action=ACT[(a["role"], a["side"])]))

name = f"推播紀錄_{start:%Y%m%d}～{today:%Y%m%d}"
rows, missed = ledger(msgs, expected, name)
report = render(msgs, start, today, now, missed=missed,
                check_note=f"漏推對帳範圍：主推播日 {check_from:%m/%d}～{last_push_day:%m/%d}（推播入庫起日 {log_start:%Y-%m-%d}），"
                           f"策略訊號應推 {len(expected)} 項、漏推 {len(missed)} 項；IPO、舊板塊沒有應推清單，只列已推項目")
open("report.md", "w", encoding="utf-8").write(report)
json.dump({"name": name, "columns": LEDGER_COLS, "rows": [[r[c] for c in LEDGER_COLS] for r in rows],
           "missed": len(missed), "expected": len(expected), "check_from": check_from.isoformat()},
          open("ledger.json", "w", encoding="utf-8"), ensure_ascii=False)
print("===BEGIN===")
print(report)
print("===END===")
print(f"總表 {len(rows)} 列；應推 {len(expected)} 項，漏推 {len(missed)} 項")
if os.environ.get("RAW") == "1":
    json.dump({"messages": msgs, "expected": expected}, open("raw.json", "w", encoding="utf-8"), ensure_ascii=False)
