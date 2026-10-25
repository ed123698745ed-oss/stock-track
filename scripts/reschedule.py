"""休市日變動（颱風等臨時休市）後，統一重算 strategy_actions 尚未完成的進出場日。

為什麼要統一：各策略程式各自算日期，有的會依新日曆重算（004、010），有的只掃最近幾天（019），
有的照公告起迄重數天數而誤判作廢（A02）。2026-10-23 颱風休市就因此漏推、誤推。
新增休市日時一律跑這支，讓所有訊號用同一套規則改期。

規則（每一組＝同策略、同變體、同代號、同週期的進場＋出場列）：
  持有型（HOLD）：出場日＝進場日起算的「原交易日數」不變，休市日不算 → 出場往後延。
      進場日若正好休市，順延到下一個交易日。A02 處置也屬此類（證交所：開休市日變動則調整處置迄日）。
  錨定型（其他）：只有正好落在新休市日的日期順延到下一個交易日（例：除權息日、法說日、上市日）。
  只處理進出場區間碰到「新增休市日」的組；其他不動。已過去而且是交易日的進場不動。

用法：python3 scripts/reschedule.py 2026-10-23 [更多日期…]   DRY_RUN=1 只印不寫
"""
import datetime as dt
import os
import sys

HOLD = {"004", "010", "014", "015", "019", "020", "A02", "A08"}


def next_trading(cal, d):
    return d if cal.is_trading(d) else cal.shift(d, 1)


def plan(rows, old_cal, new_cal, added, today):
    """rows：strategy_actions 列（含 id、strategy_id、variant、company_code、cycle、role、act_date、pair_date）。
    回傳 [(id, {"act_date":…, "pair_date":…}, 說明)]，只列有變動的。"""
    added = set(added)
    D = dt.date.fromisoformat
    groups = {}
    for r in rows:
        groups.setdefault((r["strategy_id"], r.get("variant"), r["company_code"], r["cycle"]), {})[r["role"]] = r
    out = []
    for (sid, _, code, _), g in groups.items():
        e, x = g.get("entry"), g.get("exit")
        E = D(e["act_date"]) if e else None
        X = D(x["act_date"]) if x else None
        lo, hi = (E or X), (X or E)
        if not any(lo <= c <= hi for c in added):
            continue
        if sid in HOLD and e and x:
            n = len(old_cal.days(E, X))  # 原本含進出場日的交易日數
            nE = E if (E < today and old_cal.is_trading(E) and E not in added) else next_trading(new_cal, E)
            nX = new_cal.shift(nE, n - 1) if n > 1 else nE
        else:
            nE = next_trading(new_cal, E) if E and E in added else E
            nX = next_trading(new_cal, X) if X and X in added else X
        name = (e or x).get("company_name") or code
        if (e and nE != E) or (x and nX != X):
            note = f"{sid} {name} {code}：" + (f"進場 {E}→{nE} " if e and nE != E else "") + (f"出場 {X}→{nX}" if x and nX != X else "")
            if e:  # 進場日沒變就只更新對應的出場日
                pe = ({"act_date": nE.isoformat()} if nE != E else {}) | ({"pair_date": nX.isoformat()} if x else {})
                out.append((e["id"], pe, note))
            if x:
                out.append((x["id"], {"act_date": nX.isoformat(), **({"pair_date": nE.isoformat()} if e else {})}, note))
    return out


def run(added, hol, today, dry=False):
    """hol：已含 added 的休市日清單。回傳 plan() 的變動；dry=True 只算不寫。"""
    from calendar_signals import Cal, supa
    old_cal = Cal([h for h in hol if h not in set(added)])
    new_cal = Cal(hol)  # 最後建立的 Cal 決定 KNOWN_YEARS
    since = (min(added) - dt.timedelta(days=60)).isoformat()
    rows = supa("strategy_actions?select=id,strategy_id,variant,company_code,company_name,cycle,role,act_date,pair_date"
                f"&ignored=is.false&act_date=gte.{since}&limit=5000") or []
    changes = plan(rows, old_cal, new_cal, added, today)
    if not dry:
        for rid, patch, _ in changes:
            supa(f"strategy_actions?id=eq.{rid}", "PATCH", patch)
    return changes


def main():
    from calendar_signals import supa
    added = [dt.date.fromisoformat(a) for a in sys.argv[1:]]
    if not added:
        raise SystemExit("用法：reschedule.py YYYY-MM-DD …")
    TPE = dt.timezone(dt.timedelta(hours=8))
    today = dt.datetime.now(TPE).date()
    hol = [dt.date.fromisoformat(r["market_date"]) for r in supa("holidays?select=market_date&limit=5000")]
    hol = sorted(set(hol) | set(added))
    changes = run(added, hol, today, dry=os.environ.get("DRY_RUN") == "1")
    for note in dict.fromkeys(n for _, _, n in changes):
        print("  " + note)
    print(f"新增休市日 {', '.join(map(str, added))}：改期 {len(changes)} 列" + ("（DRY_RUN，未寫入）" if os.environ.get("DRY_RUN") == "1" else ""))


if __name__ == "__main__":
    main()
