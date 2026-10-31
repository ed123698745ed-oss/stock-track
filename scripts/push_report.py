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
MODE = {"main": "主推播", "late": "補推", "intraday": "盤中提醒", "closure": "臨時休市通知", "closure_check": "休市待確認"}
TIMING = {"open": "開盤", "close": "收盤"}

HEAD = re.compile(r"(?:交易提醒|補充提醒)｜(\d{1,2})/(\d{1,2})")
INTRA = re.compile(r"盤中提醒 (\d{1,2})/(\d{1,2})")
ITEM = re.compile(r"^【([^】]+)】(?:(開盤|收盤)　)?(.+?) (\w+)$")
FIX = re.compile(r"^【更正】(.+?)｜(.+?) (\w+) (\S+)$")
INTRA_ITEM = re.compile(r"^【(\S+) ([^】]+)】(.+?) (\w+)（(.+)）$")
WATCH = re.compile(r"^(\S.*?) (\w+)　(已連 \d+ 根漲停)$")
MOVED = re.compile(r"改為 (\d{1,2})/(\d{1,2})")
# 2026-10-20 起的分組排版：【策略】→ ◆ 時點動作 N 檔 → ・名稱 代號
GROUP = re.compile(r"^【(\S+) ([^】]+)】$")
SUB = re.compile(r"^◆ (開盤|收盤)?(\S+?)(?:（[^）]*）)? \d+ 檔")
ITEM2 = re.compile(r"^・(.+?) (\w+)(?:　(.*))?$")

ALIAS = {"開板放空": "放空"}  # 010 盤中提醒的動作名稱
INTRA_010 = "盤中提醒／收盤執行（條件成立才放空）"  # 010 開板放空：盤中只是提醒，收盤仍沒漲停才放空
# 核准版本（測試版本／進出場）。來源：可執行策略總表 1C4NExodXR0EY0zRhiQ4bpuGz7jdfYM_duPX_diFrGwE
# 分頁 Bot可執行策略 欄 測試版本／進出場；新策略上線要一併補
APPROVED = {"004": "V02/R02", "010": "V01/R04", "019": "V01/R03"}
LEDGER_COLS = ["策略", "代號", "名稱", "動作", "執行日", "時點", "狀態", "首次推播", "推播類型",
               "LINE回應", "更正", "週報", "核准V/R"]  # 新欄只加在最後，不動 Drive 總表既有欄位


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
    grp, sub, common = None, None, ""
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
            timing = m.group(2) or ""
            sid = next((re.match(r"(A\d{2}|\d{3})｜", x).group(1) for x in body if re.match(r"(A\d{2}|\d{3})｜", x)), None)
            if sline.startswith("IPO"):
                strat, rest = "IPO", body
            elif sid and "｜" in sline and not re.match(r"(A\d{2}|\d{3})｜", sline):
                # 舊板塊格式：「庫藏股｜開盤買進　目的…」＋「A03｜平均…」→ 策略取 A03，時點取開盤／收盤
                head, tail = sline.split("｜", 1)
                strat = sid
                timing = timing or (re.search(r"開盤|收盤", tail).group(0) if re.search(r"開盤|收盤", tail) else "")
                rest = [re.sub(r"^(開盤|收盤)(買進|賣出)\s*", "", tail).strip()] + [x for x in body[1:] if not x.startswith(sid + "｜")]
            else:
                strat, rest = sline.split(" ")[0] or "?", body[1:]
            detail = "；".join(x for x in rest if x and not x.startswith("平均"))
            items.append({"strategy": strat, "name": m.group(3), "code": m.group(4), "action": m.group(1),
                          "timing": timing, "detail": detail})
        elif m := GROUP.match(ln):
            grp, sub, common = m.group(1), None, ""
        elif (m := SUB.match(ln)) and grp:
            sub, common = (m.group(1) or ("盤中" if INTRA.search(text) else ""), m.group(2)), "；".join(body)
        elif (m := ITEM2.match(ln)) and grp and sub:
            detail = "；".join(x for x in [m.group(3) or ""] + body + [common] if x)
            items.append({"strategy": grp, "name": m.group(1), "code": m.group(2), "action": sub[1],
                          "timing": sub[0], "detail": detail})
        elif m := WATCH.match(ln):
            watch.append({"name": m.group(1), "code": m.group(2), "detail": m.group(3)})
        i = j if j > i + 1 else i + 1
    return items, fixes, watch


def key(it):
    return (it["strategy"], it["code"], it["action"])


def timing_label(it):
    return INTRA_010 if it["timing"] == "盤中" and it["action"] == "開板放空" else it["timing"]


def approved(sid):
    return APPROVED.get(sid, "待補／見策略總表")


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


def moved_to(f, d):
    """更正把執行日改到別天 → 新日期；同一天（只改時點或補出場日）→ None。"""
    mv = MOVED.search(f["detail"])
    if not mv:
        return None
    mo, dd = int(mv.group(1)), int(mv.group(2))
    if (mo, dd) == (d.month, d.day):
        return None
    y = d.year + (1 if mo < d.month - 6 else -1 if mo > d.month + 6 else 0)
    return dt.date(y, mo, dd)


def fix_kind(f, d):
    """更正種類：改執行日／補出場日（日期時點都沒變，只多了出場日）／已更正（其他，例如改時點）。"""
    if moved_to(f, d):
        return "改執行日"
    m = re.match(r"原 (.+?) → 改為 (.+?)(｜|$)", f["detail"])
    if m and m.group(1).strip() == m.group(2).strip() and "出場" in f["detail"]:
        return "補出場日"
    return "已更正"


def fix_note(f, d):
    kind = fix_kind(f, d)
    label = "補出場日" if kind == "補出場日" else "已更正"
    note = f"⚠ {label}：{f['detail']}（{f['src']}）"
    if kind == "改執行日":
        note += "；執行日已移出本日"
    return note


def render(messages, start, end, generated, ledger_url=None, missed=None, check_note=None, push_alerts=None,
           appendix=None):
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
    if check_note:
        w(f"- {check_note}")
    if ledger_url:
        w(f"- 依策略查詢：《推播總表》{ledger_url}")
    w("")
    if push_alerts:
        w("## ⚠ 主推播時間異常\n")
        w("⑦ 主推播送出時間不在 19:00～23:59；⑧ 某交易日開盤前沒收到成功的主推播（依目標交易日判斷，休市日不算）。請人工確認內容與日期。\n")
        for a in push_alerts:
            w(f"- {a}")
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
            w(f"| {n} | {it['strategy']} | {it['name']} {it['code']} | {it['action']} | {timing_label(it)} | {note} | {it['src']} |")
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

    if appendix:
        w(appendix)
    w("## 附錄：訊息原文\n")
    for m in sorted(msgs, key=lambda x: x["sent"]):
        w(f"### {m['sent']:%m/%d %H:%M}｜{MODE.get(m['mode'], m['mode'])}｜LINE {m['status']}\n")
        w("```\n" + m["text"] + "\n```\n")
    return "\n".join(out)


def recon_key(strategy, code, action, act_date):
    """對帳鍵 策略|代號|動作|執行日；010 開板放空（盤中提醒）以收盤放空計。"""
    return (strategy, code, ALIAS.get(action, action), act_date)


def ledger(messages, expected=(), report_name="", prior=None):
    """依策略排序的明細列（LEDGER_COLS），以及漏推清單。

    expected：strategy_actions 中「推播時間已過」的應推項目
      （strategy_id, company_code, company_name, action, act_date, act_timing）。
    已推送列狀態為「已推播」或「已推播（已更正）」；應推但沒推的列為「⚠ 漏推」。
    prior：上週總表列 {(策略, 代號, 動作, 執行日): 列}；本週再提醒同一項時沿用上週首次推播與更正。
    """
    prior = prior or {}
    days = build_days(prepare(messages))
    rows, pushed = [], set()
    for d, info in days.items():
        fixed = {(f["strategy"], f["code"], f["action"]): f for f in info["fixes"]}
        for it in info["rows"].values():
            f = fixed.get(key(it))
            status, act_day, fix_txt = "已推播", d, ""
            if f:
                kind = fix_kind(f, d)
                fix_txt = f["detail"]
                if kind == "改執行日":  # 執行日欄改成更正後的日期，原推播日期留在更正欄
                    act_day = moved_to(f, d)
                    fix_txt = f"原推播執行日 {d:%m/%d}；{f['detail']}"
                status = "已推播（補出場日）" if kind == "補出場日" else "已推播（已更正）"
            if it["status"] != 200:
                status = f"⚠ LINE 回應 {it['status']}"
            sent, week = f"{it['sent']:%Y-%m-%d %H:%M}", report_name
            p = prior.get((it["strategy"], it["code"], it["action"], act_day.isoformat()))
            if p:  # 跨週延續：上週已推、本週再提醒
                sent = min(x for x in (p.get("首次推播"), sent) if x)
                fix_txt = "延續上週：" + ("；".join(x for x in (p.get("更正"), fix_txt) if x) or "無更正")
                status += "（延續上週再提醒）"
                week = f"{p.get('週報', '')}；{report_name}（延續上週＋本週再提醒，本週送出 {it['sent']:%Y-%m-%d %H:%M}）"
            rows.append({"策略": it["strategy"], "代號": it["code"], "名稱": it["name"], "動作": it["action"],
                         "執行日": act_day.isoformat(), "時點": timing_label(it), "狀態": status,
                         "首次推播": sent, "推播類型": it["src"].split(" ")[0],
                         "LINE回應": it["status"], "更正": fix_txt, "週報": week, "核准V/R": approved(it["strategy"])})
            pushed.add(recon_key(it["strategy"], it["code"], it["action"], act_day.isoformat()))
    missed = []
    for e in expected:
        if recon_key(e["strategy_id"], e["company_code"], e["action"], e["act_date"]) in pushed:
            continue
        r = {"策略": e["strategy_id"], "代號": e["company_code"], "名稱": e["company_name"], "動作": e["action"],
             "執行日": e["act_date"], "時點": TIMING.get(e.get("act_timing"), ""), "狀態": "⚠ 漏推",
             "首次推播": "", "推播類型": "", "LINE回應": "", "更正": "", "週報": report_name,
             "核准V/R": approved(e["strategy_id"])}
        missed.append(r)
        rows.append(r)
    rows.sort(key=lambda r: (r["策略"], r["執行日"], r["代號"], r["動作"]))
    return rows, missed


def load_prior(path):
    """上週總表列（ledger.json 的 columns+rows、列 dict 的 JSON 陣列，或 CSV）→ {(策略, 代號, 動作, 執行日): 列}。
    同鍵多列取首次推播最早的一列；已漏推的列不算推過。"""
    import csv
    if path.lower().endswith(".csv"):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rs = list(csv.DictReader(fh))
    else:
        d = json.load(open(path, encoding="utf-8"))
        rs = [dict(zip(d["columns"], r)) for r in d["rows"]] if isinstance(d, dict) else d
    out = {}
    for r in rs:
        if not r.get("首次推播"):
            continue
        k = (r["策略"], str(r["代號"]), r["動作"], r["執行日"])
        if k not in out or r["首次推播"] < out[k]["首次推播"]:
            out[k] = r
    return out


def expected_appendix(expected, rows, check_from, push_day, act_range):
    """應推對帳快照：strategy_actions 應推項目逐項對到總表列；再列出總表有、應推清單沒有的列與理由。

    expected 每項需有 act_date；push_day(date) → 應推主推播日（執行日前一交易日）。
    rows：ledger() 的列（含漏推列）。act_range=(lo, hi)：strategy_actions 查詢範圍 lo < act_date ≤ hi。
    """
    pushed = {}
    for r in rows:
        if r["狀態"] != "⚠ 漏推":
            k = recon_key(r["策略"], r["代號"], r["動作"], r["執行日"])
            pushed[k] = min(pushed.get(k) or r["首次推播"], r["首次推播"])
    out = ["## 附錄：應推對帳快照（strategy_actions）\n",
           "口徑：「已推列數」是《推播總表》本期已推播的列（同一 策略｜代號｜動作｜執行日 只算一列，"
           "含 010 盤中提醒、IPO／舊板塊、跨週延續等不在應推清單的項目）；「應推數」只算 strategy_actions 中"
           f"主推播日落在 {check_from:%m/%d} 起、且推播時間已過的策略訊號。兩者口徑不同，數字不必相等，"
           "差額逐項列在下方「未列入應推」。\n",
           f"應推 {len(expected)} 項：\n",
           "| 策略 | 代號 | 名稱 | 動作 | 執行日 | 時點 | 應推時段 | 對帳鍵 | 對應推播 |",
           "|---|---|---|---|---|---|---|---|---|"]
    keys = set()
    for e in sorted(expected, key=lambda e: (e["act_date"], e["strategy_id"], e["company_code"])):
        ad = dt.date.fromisoformat(e["act_date"])
        k = recon_key(e["strategy_id"], e["company_code"], e["action"], e["act_date"])
        keys.add(k)
        out.append(f"| {e['strategy_id']} | {e['company_code']} | {e.get('company_name') or ''} | {e['action']} "
                   f"| {e['act_date']} | {TIMING.get(e.get('act_timing'), '')} "
                   f"| {push_day(ad):%m/%d} 19:00～{ad:%m/%d} 08:30 | {'｜'.join(k)} "
                   f"| {pushed.get(k) or '⚠漏推'} |")
    out.append("")
    sids = {e["strategy_id"] for e in expected}
    extra = []
    for r in rows:
        if r["狀態"] == "⚠ 漏推" or recon_key(r["策略"], r["代號"], r["動作"], r["執行日"]) in keys:
            continue
        ad = dt.date.fromisoformat(r["執行日"])
        if r["時點"] == INTRA_010:
            why = "盤中提醒（010 開板放空提醒，執行屬收盤放空，對帳鍵以收盤放空計）"
        elif push_day(ad) < check_from or not act_range[0] < ad <= act_range[1]:
            why = "跨週延續（執行日的應推推播日早於本期起日，或執行日不在查詢範圍）"
        elif r["策略"] == "IPO" or r["策略"] not in sids:
            why = "IPO・舊板塊無應推表"
        else:
            why = "應推清單無此項（待查：執行日或動作與 strategy_actions 不一致）"
        extra.append(f"| {r['策略']} | {r['代號']} | {r['名稱']} | {r['動作']} | {r['執行日']} | {r['時點']} "
                     f"| {r['首次推播']} | {why} |")
    out.append(f"未列入應推（總表已推、應推清單沒有）{len(extra)} 列：\n")
    if extra:
        out += ["| 策略 | 代號 | 名稱 | 動作 | 執行日 | 時點 | 首次推播 | 未列入應推理由 |",
                "|---|---|---|---|---|---|---|---|"] + extra
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    now = dt.datetime.now(TPE)
    rows, missed = ledger(d["messages"], d.get("expected", []))
    print(render(d["messages"], now.date() - dt.timedelta(days=7), now.date(), now, missed=missed))
    print(f"\n# 總表列 {len(rows)}，漏推 {len(missed)}", file=sys.stderr)
