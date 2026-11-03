"""推播週報程式比對（scripts/push_compare.py）：植入錯誤都要抓到、正常資料 0 筆差異。

不連網、不碰資料庫、不送 LINE：python -m pytest tests/test_push_compare.py -q
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
os.environ.setdefault("SUPABASE_URL", "http://x")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "x")
import push_compare as pc  # noqa: E402
from calendar_signals import Cal  # noqa: E402
from push_report import ledger, parse, LEDGER_COLS  # noqa: E402

# 2026 年 10～11 月：10/23 颱風、10/26 光復節補假
CAL = Cal([dt.date(2026, 1, 1), dt.date(2026, 10, 23), dt.date(2026, 10, 26), dt.date(2027, 1, 1)])
NOW = dt.datetime(2026, 11, 7, 9, 52, tzinfo=pc.TPE)
PERF = {"004": "V02/R02", "019": "V01/R03", "010": "V01/R04"}


def ts(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=pc.TPE).isoformat()


def row(i, sid, code, role, side, act, timing, pair, ptiming, variant="", cycle="2026", ignored=False, checked=False):
    return {"id": i, "strategy_id": sid, "variant": variant, "company_code": code, "company_name": f"股{code}",
            "cycle": cycle, "role": role, "side": side, "act_date": act, "act_timing": timing, "pair_date": pair,
            "pair_timing": ptiming, "detail": "", "ignored": ignored, "checked": checked, "notified_at": None}


def plog(mid, sid, code, action, act, timing, line=""):
    return {"message_id": mid, "source": sid, "code": code, "name": f"股{code}", "action": action,
            "act_date": act, "act_timing": timing, "line": line or f"{sid} {code}"}


def exp(sid, code, action, act, timing, role, side):
    return {"strategy_id": sid, "company_code": code, "company_name": f"股{code}", "action": action,
            "act_date": act, "act_timing": timing, "role": role, "side": side,
            "push_day": CAL.shift(dt.date.fromisoformat(act), -1).isoformat(), "hidden": False}


def base():
    """正常的一週：11/2 主推播 004 放空（11/3 開盤，出場 11/16）＋019 回補（11/3 收盤）；11/3 盤中 010 開板。"""
    actions = [
        row(1, "004", "1101", "entry", "short", "2026-11-03", "open", "2026-11-16", "close"),
        row(2, "004", "1101", "exit", "short", "2026-11-16", "close", "2026-11-03", "open"),
        row(3, "019", "2201", "entry", "short", "2026-10-28", "open", "2026-11-03", "close"),
        row(4, "019", "2201", "exit", "short", "2026-11-03", "close", "2026-10-28", "open"),
        row(5, "010", "3301", "entry", "short", "2026-11-03", "close", "2026-11-04", "close"),
        row(6, "010", "3301", "exit", "short", "2026-11-04", "close", "2026-11-03", "close"),
        row(7, "A09", "TAIEX", "entry", "long", "2026-11-03", "close", "2026-11-06", "close", variant="不存在"),
    ][:6]
    msgs = [{"id": 10, "sent_at": ts("2026-11-02T19:33:00"), "mode": "main", "status": 200,
             "text": "交易提醒｜11/3(二)\n【004】x\n· 開盤放空：股1101 1101"},
            {"id": 11, "sent_at": ts("2026-11-03T13:08:00"), "mode": "intraday", "status": 200,
             "text": "⚡ 盤中提醒 11/03 13:05"}]
    logs = [plog(10, "004", "1101", "放空", "2026-11-03", "open"),
            plog(10, "019", "2201", "回補", "2026-11-03", "close"),
            plog(10, "010盯盤", "3301", "盯盤", "2026-11-03", None),
            plog(11, "010", "3301", "盤中提醒", "2026-11-03", "close", "・股3301 3301　連5｜現 30.9／停 37.25")]
    expected = [exp("004", "1101", "放空", "2026-11-03", "open", "entry", "short"),
                exp("019", "2201", "回補", "2026-11-03", "close", "exit", "short"),
                exp("010", "3301", "放空", "2026-11-03", "close", "entry", "short")]
    return msgs, logs, actions, expected


def run(msgs, logs, actions, expected, **kw):
    return pc.compare(msgs, logs, actions, expected, CAL, NOW, parse, perf_vr=PERF, **kw)


def kinds(res):
    return sorted((d["類型"], d["策略"], d["股票"].split(" ")[-1]) for d in res["diffs"])


def test_clean_week_zero_diffs():
    res = run(*base())
    assert res["diffs"] == [], res["diffs"]
    assert res["n_trade"] == 3 and res["n_expected"] == 3
    md = pc.render_section(res)
    assert "三項比對 0 筆差異" in md and "推播項目 4 項" in md and "應推項目 3 項" in md


def test_off_table_stock_and_strategy():
    msgs, logs, actions, expected = base()
    logs.append(plog(10, "009", "2603", "放空", "2026-11-03", "open"))   # 009 名單外標的
    logs.append(plog(10, "018", "2330", "買進", "2026-11-03", "open"))   # 總表沒有的策略
    logs.append(plog(10, "022", "2330", "買進", "2026-11-03", "open"))   # 總表有、未交付 Emit
    got = kinds(run(msgs, logs, actions, expected))
    assert ("表外推播", "009", "2603") in got and ("表外推播", "018", "2330") in got and ("表外推播", "022", "2330") in got


def test_stopped_strategy_is_wrong_push():
    msgs, logs, actions, expected = base()
    logs.append(plog(10, "A07", "TAIEX", "買進", "2026-11-03", "open"))
    assert ("誤推", "A07", "TAIEX") in kinds(run(msgs, logs, actions, expected))


def test_date_off_by_one_trading_day():
    msgs, logs, actions, expected = base()
    logs[0]["act_date"] = "2026-11-04"  # 應為 11/3
    res = run(msgs, logs, actions, expected)
    d = [x for x in res["diffs"] if x["類型"] == "時點不符" and x["策略"] == "004"]
    assert d and "11/3(二)" in d[0]["應為何值"]
    assert ("漏推", "004", "1101") in kinds(res)  # 11/3 那筆應推的也沒推到


def test_open_close_swapped():
    msgs, logs, actions, expected = base()
    logs[0]["act_timing"] = "close"  # 004 應開盤
    res = run(msgs, logs, actions, expected)
    d = [x for x in res["diffs"] if x["類型"] == "時點不符"]
    assert d and d[0]["應為何值"].startswith("開盤")


def test_rule_dates_checked_against_calendar():
    msgs, logs, actions, expected = base()
    actions[0]["pair_date"] = actions[1]["act_date"] = "2026-11-13"  # 持有 10 日應出場 11/16，資料列錯一天
    res = run(msgs, logs, actions, expected)
    assert any(x["類型"] == "時點不符" and "11/16(一)" in x["應為何值"] for x in res["diffs"])


def test_missed_push():
    msgs, logs, actions, expected = base()
    del logs[1]  # 019 回補沒推
    assert ("漏推", "019", "2201") in kinds(run(msgs, logs, actions, expected))


def test_hidden_row_still_expected():
    """網站隱藏（ignored+checked）不是取消，仍是應推；有推就不是漏推（F03／N04 口徑）。"""
    msgs, logs, actions, expected = base()
    actions[3].update(ignored=True, checked=True)
    expected[1]["hidden"] = True
    assert run(msgs, logs, actions, expected)["diffs"] == []
    del logs[1]
    d = [x for x in run(msgs, logs, actions, expected)["diffs"] if x["類型"] == "漏推"]
    assert d and "網站隱藏" in d[0]["證據"]


def test_duplicate_send_one_row_per_message():
    msgs, logs, actions, expected = base()
    msgs.append(dict(msgs[0], id=12, sent_at=ts("2026-11-02T21:07:00"), mode="late"))
    logs += [dict(x, message_id=12) for x in logs if x["message_id"] == 10]
    res = run(msgs, logs, actions, expected)
    dup = [x for x in res["diffs"] if x["類型"] == "誤推"]
    assert len(dup) == 1 and "訊息 12" in dup[0]["證據"] and "2 項" not in dup[0]["股票"]


def test_noon_resend_is_timing_and_duplicate():
    msgs, logs, actions, expected = base()
    msgs.append(dict(msgs[0], id=13, sent_at=ts("2026-10-31T12:12:00")))  # 週六中午重送：時間不符
    logs += [dict(x, message_id=13) for x in logs if x["message_id"] == 10]
    got = {x["類型"] for x in run(msgs, logs, actions, expected)["diffs"]}
    assert got == {"時點不符", "誤推"}


def test_after_midnight_main_push():
    msgs, logs, actions, expected = base()
    msgs[0]["sent_at"] = ts("2026-11-03T00:03:00")
    assert any(x["類型"] == "時點不符" and "00:03" in x["證據"] for x in run(msgs, logs, actions, expected)["diffs"])


def test_010_intraday_unknown_quote_is_wrong_push():
    """事故 11：報價暫缺仍推開板放空 → 誤推；有「現＜停」且收盤沒成立 → 提醒正確，不列差異。"""
    msgs, logs, actions, expected = base()
    logs.append(plog(11, "010", "4401", "盤中提醒", "2026-11-03", "close", "・股4401 4401　連4｜報價暫缺，請自行看盤"))
    logs.append(plog(11, "010", "5501", "盤中提醒", "2026-11-03", "close", "・股5501 5501　連4｜現 50／停 55"))
    res = run(msgs, logs, actions, expected)
    assert [x["股票"] for x in res["diffs"]] == ["股4401 4401"]
    assert any("010 盤中提醒" in k for k in res["na"])


def test_pair_date_out_of_sync_without_correction():
    """事故 9：出場改期，進場列仍記舊出場日、又沒推【更正】→ 時點不符；有更正就正常。"""
    msgs, logs, actions, expected = base()
    actions[2]["pair_date"] = "2026-11-02"  # 進場列沒同步
    res = run(msgs, logs, actions, expected)
    assert any("進場列 id 3 記出場 11/2(一)" in x["證據"] for x in res["diffs"])
    fix = {"msg_id": 9, "sent": dt.datetime(2026, 10, 24, 19, 33, tzinfo=pc.TPE), "status": 200, "mode": "main",
           "sid": "019", "code": "2201", "action": "更正", "act_date": "2026-10-28",
           "line": "【更正】019 x｜股2201 2201 回補\n　原 11/2(一) 收盤 → 改為 11/3(二) 收盤"}
    assert run(msgs, logs, actions, expected, prior_fixes=[fix])["diffs"] == []


def test_cancelled_row_needs_cancel_notice():
    msgs, logs, actions, expected = base()
    actions[0].update(ignored=True, checked=False)
    expected.pop(0)
    assert ("誤推", "004", "1101") in kinds(run(msgs, logs, actions, expected))


def test_vr_mismatch_flagged():
    msgs, logs, actions, expected = base()
    res = pc.compare(msgs, logs, actions, expected, CAL, NOW, parse, perf_vr=dict(PERF, **{"004": "V02/R01"}))
    assert any(x["類型"] == "表外推播" and "推播程式 V02/R01" in x["證據"] for x in res["diffs"])


def test_block_notice_and_watch_not_applicable():
    msgs, logs, actions, expected = base()
    logs.append(plog(10, "處置股", "7856", "注意", "2026-11-03", None))
    res = run(msgs, logs, actions, expected)
    assert res["diffs"] == [] and sum(res["na"].values()) == 2


def test_falls_back_to_text_when_push_log_missing():
    msgs, logs, actions, expected = base()
    logs = [x for x in logs if x["message_id"] != 10]
    msgs[0]["text"] = "交易提醒｜11/3(二)\n\n【004】x｜持有10日收盤回補\n· 開盤放空：股1101 1101\n"
    res = run(msgs, logs, actions, expected)
    assert res["notes"] and "改以原文解析" in res["notes"][0]


def test_ledger_column_and_result():
    msgs, logs, actions, expected = base()
    msgs[0]["text"] = "交易提醒｜11/3(二)\n\n【004】x\n· 開盤放空：股1101 1101\n"
    logs[0]["act_timing"] = "close"
    res = run(msgs, logs, actions, expected)
    rows, _ = ledger(msgs, expected, "週報", compare=res)
    r = {(x["策略"], x["代號"]): x for x in rows}
    assert LEDGER_COLS[-1] == "比對結果"
    assert r[("004", "1101")]["比對結果"] == "時點不符"
    assert r[("019", "2201")]["比對結果"] == "漏推"  # 原文沒有 019 → 總表列為漏推
    assert pc.result_for(res, "IPO", "1234", "申購", "2026-11-03") == "不適用"
