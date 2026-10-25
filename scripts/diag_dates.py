"""唯讀診斷：列出一段期間內的策略訊號、舊板塊訊號與處置公告，核對休市順延用。不寫入任何資料。

FROM／TO：日期範圍（預設今天前 10 天～後 14 天）
"""
import datetime as dt
import json
import os

from calendar_signals import supa

TPE = dt.timezone(dt.timedelta(hours=8))
today = dt.datetime.now(TPE).date()
f = os.environ.get("FROM") or (today - dt.timedelta(days=10)).isoformat()
t = os.environ.get("TO") or (today + dt.timedelta(days=14)).isoformat()


def show(title, path):
    print(f"\n===== {title}")
    try:
        rows = supa(path) or []
    except Exception as e:
        print("  讀取失敗", e)
        return
    for r in rows:
        print("  " + json.dumps(r, ensure_ascii=False))
    print(f"  共 {len(rows)} 列")


show("holidays", f"holidays?select=market_date,name&market_date=gte.{f}&market_date=lte.{t}&order=market_date")
show("strategy_actions", "strategy_actions?select=id,strategy_id,company_code,company_name,cycle,role,side,act_date,act_timing,pair_date,ignored,notified_at"
     f"&act_date=gte.{f}&act_date=lte.{t}&order=act_date,strategy_id,company_code")
show("disposals", f"disposals?select=company_code,company_name,start_date,end_date,ignored&end_date=gte.{f}&order=start_date")
show("signals（舊板塊）", f"signals?select=*&or=(entry_date.gte.{f},exit_date.gte.{f})&entry_date=lte.{t}&order=entry_date&limit=200")
show("v_tomorrow", "v_tomorrow?select=*")
