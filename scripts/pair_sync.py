"""成對日期同步：同一筆交易的進場列與出場列，互相記的對方日期要一致。

以各列自己的執行日為準：進場列的 pair_date／pair_timing ＝ 出場列的 act_date／act_timing；
出場列的 pair_date／pair_timing ＝ 進場列的 act_date／act_timing。
為什麼：改期（休市順延、重算）常只改到一邊（事故 9：019 勝一；事故 17：004 進場列停在 10/23 颱風前的出場日），
進場列記的出場日沒跟著改，daily_push.changes() 用進場列快照比對就看不出變動，不會推【更正】。
同步後若進場已推過、出場日在今天以後，當晚主推播的 changes() 會推【更正】；已經過去的不會補推。

在「推播 LINE」前執行。DRY_RUN=1 只印不寫。只處理執行日在 120 天內的列；策略取消（ignored 且未 checked）的不動。
"""
import datetime as dt
import os

TPE = dt.timezone(dt.timedelta(hours=8))


def plan(rows):
    """rows：strategy_actions 列 → [(id, patch, 說明)]，只列需要改的。"""
    groups = {}
    for r in rows:
        if r.get("ignored") and not r.get("checked"):
            continue
        groups.setdefault((r["strategy_id"], r.get("variant"), r["company_code"], r.get("cycle")), {})[r["role"]] = r
    out = []
    for (sid, _, code, _), g in sorted(groups.items(), key=lambda x: str(x[0])):
        e, x = g.get("entry"), g.get("exit")
        if not (e and x):
            continue
        name = e.get("company_name") or code
        pe = {}
        if e.get("pair_date") != x["act_date"]:
            pe["pair_date"] = x["act_date"]
        if x.get("act_timing") and e.get("pair_timing") != x["act_timing"]:
            pe["pair_timing"] = x["act_timing"]
        if pe:
            out.append((e["id"], pe, f"{sid} {name} {code} 進場列 id {e['id']}：記出場 {e.get('pair_date')} {e.get('pair_timing')}"
                                     f" → {x['act_date']} {x.get('act_timing')}（出場列 id {x['id']}）"))
        px = {}
        if x.get("pair_date") != e["act_date"]:
            px["pair_date"] = e["act_date"]
        if e.get("act_timing") and x.get("pair_timing") != e["act_timing"]:
            px["pair_timing"] = e["act_timing"]
        if px:
            out.append((x["id"], px, f"{sid} {name} {code} 出場列 id {x['id']}：記進場 {x.get('pair_date')} {x.get('pair_timing')}"
                                     f" → {e['act_date']} {e.get('act_timing')}（進場列 id {e['id']}）"))
    return out


def main():
    from calendar_signals import supa
    today = dt.datetime.now(TPE).date()
    since = (today - dt.timedelta(days=120)).isoformat()
    rows = supa("strategy_actions?select=id,strategy_id,variant,company_code,company_name,cycle,role,act_date,act_timing,"
                f"pair_date,pair_timing,ignored,checked&act_date=gte.{since}&limit=10000") or []
    changes = plan(rows)
    dry = os.environ.get("DRY_RUN") == "1"
    for rid, patch, note in changes:
        print(("（DRY_RUN）" if dry else "") + note)
        if not dry:
            supa(f"strategy_actions?id=eq.{rid}", "PATCH", patch)
    print(f"成對日期同步：讀 {len(rows)} 列，{'應' if dry else '已'}更新 {len(changes)} 列")


if __name__ == "__main__":
    main()
