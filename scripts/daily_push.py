"""每日推播：把「下一個交易日要進出場的部位」推到 LINE。

資料來源：
  v_tomorrow          既有板塊（處置、庫藏、分割、0050、MSCI…）
  v_strategy_actions  日曆型策略（sql/001_strategy_actions.sql）
  runs                最後一次抓取狀態

原則：「沒有訊號」和「抓取失敗所以沒有訊號」要分得出來，失敗一定寫在訊息裡。

環境變數：SUPABASE_URL、SUPABASE_SERVICE_KEY、LINE_CHANNEL_ACCESS_TOKEN、LINE_USER_ID
         DRY_RUN=1 只印不推；CAL_OUTCOME=日曆策略那一步的結果（success/failure）
"""
import re
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.request

from calendar_signals import Cal, supa

SITE = "https://ed123698745ed-oss.github.io/stock-track/"
TPE = dt.timezone(dt.timedelta(hours=8))
W = "一二三四五六日"
TIMING = {"open": "開盤", "close": "收盤", None: "時點待確認"}


def md(d):
    d = dt.date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d.month}/{d.day}({W[d.weekday()]})"


def safe(fn):
    try:
        return fn(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:120]}"


def strategy_line(r):
    pair = "出場" if r["role"] == "entry" else "進場"
    lines = [f"【{r['action']}】{TIMING.get(r.get('act_timing'))}　{r['company_name']} {r['company_code']}",
             f"　{r['strategy_id']} {r['strategy_name']}"
             + ("" if r["variant"] == r["company_name"] + r["company_code"] else f"・{r['variant']}")]
    tail = ([f"{pair} {md(r['pair_date'])} {TIMING.get(r.get('pair_timing'))}"]
            if r.get("pair_date") else [])
    if r.get("detail"):
        tail.append(re.sub(r"承銷價 (0\.0|0|None)(?=[^\d.]|$)", "承銷價 未定", r["detail"]))
    if tail:
        lines.append("　" + "｜".join(tail))
    return "\n".join(lines)


def block_line(r):
    name = f"{r.get('company_name') or ''} {r.get('company_code') or ''}".strip()
    lines = [f"【{r.get('action') or '注意'}】{name}"]
    sub = "｜".join(x for x in (r.get("block"), r.get("detail")) if x)
    sub = re.sub(r"承銷價 (0\.0|0|None)(?=[^\d.]|$)", "承銷價 未定", sub)
    if sub:
        lines.append("　" + sub)
    return "\n".join(lines)


def watch_lines(watch):
    if not watch:
        return []
    out = ["", f"▍明天盯盤（010 開板放空）　{len(watch)} 檔"]
    for w in watch[:10]:
        out.append(f"{w['name']} {w['code']}　已連 {w['streak']} 根漲停")
    if len(watch) > 10:
        out.append(f"…另有 {len(watch) - 10} 檔")
    out.append("　收盤沒鎖漲停 → 收盤放空、下一交易日收盤回補（13:05 盤中會再提醒）")
    return out


IDX_NAME = {"msci": "MSCI", "tw50": "台灣50（0050）"}


def index_prep(cal, today):
    """指數調整生效日前兩個交易日的晚上提醒：準備 015 名單、確認券源。"""
    if not cal:
        return []
    target = cal.shift(today, 2)
    try:
        rows = supa("calendar?select=strategy_code,event_date&kind=eq.effective"
                    f"&event_date=eq.{target.isoformat()}")
    except Exception:
        return []
    codes = sorted({r["strategy_code"] for r in rows if r.get("strategy_code") in IDX_NAME})
    if not codes:
        return []
    out = ["", f"▍提前準備（{md(target)} 指數調整生效）"]
    for c in codes:
        out.append(f"{IDX_NAME[c]}：後天收盤生效")
    out.append("　確認新增／刪除名單、放空腳的券源；015 生效日後第 1 個交易日開盤進場")
    return out


def warn_key(p):
    import hashlib
    return "warn:" + hashlib.md5(p.encode()).hexdigest()[:16]


def board_key(r):
    """既有板塊（處置股、庫藏股、IPO…）一筆的識別：用顯示文字的雜湊，推過就記在 intraday_alerts。"""
    import hashlib
    return "tmr:" + hashlib.md5(block_line(r).encode()).hexdigest()[:16]


def compose(now, tmr, stg, run, next_day, problems, watch=None, late=False, prep=None):
    head_day = md(next_day) if next_day else "下一個交易日"
    if late:
        out = [f"補充提醒｜{head_day} 新增訊號（稍晚公布的資料）"]
        out += [f"⚠ {p}" for p in problems] + [""]
        out += [block_line(r) for r in (tmr or [])]
        out += [strategy_line(r) for r in stg]
        return fit("\n".join(out + ["", SITE]))
    out = [f"交易提醒｜{head_day} 要做的事"]

    if run:
        t = dt.datetime.fromisoformat((run.get("finished_at") or run["started_at"]).replace("Z", "+00:00"))
        label = {"success": "正常", "partial": "部分失敗", "failed": "失敗",
                 "running": "執行中"}.get(run.get("status"), run.get("status"))
        stale = "（超過 30 小時，可能過期）" if (now - t).total_seconds() > 30 * 3600 else ""
        out.append(f"資料更新：{t.astimezone(TPE):%m/%d %H:%M} {label}{stale}")
    for p in problems:
        out.append(f"⚠ {p}")

    items = [(0, r.get("sort_key") or 0, block_line(r)) for r in (tmr or [])
             if r.get("due_label") == "明天"]
    items += [(1, (r.get("act_timing") != "open", r["strategy_id"]), strategy_line(r))
              for r in (stg or []) if r.get("due_label") == "明天"]
    out.append("")
    if items:
        out.append(f"▍明天 {head_day}　{len(items)} 筆")
        # 既有板塊照 sort_key、策略照「開盤先、收盤後」，兩組各自排序
        out += [x[2] for x in sorted((i for i in items if i[0] == 0), key=lambda i: i[1])]
        out += [x[2] for x in sorted((i for i in items if i[0] == 1), key=lambda i: i[1])]
    elif tmr is None and stg is None:
        out.append("無法讀取待辦清單，請直接開網站確認。")
    else:
        out.append(f"明天 {head_day} 沒有要進出場的部位。")

    out += watch_lines(watch)
    out += prep or []

    pending = sum(1 for r in (tmr or []) + (stg or [])
                  if r.get("due_label") in ("今天", "未處理") and not r.get("checked"))
    if pending:
        out += ["", f"另有 {pending} 筆今天或之前的待辦還沒勾選。"]
    out += ["", SITE]

    return fit("\n".join(out))


def fit(text):
    """LINE 單則上限 5000（UTF-16 單位）；超過就截斷並指向網站。被截掉的項目不會標成已推播。"""
    if len(text.encode("utf-16-le")) // 2 > 4800:
        text = text[:4600].rsplit("\n", 1)[0] + f"\n…（其餘請看網站）\n{SITE}"
    return text


def push_line(text):
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push", method="POST",
        data=json.dumps({"to": os.environ["LINE_USER_ID"].strip(),
                         "messages": [{"type": "text", "text": text}]}).encode(),
        headers={"Authorization": "Bearer " + os.environ["LINE_CHANNEL_ACCESS_TOKEN"].strip(),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def read_out(name):
    p = pathlib.Path(__file__).resolve().parent.parent / "out" / name
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return None


def unregistered_closures(cal, today):
    """休市日表當成交易日、卻沒有任何行情的平日（多半是颱風假等臨時休市）。不自動登錄，等人確認。"""
    try:
        have = {r["d"] for r in supa("market_days?select=d&order=d.asc&limit=1000")}
    except Exception:
        return []
    if not have:
        return []
    d, miss = dt.date.fromisoformat(min(have)), []
    while d < today:
        if d.year in cal.years and cal.is_trading(d) and d.isoformat() not in have:
            miss.append(d)
        d += dt.timedelta(days=1)
    if not miss:
        return []
    days = "、".join(f"{x:%Y/%m/%d}" for x in miss[:10])
    return [f"{days} 是平日但沒有行情，可能是颱風假等臨時休市（也可能是漏抓）。"
            f"確認休市請到 Actions →「新增休市日」登錄；漏抓請跑「回補歷史行情」"]


def index_review_notice(today):
    """證交所新聞出現「MSCI 指數臺股權重調整結果」（近 3 天）→ 提醒去填 A04 名單。
    MSCI 官網擋程式、證交所 PDF 只有權重沒有名單，所以名單仍需手動輸入。"""
    try:
        j = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://www.twse.com.tw/rwd/zh/news/newsList?response=json",
            headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read())
    except Exception:
        return []
    out = []
    for r in j.get("data") or []:
        title, d = r[1], r[2]
        m = re.match(r"(\d+)年(\d+)月(\d+)日", d)
        if not m or not re.search(r"MSCI.*調整結果", title):
            continue
        day = dt.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
        if 0 <= (today - day).days <= 3:
            out.append(f"📣 {title}（{day:%m/%d} 公布）：請到網站「指數調整」填入 MSCI 新增／刪除名單（A04）")
    return out


def market_problems(today, cal):
    """行情資料狀態 → 警告文字。沒抓到和沒訊號要分得出來。"""
    out = []
    for step, label in (("MARKET_OUTCOME", "行情抓取"), ("EVENT_OUTCOME", "事件型策略判斷")):
        if os.environ.get(step, "success") != "success":
            out.append(f"{label}失敗，A08／014／010／020 今天的結果可能不完整")
    if os.environ.get("CASH_OUTCOME", "success") != "success":
        out.append("現增公告抓取失敗，004 今天可能漏掉新公告（明天會再掃最近 7 天）")
    if os.environ.get("INSIDER_OUTCOME", "success") != "success":
        out.append("內部人申報轉讓抓取失敗，019 今天可能漏掉訊號（明天會再掃最近 7 天）")
    if os.environ.get("EXRIGHT_OUTCOME", "success") != "success":
        out.append("除權息預告表抓取失敗，A11 今天可能漏掉 T-5 進場的訊號")
    if cal:
        out += unregistered_closures(cal, today)
    out += index_review_notice(today)
    st = read_out("market_status.json")
    if cal and cal.is_trading(today):
        if not st or st.get("d") != today.isoformat():
            out.append("今天的行情還沒抓到，事件型策略用的是前一個交易日的資料")
        else:
            if not st.get("has_otc"):
                out.append("上櫃行情沒抓到，014 跌停家數今天不判斷")
            if not st.get("has_margin"):
                out.append("融資餘額尚未公布，020 今天稍晚（22:37）再判斷，有訊號會補推")
    return out


def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(TPE).date()
    late = os.environ.get("LATE") == "1"
    problems = []

    tmr, e1 = safe(lambda: supa("v_tomorrow?select=*"))
    if e1:
        problems.append(f"既有板塊讀取失敗 {e1}")
    stg, e2 = safe(lambda: supa("v_strategy_actions?select=*"))
    if e2:
        problems.append(f"策略訊號讀取失敗（sql/001 是否已執行？）{e2}")
    if os.environ.get("CAL_OUTCOME", "success") != "success":
        problems.append("日曆策略今天沒有更新成功，日曆策略的日期可能不是最新")
    runs, _ = safe(lambda: supa("runs?select=*&order=started_at.desc&limit=1"))
    hol, _ = safe(lambda: [dt.date.fromisoformat(r["market_date"])
                           for r in supa("holidays?select=market_date&limit=5000")])
    next_day = None
    if hol:
        cal = Cal(hol)
        next_day = cal.shift(today, 1)
        if next_day.year not in cal.years:
            next_day = None  # 休市日未公布，不硬算日期

    problems += market_problems(today, cal if hol else None)
    if late:
        # 晚間補推：只推第一次推播之後才出現的「明天」策略訊號
        stg = [r for r in (stg or []) if r.get("due_label") == "明天" and not r.get("notified_at")]
        sent, _ = safe(lambda: {x["key"] for x in supa(f"intraday_alerts?select=key&d=eq.{today.isoformat()}&key=like.tmr:*")})
        tmr = [r for r in (tmr or []) if r.get("due_label") == "明天" and board_key(r) not in (sent or set())] if sent is not None else []
        problems = [p for p in problems if "融資" not in p]
        warned, _ = safe(lambda: {x["key"] for x in supa(f"intraday_alerts?select=key&d=eq.{today.isoformat()}&key=like.warn:*")})
        problems = [p for p in problems if warn_key(p) not in (warned or set())]
        if not stg and not tmr and not problems:
            print("沒有新增訊號，不補推")
            if any(os.environ.get(k, "success") != "success" for k in
                   ("CAL_OUTCOME", "MARKET_OUTCOME", "EVENT_OUTCOME", "CASH_OUTCOME", "INSIDER_OUTCOME", "EXRIGHT_OUTCOME")):
                sys.exit(1)  # 警告稍早已推過；仍讓 Actions 顯示紅燈
            return
        text = compose(now, tmr, stg, None, next_day, problems, late=True)
    else:
        text = compose(now, tmr, stg, (runs or [None])[0], next_day, problems, read_out("watch010.json"),
                       prep=index_prep(cal if hol else None, today))
    print(text)
    if os.environ.get("DRY_RUN") == "1":
        print("\nDRY_RUN：不推送")
    else:
        print("\nLINE 回應", push_line(text))
        ids = [str(r["id"]) for r in (stg or []) if r.get("due_label") == "明天" and r.get("id")
               and strategy_line(r) in text]  # 被截斷沒送出的不標記，補推會再送
        if ids:
            safe(lambda: supa(f"strategy_actions?id=in.({','.join(ids)})", "PATCH",
                              {"notified_at": now.isoformat()}))
        keys = [{"d": today.isoformat(), "key": board_key(r)} for r in (tmr or [])
                if r.get("due_label") == "明天" and block_line(r) in text]
        keys += [{"d": today.isoformat(), "key": warn_key(p)} for p in problems]
        if keys:
            safe(lambda: supa("intraday_alerts?on_conflict=d,key", "POST", keys,
                              prefer="resolution=ignore-duplicates,return=minimal"))
    failed = [k for k in ("CAL_OUTCOME", "MARKET_OUTCOME", "EVENT_OUTCOME", "CASH_OUTCOME", "INSIDER_OUTCOME", "EXRIGHT_OUTCOME")
              if os.environ.get(k, "success") != "success"]
    if (tmr is None and stg is None) or failed:
        sys.exit(1)  # 訊息已送出；讓 Actions 顯示紅燈，不要靜靜綠燈


if __name__ == "__main__":
    main()
