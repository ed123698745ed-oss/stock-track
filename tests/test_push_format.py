"""LINE 交易提醒精簡格式：【代號】策略名 → 「· 時點動作：股名 代號」，不帶績效、持有、券源等說明。

不連網、不碰資料庫：python -m pytest tests/test_push_format.py -q
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
os.environ.setdefault("SUPABASE_URL", "http://x")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "x")
import daily_push as dp  # noqa: E402

NOW = dt.datetime(2026, 10, 31, 13, 0, tzinfo=dt.timezone.utc)
NEXT = dt.date(2026, 11, 2)
RUN = {"status": "success", "started_at": "2026-10-31T12:30:00+00:00", "finished_at": "2026-10-31T12:40:00+00:00"}


def srow(sid, sname, name, code, role, side, timing, detail="", pair_date=None):
    return {"id": hash((sid, code, role)) % 10**6, "strategy_id": sid, "strategy_name": sname, "variant": name + code,
            "company_name": name, "company_code": code, "role": role, "side": side,
            "action": dp.ACT[(role, side)], "act_date": NEXT.isoformat(), "act_timing": timing,
            "pair_date": pair_date, "pair_timing": "close", "detail": detail, "due_label": "明天"}


def fake_rows():
    stg = [
        srow("004", "菲比斯 630 大額現增放空", "源大環能", "6639", "exit", "short", "close",
             "每仟股認購 92.60 股（9.3%）｜繳款 10/20~10/24｜先確認券源、借券費", "2026-10-27"),
        srow("004", "菲比斯 630 大額現增放空", "東森", "2614", "entry", "short", "open",
             "先確認融券資格、非平盤下禁空、券源", "2026-11-09"),
        srow("019", "內部人申報轉讓", "勝一", "1773", "entry", "short", "open",
             "10/30 申報一般交易轉讓：董事｜加權在月線下｜先確認券源", "2026-11-04"),
    ]
    tmr = [{"block": "處置股", "block_code": "disposal", "action": "注意", "company_name": "漢測",
            "company_code": "7856", "detail": "處置期間 11/03～11/14，每 5 分鐘撮合一次", "due_label": "明天"}]
    watch = [{"name": "群聯", "code": "8299", "streak": 3}]
    return tmr, stg, watch


def compose():
    tmr, stg, watch = fake_rows()
    text, shown = dp.compose(NOW, tmr, stg, RUN, NEXT, [], watch)
    return text, shown, tmr, stg


def test_header_and_counts():
    text, *_ = compose()
    lines = text.split("\n")
    assert lines[0] == "交易提醒｜11/2(一)"
    assert lines[1].startswith("資料更新：10/31 20:40 正常")
    assert "▍明天 11/2(一)　4 筆" in lines


def test_group_lines():
    text, *_ = compose()
    want = "【004】菲比斯 630 大額現增放空\n· 開盤放空：東森 2614\n· 收盤回補：源大環能 6639"
    assert want in text
    assert "【019】內部人申報轉讓\n· 開盤放空：勝一 1773" in text
    assert "【A02】處置股\n· 注意：漢測 7856" in text
    assert "【010】開板放空（盯盤）\n· 收盤沒鎖漲停放空：群聯 8299" in text


def test_no_extra_details():
    text, *_ = compose()
    for bad in ("平均", "持有", "年化", "凱利", "n=", "認購", "繳款", "券源", "月線", "處置期間",
                "出場", "進場", "若有持倉", "績效", "◆", "要做的事"):
        assert bad not in text, bad


def test_all_rows_shown():
    _, shown, tmr, stg = compose()
    assert {id(r) for r in shown} == {id(r) for r in tmr + stg}


def test_empty_day():
    text, _ = dp.compose(NOW, [], [], RUN, NEXT, [])
    assert "明天 11/2(一) 沒有要進出場的部位。" in text


class FakeCal:
    """週一到週五都是交易日、年份都算已知。"""
    def known(self, *days):
        return True

    def shift(self, d, n):
        step = 1 if n > 0 else -1
        while n:
            d += dt.timedelta(days=step)
            if d.weekday() < 5:
                n -= step
        return d


def test_msci_prep_with_effective(monkeypatch):
    # 美東 11/2(一) 公布 → 台灣 11/3(二) 看到；前一晚 11/2 提醒
    rows = [{"strategy_code": "msci", "kind": "announce", "event_date": "2026-11-02"},
            {"strategy_code": "msci", "kind": "effective", "event_date": "2026-11-24"}]
    monkeypatch.setattr(dp, "supa", lambda *a, **k: rows)
    out = dp.msci_prep(FakeCal(), dt.date(2026, 11, 2))
    assert out == ["", "【A04】MSCI 季度調整",
                   "· 收盤買進：新增成分股（名單填到網站「指數調整」）",
                   "· 生效日收盤賣：11/24(二)"]


def test_msci_prep_without_effective(monkeypatch):
    rows = [{"strategy_code": "msci", "kind": "announce", "event_date": "2026-11-02"},
            {"strategy_code": "msci", "kind": "effective", "event_date": "2026-11-03"}]
    monkeypatch.setattr(dp, "supa", lambda *a, **k: rows)
    out = dp.msci_prep(FakeCal(), dt.date(2026, 11, 2))
    assert out[-1] == "· 生效日收盤賣：請對照公告"


if __name__ == "__main__":
    print(compose()[0])
