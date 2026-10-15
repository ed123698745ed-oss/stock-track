"""A06 分割（依可執行策略總表，2026-10-15 Elon 修正版）

規則：公告後首個可成交開盤買 → 新股上市第 5 日收盤賣（上市日 = 第 1 日）
  換股時程公告多在收盤後發布（寶雅 14:36、強生 15:01、沛爾 18:03），
  所以進場 = 公告換股日的下一個交易日開盤；不用公告當日開盤（那是偷看未來）。
資料：Supabase v_split 的 swap_date（公告換股日）、listing_date（新股上市日）
  上市：split.yml（證交所預告表）；上櫃／興櫃：split_mops.py（重大訊息）。
  新股上市日還沒公布時，先只提醒進場，出場日等公告後補上。

舊板塊（v_tomorrow）的分割買賣是「新股上市日收盤買」，和總表不同；
推播與網站改用這裡寫的 strategy_actions，舊的分割買賣列不再顯示。

用法：python3 scripts/split_signals.py；DRY_RUN=1 只印不寫
"""
import datetime as dt
import os

from calendar_signals import Cal, leg, supa

TPE = dt.timezone(dt.timedelta(hours=8))
SID, VAR = "A06", "公告後開盤→上市第5日"
HOLD = 5  # 上市日算第 1 日


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    today = dt.datetime.now(TPE).date()
    cal = Cal([dt.date.fromisoformat(r["market_date"]) for r in supa("holidays?select=market_date&limit=5000")])
    rows = supa("v_split?select=company_code,company_name,ratio,swap_date,suspend_date,listing_date") or []
    out = []
    for r in rows:
        if not r.get("swap_date"):
            continue
        swap = dt.date.fromisoformat(r["swap_date"])
        lst = dt.date.fromisoformat(r["listing_date"]) if r.get("listing_date") else None
        sus = dt.date.fromisoformat(r["suspend_date"]) if r.get("suspend_date") else None
        if lst and lst < today - dt.timedelta(days=30):
            continue  # 早就結束的不再重算
        if not cal.known(swap + dt.timedelta(days=10)):
            print(f"  {r['company_code']} {r['company_name']}：休市日未公布，略過")
            continue
        ent = cal.shift(swap, 1)
        if sus and ent >= sus:
            print(f"  {r['company_code']} {r['company_name']}：公告後下一交易日 {ent} 已停止買賣（{sus} 起），無法進場，略過")
            continue
        ext = cal.shift(lst, HOLD - 1) if lst and cal.known(lst + dt.timedelta(days=15)) else None
        legs = leg(SID, VAR, r["company_code"], r["company_name"], swap.isoformat(), "long",
                   ent, "open", ext, "close", {})
        ratio = f"一拆{r['ratio']}｜" if r.get("ratio") else ""
        for x in legs:
            x["strategy_name"] = "分割"
            x["detail"] = (f"{ratio}{swap:%m/%d} 公告換股（盤後）→ 隔日開盤進場｜"
                           + (f"新股上市 {lst:%m/%d}，第 {HOLD} 日收盤賣" if lst else "新股上市日待公告，出場日之後補上"))
        out += legs
        print(f"  {r['company_code']} {r['company_name']} 公告 {swap} → 買 {ent} 開盤、賣 {ext or '待定'} 收盤")

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
