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
from collections import OrderedDict
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.request

import perf
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


# 訊號產生時寫進 detail 的舊版統計（n=… 勝率…% p…）；改由 perf.json 的四指標取代
OLD_STAT = re.compile(r"n=\d+(?: 勝率[\d.]+%)?(?: p[=<][\d.e-]+)?")


def strategy_line(r):
    pair = "出場" if r["role"] == "entry" else "進場"
    lines = [f"【{r['action']}】{TIMING.get(r.get('act_timing'))}　{r['company_name']} {r['company_code']}",
             f"　{r['strategy_id']} {r['strategy_name']}"
             + ("" if r["variant"] == r["company_name"] + r["company_code"] else f"・{r['variant']}")]
    tail = ([f"{pair} {md(r['pair_date'])} {TIMING.get(r.get('pair_timing'))}"]
            if r.get("pair_date") else [])
    if r["role"] == "exit":
        tail.append("若有持倉")
    stat = perf.summary(r["strategy_id"], r.get("variant"))
    detail = r.get("detail") or ""
    if stat:
        detail = "｜".join(x for x in OLD_STAT.sub("", detail).split("｜") if x.strip())
    if detail:
        tail.append(re.sub(r"承銷價 (0\.0|0|None)(?=[^\d.]|$)", "承銷價 未定", detail))
    if tail:
        lines.append("　" + "｜".join(tail))
    lines.append("　" + (stat or "績效：總表未提供"))
    if stat and perf.NOTES.get(r["strategy_id"]):
        lines.append("　※" + perf.NOTES[r["strategy_id"]])
    return "\n".join(lines)


def old_trade(r):
    """舊板塊裡規則已改由 strategy_actions 提醒的買賣列（處置 → A02、分割 → A06、庫藏股 → A03）。"""
    return ((r.get("block_code") in ("disposal", "buyback") and r.get("src_table") == "signals")
            or (r.get("block_code") == "split" and r.get("act_kind") in ("buy", "sell")))


OLD_NAMES = {"msci": "MSCI調整", "tw50": "0050調整"}  # 庫藏股 2026-10-25 起改由 A03（buyback_actions.py）


def buyback_summary(ev):
    """庫藏股摘要：原始資料列有 20 格（價格、期間都拆成兩格）時依原始格重組，避免把價格上限誤標成期間。"""
    c = ((ev.get("raw") or {}).get("cols")) or []
    dre = r"\d{2,3}/\d{1,2}/\d{1,2}"
    if len(c) >= 11 and re.fullmatch(r"[\d,.]+", c[8] or "x") and re.fullmatch(dre, c[9] or "") and re.fullmatch(dre, c[10] or ""):
        purpose = {"1": "轉讓員工", "2": "股權轉換", "3": "維護信用並銷除"}.get(c[4], c[4])
        n = int(re.sub(r"[^\d]", "", c[6]) or 0)
        sh = f"{n / 10**4:,.0f} 萬股" if n >= 10**4 else f"{n:,} 股"
        return f"目的 {purpose}・預定 {sh}・價格 {c[7]}～{c[8]}・期間 {c[9]}～{c[10]}"
    return ev.get("summary") or ""


def old_board_for(day):
    """直接從 signals 取「day 要做」的舊板塊買賣列（處置、分割已改由 A02／A06，不取）。
    v_tomorrow 以「下一個交易日」當今天：週末、連假時會把「明天」算成下下個交易日，漏掉真正的下一個交易日
    （2026-10-25 漢測 7856 10/27 開盤買進沒推出）。非交易日改用這裡補。"""
    rows = supa("signals?select=id,strategy_code,entry_date,exit_date,entry_timing,exit_timing,status,ignored,"
                "events(company_code,company_name,summary,raw)"
                f"&or=(entry_date.eq.{day},exit_date.eq.{day})&ignored=is.false") or []
    out = []
    for s in rows:
        code = s.get("strategy_code")
        if code not in OLD_NAMES:
            continue
        ev = s.get("events") or {}
        tm = {"open": "開盤", "close": "收盤"}
        if s.get("entry_date") == day and s.get("status") in ("pending", None):
            ex = dt.date.fromisoformat(s["exit_date"]) if s.get("exit_date") else None
            detail = f"{tm.get(s.get('entry_timing'), '')}買進　{buyback_summary(ev)}".strip()
            if ex:
                detail += f"　預計出場 {ex:%m/%d}"
            act, kind = "買進", "buy"
        elif s.get("exit_date") == day and s.get("status") != "closed":
            ent = dt.date.fromisoformat(s["entry_date"]) if s.get("entry_date") else None
            detail = f"{tm.get(s.get('exit_timing'), '')}賣出" + (f"　進場日 {ent:%m/%d}" if ent else "")
            act, kind = "賣出", "sell"
        else:
            continue
        out.append({"src_table": "signals", "src_id": s["id"], "block": OLD_NAMES[code], "block_code": code,
                    "action": act, "act_kind": kind, "due_label": "明天", "company_code": ev.get("company_code"),
                    "company_name": ev.get("company_name"), "detail": detail, "event_date": day, "sort_key": 1})
    return out


def block_line(r):
    name = f"{r.get('company_name') or ''} {r.get('company_code') or ''}".strip()
    lines = [f"【{r.get('action') or '注意'}】{name}"]
    hold = "若有持倉" if re.search(r"賣出|回補", r.get("action") or "") else None
    sub = "｜".join(x for x in (r.get("block"), hold, r.get("detail")) if x)
    sub = re.sub(r"承銷價 (0\.0|0|None)(?=[^\d.]|$)", "承銷價 未定", sub)
    if sub:
        lines.append("　" + sub)
    sid = perf.BLOCK_SID.get(r.get("block_code"))
    if r.get("act_kind") in ("buy", "sell"):
        if r.get("block_code") in perf.PENDING:
            lines.append("　" + perf.PENDING[r["block_code"]])
        elif sid:
            lines.append(f"　{sid}｜" + (perf.summary(sid) or "績效：總表未提供"))
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


def msci_prep(cal, today):
    """A04（Ed 2026-10-19 選方案 B）：MSCI 季度調整台灣公布日的前一晚先提醒。
    calendar 的 msci announce 是 MSCI 官方（美東）公布日；台灣隔天清晨才看到名單，
    A04 回測的「公布日」＝台灣看到名單那天（例：2025/11/5 美東 → 2025/11/6），所以台灣公布日＝美東日期的下一個交易日。"""
    if not cal:
        return []
    nxt = cal.shift(today, 1)
    try:
        rows = supa("calendar?select=strategy_code,kind,event_date&strategy_code=eq.msci"
                    f"&event_date=gte.{(today - dt.timedelta(days=7)).isoformat()}"
                    f"&event_date=lte.{(today + dt.timedelta(days=120)).isoformat()}&order=event_date")
    except Exception:
        return []
    out = []
    for r in rows:
        us = dt.date.fromisoformat(r["event_date"])
        if r["kind"] != "announce" or not cal.known(us + dt.timedelta(days=10)):
            continue
        tw = cal.shift(us, 1)
        if tw != nxt:
            continue
        eff = next((dt.date.fromisoformat(x["event_date"]) for x in rows
                    if x["kind"] == "effective" and x["event_date"] > tw.isoformat()), None)
        out += ["", "▍提前準備（A04 MSCI 季度調整）",
                f"MSCI 美東 {md(us)} 公布，台灣明天 {md(tw)} 清晨看到名單",
                f"　新增成分股 → 明天收盤買進" + (f"，生效日 {md(eff)} 收盤賣" if eff else "，生效日請對照公告"),
                "　名單出來後請到網站「指數調整」填入新增股",
                "　" + (perf.summary("A04") or "績效：總表未提供")]
    return out


def log_push(mode, text, status, today, items):
    """推播紀錄：整則訊息＋每個項目一筆。寫入失敗只印警告，不影響推播。"""
    try:
        m = supa("push_messages", "POST", {"mode": mode, "status": status, "text": text},
                 prefer="return=representation")
        mid = m[0]["id"] if m else None
        # PostgREST 整批寫入要求每列欄位一致；板塊／盯盤項目沒有時點，缺的補 None（否則整批被拒、0 筆）
        cols = ("source", "code", "name", "action", "act_date", "act_timing", "line")
        rows = [dict({k: r.get(k) for k in cols}, message_id=mid, push_date=today.isoformat(), mode=mode)
                for r in items]
        if rows:
            supa("push_log", "POST", rows)
        print(f"推播紀錄已寫入 {len(rows)} 項")
    except Exception as e:
        print(f"⚠ 推播紀錄寫入失敗（sql/004 是否已執行？）：{e}")


def log_items(text, shown, watch, next_day):
    ids = {id(r) for r in shown}
    out = []
    for r in [x for x in shown if "strategy_id" in x]:
        ln = strategy_line(r)
        if r.get("due_label") == "明天" and id(r) in ids:
            out.append({"source": r["strategy_id"], "code": r.get("company_code"), "name": r.get("company_name"),
                        "action": r.get("action"), "act_date": r.get("act_date"),
                        "act_timing": r.get("act_timing"), "line": ln})
    for r in [x for x in shown if "strategy_id" not in x]:
        ln = block_line(r)
        if r.get("due_label") == "明天":
            out.append({"source": (r.get("block") or "板塊").split("｜")[0], "code": r.get("company_code"),
                        "name": r.get("company_name"), "action": r.get("action"),
                        "act_date": next_day.isoformat() if next_day else None, "line": ln})
    for w in watch or []:
        if f"{w['name']} {w['code']}" in text:
            out.append({"source": "010盯盤", "code": w["code"], "name": w["name"], "action": "盯盤",
                        "act_date": next_day.isoformat() if next_day else None,
                        "line": f"已連 {w['streak']} 根漲停"})
    return out


ACT = {("entry", "long"): "買進", ("exit", "long"): "賣出", ("entry", "short"): "放空", ("exit", "short"): "回補"}


def snap(r):
    """推播當下的內容快照：日期｜開收盤｜配對日期。任何一項變了都算更正。"""
    return f"{r['act_date']}|{r.get('act_timing') or ''}|{r.get('pair_date') or ''}"


def sent_key(r, now):
    return f"sent:{r['id']}:{int(now.timestamp())}:{snap(r)}"


def changes(today):
    """已推過的策略訊號，和「最後一次成功推播的內容」不同 → 更正；被訊號來源作廢 → 取消。
    回傳 [(去重 key, 訊息, 紀錄)]。推播時記 sent:<id>:<時間>:<快照>；沒記過的列不比對（不推估）。
    網站上手動「忽略」（checked=true）只是隱藏，不推取消。"""
    try:
        rows = supa("strategy_actions?select=*&notified_at=not.is.null"
                    f"&act_date=gte.{today.isoformat()}&limit=500")
        if not rows:
            return []
        since = (today - dt.timedelta(days=90)).isoformat()
        alerts = [x for k in ("sent", "cancel")
                  for x in supa(f"intraday_alerts?select=key,created_at&d=gte.{since}&key=like.{k}:*&limit=5000")]
    except Exception as e:
        print(f"⚠ 更正／取消比對失敗：{e}")
        return []
    keys = {x["key"] for x in alerts}
    last = {}  # id → (排序鍵, 快照)；舊格式 sent:<id>:<日期> 只有日期
    for x in alerts:
        k = x["key"].split(":", 3)
        if k[0] != "sent":
            continue
        if len(k) == 4:
            order, sp = (x["created_at"], int(k[2])), k[3]
        else:
            order, sp = (x["created_at"], 0), k[2]
        if k[1] not in last or order > last[k[1]][0]:
            last[k[1]] = (order, sp)
    out = []
    for r in rows:
        rid = str(r["id"])
        if rid not in last:
            continue
        old = last[rid][1].split("|")
        act = ACT[(r["role"], r["side"])]
        head = f"{r['strategy_id']} {r['strategy_name']}｜{r['company_name']} {r['company_code']} {act}"
        was = f"{md(old[0])}" + (f" {TIMING.get(old[1] or None)}" if len(old) > 1 else "")
        if r["ignored"]:
            if r.get("checked") or f"cancel:{rid}" in keys:
                continue  # 手動忽略不是策略取消；取消只推一次
            tail = "不要進場" if r["role"] == "entry" else "沒有進場就不用處理；若已有持倉請自行判斷"
            out.append((f"cancel:{rid}", f"【取消】{head}\n　原 {was}｜訊號已作廢，{tail}", dict(r, action="取消")))
            continue
        same = old[0] == r["act_date"] if len(old) == 1 else last[rid][1] == snap(r)
        if not same:
            now = f"{md(r['act_date'])} {TIMING.get(r.get('act_timing'))}"
            pair = (f"｜{'出場' if r['role'] == 'entry' else '進場'} {md(r['pair_date'])}"
                    if r.get("pair_date") and len(old) > 2 and old[2] != r["pair_date"] else "")
            out.append((None, f"【更正】{head}\n　原 {was} → 改為 {now}{pair}", dict(r, action="更正")))
    return out


def change_lines(chg):
    return ["", "▍更正／取消（之前推過的訊號有變動）"] + [c[1] for c in chg] if chg else []


def warn_key(p):
    import hashlib
    return "warn:" + hashlib.md5(p.encode()).hexdigest()[:16]


def board_key(r):
    """既有板塊（處置股、庫藏股、IPO…）一筆的識別：用顯示文字的雜湊，推過就記在 intraday_alerts。"""
    import hashlib
    return "tmr:" + hashlib.md5(block_line(r).encode()).hexdigest()[:16]


# ---------------- 排版：同策略放一起，同策略內依「時點＋動作」分組 ----------------
ACT_ORDER = {"賣出": 0, "回補": 1, "買進": 2, "放空": 3}
TIMING_ORDER = {"開盤": 0, "收盤": 1}
BLOCK_TIMING = re.compile(r"^(開盤|收盤)(買進|賣出|放空|回補)$")


def _w(s):
    """手機上的顯示寬度：中文 1、半形 0.5。"""
    return sum(0.5 if ord(c) < 0x2E80 else 1 for c in s)


def _entry(r, kind):
    """把一列（策略訊號或舊板塊）轉成排版用的資料。"""
    if kind == "S":
        sid = r["strategy_id"]
        title = f"{sid} {r['strategy_name']}" + (
            "" if r["variant"] == r["company_name"] + r["company_code"] else f"・{r['variant']}")
        stat = perf.summary(sid, r.get("variant"))
        detail = r.get("detail") or ""
        if stat:
            detail = "｜".join(x for x in OLD_STAT.sub("", detail).split("｜") if x.strip())
        frags = []
        if r.get("pair_date"):
            pair = "出場" if r["role"] == "entry" else "進場"
            frags.append(f"{pair} {md(r['pair_date'])} {TIMING.get(r.get('pair_timing'))}")
        frags += [x.strip() for x in detail.split("｜") if x.strip()]
        return {"g": ("S", sid, r.get("variant")), "title": title,
                "stat": stat or "績效：總表未提供", "note": perf.NOTES.get(sid) if stat else None,
                "timing": TIMING.get(r.get("act_timing")), "action": r["action"], "exit": r["role"] == "exit",
                "name": r["company_name"], "code": r["company_code"], "frags": frags, "row": r}
    code = r.get("block_code")
    sid = perf.BLOCK_SID.get(code)
    title = f"{sid} {r.get('block') or ''}".strip() if sid else (r.get("block") or "其他")
    stat = None
    if r.get("act_kind") in ("buy", "sell"):
        stat = perf.PENDING.get(code) or (perf.summary(sid) or "績效：總表未提供" if sid else None)
    frags = [x.strip() for x in (r.get("detail") or "").split("　") if x.strip()]
    timing = None
    if frags and (m := BLOCK_TIMING.match(frags[0])):
        timing, frags = m.group(1), frags[1:]
    frags = [re.sub(r"承銷價 (0\.0|0|None)(?=[^\d.]|$)", "承銷價 未定", x) for x in frags]
    action = r.get("action") or "注意"
    return {"g": ("B", code), "title": title, "stat": stat, "note": None, "timing": timing,
            "action": action, "exit": bool(re.search(r"賣出|回補", action)),
            "name": r.get("company_name") or "", "code": r.get("company_code") or "", "frags": frags, "row": r}


def render_items(tmr, stg):
    """回傳 (行列表, 實際列出的原始列)。
    【策略】一行績效 → ◆ 時點＋動作 N 檔 → 同組共同條件一行 → 每檔一行（個別說明接在後面或下一行）。"""
    ents = [_entry(r, "B") for r in (tmr or [])] + [_entry(r, "S") for r in (stg or [])]
    groups = OrderedDict()
    for e in ents:
        groups.setdefault(e["g"], []).append(e)

    def gorder(es):
        return (min(TIMING_ORDER.get(e["timing"], 2) for e in es), es[0]["title"])

    out = []
    for es in sorted(groups.values(), key=gorder):
        out += ["", f"【{es[0]['title']}】"]
        if es[0]["stat"]:
            out.append(es[0]["stat"])
        if es[0]["note"]:
            out.append("※" + es[0]["note"])
        subs = OrderedDict()
        for e in es:
            subs.setdefault((e["timing"], e["action"]), []).append(e)
        for (timing, action), xs in sorted(subs.items(), key=lambda kv: (
                TIMING_ORDER.get(kv[0][0], 2), ACT_ORDER.get(kv[0][1], 9), kv[0][1])):
            when = f"{timing}{action}" if timing in TIMING_ORDER else (
                f"{action}（{timing}）" if timing else action)
            out.append(f"◆ {when} {len(xs)} 檔" + ("（若有持倉）" if xs[0]["exit"] else ""))
            common = [f for f in xs[0]["frags"] if all(f in x["frags"] for x in xs)] if len(xs) > 1 else []
            if common:
                out.append("　" + "｜".join(common))
            for x in xs:
                rest = "｜".join(f for f in x["frags"] if f not in common)
                head = f"・{x['name']} {x['code']}".rstrip()
                if rest and _w(head + "　" + rest) <= 21:
                    out.append(f"{head}　{rest}")
                else:
                    out.append(head)
                    if rest:
                        out.append("　　" + rest)
    return out, [e["row"] for e in ents]


def compose(now, tmr, stg, run, next_day, problems, watch=None, late=False, prep=None, chg=None):
    """回傳 (訊息文字, 有列進訊息的原始列)。"""
    head_day = md(next_day) if next_day else "下一個交易日"
    if late:
        out = [f"補充提醒｜{head_day}（稍晚公布的資料）"]
        out += [f"⚠ {p}" for p in problems]
        shown = []
        if tmr or stg:
            lines, shown = render_items(tmr, stg)
            out += ["", "▍新增"] + lines
        out += change_lines(chg)
        return fit("\n".join(out + ["", site(next_day)])), shown
    out = [f"交易提醒｜{head_day} 要做的事"]

    if run:
        t = dt.datetime.fromisoformat((run.get("finished_at") or run["started_at"]).replace("Z", "+00:00"))
        label = {"success": "正常", "partial": "部分失敗", "failed": "失敗",
                 "running": "執行中"}.get(run.get("status"), run.get("status"))
        stale = "（超過 30 小時，可能過期）" if (now - t).total_seconds() > 30 * 3600 else ""
        out.append(f"資料更新：{t.astimezone(TPE):%m/%d %H:%M} {label}{stale}")
    for p in problems:
        out.append(f"⚠ {p}")

    t_rows = sorted((r for r in (tmr or []) if r.get("due_label") == "明天"), key=lambda r: r.get("sort_key") or 0)
    s_rows = [r for r in (stg or []) if r.get("due_label") == "明天"]
    shown = []
    out.append("")
    if t_rows or s_rows:
        out.append(f"▍明天 {head_day}　{len(t_rows) + len(s_rows)} 筆")
        lines, shown = render_items(t_rows, s_rows)
        out += lines
    elif tmr is None and stg is None:
        out.append("無法讀取待辦清單，請直接開網站確認。")
    else:
        out.append(f"明天 {head_day} 沒有要進出場的部位。")

    out += change_lines(chg)
    out += watch_lines(watch)
    out += prep or []

    out += ["", site(next_day)]

    return fit("\n".join(out)), shown


def site(day):
    """網站連結帶目標日期：點開就是這則通知指的那一天，舊連結會標成歷史。"""
    return f"{SITE}?d={day.isoformat()}" if day else SITE


def u16(s):
    return len(s.encode("utf-16-le")) // 2


def _hard_cut(u, limit):
    """單一卡片就超長（極少見）：先按行、再按字切，長度一律用 UTF-16 計。"""
    out, buf = [], ""
    for ln in u.split("\n"):
        while u16(ln) > limit:
            i, n = 0, 0
            while i < len(ln) and n + u16(ln[i]) <= limit:
                n += u16(ln[i]); i += 1
            if buf:
                out.append(buf); buf = ""
            out.append(ln[:i]); ln = ln[i:]
        cand = f"{buf}\n{ln}" if buf else ln
        if u16(cand) <= limit:
            buf = cand
        else:
            out.append(buf); buf = ln
    return out + ([buf] if buf else [])


def split_msgs(text, limit=4800):
    """切成多則，每則 ≤ limit（UTF-16 單位，和 LINE 的算法一致）。
    以卡片（【…】）、段落標題（▍）、空行為單位，卡片不會被從中間切開；不截尾。"""
    units, cur = [], []
    for ln in text.split("\n"):
        if cur and (ln == "" or ln.startswith(("【", "▍"))):
            units.append("\n".join(cur)); cur = []
        cur.append(ln)
    if cur:
        units.append("\n".join(cur))
    msgs, buf = [], ""
    for u in units:
        cand = f"{buf}\n{u}" if buf else u
        if u16(cand) <= limit:
            buf = cand
            continue
        if buf.strip():
            msgs.append(buf.strip("\n"))
        buf = ""
        if u16(u) > limit:
            pieces = _hard_cut(u, limit)
            msgs += [x for x in pieces[:-1] if x.strip()]
            u = pieces[-1] if pieces else ""
        buf = u
    if buf.strip():
        msgs.append(buf.strip("\n"))
    return msgs


def fit(text):
    return text  # 不再截尾：超過 5 則由 push_line 分批送


def push_line(text):
    """LINE 一次最多 5 則；更多就分批送，每批都要成功。"""
    msgs, status = split_msgs(text), None
    for i in range(0, len(msgs), 5):
        req = urllib.request.Request(
            "https://api.line.me/v2/bot/message/push", method="POST",
            data=json.dumps({"to": os.environ["LINE_USER_ID"].strip(),
                             "messages": [{"type": "text", "text": t} for t in msgs[i:i + 5]]}).encode(),
            headers={"Authorization": "Bearer " + os.environ["LINE_CHANNEL_ACCESS_TOKEN"].strip(),
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            status = r.status
    return status


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
    if os.environ.get("SPLIT_OUTCOME", "success") != "success":
        out.append("分割訊號更新失敗，A06 今天可能漏掉換股公告後的進場提醒")
    if os.environ.get("BUYBACK_OUTCOME", "success") != "success":
        out.append("庫藏股同步失敗，A03 今天的新訊號可能沒列出，請開網站「庫藏股」確認")
    if os.environ.get("DISPOSAL_OUTCOME", "success") != "success":
        out.append("處置股訊號更新失敗，A02 今天可能漏掉新處置（明天會再算最近 30 天）")
    if os.environ.get("EXRIGHT_OUTCOME", "success") != "success":
        out.append("除權息預告表抓取失敗，A11 今天可能漏掉 T-5 進場的訊號")
    if cal:
        out += unregistered_closures(cal, today)
    out += index_review_notice(today)
    st = read_out("market_status.json")
    if cal and cal.is_trading(today):
        if not st or st.get("d") != today.isoformat():
            out.append("今天的行情還沒抓到，事件型策略用的是前一個交易日的資料；A11 明天 T-5 進場的試算也做不了（T-6 收盤缺）")
        else:
            if not st.get("has_otc"):
                out.append("上櫃行情沒抓到，014 跌停家數今天不判斷")
            if not st.get("has_margin"):
                out.append("融資餘額尚未公布，020 今天稍晚（22:37）再判斷，有訊號會補推")
    return out


def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(TPE).date()
    # 以 workflow 開始執行時的台北日期為準：跑到午夜後才推，也不會被算成隔天的主推播
    rd = (os.environ.get("RUN_DAY") or "").strip()
    if rd:
        try:
            run_day = dt.date.fromisoformat(rd)
            if run_day != today:
                print(f"執行開始日 {run_day}，送出時已是 {today}：以 {run_day} 為今天")
                today = run_day
        except ValueError:
            print(f"RUN_DAY 格式不對（{rd!r}），改用目前日期")
    late = os.environ.get("LATE") == "1"
    problems = []
    if not late and os.environ.get("DRY_RUN") != "1" and os.environ.get("FORCE") != "1":
        # 同一天主推播已成功送出就不再送（GitHub 備援排程常延遲數小時，曾在 23:35／23:48 重複主推播）
        start = dt.datetime.combine(today, dt.time(0), TPE).astimezone(dt.timezone.utc).isoformat()
        sent, _ = safe(lambda: supa(f"push_messages?select=id&mode=eq.main&status=eq.200"
                                    f"&sent_at=gte.{start.replace('+', '%2B')}&limit=1"))
        if sent:
            print("今天的主推播已成功送出，不重複推送")
            return

    tmr, e1 = safe(lambda: supa("v_tomorrow?select=*"))
    if tmr:  # 舊板塊的處置、分割買賣和總表規則不同，改由 A02／A06（strategy_actions）提醒
        # IPO（申購、抽籤、掛牌、開標…）Ed 2026-10-19 指示先不推播；網站照常顯示
        tmr = [r for r in tmr if not old_trade(r) and r.get("block_code") != "ipo"]
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

    if hol and next_day and not cal.is_trading(today) and tmr is not None:
        # 非交易日：舊板塊的「明天」不可靠，改以 next_day 從 signals 重建（處置／分割本來就濾掉）
        extra, e3 = safe(lambda: old_board_for(next_day.isoformat()))
        if e3:
            problems.append(f"舊板塊（庫藏股等）{md(next_day)} 待辦讀取失敗，請開網站確認：{e3}")
        else:
            tmr = [r for r in tmr if r.get("due_label") != "明天" or r.get("block_code") not in OLD_NAMES] + (extra or [])
    problems += market_problems(today, cal if hol else None)
    problems += read_out("warn017.json") or []  # cash_issue.py：017 查不到認購比例
    problems += read_out("warn_a02.json") or []  # disposal_signals.py：處置天數不符、未自動取消
    if late:
        # 晚間補推：只推第一次推播之後才出現的「明天」策略訊號
        stg = [r for r in (stg or []) if r.get("due_label") == "明天" and not r.get("notified_at")]
        sent, _ = safe(lambda: {x["key"] for x in supa(f"intraday_alerts?select=key&d=eq.{today.isoformat()}&key=like.tmr:*")})
        tmr = [r for r in (tmr or []) if r.get("due_label") == "明天" and board_key(r) not in (sent or set())] if sent is not None else []
        problems = [p for p in problems if "融資" not in p]
        warned, _ = safe(lambda: {x["key"] for x in supa(f"intraday_alerts?select=key&d=eq.{today.isoformat()}&key=like.warn:*")})
        problems = [p for p in problems if warn_key(p) not in (warned or set())]
        chg = changes(today)
        if not stg and not tmr and not problems and not chg:
            print("沒有新增訊號，不補推")
            if any(os.environ.get(k, "success") != "success" for k in
                   ("CAL_OUTCOME", "MARKET_OUTCOME", "EVENT_OUTCOME", "CASH_OUTCOME", "INSIDER_OUTCOME", "EXRIGHT_OUTCOME", "DISPOSAL_OUTCOME", "SPLIT_OUTCOME", "BUYBACK_OUTCOME")):
                sys.exit(1)  # 警告稍早已推過；仍讓 Actions 顯示紅燈
            return
        text, shown = compose(now, tmr, stg, None, next_day, problems, late=True, chg=chg)
    else:
        chg = changes(today)
        text, shown = compose(now, tmr, stg, (runs or [None])[0], next_day, problems, read_out("watch010.json"),
                       prep=index_prep(cal if hol else None, today) + msci_prep(cal if hol else None, today), chg=chg)
    print(text)
    if os.environ.get("DRY_RUN") == "1":
        print("\nDRY_RUN：不推送")
    else:
        status = push_line(text)
        print("\nLINE 回應", status)
        done_chg = [c for c in chg if c[1] in text]
        log_push("late" if late else "main", text, status, today,
                 log_items(text, shown, None if late else read_out("watch010.json"), next_day)
                 + [{"source": r["strategy_id"], "code": r["company_code"], "name": r["company_name"],
                     "action": r["action"], "act_date": r["act_date"], "act_timing": r.get("act_timing"),
                     "line": ln} for _, ln, r in done_chg])
        shown_ids = {id(r) for r in shown}  # 有列進訊息的才標記（訊息不截尾，分批全部送出）
        sent_rows = [r for r in (stg or []) if r.get("due_label") == "明天" and r.get("id")
                     and id(r) in shown_ids]
        ids = [str(r["id"]) for r in sent_rows]
        if ids:
            safe(lambda: supa(f"strategy_actions?id=in.({','.join(ids)})", "PATCH",
                              {"notified_at": now.isoformat()}))
        keys = [{"d": today.isoformat(), "key": board_key(r)} for r in (tmr or [])
                if r.get("due_label") == "明天" and id(r) in shown_ids]
        keys += [{"d": today.isoformat(), "key": warn_key(p)} for p in problems]
        # 記下每筆推出去的日期，之後日期改了或作廢才分得出「更正／取消」
        keys += [{"d": today.isoformat(), "key": sent_key(r, now)} for r in sent_rows]
        keys += [{"d": today.isoformat(), "key": k} for k, _, _ in done_chg if k]  # 取消
        keys += [{"d": today.isoformat(), "key": sent_key(r, now)} for k, _, r in done_chg if not k]  # 更正後的新內容
        keys = list({k["key"]: k for k in keys}.values())
        if keys:
            safe(lambda: supa("intraday_alerts?on_conflict=d,key", "POST", keys,
                              prefer="resolution=ignore-duplicates,return=minimal"))
    failed = [k for k in ("CAL_OUTCOME", "MARKET_OUTCOME", "EVENT_OUTCOME", "CASH_OUTCOME", "INSIDER_OUTCOME", "EXRIGHT_OUTCOME", "DISPOSAL_OUTCOME", "SPLIT_OUTCOME", "BUYBACK_OUTCOME")
              if os.environ.get(k, "success") != "success"]
    if (tmr is None and stg is None) or failed:
        sys.exit(1)  # 訊息已送出；讓 Actions 顯示紅燈，不要靜靜綠燈


if __name__ == "__main__":
    main()
