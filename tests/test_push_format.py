"""LINE 交易提醒精簡格式：【代號】策略名｜出場提示 → 「· 時點動作：股名 代號」，不帶績效、券源等說明。

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
    want = "【004】菲比斯 630 大額現增放空｜持有10日收盤回補\n· 開盤放空：東森 2614\n· 收盤回補：源大環能 6639"
    assert want in text
    assert "【019】內部人申報轉讓｜持有5日收盤回補\n· 開盤放空：勝一 1773" in text
    # 提醒型板塊（處置股注意）沒有出場規則：維持原標題
    assert "【A02】處置股\n· 注意：漢測 7856" in text
    assert "【010】開板放空（盯盤）｜隔天收盤回補\n· 收盤沒鎖漲停放空：群聯 8299" in text


def test_no_extra_details():
    text, *_ = compose()
    for bad in ("平均", "持有10交易日", "年化", "凱利", "n=", "認購", "繳款", "券源", "月線", "處置期間",
                "出場", "進場", "若有持倉", "績效", "◆", "要做的事"):
        assert bad not in text, bad


def title_of(rows, tmr=()):
    lines, _ = dp.render_items(list(tmr), rows)
    return [ln for ln in lines if ln.startswith("【")]


def test_exit_hint_by_strategy():
    a08 = srow("A08", "大盤-5%", "加權指數", "TAIEX", "entry", "long", "close")
    a08["variant"] = "單日≤−5%"
    assert title_of([a08]) == ["【A08】大盤-5%・單日≤−5%｜持有5日收盤賣"]
    c010 = srow("010", "連續漲跌停開板反轉", "群聯", "8299", "exit", "short", "close")
    assert title_of([c010]) == ["【010】連續漲跌停開板反轉｜隔天收盤回補"]
    c017 = srow("017", "現增上市賣壓與反彈", "某股", "1234", "entry", "short", "open")
    c017["variant"] = "現增上市放空"
    assert title_of([c017]) == ["【017】現增上市賣壓與反彈・現增上市放空｜隔天開盤回補"]


def test_exit_hint_side_and_variant():
    # A09 依方向：多 → 賣、空 → 回補
    up = srow("A09", "台股上中下旬", "加權指數", "TAIEX", "entry", "long", "close")
    up["variant"] = "十二月下旬"
    dn = srow("A09", "台股上中下旬", "加權指數", "TAIEX", "entry", "short", "close")
    dn["variant"] = "十二月中旬"
    assert title_of([up, dn]) == ["【A09】台股上中下旬・十二月下旬｜旬末收盤賣",
                                  "【A09】台股上中下旬・十二月中旬｜旬末收盤回補"]
    # 015 多空配對 → 平倉；新增股放空 → 回補
    pair = srow("015", "ETF新增及刪除股", "等額買刪除股", "LIST", "entry", "long", "open")
    pair["variant"] = "MSCI多空"
    assert title_of([pair])[0].endswith("｜持有3日收盤平倉")


def test_exit_hint_mixed_group_keeps_title():
    # 009 variant＝股名代號，不同股票併同一組；規則不同時不加提示
    a = srow("009", "產業旺季前預期效應", "雄獅", "2731", "exit", "short", "close")
    b = srow("009", "產業旺季前預期效應", "大立光", "3008", "exit", "long", "close")
    assert title_of([a]) == ["【009】產業旺季前預期效應｜8月最後交易日收盤回補"]
    assert title_of([a, b]) == ["【009】產業旺季前預期效應"]


def test_exit_hint_blocks():
    msci = {"block": "MSCI調整", "block_code": "msci", "action": "賣出", "company_name": "台積電",
            "company_code": "2330", "detail": "收盤賣出", "due_label": "明天"}
    assert title_of([], [msci]) == ["【A04】MSCI調整｜生效日收盤賣"]
    other = {"block": "IPO", "block_code": "ipo", "action": "注意", "company_name": "X", "company_code": "1"}
    assert title_of([], [other]) == ["【IPO】"]


def test_exit_hint_keys_exist():
    # 提示表的策略代號都要在 perf.json 找得到（防打錯字）
    import perf
    for k in dp.EXIT_HINT:
        assert (k[0] if isinstance(k, tuple) else k) in perf.STRATS, k


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
