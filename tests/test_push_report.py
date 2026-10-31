"""推播週報（push_report）測試：010 盤中提醒時點、核准V/R 欄、跨週延續、應推對帳快照、盤中提醒網站連結。

不連網、不碰資料庫。python3 -m pytest tests/test_push_report.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import push_report as pr  # noqa: E402

D = dt.date.fromisoformat
SITE = "https://ed123698745ed-oss.github.io/stock-track/?d=2026-10-28"

INTRA = "\n".join([
    "⚡ 盤中提醒 10/28 13:05", "",
    "【010 開板放空】", "績效：總表未提供",
    "◆ 開板放空 1 檔（盤中未鎖漲停）",
    "　收盤仍沒漲停 → 收盤放空，下一交易日收盤回補（先確認券源）",
    "・測試 8299　連5｜現 480／停 500", "",
    "以收盤為準，晚上推播會記錄是否成立。", "",
    SITE])
MAIN = "\n".join([
    "交易提醒｜10/29（四）", "",
    "【004 測試策略】",
    "◆ 開盤買進 1 檔",
    "・甲公司 2330", "",
    "【IPO 新股】",
    "◆ 收盤買進 1 檔",
    "・乙公司 6999", "",
    "https://ed123698745ed-oss.github.io/stock-track/?d=2026-10-29"])
MSGS = [
    {"id": 1, "sent_at": "2026-10-28T05:05:00Z", "mode": "intraday", "status": 200, "text": INTRA},
    {"id": 2, "sent_at": "2026-10-28T11:30:00Z", "mode": "main", "status": 200, "text": MAIN},
]
EXPECTED = [
    {"strategy_id": "010", "company_code": "8299", "company_name": "測試", "action": "放空",
     "act_date": "2026-10-28", "act_timing": "close"},
    {"strategy_id": "004", "company_code": "2330", "company_name": "甲公司", "action": "買進",
     "act_date": "2026-10-29", "act_timing": "open"},
    {"strategy_id": "019", "company_code": "1101", "company_name": "丙公司", "action": "賣出",
     "act_date": "2026-10-29", "act_timing": "close"},
]


def prev_day(d):
    return d - dt.timedelta(days=1)


def by_code(rows):
    return {r["代號"]: r for r in rows}


def test_parse_ignores_site_url():
    items, fixes, watch = pr.parse(INTRA)
    assert [(i["strategy"], i["code"], i["action"], i["timing"]) for i in items] == [("010", "8299", "開板放空", "盤中")]
    assert not fixes and not watch
    assert [i["code"] for i in pr.parse(MAIN)[0]] == ["2330", "6999"]


def test_ledger_010_timing_and_approval():
    rows, missed = pr.ledger(MSGS, EXPECTED, "週報A")
    r = by_code(rows)
    assert r["8299"]["時點"] == pr.INTRA_010 == "盤中提醒／收盤執行（條件成立才放空）"
    assert r["8299"]["核准V/R"] == "V01/R04"
    assert r["2330"]["核准V/R"] == "V02/R02"
    assert r["1101"]["核准V/R"] == "V01/R03" and r["1101"]["狀態"] == "⚠ 漏推"
    assert r["6999"]["核准V/R"] == "待補／見策略總表"
    assert [m["代號"] for m in missed] == ["1101"]  # 010 盤中提醒以收盤放空對上應推
    assert pr.LEDGER_COLS[-1] == "核准V/R" and pr.LEDGER_COLS[:12][-1] == "週報"


def test_render_shows_010_wording():
    md = pr.render(MSGS, D("2026-10-24"), D("2026-10-31"), dt.datetime(2026, 10, 31, 9, tzinfo=pr.TPE))
    assert f"| 開板放空 | {pr.INTRA_010} |" in md
    assert "| 盤中 |" not in md


def test_missed_key_includes_act_date():
    exp = [dict(EXPECTED[1], act_date="2026-10-30")]  # 同標的同動作，但執行日不同 → 仍算漏推
    _, missed = pr.ledger(MSGS, exp, "週報A")
    assert [(m["代號"], m["執行日"]) for m in missed] == [("2330", "2026-10-30")]


def test_prior_carry_over():
    prior = {("004", "2330", "買進", "2026-10-29"):
             {"首次推播": "2026-10-23 20:00", "更正": "原 開盤 → 改為 收盤", "週報": "週報0"}}
    r = by_code(pr.ledger(MSGS, EXPECTED, "週報A", prior)[0])["2330"]
    assert r["首次推播"] == "2026-10-23 20:00"
    assert r["更正"] == "延續上週：原 開盤 → 改為 收盤"
    assert r["狀態"] == "已推播（延續上週再提醒）"
    assert r["週報"] == "週報0；週報A（延續上週＋本週再提醒，本週送出 2026-10-28 19:30）"
    # 沒有上週資料的列不受影響
    assert by_code(pr.ledger(MSGS, EXPECTED, "週報A", prior)[0])["6999"]["週報"] == "週報A"


def test_load_prior_json_and_csv(tmp_path):
    import json
    cols = ["策略", "代號", "名稱", "動作", "執行日", "首次推播", "更正", "週報"]
    rows = [["004", "2330", "甲", "買進", "2026-10-29", "2026-10-23 20:00", "", "週報0"],
            ["004", "2330", "甲", "買進", "2026-10-29", "2026-10-22 20:00", "x", "週報-1"],
            ["019", "1101", "丙", "賣出", "2026-10-29", "", "", "週報0"]]  # 漏推列不算
    pj = tmp_path / "prior.json"
    pj.write_text(json.dumps({"columns": cols, "rows": rows}, ensure_ascii=False), encoding="utf-8")
    pc = tmp_path / "prior.csv"
    pc.write_text("\n".join([",".join(cols)] + [",".join(r) for r in rows]), encoding="utf-8")
    for p in (pj, pc):
        got = pr.load_prior(str(p))
        assert list(got) == [("004", "2330", "買進", "2026-10-29")]
        assert got[("004", "2330", "買進", "2026-10-29")]["週報"] == "週報-1"


def test_expected_appendix():
    rows, _ = pr.ledger(MSGS, EXPECTED, "週報A")
    # 跨週延續：上週推的列（執行日早於本期）
    rows.append({"策略": "004", "代號": "2603", "名稱": "丁", "動作": "賣出", "執行日": "2026-10-24",
                 "時點": "收盤", "狀態": "已推播", "首次推播": "2026-10-23 20:00"})
    exp = [dict(e, action=e["action"]) for e in EXPECTED]
    md = pr.expected_appendix(exp, rows, D("2026-10-25"), prev_day, (D("2026-10-24"), D("2026-11-02")))
    assert md.startswith("## 附錄：應推對帳快照（strategy_actions）")
    assert "口徑" in md and "已推列數" in md and "應推數" in md
    assert ("| 004 | 2330 | 甲公司 | 買進 | 2026-10-29 | 開盤 | 10/28 19:00～10/29 08:30 "
            "| 004｜2330｜買進｜2026-10-29 | 2026-10-28 19:30 |") in md
    assert "| 010 | 8299 | 測試 | 放空 | 2026-10-28 | 收盤 | 10/27 19:00～10/28 08:30 | 010｜8299｜放空｜2026-10-28 | 2026-10-28 13:05 |" in md
    assert "| 019 | 1101 | 丙公司 | 賣出 | 2026-10-29 | 收盤 | 10/28 19:00～10/29 08:30 | 019｜1101｜賣出｜2026-10-29 | ⚠漏推 |" in md
    tail = md.split("未列入應推")[-1]
    assert "6999" in tail and "IPO・舊板塊無應推表" in tail
    assert "2603" in tail and "跨週延續" in tail
    assert "8299" not in tail  # 已對上收盤放空


def test_is_cancelled():
    assert not pr.is_cancelled({"ignored": False, "checked": False})
    assert not pr.is_cancelled({"ignored": False, "checked": True})
    assert not pr.is_cancelled({"ignored": True, "checked": True})  # 網站隱藏，非取消
    assert pr.is_cancelled({"ignored": True, "checked": False})  # 腳本取消
    assert pr.is_cancelled({"ignored": True, "checked": None})


def test_expected_appendix_hidden_note():
    rows, _ = pr.ledger(MSGS, EXPECTED, "週報A")
    exp = [dict(e, hidden=e["company_code"] == "1101") for e in EXPECTED]
    md = pr.expected_appendix(exp, rows, D("2026-10-25"), prev_day, (D("2026-10-24"), D("2026-11-02")))
    assert "| 019｜1101｜賣出｜2026-10-29 | ⚠漏推（網站隱藏，非取消） |" in md
    assert "| 004｜2330｜買進｜2026-10-29 | 2026-10-28 19:30 |" in md


def test_expected_appendix_intraday_unmatched():
    rows, _ = pr.ledger(MSGS, [], "週報A")
    md = pr.expected_appendix([], rows, D("2026-10-25"), prev_day, (D("2026-10-24"), D("2026-11-02")))
    assert "| 010 | 8299 |" in md and "盤中提醒（010 開板放空提醒，執行屬收盤放空，對帳鍵以收盤放空計）" in md


def test_intraday_message_has_site_link(monkeypatch):
    import intraday
    sent = []

    class FakeNow(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 10, 28, 13, 5, tzinfo=tz)

    def fake_supa(path, *a, **k):
        if path.startswith("holidays"):
            return []
        if path.startswith("market_days?select=d,stocks&order=d.desc&limit=1"):
            return [{"d": "2026-10-27", "stocks": {}}]
        if path.startswith("market_days"):
            return [{"d": "2026-10-27", "stocks": {"8299": {"m": "O"}}}]
        return []

    monkeypatch.setattr(intraday.dt, "datetime", FakeNow)
    monkeypatch.setattr(intraday, "supa", fake_supa)
    monkeypatch.setattr(intraday, "mis", lambda chs, **k: [])
    monkeypatch.setattr(intraday, "watch010", lambda days, cal: [{"code": "8299", "name": "測試", "streak": 5}])
    monkeypatch.setattr(intraday, "scan010", lambda *a: [("010:8299", "・測試 8299　連5｜現 480／停 500")])
    monkeypatch.setattr(intraday.perf, "summary", lambda *a: None)
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr("builtins.print", lambda *a, **k: sent.append(" ".join(map(str, a))))
    intraday.main()
    text = next(s for s in sent if s.startswith("⚡ 盤中提醒"))
    assert text.endswith("以收盤為準，晚上推播會記錄是否成立。\n\n" + SITE)
    items, _, _ = pr.parse(text)
    assert [(i["code"], i["timing"]) for i in items] == [("8299", "盤中")]
