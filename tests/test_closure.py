"""休市演練測試：模擬 2026-10-23 颱風臨時休市（接週末與 10/26 補假）。

不連網、不碰資料庫。PR 時由 .github/workflows/tests.yml 自動跑：python3 tests/test_closure.py
涵蓋：統一改期（持有型／錨定型）、A02 處置迄日順延、019 出場重算、週報主推播時間檢查、
推播執行日判斷、舊板塊週末摘要、臨時休市自動偵測。
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import calendar_signals as cs  # noqa: E402
from calendar_signals import Cal  # noqa: E402

D = dt.date.fromisoformat
BASE = [D(x) for x in ("2026-01-01", "2026-10-09", "2026-10-26", "2026-12-25")]
CLOSE = D("2026-10-23")
OLD = Cal(BASE)
NEW = Cal(BASE + [CLOSE])
TODAY = D("2026-10-25")
FAIL = []


def check(name, got, want):
    if got != want:
        FAIL.append(f"{name}：得到 {got}，應為 {want}")
    print(("✓ " if got == want else "✗ ") + name)


def pair(rid, sid, code, e, x, var="v"):
    return [dict(id=rid, strategy_id=sid, variant=var, company_code=code, company_name=code, cycle=e,
                 role="entry", act_date=e, pair_date=x),
            dict(id=rid + 1, strategy_id=sid, variant=var, company_code=code, company_name=code, cycle=e,
                 role="exit", act_date=x, pair_date=e)]


def t_reschedule():
    import reschedule
    rows = (pair(10, "A02", "4979", "2026-10-19", "2026-10-23")      # 處置 10/19～10/23 → 迄日順延 10/27
            + pair(20, "A02", "3167", "2026-10-20", "2026-10-27")    # 10/20～10/27 → 10/28
            + pair(30, "A02", "8358", "2026-10-23", "2026-10-30")    # 起日休市 → 10/27～11/02
            + pair(40, "A02", "4542", "2026-10-23", "2026-11-03")    # 7 日 → 10/27～11/04
            + pair(50, "019", "6668", "2026-10-19", "2026-10-23")    # 5 日 → 10/27
            + pair(60, "019", "1773", "2026-10-22", "2026-10-29")    # 5 日 → 10/30
            + pair(70, "004", "6793", "2026-10-12", "2026-10-23")    # 10 日 → 10/27
            + pair(80, "010", "3354", "2026-10-22", "2026-10-23")    # 隔日回補 → 10/27
            + pair(90, "A11", "6165", "2026-10-16", "2026-10-23")    # 錨定型：除息日落在休市才順延 → 10/27
            + pair(100, "A11", "9999", "2026-10-21", "2026-10-29")   # 錨定型、日期都不是休市 → 不動
            + pair(110, "004", "1111", "2026-11-05", "2026-11-18"))  # 區間不含休市 → 不動
    ch = {rid: p for rid, p, _ in reschedule.plan(rows, OLD, NEW, [CLOSE], TODAY)}
    check("A02 10/19 起處置賣出 → 10/27", ch.get(11, {}).get("act_date"), "2026-10-27")
    check("A02 大量 10/20 起處置賣出 → 10/28", ch.get(21, {}).get("act_date"), "2026-10-28")
    check("A02 金居 起日休市 → 10/27 買", ch.get(30, {}).get("act_date"), "2026-10-27")
    check("A02 金居 出場 → 11/02", ch.get(31, {}).get("act_date"), "2026-11-02")
    check("A02 科嶠 7 日 → 11/04", ch.get(41, {}).get("act_date"), "2026-11-04")
    check("019 中揚光 回補 → 10/27", ch.get(51, {}).get("act_date"), "2026-10-27")
    check("019 勝一 回補 → 10/30", ch.get(61, {}).get("act_date"), "2026-10-30")
    check("019 勝一 已進場（10/22）不動，只更新對應出場日", (ch.get(60, {}).get("act_date"), ch.get(60, {}).get("pair_date")), (None, "2026-10-30"))
    check("004 天力離岸 回補 → 10/27", ch.get(71, {}).get("act_date"), "2026-10-27")
    check("010 律勝 回補 → 10/27", ch.get(81, {}).get("act_date"), "2026-10-27")
    check("A11 錨定型 除息日在休市 → 10/27", ch.get(91, {}).get("act_date"), "2026-10-27")
    check("A11 錨定型 不在休市 → 不動", 101 in ch, False)
    check("區間不含休市 → 不動", 110 in ch or 111 in ch, False)


def t_disposal():
    import disposal_signals as dsg
    disposals = [dict(company_code="4979", company_name="華星光", start_date="2026-10-19", end_date="2026-10-23", ignored=False),
                 dict(company_code="3167", company_name="大量", start_date="2026-10-20", end_date="2026-10-27", ignored=False),
                 dict(company_code="4542", company_name="科嶠", start_date="2026-10-23", end_date="2026-11-03", ignored=False)]
    hol = [{"market_date": d.isoformat(), "name": "國定假日"} for d in BASE] + [{"market_date": "2026-10-23", "name": "薔琵颱風停止上班"}]
    written = []

    def supa(q, method="GET", payload=None, **k):
        if q.startswith("holidays"):
            return hol
        if q.startswith("disposals"):
            return disposals
        if method == "POST" and q.startswith("strategy_actions"):
            written.extend(payload)
        return []
    dsg.supa = supa
    real = dt.datetime

    class FD(real):
        @classmethod
        def now(cls, tz=None):
            return real(2026, 10, 25, 13, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    dsg.dt.datetime = FD
    try:
        dsg.main()
    finally:
        dsg.dt.datetime = real
    got = {(w["company_code"], w["role"]): w["act_date"] for w in written}
    check("A02 程式：華星光 賣出 10/27", got.get(("4979", "exit")), "2026-10-27")
    check("A02 程式：大量 賣出 10/28", got.get(("3167", "exit")), "2026-10-28")
    check("A02 程式：科嶠 買進 10/27", got.get(("4542", "entry")), "2026-10-27")
    check("A02 程式：科嶠 賣出 11/04", got.get(("4542", "exit")), "2026-11-04")
    check("A02 程式：沒有自動作廢", any(w.get("ignored") is True for w in written), False)


def t_export_alerts():
    """週報主推播檢查：休市不誤判，真的缺推要抓到。"""
    TPE = dt.timezone(dt.timedelta(hours=8))
    cal = NEW
    sent = [dt.datetime(2026, 10, 22, 19, 33, tzinfo=TPE), dt.datetime(2026, 10, 27, 19, 33, tzinfo=TPE)]

    def missing(start, end):
        out, d = [], start
        while d <= end:
            if cal.is_trading(d):
                tgt = cal.shift(d, 1)
                lo, hi = dt.datetime.combine(d, dt.time(19), TPE), dt.datetime.combine(tgt, dt.time(8, 30), TPE)
                if not any(lo <= t < hi for t in sent):
                    out.append(tgt)
            d += dt.timedelta(days=1)
        return out
    check("10/22 晚推過 → 10/27 不算缺（中間休市＋連假）", D("2026-10-27") in missing(D("2026-10-19"), D("2026-10-28")), False)
    check("10/28 晚沒推 → 10/29 算缺", D("2026-10-29") in missing(D("2026-10-19"), D("2026-10-28")), True)


def t_buyback_summary():
    import daily_push
    ev = {"summary": "目的 轉讓員工・預定 30 萬股・價格 3,700.00・期間 4,300.00",
          "raw": {"cols": ["5", "7856", "漢測", "115/10/22", "1", "1,544,990,288", "300,000", "3,700.00", "4,300.00", "115/10/23", "115/12/22", "N"]}}
    check("庫藏股摘要：價格區間與期間正確", daily_push.buyback_summary(ev),
          "目的 轉讓員工・預定 30 萬股・價格 3,700.00～4,300.00・期間 115/10/23～115/12/22")


def t_closure_watch():
    """臨時休市偵測：證交所標題解析"""
    import closure_watch as cw
    rows = [[1, "東擎科技股份有限公司股票自115年10月27日開始上市買賣", "115年10月22日"],
            [2, "臺灣證券交易所集中交易市場115年10月23日休市一天", "115年10月22日"],
            [3, "泰山企業股份有限公司(泰山，公司代號：1218)上市普通股自115年8月13日起暫停交易", "115年10月22日"],
            [4, "臺灣證券交易所集中交易市場115年7月10日休市一天", "115年07月09日"],
            [5, "臺灣證券交易所集中交易市場115年10月24日上午休市", "115年10月22日"]]
    auto, manual = cw.scan(rows, D("2026-10-22"), set(BASE))
    check("偵測 10/23 休市一天", [d for d, _ in auto], [D("2026-10-23")])
    check("半日休市只提醒、個股暫停交易不提醒", manual, ["臺灣證券交易所集中交易市場115年10月24日上午休市"])
    auto, _ = cw.scan(rows, D("2026-10-22"), set(BASE) | {CLOSE})
    check("已登錄的不重複處理", auto, [])
    auto, _ = cw.scan(rows, D("2026-10-25"), set(BASE))
    check("休市日已過不處理", auto, [])
    msg = cw.message(CLOSE, rows[1][1], ["004 達勝 7419：出場 2026-10-23→2026-10-27"], D("2026-10-22"))
    check("通知訊息日期格式", "・004 達勝 7419：出場 10/23→10/27" in msg and "10/23（五）" in msg, True)


def t_buyback_actions():
    """A03 庫藏股同步：signals → strategy_actions"""
    import buyback_actions as ba
    sig = {"id": 7673, "entry_date": "2026-10-27", "exit_date": "2026-11-09", "entry_timing": "open",
           "exit_timing": "close", "ignored": False,
           "events": {"company_code": "7856", "company_name": "漢測", "event_date": "2026-10-22"}}
    rows = ba.build([sig], lambda ev: "摘要")
    check("進出場兩列", [(r["role"], r["act_date"], r["act_timing"], r["pair_date"]) for r in rows],
          [("entry", "2026-10-27", "open", "2026-11-09"), ("exit", "2026-11-09", "close", "2026-10-27")])
    check("欄位一致（整批寫入）", len({tuple(sorted(r)) for r in rows}), 1)
    import reschedule
    check("A03 屬持有型", "A03" in reschedule.HOLD, True)
    import daily_push
    check("舊看板庫藏股買賣不再重複推", daily_push.old_trade({"block_code": "buyback", "src_table": "signals"}), True)


def t_pair_change():
    """已進場、出場日被順延 → 主推播要推更正（2026-10-29 勝一事故）"""
    import daily_push as dp
    today = D("2026-10-28")
    row = dict(id=3132, strategy_id="019", strategy_name="內部人申報轉讓", company_code="1773", company_name="勝一",
               role="entry", side="short", act_date="2026-10-22", act_timing="open", pair_date="2026-10-30",
               pair_timing="close", ignored=False, checked=False)
    sent = "sent:3132:1761046459:2026-10-22|open|2026-10-29"
    asked = []

    def fake(path, *a, **k):
        asked.append(path)
        if path.startswith("strategy_actions"):
            return [row]
        return [{"key": sent, "created_at": "2026-10-21T11:34:19+00:00"}]
    orig, dp.supa = dp.supa, fake
    try:
        out = dp.changes(today)
        check("查詢含 pair_date>今天", "pair_date.gt.2026-10-28" in asked[0], True)
        check("推一則更正", len(out), 1)
        check("內容寫回補 10/29→10/30", ("回補" in out[0][1] and "10/29" in out[0][1] and "10/30" in out[0][1]), True)
        row["pair_date"] = "2026-10-29"
        check("出場日沒變不推", dp.changes(today), [])
    finally:
        dp.supa = orig


if __name__ == "__main__":
    os.environ.setdefault("SUPABASE_URL", "http://x")
    os.environ.setdefault("SUPABASE_SERVICE_KEY", "x")
    for f in (t_reschedule, t_disposal, t_export_alerts, t_buyback_summary, t_closure_watch, t_buyback_actions, t_pair_change):
        print(f"\n— {f.__doc__.splitlines()[0] if f.__doc__ else f.__name__}")
        f()
    print()
    if FAIL:
        print("失敗：\n" + "\n".join(FAIL))
        sys.exit(1)
    print("全部通過")
