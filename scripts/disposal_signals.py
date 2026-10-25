"""A02 新制處置股（依 07_上線策略／A02 來源公式）

規則：處置第 1 天收盤買進 → 處置最後一天收盤賣出；只做 5 日、7 日處置
  依據：A02 表 T 欄「處置1買→末日賣」= 處置第 2～5 日（7 日處置為 2～7 日）報酬連乘，
  不含出關1；總表的 n=107、平均 +4.96% 就是引用 T 欄（A151 列標題寫「出關日收盤」是誤植）。
  回測只算 5 日、7 日處置，其他天數不產生訊號（沒有對應績效）。
資料：Supabase disposals（disposal.yml 每天 19:05／19:20 抓官方公告）

推播與網站用這裡寫的 strategy_actions；舊板塊（signals）的處置買賣列不再顯示。

同一檔前一次處置還沒結束、又被再處置：兩筆各自照規則列出，detail 標「與前次處置重疊」。

用法：python3 scripts/disposal_signals.py；DRY_RUN=1 只印不寫
"""
import datetime as dt
import os
from urllib.parse import quote

from calendar_signals import Cal, leg, supa

TPE = dt.timezone(dt.timedelta(hours=8))
SID, VAR = "A02", "處置首日→末日"
DAYS = (5, 7)  # 回測涵蓋的處置天數
OLD_VAR = "處置首日→出關日"
TEMP_WORDS = ("颱風", "臨時", "停止上班", "天災", "停市")  # holidays.name 含這些字＝臨時休市（add_holiday 登錄）  # PR31 誤用的版本（出關日賣）；改名沿用同一列，日期變了會推「更正」


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    today = dt.datetime.now(TPE).date()
    hols = supa("holidays?select=market_date,name&limit=5000")
    cal = Cal([dt.date.fromisoformat(r["market_date"]) for r in hols])
    # 臨時休市（颱風等）：證交所處置公告寫「開休市日變動則調整處置迄日」＝處置營業日數不變、迄日順延。
    # 公告日期是休市前公布的，休市日登錄後要把它加回來算原本的營業日數，起日落在休市日就順延到下一個交易日。
    temp = {dt.date.fromisoformat(r["market_date"]) for r in hols
            if any(k in (r.get("name") or "") for k in TEMP_WORDS) and dt.date.fromisoformat(r["market_date"]).weekday() < 5}
    if not dry:  # 舊版本的列改名成現行版本，保留 id 與推播紀錄，下面 upsert 會把出場日改回處置最後一天
        supa(f"strategy_actions?strategy_id=eq.{SID}&variant=eq.{quote(OLD_VAR)}", "PATCH", {"variant": VAR})
    skipped = []
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
            cycle = start.isoformat()  # 週期鍵沿用公告起日，順延後同一列改日期（推播會列「更正」）
            k = sum(1 for x in temp if start <= x <= end)
            if k and cal.known(start, end):
                n0 = len(cal.days(start, end)) + k  # 公告時的營業日數
                s2 = start if cal.is_trading(start) else cal.shift(start, 1)
                e2 = cal.shift(s2, n0 - 1) if n0 > 1 else s2
                print(f"  {code} {r['company_name']} 處置 {start}～{end} 遇臨時休市 {k} 天 → 順延為 {s2}～{e2}（{n0} 日）")
                start, end = s2, e2
            if not cal.known(start, end) or not cal.is_trading(start):
                print(f"  {code} {r['company_name']} {start}～{end}：休市日未公布或起日非交易日，略過")
                continue
            n = len(cal.days(start, end))
            if n not in DAYS:
                print(f"  {code} {r['company_name']} 處置 {start}～{end} 共 {n} 個交易日：回測只涵蓋 5／7 日，不產生")
                skipped.append((code, cycle))
                continue
            note = "與前次處置重疊（前次 %s 結束）｜" % f"{prev_exit:%m/%d}" if prev_exit and start <= prev_exit else ""
            legs = leg(SID, VAR, code, r["company_name"], cycle, "long", start, "close", end, "close", {})
            for x in legs:
                if k:  # 先前因休市少算天數被作廢的列，順延後恢復
                    x["ignored"] = False
                x["strategy_name"] = "新制處置股"
                x["detail"] = f"{note}處置 {start:%m/%d}～{end:%m/%d}（{n} 日）｜處置最後一天收盤賣"
            out += legs
            prev_exit = end
            print(f"  {code} {r['company_name']} 處置 {start}～{end}（{n} 日）→ 買 {start} 收盤、賣 {end} 收盤" + ("（重疊）" if note else ""))

    out = [r for r in out if r["act_date"] >= (today - dt.timedelta(days=14)).isoformat()]
    if dry:
        print(f"DRY_RUN：不寫入（{len(out)} 列）")
        return
    # PostgREST 批次寫入要求每列欄位相同：有 ignored（休市順延恢復）與沒有的分兩批
    for batch in ([r for r in out if "ignored" not in r], [r for r in out if "ignored" in r]):
        if batch:
            supa("strategy_actions?on_conflict=strategy_id,variant,company_code,cycle,role",
                 "POST", batch, prefer="resolution=merge-duplicates,return=minimal")
    # 之前已寫入（多半已推播）、這次卻算成不是 5／7 日的處置：不自動作廢，改發警告請 Ed 確認。
    # 2026-10-25 教訓：颱風休市後重數天數只剩 4 天，自動作廢讓大量、應廣被誤推「取消」。
    warns = []
    for code, cyc in skipped:
        had = supa(f"strategy_actions?select=company_name,act_date,role&strategy_id=eq.{SID}&company_code=eq.{code}"
                   f"&cycle=eq.{cyc}&ignored=is.false&act_date=gte.{today.isoformat()}") or []
        if had:
            nm = had[0].get("company_name") or code
            warns.append(f"A02 {nm} {code} 處置（{cyc} 起）天數與原訊號不符，未自動取消，請確認是否仍要依原日期執行")
    try:
        import json, pathlib
        out_dir = pathlib.Path(__file__).resolve().parent.parent / "out"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "warn_a02.json").write_text(json.dumps(warns, ensure_ascii=False), "utf-8")
    except Exception as e:
        print(f"⚠ A02 警告檔寫入失敗：{e}")
    for w in warns:
        print("  ⚠ " + w)
    print(f"已寫入 {len(out)} 列")


if __name__ == "__main__":
    main()
