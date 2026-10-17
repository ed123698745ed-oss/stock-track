"""推播週報：從 push_messages 原文解析。
- render()：週報，依「執行日」分章、去重，補推新增與更正分開標示。
- ledger()：依策略排序的推播明細（寫入 Drive《推播總表》用），並和 strategy_actions 應推項目對帳，標出漏推。

用法：
  python3 scripts/push_report.py raw.json        # 讀 export_push_log.py RAW=1 的 JSON
以訊息原文為準（push_log 在 PR35 前主推播項目為 0 筆，不能當唯一來源）。
"""
import datetime as dt
import json
import re
import sys
from collections import OrderedDict

TPE = dt.timezone(dt.timedelta(hours=8))
WD = "一二三四五六日"
MODE = {"main": "主推播", "late": "補推", "intraday": "盤中提醒"}
TIMING = {"open": "開盤", "close": "收盤"}

HEAD = re.compile(r"(?:交易提醒|補充提醒)｜(\d{1,2})/(\d{1,2})")
INTRA = re.compile(r"盤中提醒 (\d{1,2})/(\d{1,2})")
ITEM = re.compile(r"^【([^】]+)】(?:(開盤|收盤)　)?(.+?) (\w+)$")
FIX = re.compile(r"^【更正】(.+?)｜(.+?) (\w+) (\S+)$")
INTRA_ITEM = re.compile(r"^【(\S+) ([^】]+)】(.+?) (\w+)（(.+)）$")
WATCH = re.compile(r"^(\S.*?) (\w+)　(已連 \d+ 根漲停)$")
MOVED = re.compile(r"改為 (\d{1,2})/(\d{1,2})")

LEDGER_COLS = ["策略", "代號", "名稱", "動作", "執行日", "時點", "狀態", "首次推播", "推播類型",
               "LINE回應", "更正", "週報"]


def tpe(ts):
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TPE)


def target_day(text, sent):
    m = HEAD.search(text) or INTRA.search(text)
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    y = sent.year + (1 if mo < sent.month - 6 else 0)
    return dt.date(y, mo, d)


def parse(text):
    """回傳 (items, fixes, watch)。item: strategy, name, code, action, timing, detail。"""
    items, fixes, watch = [], [], []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        body = []
        j = i + 1
        while j < len(lines) and lines[j].startswith("　"):
            body.append(lines[j].strip())
            j += 1
        if m := FIX.match(ln):
            fixes.append({"strategy": m.group(1).split(" ")[0], "name": m.group(2), "code": m.group(3),
                          "action": m.group(4), "detail": "；".join(body)})
        elif m := INTRA_ITEM.match(ln):
            items.append({"strategy": m.group(1), "name": m.group(3), "code": m.group(4), "action": m.group(2),
                          "timing": "盤中", "detail": m.group(5) + ("；" + "；".join(body) if body else "")})
        elif m := ITEM.match(ln):
            sline = body[0] if body else ""
            if sline.startswith("IPO"):
                strat, rest = "IPO", body
            else:
                strat, rest = sline.split(" ")[0] or "?", body[1:]
            detail = "；".join(x for x in rest if not x.startswith("平均"))
            items.append({"strategy": strat, "name": m.group(3), "code": m.group(4), "action": m.group(1),
                          "timing": m.group(2) or "", "detail": detail})
        elif m := WATCH.match(ln):
            watch.append({"name": m.group(1), "code": m.group(2), "detail": m.group(3)})
        i = j if j > i + 1 else i + 1
    return items, fixes, watch


def key(it):
    return (it["strategy"], it["code"], it["action"])


def prepare(messages):
    msgs = []
    for m in messages:
        sent = tpe(m["sent_at"])
        msgs.append(dict(m, sent=sent, day=target_day(m["text"], sent)))
    return msgs


def build_days(msgs):
    """每個執行日：去重後的項目（含來源、首次推播時間、回應碼）、更正、盯盤、重複推播說明。"""
    days = OrderedDict()
    for m in sorted(msgs, key=lambda x: (x["day"] or dt.date.min, x["sent"])):
        days.setdefault(m["day"], []).append(m)
    out = OrderedDict()
    for d, ms in days.items():
        if d is None:
            continue
        rows, fixes, watch, dup = OrderedDict(), [], OrderedDict(), []
        base_done = False
        for m in ms:
            items, fx, wt = parse(m["text"])
            label = MODE.get(m["mode"], m["mode"])
            meta = {"sent": m["sent"], "status": m["status"], "mode": m["mode"]}
            if m["mode"] == "main" and base_done:
                new = [it for it in items if key(it) not in rows]
                dup.append(f"{m['sent']:%m/%d %H:%M} 重複主推播："
                           + ("內容已涵蓋於同日較早的推播，不重列。" if not new
                              else f"另含 {len(new)} 項前面沒有的項目，已標「重複主推播」列入。"))
                for it in new:
                    rows[key(it)] = dict(it, **meta, src=f"重複主推播 {m['sent']:%H:%M}")
                continue
            for it in items:
                if key(it) in rows:
                    continue
                src = label if m["mode"] == "main" else f"{label} {m['sent']:%m/%d %H:%M}"
                rows[key(it)] = dict(it, **meta, src=src)
            for f in fx:
                fixes.append(dict(f, src=f"補推 {m['sent']:%m/%d %H:%M}"))
            for x in wt:
                watch.setdefault(x["code"], x)
            if m["mode"] == "main":
                base_done = True
        out[d] = {"msgs": ms, "rows": rows, "fixes": fixes, "watch": watch, "dup": dup}
    return out


def fix_note(f, d):
    note = f"⚠ 已更正：{f['detail']}（{f['src']}）"
    mv = MOVED.search(f["detail"])
    if mv and (int(mv.group(1)), int(mv.group(2))) != (d.month, d.day):
        note += "；執行日已移出本日"
    return note


def render(messages, start, end, generated, ledger_url=None, missed=None):
    msgs = prepare(messages)
    days = build_days(msgs)
    out = []
    w = out.append
    w(f"# 推播紀錄 {start:%Y/%m/%d}～{end:%Y/%m/%d}\n")
    w(f"- 時區：Asia/Taipei（UTC+8）")
    w(f"- 產生時間：{generated:%Y-%m-%d %H:%M}")
    if msgs:
        w(f"- 資料實際起訖：{min(m['sent'] for m in msgs):%m/%d %H:%M}～{max(m['sent'] for m in msgs):%m/%d %H:%M}"
          f"（Supabase push_messages 原文，共 {len(msgs)} 則）")
    else:
        w("- ⚠ 本週沒有任何推播紀錄")
    w("- 整理方式：以「要執行的日子」為單位；同一標的同一動作只列一次；補推新增的項目標「補推」，"
      "更正標在原項目；重複推送只記時間，不重列內容。訊息送出不等於成交。")
    if ledger_url:
        w(f"- 依策略查詢：《推播總表》{ledger_url}")
    w("")
    if missed:
        w("## ⚠ 漏推（策略訊號有、推播沒有）\n")
        w("| 策略 | 標的 | 動作 | 執行日 | 時點 |\n|---|---|---|---|---|")
        for r in missed:
            w(f"| {r['策略']} | {r['名稱']} {r['代號']} | {r['動作']} | {r['執行日']} | {r['時點']} |")
        w("")

    w("## 訊息總覽\n")
    w("| 送出時間 | 類型 | 對應執行日 | LINE 回應 | 備註 |\n|---|---|---|---|---|")
    notes = {}
    for d, info in days.items():
        first = None
        for m in info["msgs"]:
            if m["mode"] == "main":
                if first is None:
                    first = m
                else:
                    notes[m["id"]] = f"重複主推播（同日已於 {first['sent']:%H:%M} 送出）"
    for m in sorted(msgs, key=lambda x: x["sent"]):
        dd = f"{m['day']:%m/%d}({WD[m['day'].weekday()]})" if m["day"] else "—"
        w(f"| {m['sent']:%m/%d %H:%M} | {MODE.get(m['mode'], m['mode'])} | {dd} | {m['status']} | {notes.get(m['id'], '')} |")
    w("")

    for d, info in days.items():
        w(f"## {d:%m/%d}({WD[d.weekday()]}) 要做的事\n")
        mains = [m for m in info["msgs"] if m["mode"] == "main"]
        if mains:
            w(f"主推播：{mains[0]['sent']:%m/%d %H:%M} 送出，LINE {mains[0]['status']}。")
        for m in info["msgs"]:
            if m["mode"] != "main":
                w(f"{MODE.get(m['mode'], m['mode'])}：{m['sent']:%m/%d %H:%M} 送出，LINE {m['status']}。")
        for x in info["dup"]:
            w(x)
        w("")
        fixed = {(f["strategy"], f["code"], f["action"]): f for f in info["fixes"]}
        w("| # | 策略 | 標的 | 動作 | 時點 | 說明 | 來源 |\n|---|---|---|---|---|---|---|")
        for n, it in enumerate(info["rows"].values(), 1):
            f = fixed.get(key(it))
            note = fix_note(f, d) if f else it["detail"]
            w(f"| {n} | {it['strategy']} | {it['name']} {it['code']} | {it['action']} | {it['timing']} | {note} | {it['src']} |")
        w("")
        orphan = [f for k, f in fixed.items() if k not in info["rows"]]
        if orphan:
            w("更正（原項目不在本日主推播）：\n")
            for f in orphan:
                w(f"- {f['strategy']} {f['name']} {f['code']} {f['action']}：{f['detail']}（{f['src']}）")
            w("")
        if info["watch"]:
            w("盯盤（010 開板放空）：" + "、".join(f"{x['name']} {x['code']}（{x['detail']}）"
                                          for x in info["watch"].values()) + "\n")

    w("## 附錄：訊息原文\n")
    for m in sorted(msgs, key=lambda x: x["sent"]):
        w(f"### {m['sent']:%m/%d %H:%M}｜{MODE.get(m['mode'], m['mode'])}｜LINE {m['status']}\n")
        w("```\n" + m["text"] + "\n```\n")
    return "\n".join(out)


def ledger(messages, expected=(), report_name=""):
    """依策略排序的明細列（LEDGER_COLS），以及漏推清單。

    expected：strategy_actions 中「推播時間已過」的應推項目
      （strategy_id, company_code, company_name, action, act_date, act_timing）。
    已推送列狀態為「已推播」或「已推播（已更正）」；應推但沒推的列為「⚠ 漏推」。
    """
    days = build_days(prepare(messages))
    rows, pushed = [], set()
    for d, info in days.items():
        fixed = {(f["strategy"], f["code"], f["action"]): f for f in info["fixes"]}
        for it in info["rows"].values():
            f = fixed.get(key(it))
            status = "已推播"
            if it["status"] != 200:
                status = f"⚠ LINE 回應 {it['status']}"
            elif f:
                status = "已推播（已更正）"
            rows.append({"策略": it["strategy"], "代號": it["code"], "名稱": it["name"], "動作": it["action"],
                         "執行日": d.isoformat(), "時點": it["timing"], "狀態": status,
                         "首次推播": f"{it['sent']:%Y-%m-%d %H:%M}", "推播類型": it["src"].split(" ")[0],
                         "LINE回應": it["status"], "更正": f["detail"] if f else "", "週報": report_name})
            pushed.add((it["strategy"], it["code"], it["action"]))
    missed = []
    for e in expected:
        k = (e["strategy_id"], e["company_code"], e["action"])
        if k in pushed:
            continue
        r = {"策略": e["strategy_id"], "代號": e["company_code"], "名稱": e["company_name"], "動作": e["action"],
             "執行日": e["act_date"], "時點": TIMING.get(e.get("act_timing"), ""), "狀態": "⚠ 漏推",
             "首次推播": "", "推播類型": "", "LINE回應": "", "更正": "", "週報": report_name}
        missed.append(r)
        rows.append(r)
    rows.sort(key=lambda r: (r["策略"], r["執行日"], r["代號"], r["動作"]))
    return rows, missed


if __name__ == "__main__":
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    now = dt.datetime.now(TPE)
    rows, missed = ledger(d["messages"], d.get("expected", []))
    print(render(d["messages"], now.date() - dt.timedelta(days=7), now.date(), now, missed=missed))
    print(f"\n# 總表列 {len(rows)}，漏推 {len(missed)}", file=sys.stderr)
