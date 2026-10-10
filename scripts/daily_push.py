"""每日推播：把「下一個交易日要進出場的部位」推到 LINE。

資料來源：
  v_tomorrow          既有板塊（處置、庫藏、分割、0050、MSCI…）
  v_strategy_actions  日曆型策略（sql/001_strategy_actions.sql）
  runs                最後一次抓取狀態

原則：「沒有訊號」和「抓取失敗所以沒有訊號」要分得出來，失敗一定寫在訊息裡。

環境變數：SUPABASE_URL、SUPABASE_SERVICE_KEY、LINE_CHANNEL_ACCESS_TOKEN、LINE_USER_ID
         DRY_RUN=1 只印不推；CAL_OUTCOME=日曆策略那一步的結果（success/failure）
"""
import datetime as dt
import json
import os
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
        tail.append(r["detail"])
    if tail:
        lines.append("　" + "｜".join(tail))
    return "\n".join(lines)


def block_line(r):
    name = f"{r.get('company_name') or ''} {r.get('company_code') or ''}".strip()
    lines = [f"【{r.get('action') or '注意'}】{name}"]
    sub = "｜".join(x for x in (r.get("block"), r.get("detail")) if x)
    if sub:
        lines.append("　" + sub)
    return "\n".join(lines)


def compose(now, tmr, stg, run, next_day, problems):
    head_day = md(next_day) if next_day else "下一個交易日"
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

    pending = sum(1 for r in (tmr or []) + (stg or [])
                  if r.get("due_label") in ("今天", "未處理") and not r.get("checked"))
    if pending:
        out += ["", f"另有 {pending} 筆今天或之前的待辦還沒勾選。"]
    out += ["", SITE]

    text = "\n".join(out)
    if len(text) > 4800:  # LINE 單則上限 5000 字
        text = text[:4700].rsplit("\n", 1)[0] + f"\n…（其餘請看網站）\n{SITE}"
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


def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(TPE).date()
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

    text = compose(now, tmr, stg, (runs or [None])[0], next_day, problems)
    print(text)
    if os.environ.get("DRY_RUN") == "1":
        print("\nDRY_RUN：不推送")
    else:
        print("\nLINE 回應", push_line(text))
    if tmr is None and stg is None:
        sys.exit(1)  # 讓 Actions 顯示紅燈


if __name__ == "__main__":
    main()
