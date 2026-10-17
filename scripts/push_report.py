"""推播週報：從 push_messages 原文解析，依「執行日」分章、去重，補推新增與更正分開標示。

用法：
  python3 scripts/push_report.py raw.json        # 讀 export_push_log.py RAW=1 的 JSON
  render(messages, start, end, generated)         # 給 export_push_log.py 呼叫
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

HEAD = re.compile(r"(?:交易提醒|補充提醒)｜(\d{1,2})/(\d{1,2})")
INTRA = re.compile(r"盤中提醒 (\d{1,2})/(\d{1,2})")
ITEM = re.compile(r"^【([^】]+)】(?:(開盤|收盤)　)?(.+?) (\w+)$")
FIX = re.compile(r"^【更正】(.+?)｜(.+?) (\w+) (\S+)$")
INTRA_ITEM = re.compile(r"^【(\S+) ([^】]+)】(.+?) (\w+)（(.+)）$")
WATCH = re.compile(r"^(\S.*?) (\w+)　(已連 \d+ 根漲停)$")


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


def render(messages, start, end, generated, extra_days=None):
    msgs = []
    for m in messages:
        sent = tpe(m["sent_at"])
        msgs.append(dict(m, sent=sent, day=target_day(m["text"], sent)))
    days = OrderedDict()
    for m in sorted(msgs, key=lambda x: (x["day"] or dt.date.min, x["sent"])):
        days.setdefault(m["day"], []).append(m)

    out = []
    w = out.append
    w(f"# 推播紀錄 {start:%Y/%m/%d}～{end:%Y/%m/%d}\n")
    w(f"- 時區：Asia/Taipei（UTC+8）")
    w(f"- 產生時間：{generated:%Y-%m-%d %H:%M}")
    if msgs:
        w(f"- 資料實際起訖：{min(m['sent'] for m in msgs):%m/%d %H:%M}～{max(m['sent'] for m in msgs):%m/%d %H:%M}"
          f"（Supabase push_messages 原文，共 {len(msgs)} 則）")
    w("- 整理方式：以「要執行的日子」為單位；同一標的同一動作只列一次；補推新增的項目標「補推」，"
      "更正另列；重複推送只記時間，不重列內容。訊息送出不等於成交。\n")

    w("## 訊息總覽\n")
    w("| 送出時間 | 類型 | 對應執行日 | LINE 回應 | 備註 |\n|---|---|---|---|---|")
    notes = {}
    for d, ms in days.items():
        seen_main = None
        for m in ms:
            if m["mode"] == "main":
                if seen_main is None:
                    seen_main = m
                else:
                    notes[m["id"]] = f"重複主推播（同日已於 {seen_main['sent']:%H:%M} 送出）"
    for m in sorted(msgs, key=lambda x: x["sent"]):
        dd = f"{m['day']:%m/%d}({WD[m['day'].weekday()]})" if m["day"] else "—"
        w(f"| {m['sent']:%m/%d %H:%M} | {MODE.get(m['mode'], m['mode'])} | {dd} | {m['status']} | {notes.get(m['id'], '')} |")
    w("")

    for d, ms in list(days.items()) + list((extra_days or {}).items()):
        if d is None:
            continue
        if isinstance(ms, str):  # 外部補充說明（例如資料庫啟用前的日子）
            continue
        w(f"## {d:%m/%d}({WD[d.weekday()]}) 要做的事\n")
        rows, fixes, watch, dup = OrderedDict(), [], OrderedDict(), []
        base_done = False
        for m in ms:
            items, fx, wt = parse(m["text"])
            label = MODE.get(m["mode"], m["mode"])
            if m["mode"] == "main" and base_done:
                new = [it for it in items if key(it) not in rows]
                dup.append(f"{m['sent']:%m/%d %H:%M} 重複主推播："
                           + ("內容已涵蓋於同日較早的推播，不重列。" if not new
                              else f"另含 {len(new)} 項前面沒有的項目，已標「重複主推播」列入。"))
                for it in new:
                    rows[key(it)] = dict(it, src=f"重複主推播 {m['sent']:%H:%M}")
                continue
            for it in items:
                if key(it) in rows:
                    continue
                src = label if m["mode"] == "main" else f"{label} {m['sent']:%m/%d %H:%M}"
                rows[key(it)] = dict(it, src=src)
            for f in fx:
                fixes.append(dict(f, src=f"補推 {m['sent']:%m/%d %H:%M}"))
            for x in wt:
                watch.setdefault(x["code"], x)
            if m["mode"] == "main":
                base_done = True
        mains = [m for m in ms if m["mode"] == "main"]
        if mains:
            m0 = mains[0]
            w(f"主推播：{m0['sent']:%m/%d %H:%M} 送出，LINE {m0['status']}。")
        for m in ms:
            if m["mode"] != "main":
                w(f"{MODE.get(m['mode'], m['mode'])}：{m['sent']:%m/%d %H:%M} 送出，LINE {m['status']}。")
        for x in dup:
            w(x)
        w("")
        fixed = {(f["strategy"], f["code"], f["action"]): f for f in fixes}
        w("| # | 策略 | 標的 | 動作 | 時點 | 說明 | 來源 |\n|---|---|---|---|---|---|---|")
        for n, it in enumerate(rows.values(), 1):
            note = it["detail"]
            f = fixed.get(key(it))
            if f:
                note = f"⚠ 已更正：{f['detail']}（{f['src']}）"
                if "改為" in f["detail"] and f"改為 {d.month}/{d.day}(" not in f["detail"]:
                    note += "；執行日已移出本日"
            w(f"| {n} | {it['strategy']} | {it['name']} {it['code']} | {it['action']} | {it['timing']} | {note} | {it['src']} |")
        w("")
        orphan = [f for k, f in fixed.items() if k not in rows]
        if orphan:
            w("更正（原項目不在本日主推播）：\n")
            for f in orphan:
                w(f"- {f['strategy']} {f['name']} {f['code']} {f['action']}：{f['detail']}（{f['src']}）")
            w("")
        if watch:
            w("盯盤（010 開板放空）：" + "、".join(f"{x['name']} {x['code']}（{x['detail']}）" for x in watch.values()) + "\n")

    w("## 附錄：訊息原文\n")
    for m in sorted(msgs, key=lambda x: x["sent"]):
        w(f"### {m['sent']:%m/%d %H:%M}｜{MODE.get(m['mode'], m['mode'])}｜LINE {m['status']}\n")
        w("```\n" + m["text"] + "\n```\n")
    return "\n".join(out)


if __name__ == "__main__":
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    now = dt.datetime.now(TPE)
    print(render(d["messages"], now.date() - dt.timedelta(days=7), now.date(), now))
