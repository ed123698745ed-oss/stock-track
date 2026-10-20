"""盤中提醒（約 13:05、13:15 各跑一次）：A08、014、010 都是訊號日「當天收盤」進場，晚上推播來不及。

  A08  加權指數目前跌幅 ≤ −4.5%                → 提醒：收盤 ≤ −5% 就收盤買進
  014  掃全市場跌停家數 ≥ 90                    → 提醒：收盤 ≥ 100 家就收盤買進
  010  昨天已連 ≥ 4 根漲停的股票，現在沒鎖漲停     → 提醒：收盤沒漲停就收盤放空

門檻故意比正式條件寬一點，是「快到了，請看盤」；最後是否成立以收盤為準，晚上會記錄。
同一天同一件事只推一次（intraday_alerts 表去重）。沒事不推。

環境變數：SUPABASE_URL、SUPABASE_SERVICE_KEY、LINE_CHANNEL_ACCESS_TOKEN、LINE_USER_ID
         DRY_RUN=1 只印不推；FORCE=1 不檢查時間窗（測試用）
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request

from calendar_signals import Cal, supa
import perf
from daily_push import push_line
from event_signals import C014_GAP, watch010

TPE = dt.timezone(dt.timedelta(hours=8))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
A08_WARN, SCAN_014, WARN_014 = -4.5, -2.5, 90


def f(x):
    """MIS 價格欄位 → float；"-"、空白、0（沒有報價）一律回傳 None。"""
    try:
        v = float(str(x).split("_")[0])
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def mis(chs):
    """MIS 即時報價。chs 例：["tse_t00.tw", "otc_6488.tw"]。每批 50 檔。"""
    out = []
    for i in range(0, len(chs), 50):
        url = ("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?json=1&delay=0&ex_ch="
               + "|".join(chs[i:i + 50]))
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Referer": "https://mis.twse.com.tw/stock/fibest.jsp"})
        with urllib.request.urlopen(req, timeout=20) as r:
            out += json.loads(r.read()).get("msgArray") or []
        time.sleep(0.4)
    return out


def last_price(x):
    """最近成交價；兩筆成交之間 z 會是 "-"，改用最佳買價、再用最佳賣價。
    三個都沒有（例如瞬間價格穩定措施的試撮空檔）→ None。"""
    return f(x.get("z")) or f(x.get("b")) or f(x.get("a"))


def at_limit_down(x):
    w = f(x.get("w"))
    if not w:
        return False
    p = f(x.get("z"))
    ask = f(x.get("a"))
    return (p is not None and p <= w + 1e-9) or (ask is not None and ask <= w + 1e-9)


def at_limit_up(x):
    u = f(x.get("u"))
    if not u:
        return False
    p = f(x.get("z"))
    bid = f(x.get("b"))
    return (p is not None and p >= u - 1e-9) or (bid is not None and bid >= u - 1e-9)


_SENT = None
_PENDING = []


def once(today, key):
    """同一天同一個 key 只提醒一次。這裡只檢查；LINE 確定送出後才由 mark_sent() 記錄，
    送失敗的下一輪（13:15）會再送。"""
    global _SENT
    if _SENT is None:
        _SENT = {x["key"] for x in supa(f"intraday_alerts?select=key&d=eq.{today.isoformat()}")}
    if key in _SENT:
        return False
    _PENDING.append(key)
    return True


def mark_sent(today):
    if _PENDING:
        supa("intraday_alerts?on_conflict=d,key", "POST", [{"d": today.isoformat(), "key": k} for k in _PENDING],
             prefer="resolution=ignore-duplicates,return=minimal")


def main():
    now = dt.datetime.now(TPE)
    today = now.date()
    dry = os.environ.get("DRY_RUN") == "1"
    hol = [dt.date.fromisoformat(r["market_date"]) for r in supa("holidays?select=market_date&limit=5000")]
    cal = Cal(hol)
    if not cal.is_trading(today):
        print(f"{today} 不是交易日"); return
    if os.environ.get("FORCE") != "1" and not (dt.time(12, 30) <= now.time() <= dt.time(13, 27)):
        print(f"{now:%H:%M} 不在 12:30~13:27 盤中提醒時間窗，略過（GitHub 排程延遲太久就不推）"); return

    alerts = []
    idx = {x.get("c"): x for x in mis(["tse_t00.tw"])}
    t00 = idx.get("t00") or {}
    z, y = f(t00.get("z")), f(t00.get("y"))
    pct = (z / y - 1) * 100 if z and y else None
    print(f"{now:%H:%M} 加權 {z}（昨收 {y}）{pct:+.2f}%" if pct is not None else "加權指數讀取失敗")

    # A08
    if pct is not None and pct <= A08_WARN and (dry or once(today, "A08")):
        alerts.append(("A08", "\n".join([
            "【A08 大盤-5%】", perf.summary("A08") or "績效：總表未提供",
            f"◆ 加權目前 {pct:+.2f}%",
            "　收盤 ≤ −5% → 收盤買進加權指數，持有 5 個交易日後收盤賣出"])))

    # 014：每次都掃全市場跌停家數（正式策略沒有大盤跌幅條件）
    if True:
        last = supa("market_days?select=d,stocks&order=d.desc&limit=1")[0]
        chs = [f"{'tse' if s.get('m') == 'L' else 'otc'}_{c}.tw" for c, s in last["stocks"].items()]
        quotes = mis(chs)
        n = sum(at_limit_down(x) for x in quotes)
        print(f"跌停家數（盤中）{n}／{len(quotes)} 檔")
        recent = supa("strategy_actions?select=act_date&strategy_id=eq.014&role=eq.entry"
                      "&order=act_date.desc&limit=1")
        in_window = False
        if recent:
            prev = dt.date.fromisoformat(recent[0]["act_date"])
            in_window = len(cal.days(prev, today)) - 1 < C014_GAP
        if n >= WARN_014 and not in_window and (dry or once(today, "014")):
            alerts.append(("014", "\n".join([
                "【014 跌停群聚】",
                f"持有5日 {perf.summary('014', '持有5日') or '未提供'}",
                f"持有15日 {perf.summary('014', '持有15日') or '未提供'}",
                f"◆ 盤中跌停 {n} 家",
                "　收盤 ≥ 100 家 → 收盤買進加權指數，持有 5 日／15 日"])))

    # 010：昨天已連 ≥ 4 根漲停的股票
    days = supa("market_days?select=d,stocks&order=d.desc&limit=12")
    days = [d for d in sorted(days, key=lambda r: r["d"]) if d["d"] < today.isoformat()]
    watch = watch010(days, cal)
    o010 = []
    if watch:
        mk = {c: s.get("m") for c, s in days[-1]["stocks"].items()}
        q = {x.get("c"): x for x in mis([f"{'tse' if mk.get(w['code']) == 'L' else 'otc'}_{w['code']}.tw"
                                         for w in watch])}
        for w in watch:
            x = q.get(w["code"])
            if not x:
                continue
            px = last_price(x)
            locked = at_limit_up(x)
            print(f"010 盯盤 {w['name']}{w['code']} 連{w['streak']} 現價 {px} 漲停 {x.get('u')} "
                  f"{'鎖漲停' if locked else '未鎖（報價暫缺）' if px is None else '未鎖'}")
            if not locked and (dry or once(today, f"010:{w['code']}")):
                u = f(x.get("u"))
                now_txt = f"現 {px:g}／停 {u:g}" if px is not None and u else "報價暫缺，請自行看盤"
                o010.append((f"010:{w['code']}", f"・{w['name']} {w['code']}　連{w['streak']}｜{now_txt}"))

    # 排版與晚上推播相同：【策略】→ 一行績效 → ◆ 動作 N 檔 → 共同條件一行 → 每檔一行
    if o010:
        alerts += [(k, ln) for k, ln in o010]
    if not alerts:
        print("沒有需要提醒的事"); return
    blocks = [a for k, a in alerts if not k.startswith("010:")]
    if o010:
        blocks.append("\n".join([
            "【010 開板放空】", perf.summary("010") or "績效：總表未提供",
            f"◆ 開板放空 {len(o010)} 檔（盤中未鎖漲停）",
            "　收盤仍沒漲停 → 收盤放空，下一交易日收盤回補（先確認券源）"] + [ln for _, ln in o010]))
    text = (f"⚡ 盤中提醒 {now:%m/%d %H:%M}\n\n" + "\n\n".join(blocks)
            + "\n\n以收盤為準，晚上推播會記錄是否成立。")
    print(text)
    if dry:
        print("\nDRY_RUN：不推送")
    else:
        status = push_line(text)
        print("LINE 回應", status)
        mark_sent(today)
        from daily_push import log_push
        log_push("intraday", text, status, today,
                 [{"source": k.split(":")[0], "code": (k.split(":") + [None])[1], "action": "盤中提醒",
                   "act_date": today.isoformat(), "act_timing": "close", "line": a}
                  for k, a in alerts if k in _PENDING])


if __name__ == "__main__":
    main()
