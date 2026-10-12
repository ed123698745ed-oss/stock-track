"""每日行情：抓上市／上櫃普通股收盤、漲跌停、融資餘額，存成 market_days 一天一列。

事件型策略（scripts/event_signals.py）只讀這張表，不直接碰外部網站。

用法：
  python3 scripts/market.py                 # 抓今天（非交易日自動略過）
  python3 scripts/market.py 2026-10-08      # 抓指定日
  BACKFILL=140 python3 scripts/market.py    # 往回補 140 個交易日（已存在的日子略過）
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from calendar_signals import Cal, supa

TPE = dt.timezone(dt.timedelta(hours=8))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
COMMON = re.compile(r"^[1-9]\d{3}$")  # 普通股：4 碼數字、非 0 開頭（排除 ETF、特別股、權證、TDR）


# ---------------- 漲跌停價（台股升降單位）----------------
_TICKS = [(10, "0.01"), (50, "0.05"), (100, "0.1"), (500, "0.5"), (1000, "1"), (10 ** 12, "5")]


def _tick(p):
    return next(Decimal(t) for lim, t in _TICKS if p < lim)


def limit_up(ref):
    raw = Decimal(str(ref)) * Decimal("1.1")
    t = _tick(raw)
    return float((raw / t).to_integral_value(ROUND_FLOOR) * t)


def limit_down(ref):
    raw = Decimal(str(ref)) * Decimal("0.9")
    t = _tick(raw)
    return float((raw / t).to_integral_value(ROUND_CEILING) * t)


def num(s):
    s = re.sub(r"<[^>]+>", "", str(s or "")).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def get_json(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8-sig"))
        except Exception as e:
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url} -> {type(last).__name__}: {last}")


def table(j, title_part):
    for t in j.get("tables") or []:
        if title_part in (t.get("title") or ""):
            return t
    return None


# ---------------- 上市（證交所）----------------
def stock_row(close, sign, diff, open_, vol):
    """收盤、漲跌符號、漲跌價差 → {c 收盤, lu 收漲停, ld 收跌停, v 有效行情日}。參考價 = 收盤 − 漲跌。
    有效行情日（020 用）：有開盤價、有收盤價、成交股數 > 0。"""
    if close is None:
        return None
    if diff is None:  # 除權息、新上市等漲跌欄不是數字：有效行情日照記，漲跌停無法判斷
        return {"c": close, "lu": None, "ld": None, "v": open_ is not None and (vol or 0) > 0}  # None＝未知
    s = re.sub(r"<[^>]+>", "", str(sign or "")).strip()
    ref = close - diff if s == "+" else close + diff if s == "-" else close
    if ref <= 0:
        return None
    return {"c": close, "lu": close >= limit_up(ref) - 1e-9, "ld": close <= limit_down(ref) + 1e-9,
            "v": open_ is not None and (vol or 0) > 0}


def parse_twse_quotes(j):
    """MI_INDEX type=ALLBUT0999 → (加權指數收盤, 漲跌幅%, {代號: 列})"""
    if j.get("stat") != "OK":
        return None, None, {}
    idx = table(j, "價格指數(臺灣證券交易所)")
    taiex = pct = None
    for r in (idx or {}).get("data") or []:
        if r[0] == "發行量加權股價指數":
            taiex, pct = num(r[1]), num(r[4])
    q = table(j, "每日收盤行情")
    out = {}
    if q:
        f = q["fields"]
        ic, ix, isg, idf = f.index("證券代號"), f.index("收盤價"), f.index("漲跌(+/-)"), f.index("漲跌價差")
        io, iv = f.index("開盤價"), f.index("成交股數")
        for r in q["data"]:
            if COMMON.match(r[ic]):
                row = stock_row(num(r[ix]), r[isg], num(r[idf]), num(r[io]), num(r[iv]))
                if row:
                    row["n"] = r[1].strip()
                    out[r[ic]] = row
    return taiex, pct, out


def parse_twse_limit_counts(j):
    """MI_INDEX 的「漲跌證券數合計」股票欄 → (漲停家數, 跌停家數)，官方數字，用來對帳。"""
    t = table(j, "漲跌證券數合計")
    up = down = None
    for r in (t or {}).get("data") or []:
        m = re.search(r"\(([\d,]+)\)", r[2] if len(r) > 2 else "")
        if m and r[0].startswith("上漲"):
            up = int(m.group(1).replace(",", ""))
        if m and r[0].startswith("下跌"):
            down = int(m.group(1).replace(",", ""))
    return up, down


def parse_twse_margin(j):
    """MI_MARGN selectType=ALL → {代號: (融資前日餘額, 今日餘額)}（張）。前日餘額用來鏈接減資、分割。"""
    t = table(j, "融資融券彙總")
    out = {}
    if t:
        for r in t["data"]:
            if COMMON.match(r[0]):
                prev, bal = num(r[5]), num(r[6])  # 代號 名稱 買進 賣出 現金償還 前日餘額 今日餘額 …
                if bal is not None:
                    out[r[0]] = (int(prev) if prev is not None else None, int(bal))
    return out


# ---------------- 上櫃（櫃買中心）----------------
def parse_tpex_quotes(j):
    """afterTrading/otc type=EW → {代號: 列}。漲跌欄帶正負號（例 "+0.05"、"-0.10"）。"""
    out = {}
    for t in j.get("tables") or []:
        f = [x.strip() for x in t.get("fields") or []]
        if "代號" not in f or "收盤" not in f:
            continue
        ic, ix, idf = f.index("代號"), f.index("收盤"), f.index("漲跌")
        io = f.index("開盤")
        iv = next(i for i, x in enumerate(f) if x.startswith("成交股數"))
        for r in t.get("data") or []:
            if not COMMON.match(r[ic].strip()):
                continue
            close, diff = num(r[ix]), num(r[idf])
            row = stock_row(close, None if diff is None else "+" if diff >= 0 else "-",
                            None if diff is None else abs(diff), num(r[io]), num(r[iv]))
            if row:
                row["n"] = r[1].strip()
                out[r[ic].strip()] = row
    return out


def parse_tpex_margin(j):
    """margin/balance → {代號: (前資餘額, 資餘額)}（張）"""
    out = {}
    for t in j.get("tables") or []:
        f = [x.strip() for x in t.get("fields") or []]
        if "資餘額" not in f:
            continue
        ic, iv, ip = f.index("代號"), f.index("資餘額"), f.index("前資餘額(張)")
        for r in t.get("data") or []:
            v, pv = num(r[iv]), num(r[ip])
            if COMMON.match(r[ic].strip()) and v is not None:
                out[r[ic].strip()] = (int(pv) if pv is not None else None, int(v))
    return out


def fetch_day(d):
    """抓一天。回傳 market_days 的一列；該日沒有資料（休市）回傳 None。"""
    ymd = d.strftime("%Y%m%d")
    j = get_json(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json")
    taiex, pct, stocks = parse_twse_quotes(j)
    if not stocks:
        return None
    up_off, down_off = parse_twse_limit_counts(j)
    time.sleep(2)
    margin_ok = False
    try:
        m = parse_twse_margin(get_json(
            f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ymd}&selectType=ALL&response=json"))
        for code, (prev, bal) in m.items():
            if code in stocks:
                stocks[code]["mb"], stocks[code]["mp"] = bal, prev
        margin_ok = bool(m)
    except Exception as e:
        print(f"  {d} 上市融資抓取失敗：{e}")
    for s in stocks.values():
        s["m"] = "L"
    n_twse_ld = sum(s["ld"] for s in stocks.values())

    # 上櫃：任何一步失敗都只標記，不讓上市資料一起作廢
    ymd2 = d.strftime("%Y/%m/%d")
    otc_ok = otc_margin_ok = False
    try:
        time.sleep(2)
        otc = parse_tpex_quotes(get_json(
            f"https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={ymd2}&type=EW&response=json"))
        for code, row in otc.items():
            row["m"] = "O"
            stocks.setdefault(code, row)
        otc_ok = bool(otc)
        time.sleep(2)
        om = parse_tpex_margin(get_json(
            f"https://www.tpex.org.tw/www/zh-tw/margin/balance?date={ymd2}&id=&response=json"))
        for code, (prev, bal) in om.items():
            if code in stocks and stocks[code]["m"] == "O":
                stocks[code]["mb"], stocks[code]["mp"] = bal, prev
        otc_margin_ok = bool(om)
    except Exception as e:
        print(f"  {d} 上櫃抓取失敗：{e}")
    n_otc_ld = sum(s["ld"] for s in stocks.values() if s["m"] == "O")

    return {
        "d": d.isoformat(), "taiex": taiex, "taiex_pct": pct,
        "ld_twse": n_twse_ld, "ld_tpex": n_otc_ld if otc_ok else None,
        "ld_twse_official": down_off, "lu_twse_official": up_off,
        "has_otc": otc_ok, "has_margin": margin_ok and otc_margin_ok,
        "stocks": stocks,
    }


def main():
    hol = [dt.date.fromisoformat(r["market_date"]) for r in supa("holidays?select=market_date&limit=5000")]
    cal = Cal(hol)
    today = dt.datetime.now(TPE).date()
    if len(sys.argv) > 1:
        days = [dt.date.fromisoformat(sys.argv[1])]
    elif os.environ.get("BACKFILL"):
        n = int(os.environ["BACKFILL"])
        end = today if cal.is_trading(today) else cal.shift(today, -1)
        days = [cal.shift(end, -i) for i in range(n - 1, -1, -1)]
        if os.environ.get("REFETCH") != "1":
            have = {r["d"] for r in supa(f"market_days?select=d&d=gte.{days[0].isoformat()}")}
            days = [x for x in days if x.isoformat() not in have]
    else:
        if not cal.is_trading(today):
            print(f"{today} 不是交易日，略過")
            return
        days = [today]
    print(f"要抓 {len(days)} 天")
    for d in days:
        row = fetch_day(d)
        if not row:
            print(f"  {d} 無資料（休市或尚未公布）")
            continue
        supa("market_days?on_conflict=d", "POST", row, prefer="resolution=merge-duplicates,return=minimal")
        print(f"  {d} 加權 {row['taiex']} ({row['taiex_pct']}%) "
              f"上市跌停 {row['ld_twse']}（官方股票欄 {row['ld_twse_official']}） 上櫃跌停 {row['ld_tpex']} "
              f"普通股共 {len(row['stocks'])} 檔 融資 {'齊' if row['has_margin'] else '缺'}")
        time.sleep(3)


if __name__ == "__main__":
    main()
