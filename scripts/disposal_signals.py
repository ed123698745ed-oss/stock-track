"""A02 新制處置股（依可執行策略總表）

規則（07_上線策略／A02 的「首日收盤→出關日收盤」，n=107）：
  處置第 1 天收盤買進 → 出關日收盤賣出
  出關日 = 處置最後一天之後的第 1 個交易日（A02 表的「出關1」）
資料：Supabase disposals（disposal.yml 每天 19:05／19:20 抓官方公告）

舊板塊（signals 表）的處置訊號是「處置最後一天收盤賣」，和總表不同；
推播與網站改用這裡寫的 strategy_actions，舊的處置買賣列不再顯示。

同一檔前一次處置還沒出關、又被再處置：兩筆各自照規則列出，detail 標「與前次處置重疊」。

用法：python3 scripts/disposal_signals.py；DRY_RUN=1 只印不寫
"""
import datetime as dt
import os

from calendar_signals import Cal, leg, supa

TPE = dt.timezone(dt.timedelta(hours=8))
SID, VAR = "A02", "處置首日→出關日"


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    today = dt.datetime.now(TPE).date()
    cal = Cal([dt.date.fromisoformat(r["market_date"]) for r in supa("holidays?select=market_date&limit=5000")])
    since = (today - dt.timedelta(days=30)).isoformat()
    rows = supa("disposals?select=company_code,company_name,start_date,end_date,ignored"
                f"&end_date=gte.{since}&order=start_date.asc&limit=1000") or []
    by_code = {}
    for r in rows:
        if not r.get("ignored"):
            by_code.setdefault(r["company_code"], []).append(r)

    out = []
    for code, ds in by_code.items():
        prev_exit = None
        for r in ds:
            start, end = dt.date.fromisoformat(r["start_date"]), dt.date.fromisoformat(r["end_date"])
            if not cal.known(start, end) or not cal.is_trading(start):
                print(f"  {code} {r['company_name']} {start}～{end}：休市日未公布或起日非交易日，略過")
                continue
            ext = cal.shift(end, 1) if cal.known(end + dt.timedelta(days=10)) else None
            legs = leg(SID, VAR, code, r["company_name"], start.isoformat(), "long", start, "close", ext, "close", {})
            note = "與前次處置重疊（前次 %s 出關）｜" % f"{prev_exit:%m/%d}" if prev_exit and start <= prev_exit else ""
            for x in legs:
                x["strategy_name"] = "新制處置股"
                x["detail"] = f"{note}處置 {start:%m/%d}～{end:%m/%d}｜出關日 = 處置結束後第 1 個交易日"
            out += legs
            prev_exit = ext or prev_exit
            print(f"  {code} {r['company_name']} 處置 {start}～{end} → 買 {start} 收盤、賣 {ext} 收盤" + ("（重疊）" if note else ""))

    out = [r for r in out if r["act_date"] >= (today - dt.timedelta(days=14)).isoformat()]
    if dry:
        print(f"DRY_RUN：不寫入（{len(out)} 列）")
        return
    if out:
        supa("strategy_actions?on_conflict=strategy_id,variant,company_code,cycle,role",
             "POST", out, prefer="resolution=merge-duplicates,return=minimal")
    print(f"已寫入 {len(out)} 列")


if __name__ == "__main__":
    main()
