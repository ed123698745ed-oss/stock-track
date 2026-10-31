"""A11 除權息預告表抓取韌性、010 盤中鎖漲停判斷。

不連網、不碰資料庫（HTTP 與 Supabase 全部假造、sleep 不真的等）：
  python -m pytest tests/test_fetch_resilience.py -q
"""
import datetime as dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
os.environ.setdefault("SUPABASE_URL", "http://x")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "x")
import cash_issue  # noqa: E402
import daily_push as dp  # noqa: E402
import exright  # noqa: E402
import intraday  # noqa: E402

TODAY = dt.date(2026, 10, 30)
TWSE = [{"Code": "2330", "Name": "台積電", "Date": "1151110", "CashDividend": "5",
         "StockDividendRatio": "", "SubscriptionRatio": "", "SubscriptionPricePerShare": ""}]
TPEX = [{"SecuritiesCompanyCode": "6488", "CompanyName": "環球晶", "ExRrightsExDividendDate": "1151112",
         "CashDividend": "8", "StockDividendRatio": "0.1", "SubscriptionRatioToNewSharesIssued": "",
         "SubscriptionPricePerShare": ""}]


class Resp:
    def __init__(self, body, ctype="application/json", status=200):
        self.body, self.status = body.encode(), status
        self.headers = {"Content-Type": ctype}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(cash_issue.time, "sleep", calls.append)
    return calls


def route(monkeypatch, table):
    """URL 片段 → 依序回傳的 Resp 清單（最後一個重複使用）。"""
    hits = {k: 0 for k in table}

    def fake_open(req, timeout=None):
        for k, seq in table.items():
            if k in req.full_url:
                r = seq[min(hits[k], len(seq) - 1)]
                hits[k] += 1
                if isinstance(r, Exception):
                    raise r
                return r
        raise AssertionError(req.full_url)
    monkeypatch.setattr(cash_issue._op, "open", fake_open)
    return hits


# ---------------- FIX1：A11 ----------------

def test_non_json_2xx_is_retried_and_logged(monkeypatch, sleeps, capsys):
    hits = route(monkeypatch, {"TWT48U_ALL": [Resp("<html>請稍後再試</html>", "text/html"),
                                              Resp(""), Resp(json.dumps(TWSE))]})
    rows = exright._twse()
    assert [r["code"] for r in rows] == ["2330"]
    assert hits["TWT48U_ALL"] == 3 and sleeps == [5, 10]
    log = capsys.readouterr().out
    assert "HTTP 200" in log and "Content-Type text/html" in log and "請稍後再試" in log
    assert "JSONDecodeError" in log and "空白" in log


def test_parse_failure_gives_up_after_tries(monkeypatch, sleeps):
    route(monkeypatch, {"TWT48U_ALL": [Resp('{"stat":"error"}')]})
    with pytest.raises(ValueError):
        exright._twse()
    assert sleeps == [5, 10]  # 最後一次失敗不再白等


def test_listed_fails_otc_still_ok(monkeypatch, sleeps):
    route(monkeypatch, {"TWT48U_ALL": [Resp("<html>blocked</html>", "text/html")],
                        "tpex_exright_prepost": [Resp(json.dumps(TPEX))]})
    failed = []
    evs = exright.events(failed)
    assert failed == ["twse"]
    assert [(e["code"], e["t0"], e["cash"], e["stock"]) for e in evs] == [("6488", dt.date(2026, 11, 12), 8.0, 0.1)]


def test_both_fail_without_collector_raises(monkeypatch, sleeps):
    route(monkeypatch, {"TWT48U_ALL": [Resp("")], "tpex_exright_prepost": [Resp("")]})
    with pytest.raises(ValueError):
        exright.events()


def problems(monkeypatch, status, ok_keys):
    monkeypatch.setenv("EXRIGHT_OUTCOME", "failure")
    monkeypatch.setattr(dp, "index_review_notice", lambda today: [])
    monkeypatch.setattr(dp, "read_out", lambda name: status if name == "exright_status.json" else None)
    asked = []

    def fake_supa(path, *a, **k):
        asked.append(path)
        return [{"key": k} for k in ok_keys]
    monkeypatch.setattr(dp, "supa", fake_supa)
    out = [p for p in dp.market_problems(TODAY, None) if "除權息" in p]
    assert asked and "ok:A11" in asked[0]
    return out


def test_same_day_success_suppresses_warning(monkeypatch):
    st = {"d": TODAY.isoformat(), "failed": ["twse", "tpex"]}
    assert problems(monkeypatch, st, ["ok:A11:twse", "ok:A11:tpex"]) == []


def test_no_earlier_success_keeps_original_warning(monkeypatch):
    st = {"d": TODAY.isoformat(), "failed": ["twse", "tpex"]}
    assert problems(monkeypatch, st, []) == ["除權息預告表抓取失敗，A11 今天可能漏掉 T-5 進場的訊號"]
    # 狀態檔是舊的（或沒寫）→ 當兩邊都失敗
    assert problems(monkeypatch, {"d": "2026-10-29", "failed": []}, ["ok:A11:tpex"]) == \
        ["上市除權息預告表抓取失敗，A11 今天可能漏掉上市 T-5 進場的訊號"]


def test_partial_failure_names_market(monkeypatch):
    st = {"d": TODAY.isoformat(), "failed": ["tpex"]}
    assert problems(monkeypatch, st, ["ok:A11:twse"]) == \
        ["上櫃除權息預告表抓取失敗，A11 今天可能漏掉上櫃 T-5 進場的訊號"]
    assert problems(monkeypatch, st, ["ok:A11:tpex"]) == []


# ---------------- FIX2：010 盤中 ----------------

def q(code="8299", z="-", b="-", a="-", h="-", u="500.0"):
    return {"c": code, "ex": "otc", "n": "群聯", "z": z, "b": b, "a": a, "h": h, "u": u, "y": "455.0"}


@pytest.fixture
def mis_seq(monkeypatch):
    """依序回傳的 MIS msgArray；記錄 sleep 與 once。"""
    st = {"seq": [], "calls": 0, "sleeps": [], "once": []}

    def fake_urlopen(req, timeout=None):
        arr = st["seq"][min(st["calls"], len(st["seq"]) - 1)]
        st["calls"] += 1
        return Resp(json.dumps({"msgArray": arr}))
    monkeypatch.setattr(intraday.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(intraday.time, "sleep", st["sleeps"].append)
    monkeypatch.setattr(intraday, "once", lambda today, key: st["once"].append(key) or True)
    return st


WATCH = [{"code": "8299", "name": "群聯", "streak": 4}]


def test_missing_quote_refetched_then_priced(mis_seq):
    mis_seq["seq"] = [[q()], [q(z="480.0", b="479.5_479.0_", a="480.5_481.0_", h="500.0")]]
    out = intraday.scan010(WATCH, {"8299": "O"}, TODAY, dry=False)
    assert mis_seq["calls"] == 2 and 3 in mis_seq["sleeps"]
    assert mis_seq["once"] == ["010:8299"]
    assert out == [("010:8299", "・群聯 8299　連4｜現 480／停 500")]


def test_no_ask_and_high_at_limit_is_locked(mis_seq):
    x = q(z="-", b="499.5_499.0_", a="-", h="500.0")
    assert intraday.at_limit_up(x) and intraday.limit_up_state(x) == "locked"
    assert intraday.limit_up_state(q(z="-", b="-", a="-", h="500.0")) == "locked"
    assert intraday.limit_up_state(q(z="495.0", b="494.5_", a="-", h="498.0")) == "open"  # 最高沒碰漲停
    mis_seq["seq"] = [[x]]
    assert intraday.scan010(WATCH, {"8299": "O"}, TODAY, dry=False) == []
    assert mis_seq["once"] == []


def test_unknown_state_not_marked_once(mis_seq, capsys):
    mis_seq["seq"] = [[q()]]  # 重抓兩次仍全空
    assert intraday.scan010(WATCH, {"8299": "O"}, TODAY, dry=False) == []
    assert mis_seq["calls"] == 3 and mis_seq["once"] == []
    assert "狀態不明" in capsys.readouterr().out
    mis_seq["seq"], mis_seq["calls"] = [[q(z="480.0", u="-")]], 0  # 有價但沒有漲停價 → 也判斷不了
    assert intraday.scan010(WATCH, {"8299": "O"}, TODAY, dry=False) == []
    assert mis_seq["once"] == []


def test_010_log_keeps_raw_mis_fields(mis_seq, capsys):
    mis_seq["seq"] = [[dict(q(z="480.0", b="479.5_", a="480.5_", h="500.0"), tlong="1793334600000")]]
    intraday.scan010(WATCH, {"8299": "O"}, TODAY, dry=True)
    assert "MIS z=480.0 b=479.5_ a=480.5_ h=500.0 u=500.0 tlong=1793334600000 state=open" in capsys.readouterr().out


def test_exright_main_logs_every_event(monkeypatch, capsys):
    """每筆走到試算的事件都印一行（含市場、T-5/T-6、幅度、稅拖曳、結果）；略過的也印原因。"""
    t0 = dt.date(2026, 11, 9)  # 週一 → T-5=11/02、T-6=10/30（= 今天）

    def ev(mkt, code, name, cash, stock=0.0, t=t0):
        return {"mkt": mkt, "code": code, "name": name, "t0": t, "cash": cash, "stock": stock,
                "sub": 0.0, "sub_px": 0.0}
    evs = [ev("上市", "1111", "大配息", 20.0), ev("上櫃", "2222", "小配息", 1.0),
           ev("上市", "3333", "沒行情", 1.0), ev("上櫃", "4444", "未公告", None),
           ev("上市", "6666", "大配股", 0.0, 0.25), ev("上市", "5555", "太早", 1.0, t=dt.date(2026, 11, 30))]

    class FakeNow(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 10, 30, 20, 0, tzinfo=tz)

    def fake_supa(path, *a, **k):
        if path.startswith("holidays"):
            return [{"market_date": "2026-01-01"}]
        if path.startswith("market_days"):
            return [{"stocks": {c: {"c": 100} for c in ("1111", "2222", "4444", "6666")}}]
        raise AssertionError(path)

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.delenv("PREVIEW", raising=False)
    monkeypatch.setattr(exright.dt, "datetime", FakeNow)
    monkeypatch.setattr(exright, "supa", fake_supa)
    monkeypatch.setattr(exright, "events", lambda failed: [dict(e) for e in evs])
    monkeypatch.setattr(exright, "write_status", lambda today, failed: None)
    monkeypatch.setattr(exright, "face_values", lambda: {"6666": 10.0})
    exright.main()
    out = capsys.readouterr().out
    assert ("上市 1111 大配息 T0=2026-11-09 T-5=2026-11-02 T-6=2026-10-30 T-6收盤=100 現金=20 配股=0 "
            "幅度=20.00% 稅拖曳=20.00% → 不符合") in out
    assert "上櫃 2222 小配息" in out and "幅度=1.00% 稅拖曳=1.00% → 不符合" in out
    assert "上市 6666 大配股" in out and "幅度=20.00% 稅拖曳=2.50% → 符合" in out
    assert "上市 3333 沒行情" in out and "略過：無 T-6 收盤（非普通股或無行情）" in out
    assert "上櫃 4444 未公告" in out and "略過：股利尚未公告" in out
    assert "上市 5555 太早" in out and "略過：T-6>今天" in out
    assert "DRY_RUN：不寫入" in out
