"""臨時休市自動偵測（颱風等）：盯證交所最新消息，公告「集中交易市場 X 月 X 日休市一天」就自動處理。

2026-10-23 颱風休市沒人登錄，訊號照舊日期推播、A02 誤判作廢。改成自動：
  ① 讀 TWSE 最新消息，標題符合「集中交易市場115年10月23日休市一天」→ 取出休市日期
  ② 該日是未來（或今天）的平日、休市日表還沒有 → 登錄（名稱含「臨時」，A02 處置迄日順延規則會認得）
  ③ 重算舊看板訊號（rpc recalc_signal_dates）＋新版策略訊號改期（reschedule.run）
  ④ LINE 推一則「臨時休市通知」，列出改期項目
只認得的標題格式才自動登錄；看到「颱風／休市／停止交易」字眼但格式不符（例：上午休市、延後開盤），
只推「請人工確認」提醒，不寫資料庫（同一則提醒只推一次）。

DRY_RUN=1：只印要做的事與訊息，不寫資料庫、不推 LINE。
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request

NEWS = "https://www.twse.com.tw/rwd/zh/news/newsList?response=json"
TPE = dt.timezone(dt.timedelta(hours=8))
W = "一二三四五六日"
# 實際標題：臺灣證券交易所集中交易市場115年10月23日休市一天（7/10 颱風同格式）
FULL = re.compile(r"集中交易市場(\d{3})年(\d{1,2})月(\d{1,2})日(?:全日)?休市(?:一天|一日)?$")
HINT = re.compile(r"颱風|休市|停止交易|暫停交易|延後開盤|天災")
NOT_MARKET = ("股份有限公司", "ETF", "受益憑證", "權證", "指數投資證券")  # 個股停止買賣不是市場休市
PARTIAL = ("上午", "下午", "半日", "延後", "恢復", "提前")


def roc(s):
    m = re.match(r"(\d{3})年(\d{1,2})月(\d{1,2})日", s or "")
    return dt.date(int(m[1]) + 1911, int(m[2]), int(m[3])) if m else None


def scan(rows, today, known):
    """rows：TWSE newsList 的 data。回傳 (要自動登錄的 [(日期, 標題)], 要人工確認的 [標題])。
    只看最近 7 天發布的消息。"""
    auto, manual = [], []
    for r in rows:
        title, pub = (r[1] or "").strip(), roc(r[2])
        if not pub or (today - pub).days > 7 or pub > today + dt.timedelta(days=1):
            continue
        m = FULL.search(title)
        if m and not any(k in title for k in PARTIAL):
            d = dt.date(int(m[1]) + 1911, int(m[2]), int(m[3]))
            if d >= today and d.weekday() < 5 and d not in known:
                auto.append((d, title))
            continue
        if HINT.search(title) and not any(k in title for k in NOT_MARKET):
            manual.append(title)
    return sorted(set(auto)), manual


def md(s):
    return re.sub(r"\d{4}-(\d\d)-(\d\d)", lambda m: f"{int(m[1])}/{int(m[2])}", s)


def old_board(supa, since):
    rows = supa("signals?select=id,strategy_code,entry_date,exit_date,events(company_code,company_name)"
                f"&or=(entry_date.gte.{since},exit_date.gte.{since})&ignored=is.false&limit=5000") or []
    return {r["id"]: r for r in rows}


def old_diff(before, after):
    names = {"buyback": "庫藏股", "msci": "MSCI調整", "tw50": "0050調整", "disposal": "處置股", "split": "分割"}
    out = []
    for i, a in after.items():
        b = before.get(i)
        if not b or (b["entry_date"], b["exit_date"]) == (a["entry_date"], a["exit_date"]):
            continue
        ev = a.get("events") or {}
        parts = [f"進場 {b['entry_date']}→{a['entry_date']}" if b["entry_date"] != a["entry_date"] else "",
                 f"出場 {b['exit_date']}→{a['exit_date']}" if b["exit_date"] != a["exit_date"] else ""]
        out.append(f"{names.get(a['strategy_code'], a['strategy_code'])} {ev.get('company_name') or ''} "
                   f"{ev.get('company_code') or ''}：" + " ".join(p for p in parts if p))
    return out


def message(d, title, notes, today):
    lines = [f"⚠ 臨時休市通知",
             f"證交所公告：{d.month}/{d.day}（{W[d.weekday()]}）集中市場休市",
             f"（{title}）",
             "已自動登錄休市日，受影響訊號改期如下：" if notes else "已自動登錄休市日；目前沒有訊號需要改期。"]
    lines += ["・" + md(n) for n in notes]
    if d == today:
        lines.append("今天原定的進出場動作請改依上列新日期。")
    else:
        lines.append(f"先前推播中 {d.month}/{d.day} 的動作請改依上列新日期；之後的主推播會用新日期。")
    return "\n".join(lines)


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from calendar_signals import supa
    import reschedule
    dry = os.environ.get("DRY_RUN") == "1"
    today = dt.date.fromisoformat(os.environ["TODAY"]) if os.environ.get("TODAY") else dt.datetime.now(TPE).date()

    req = urllib.request.Request(NEWS, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.loads(r.read().decode("utf-8")).get("data") or []
    hol = {dt.date.fromisoformat(h["market_date"]) for h in supa("holidays?select=market_date&limit=5000")}
    auto, manual = scan(rows, today, hol)
    print(f"最新消息 {len(rows)} 則；自動登錄 {len(auto)}、需人工確認 {len(manual)}")

    import daily_push as dp
    for d, title in auto:
        name = ("颱風" if "颱風" in title else "") + f"臨時休市（證交所公告 {today.isoformat()} 自動登錄）"
        since = (d - dt.timedelta(days=60)).isoformat()
        before = old_board(supa, since)
        if not dry:
            supa("holidays", "POST", [{"market_date": d.isoformat(), "name": name[:100]}],
                 prefer="resolution=merge-duplicates,return=minimal")
            n = supa("rpc/recalc_signal_dates", "POST", {})
            print(f"已登錄 {d} {name}；舊看板重算 {n} 筆")
        after = old_board(supa, since) if not dry else before
        changes = reschedule.run([d], sorted(hol | {d}), today, dry=dry)
        notes = list(dict.fromkeys(n for _, _, n in changes)) + old_diff(before, after)
        text = message(d, title, notes, today)
        print(text)
        if dry:
            print("（DRY_RUN：未寫入、未推播）")
            continue
        status = dp.push_line(text)
        dp.log_push("closure", text, status, today, [])
        hol.add(d)

    for title in manual:
        text = f"⚠ 證交所公告可能影響交易日，請人工確認：\n{title}\n（格式不是「X月X日休市一天」，未自動登錄；確認是全日休市請手動跑「新增休市日」）"
        q = urllib.parse.quote(text, safe="")
        if supa(f"push_messages?select=id&mode=eq.closure_check&text=eq.{q}&limit=1"):
            continue
        print(text)
        if not dry:
            status = dp.push_line(text)
            dp.log_push("closure_check", text, status, today, [])


if __name__ == "__main__":
    main()
