"""019 日報表要抓上市＋上櫃兩個市場；任一市場失敗整天算失敗（事故 25）。
不連網：python -m pytest tests/test_insider_markets.py -q
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
os.environ.setdefault("SUPABASE_URL", "http://x")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "x")
import insider  # noqa: E402

ROW = ("<tr><td></d><td>115/10/30</td><td>{code}</td><td>{name}</td><td>大股東</td><td>{who}</td>"
       "<td>一般交易(每日得轉讓股數限制)</td><td>100</td></tr>")


def fake(pages, calls):
    def _post(path, params):
        calls.append(params["report"])
        v = pages[params["report"]]
        if isinstance(v, Exception):
            raise v
        return "<table>" + v + "</table>"
    return _post


def test_both_markets_fetched():
    calls = []
    insider._post_ov = fake({"SY": ROW.format(code="3006", name="晶豪科", who="山一投資有限公司"),
                             "OY": ROW.format(code="4939", name="亞電", who="昇柏投資股份有限公司")}, calls)
    rs = insider.fetch_day(dt.date(2026, 10, 30))
    assert calls == ["SY", "OY"]
    assert {(r["code"], r["market"]) for r in rs} == {("3006", "上市"), ("4939", "上櫃")}
    assert all(insider.qualifies(r) for r in rs)


def test_one_market_failure_fails_day():
    calls = []
    insider._post_ov = fake({"SY": ROW.format(code="3006", name="晶豪科", who="山一投資有限公司"),
                             "OY": RuntimeError("blocked")}, calls)
    try:
        insider.fetch_day(dt.date(2026, 10, 30))
    except RuntimeError:
        return
    raise AssertionError("上櫃失敗應整天視為失敗")
