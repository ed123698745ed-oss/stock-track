"""A03 庫藏股：把舊看板 signals（strategy_code=buyback）同步成 strategy_actions。

為什麼：舊看板靠 v_tomorrow 決定「明天」，週末、連假會把「明天」算成下下個交易日
（2026-10-25 漢測 7856 10/27 開盤買進差點漏推）；休市改期也要另外重算。
同步到 strategy_actions 後，推播、網站、改期（reschedule.py）、週報應推檢查都走同一套。

日期仍以 signals 為準（fetch.yml 寫入、rpc recalc_signal_dates 依休市日重算）：董事會決議隔一個交易日
開盤買進、持有 10 個交易日收盤賣出。這裡只照抄，不另外推算。
signals 被忽略（ignored）→ 對應列也標 ignored（已推過的會推「取消」）。

DRY_RUN=1：只印不寫。
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calendar_signals import supa  # noqa: E402

TPE = dt.timezone(dt.timedelta(hours=8))


def build(sigs, summary):
    """sigs：signals 列（含 events）。回傳 strategy_actions 列（每檔進場＋出場兩列；缺日期的那列不寫）。"""
    rows = []
    for s in sigs:
        ev = s.get("events") or {}
        code, name = ev.get("company_code"), ev.get("company_name")
        if not code or not s.get("entry_date"):
            continue
        base = {"strategy_id": "A03", "strategy_name": "庫藏股", "variant": f"{name}{code}",
                "company_code": code, "company_name": name or code,
                "cycle": ev.get("event_date") or s["entry_date"], "side": "long",
                "detail": summary(ev), "ignored": bool(s.get("ignored"))}
        e, x = s["entry_date"], s.get("exit_date")
        rows.append(dict(base, role="entry", act_date=e, act_timing=s.get("entry_timing") or "open",
                         pair_date=x, pair_timing=(s.get("exit_timing") or "close") if x else None))
        if x:
            rows.append(dict(base, role="exit", act_date=x, act_timing=s.get("exit_timing") or "close",
                             pair_date=e, pair_timing=s.get("entry_timing") or "open"))
    return rows


def main():
    from daily_push import buyback_summary
    today = dt.datetime.now(TPE).date()
    since = (today - dt.timedelta(days=30)).isoformat()
    sigs = supa("signals?select=id,entry_date,exit_date,entry_timing,exit_timing,ignored,"
                "events(company_code,company_name,event_date,summary,raw)"
                f"&strategy_code=eq.buyback&or=(entry_date.gte.{since},exit_date.gte.{today.isoformat()})&limit=2000") or []
    rows = build(sigs, buyback_summary)
    # 進出場都已過去的不必再寫；還有一邊在今天以後就整組寫（改期需要成對）
    keep = {(r["variant"], r["cycle"]) for r in rows if r["act_date"] >= today.isoformat()}
    rows = [r for r in rows if (r["variant"], r["cycle"]) in keep]
    for r in rows:
        print(f"  {r['company_name']} {r['company_code']} {r['role']} {r['act_date']} {r['act_timing']}"
              + ("（已忽略）" if r["ignored"] else ""))
    if os.environ.get("DRY_RUN") == "1":
        print(f"DRY_RUN：不寫入（{len(rows)} 列）")
        return
    # 已過去的列（例：已買進、等出場）標 checked，網站不會列成「未處理」；
    # 今天以後的列不帶 checked，避免把網站上手動勾選的狀態蓋掉。兩種欄位不同，分開寫（PostgREST 整批欄位須一致）
    past = [dict(r, checked=True) for r in rows if r["act_date"] < today.isoformat()]
    future = [r for r in rows if r["act_date"] >= today.isoformat()]
    for batch in (past, future):
        for i in range(0, len(batch), 50):
            supa("strategy_actions?on_conflict=strategy_id,variant,company_code,cycle,role",
                 "POST", batch[i:i + 50], prefer="resolution=merge-duplicates,return=minimal")
    print(f"A03 庫藏股：已同步 {len(rows)} 列")


if __name__ == "__main__":
    main()
