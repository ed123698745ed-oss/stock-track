"""推播週報「程式比對結果」：每週自動對帳選股、時點、漏推與誤推，產出差異清單。

只檢查、不修正；不連網（資料由 export_push_log.py 從 Supabase 讀好傳進來，測試可直接餵假資料）。

三項比對（交辦《Emit交辦_推播週報程式比對_20261103》第四節）：
  1 選股：推播項目的策略在《可執行策略總表》快照（config/push_compare.json）、驗證「通過」、已交付；
          固定標的的策略（009、A10…）標的要在名單內；推播程式用的 V/R（perf.json）＝總表＝決策紀錄。
          不符 → 表外推播。策略已停止 → 誤推。
  2 時點：推播的執行日、開收盤＝strategy_actions 那一列；那一列的進出場日＝依規則與交易日曆算出的日期；
          推播時間符合手冊第 7 節（主推播／補推在執行日前一交易日 19:00 後、當晚不跨午夜；盤中提醒在當日 12:30～13:30）。
          不符 → 時點不符，寫應為何值。
  3 漏推與誤推：應推未推 → 漏推（沿用既有對帳口徑）；已推但應推清單沒有、同一事件同一時段重複發送 → 誤推。
沒有應推清單的舊板塊（處置股注意、IPO）與 010 盯盤提示不是交易項目 → 不適用，不推估。
"""
import datetime as dt
import json
import pathlib
import re

TPE = dt.timezone(dt.timedelta(hours=8))
CFG_PATH = pathlib.Path(__file__).resolve().parent.parent / "config" / "push_compare.json"
PERF_PATH = pathlib.Path(__file__).resolve().parent.parent / "config" / "perf.json"
WD = "一二三四五六日"
TM = {"open": "開盤", "close": "收盤"}
ROLE = {"買進": ("entry", "long"), "賣出": ("exit", "long"), "放空": ("entry", "short"), "回補": ("exit", "short")}
TYPES = ("表外推播", "時點不符", "漏推", "誤推")
STRAT = re.compile(r"^(A\d{2}|\d{3})$")
INTRA_PX = re.compile(r"現 ([\d.]+)／停 ([\d.]+)")
FIX_TO = re.compile(r"改為 (\d{1,2})/(\d{1,2})")


def load_cfg(path=CFG_PATH):
    return json.loads(pathlib.Path(path).read_text("utf-8"))


def load_perf_vr(path=PERF_PATH):
    """推播程式實際使用的版本：perf.json 各情境 rule 開頭的「Vxx/Rxx」（A 系列沒有）。"""
    try:
        d = json.loads(pathlib.Path(path).read_text("utf-8"))
    except Exception:
        return {}
    out = {}
    for sid, s in (d.get("strategies") or {}).items():
        vrs = {m.group(0) for sc in (s.get("scenarios") or {}).values()
               if (m := re.match(r"V\d+/R\d+", sc.get("rule") or ""))}
        if vrs:
            out[sid] = "、".join(sorted(vrs))
    return out


def tpe(ts):
    if isinstance(ts, dt.datetime):
        return ts.astimezone(TPE)
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TPE)


def D(s):
    return s if isinstance(s, dt.date) else dt.date.fromisoformat(s)


def md(d):
    d = D(d)
    return f"{d.month}/{d.day}({WD[d.weekday()]})"


def approved_vr(sid, cfg):
    s = cfg["strategies"].get(sid)
    if not s:
        return None
    return cfg["a_vr"] if s.get("group") == "A" else s.get("vr")


# ---------------- 依規則算日期（交易日曆） ----------------

def calendar_dates(sid, variant, cycle, cal, cfg):
    """日曆型策略：回傳 (進場日, 出場日)；算不出來（年度休市日未公布、cycle 格式不對）回 None。"""
    try:
        if sid == "015":
            d = D(cycle)
            return cal.shift(d, 1), cal.shift(d, 3)
        y = int(str(cycle)[:4])
        if sid == "A01":
            close, reopen = cal.lny_close(y)
            return (close, reopen) if close else None
        if sid == "A09":
            m, d1, d2 = cfg["strategies"]["A09"]["spans"][variant]
            span = [d for d in cal.month_days(y, m) if d.day >= d1 and (d2 is None or d.day <= d2)]
            return cal.shift(span[0], -1), span[-1]
        if sid == "A10":
            if variant == "長榮航冬季":
                return cal.month_days(y, 10)[9], cal.month_days(y + 1, 1)[7]
            return cal.month_days(y, 5)[14], cal.month_days(y, 6)[0]
        if sid == "009":
            if variant.startswith("統領"):
                close, _ = cal.lny_close(y)
                return (cal.shift(close, -21), close) if close else None
            if variant.startswith("大立光"):
                return cal.shift(cal.month_days(y, 7)[0], -42), cal.month_days(y, 6)[-1]
            return cal.month_days(y, 7)[0], cal.month_days(y, 8)[-1]
    except (KeyError, ValueError, IndexError, TypeError):
        return None
    return None


def calendar_timing(sid, variant):
    if sid == "A10":
        return ("open", "open") if variant == "長榮航冬季" else ("open", "close")
    return None


def rule_for(sid, variant, cfg):
    s = cfg["strategies"].get(sid) or {}
    return ((s.get("variant_rule") or {}).get(variant or "") or s.get("rule") or {})


def check_row(row, cal, cfg):
    """strategy_actions 一列的日期／開收盤是否符合規則 → [(說明, 應為)]；不能判斷的不列。"""
    sid, var, role = row["strategy_id"], row.get("variant") or "", row["role"]
    rule = rule_for(sid, var, cfg)
    out = []
    want_t = rule.get(role if role == "entry" else "exit")
    if rule.get("type") == "calendar" and calendar_timing(sid, var):
        want_t = calendar_timing(sid, var)[0 if role == "entry" else 1]
    if want_t and row.get("act_timing") and row["act_timing"] != want_t:
        out.append((f"資料列開收盤 {TM.get(row['act_timing'])}", f"{TM[want_t]}（{sid} 規則）"))
    act, pair = D(row["act_date"]), (D(row["pair_date"]) if row.get("pair_date") else None)
    ent, ext = (act, pair) if role == "entry" else (pair, act)
    if rule.get("type") == "hold" and ent and ext and cal.known(ent, ext):
        want = cal.shift(ent, rule["hold"] - 1)
        if want != ext:
            out.append((f"出場日 {md(ext)}", f"{md(want)}（進場 {md(ent)} 起持有 {rule['hold']} 個交易日）"))
    elif rule.get("type") == "calendar":
        got = calendar_dates(sid, var, row.get("cycle"), cal, cfg)
        if got:
            we, wx = got
            if ent and ent != we:
                out.append((f"進場日 {md(ent)}", f"{md(we)}（{sid}{'・' + var if var else ''} 日曆規則）"))
            if ext and ext != wx:
                out.append((f"出場日 {md(ext)}", f"{md(wx)}（{sid}{'・' + var if var else ''} 日曆規則）"))
    elif rule.get("type") == "event" and ent and ext and ext < ent:
        out.append((f"出場日 {md(ext)} 早於進場日 {md(ent)}", "出場日不得早於進場日"))
    return out


# ---------------- 推播項目 ----------------

def items_from(messages, push_log, parse):
    """每則訊息的項目。優先用 push_log（結構化欄位）；某則訊息 push_log 沒有項目時才用原文解析，並註記。
    回傳 (items, fixes, notes)。item: msg_id, sent, mode, status, sid, code, name, action, act_date, timing, line, src。"""
    by_msg = {}
    for r in push_log or []:
        by_msg.setdefault(r.get("message_id"), []).append(r)
    items, fixes, notes = [], [], []
    for m in messages:
        sent = tpe(m["sent_at"])
        base = {"msg_id": m["id"], "sent": sent, "mode": m.get("mode"), "status": m.get("status")}
        rows = by_msg.get(m["id"]) or []
        if not rows and m.get("mode") in ("main", "late", "intraday"):
            its, fx, _ = parse(m["text"])
            if its or fx:
                notes.append(f"訊息 {m['id']}（{sent:%m/%d %H:%M}）推播紀錄沒有逐項資料，改以原文解析")
            for it in its:
                items.append(dict(base, sid=it["strategy"], code=it["code"], name=it["name"],
                                  action=it["action"], act_date=None, timing=TM_REV.get(it.get("timing")),
                                  line=it.get("detail") or "", src="原文"))
            for f in fx:
                fixes.append(dict(base, sid=f["strategy"], code=f["code"], action=f["action"], line=f["detail"]))
            continue
        # 推播紀錄（push_log）與原文逐項核對：兩邊不一致代表紀錄寫錯或原文解析不到，列註記給人工
        t_items = {(i["strategy"], i["code"]) for i in parse(m["text"])[0] if i.get("action") in ROLE}
        l_items = {(BLOCK_SID.get(r.get("source"), r.get("source")), r.get("code")) for r in rows
                   if r.get("action") in ROLE}
        if t_items != l_items and m.get("mode") in ("main", "late"):
            only_t, only_l = sorted(t_items - l_items), sorted(l_items - t_items)
            notes.append(f"訊息 {m['id']}（{sent:%m/%d %H:%M}）推播紀錄與原文不一致："
                         + (f"原文有、紀錄沒有 {only_t}" if only_t else "") + (f"；紀錄有、原文沒有 {only_l}" if only_l else ""))
        for r in rows:
            src = r.get("source") or ""
            act = r.get("action")
            if src == "010" and m.get("mode") == "intraday" and act == "盤中提醒":
                act = "開板放空"  # 週報與總表的寫法；收盤條件成立才放空
            if r.get("action") in ("更正", "取消"):
                fixes.append(dict(base, sid=src, code=r.get("code"), action=r["action"], line=r.get("line") or "",
                                  act_date=r.get("act_date")))
                continue
            nm = r.get("name") or next((n for n, c in LINE_STOCK.findall(r.get("line") or "") if c == r.get("code")), None)
            items.append(dict(base, sid=src, code=r.get("code"), name=nm, action=act,
                              act_date=r.get("act_date"), timing=r.get("act_timing"), line=r.get("line") or "",
                              src="推播紀錄"))
    return items, fixes, notes


TM_REV = {"開盤": "open", "收盤": "close"}
BLOCK_SID = {"處置股": "A02", "庫藏股": "A03", "MSCI調整": "A04", "0050調整": "A05", "分割": "A06"}
MODE_TXT = {"main": "主推播", "late": "補推", "intraday": "盤中提醒"}
LINE_STOCK = re.compile(r"・(.+?) (\w+)　")


def classify(it, cfg):
    """→ ('strategy', sid) 交易項目；('na', 原因) 不適用。"""
    sid, act = it["sid"], it.get("action") or ""
    if sid == "010盯盤" or act == "盯盤":
        return "na", "010 盯盤提示（明天要看的名單，不是買賣項目）"
    if sid == "IPO":
        return "na", "IPO 板塊沒有應推清單，也不是可執行策略"
    if sid in cfg.get("blocks", {}):
        if act not in ROLE:
            return "na", f"{sid}「{act}」提醒（不是買賣項目）"
        return "strategy", cfg["blocks"][sid]
    return "strategy", sid


def earlier_fixes(rows):
    """本期以前的【更正】推播（push_log 列，含 push_messages(status,sent_at)）→ fixes 格式。改期常在上週就已更正。"""
    out = []
    for r in rows or []:
        m = r.get("push_messages") or {}
        if not m.get("sent_at"):
            continue
        out.append({"msg_id": r.get("message_id"), "sent": tpe(m["sent_at"]), "status": m.get("status"),
                    "mode": r.get("mode"), "sid": r.get("source"), "code": r.get("code"), "action": r.get("action"),
                    "line": r.get("line") or "", "act_date": r.get("act_date")})
    return out


def compare(messages, push_log, actions, expected, cal, now, parse, cfg=None, perf_vr=None, prior_fixes=None):
    """回傳 dict：diffs（差異列）、by_key（對帳鍵 → 比對結果）、counts、na、warnings、vr_lines、notes。
    prior_fixes：本期以前的【更正】（earlier_fixes() 格式），只用來判斷改期是否已通知。"""
    cfg = cfg or load_cfg()
    perf_vr = load_perf_vr() if perf_vr is None else perf_vr
    items, fixes, notes = items_from(messages, push_log, parse)
    fixes = list(prior_fixes or []) + fixes
    diffs, by_key, na = [], {}, {}

    def add(kind, it, want, why, key=None):
        diffs.append({"類型": kind, "策略": it.get("sid") or "", "股票": f"{it.get('name') or ''} {it.get('code') or ''}".strip(),
                      "動作": it.get("action") or "", "執行日": it.get("act_date") or "",
                      "時點": TM.get(it.get("timing"), it.get("timing") or ""),
                      "推播時間": f"{it['sent']:%m/%d %H:%M}" if it.get("sent") else "",
                      "應為何值": want, "證據": why})
        if key:
            by_key.setdefault(key, set()).add(kind)

    grouped = {}  # (類型, 訊息, 應為何值) → [項目]：推播時間、重複發送是整則訊息的問題，一則訊息一列

    def add_msg(kind, it, want, why):
        grouped.setdefault((kind, it["msg_id"], want, why), []).append(it)
        by_key.setdefault((it["sid"], it["code"], it["action"], it.get("act_date")), set()).add(kind)

    rows = [a for a in actions or []]
    idx = {}
    for a in rows:
        idx.setdefault((a["strategy_id"], a["company_code"], a["role"], a["side"]), []).append(a)

    def corrected(it, row):
        """之後有【更正】推播把這筆改到 row 的日期 → 已更正，不算時點不符。"""
        for f in fixes:
            if f["sid"] == it["sid"] and f["code"] == it["code"] and f["sent"] > it["sent"] and f.get("status") == 200:
                for mo, dd in FIX_TO.findall(f["line"]):
                    if (int(mo), int(dd)) == (D(row["act_date"]).month, D(row["act_date"]).day):
                        return f
        return None

    trade, seen_sids, pairs_seen = [], set(), set()
    for it in items:
        kind, sid = classify(it, cfg)
        if kind == "na":
            na[sid] = na.get(sid, 0) + 1
            continue
        it = dict(it, sid=sid, block=it["sid"] in cfg.get("blocks", {}))
        trade.append(it)
        seen_sids.add(sid)

    # ---- 1 選股 ----
    for it in trade:
        sid, key = it["sid"], (it["sid"], it["code"], it["action"], it.get("act_date"))
        s = cfg["strategies"].get(sid)
        if not s:
            add("表外推播", it, "可執行策略總表沒有此策略，不應推播", f"訊息 {it['msg_id']}：{it['line'][:60]}", key)
            it["bad"] = True
            continue
        if s.get("status") == "停止":
            add("誤推", it, f"策略已停止：{s.get('stop_note', '')}", f"訊息 {it['msg_id']}", key)
            it["bad"] = True
            continue
        if s.get("group") == "B" and (s.get("verify") != "通過" or not s.get("delivered")):
            add("表外推播", it, f"總表驗證狀態「{s.get('verify')}」、交付 Emit：{'是' if s.get('delivered') else '否'}"
                                 f"{('；' + s['note']) if s.get('note') else ''}", f"訊息 {it['msg_id']}", key)
            it["bad"] = True
            continue
        if s.get("codes") and it.get("code") not in s["codes"]:
            add("表外推播", it, f"{sid} 只做 {'、'.join(s['codes'])}", f"訊息 {it['msg_id']}：{it['line'][:60]}", key)
            it["bad"] = True

    vr_lines = []
    a_seen = sorted(s for s in seen_sids if (cfg["strategies"].get(s) or {}).get("group") == "A")
    if a_seen:
        vr_lines.append(f"{'、'.join(a_seen)}：{cfg['a_vr']}（Ed 2026-10-31 決定；以總表〈完整策略績效〉登載為準）")
    for sid in sorted(seen_sids):
        s = cfg["strategies"].get(sid)
        if not s or s.get("group") != "B":
            continue
        dec = s.get("decision")
        pv = perf_vr.get(sid)
        bad = (pv and pv != s.get("vr")) or (dec and dec.get("vr") != s.get("vr"))
        dtxt = f"決策紀錄 {dec['id']} {dec['vr']}" if dec else "決策紀錄無對應列（2026-10-25 前核准，以原始對話與策略包為準）"
        vr_lines.append(f"{sid}：總表 {s.get('vr')}｜推播程式 {pv or '未設定'}｜{dtxt}" + ("　⚠ 不一致" if bad else ""))
        if bad:
            add("表外推播", {"sid": sid, "action": "（設定）", "name": "全部項目", "code": "", "msg_id": "-", "line": ""},
                f"總表 {s.get('vr')}", f"推播程式 {pv or '未設定'}；{dtxt}")

    # ---- 2 時點 ----
    for it in trade:
        sid = it["sid"]
        if it.get("bad") or sid not in cfg["strategies"]:
            continue
        key = (sid, it["code"], it["action"], it.get("act_date"))
        if it["mode"] == "intraday":
            sd = it["sent"]
            if not (cal.is_trading(sd.date()) and dt.time(12, 30) <= sd.time() <= dt.time(13, 30)):
                add("時點不符", it, "盤中提醒應在當日 12:30～13:30 送出", f"訊息 {it['msg_id']}", key)
            continue
        if it["action"] not in ROLE:
            continue
        if not it.get("act_date"):
            add("時點不符", it, "推播項目缺執行日，無法核對", f"訊息 {it['msg_id']}（{it['src']}）", key)
            continue
        ad = D(it["act_date"])
        # 推播時間：執行日前一交易日 19:00 起、當晚送出（不跨午夜）；延後到執行日 08:30 前仍算送達，但跨午夜列不符
        if cal.known(ad):
            p = cal.shift(ad, -1)
            sd = it["sent"]
            lo = dt.datetime.combine(p, dt.time(19, 0), TPE)
            hi = dt.datetime.combine(ad, dt.time(8, 30), TPE)
            if not (lo <= sd < hi) or sd.hour < 19:
                add_msg("時點不符", it, "執行日前一交易日 19:00 以後、當晚送出（主推播以台灣日期為準、不跨午夜）",
                        f"訊息 {it['msg_id']} {'主推播' if it['mode'] == 'main' else '補推'} {sd:%m/%d %H:%M} 送出")
        if it.get("block"):
            na[f"{it['sid']} 舊板塊買賣（沒有應推清單，只核對選股與推播時間）"] = \
                na.get(f"{it['sid']} 舊板塊買賣（沒有應推清單，只核對選股與推播時間）", 0) + 1
            continue
        role, side = ROLE[it["action"]]
        cands = [a for a in idx.get((sid, it["code"], role, side), [])]
        exact = [a for a in cands if a["act_date"] == it["act_date"]]
        if not exact:
            near = sorted((a for a in cands if abs((D(a["act_date"]) - ad).days) <= 20),
                          key=lambda a: abs((D(a["act_date"]) - ad).days))
            if near:
                row = near[0]
                if corrected(it, row):
                    continue
                add("時點不符", it, f"執行日 {md(row['act_date'])}（strategy_actions id {row['id']}），推播後沒有更正通知",
                    f"訊息 {it['msg_id']}；資料列 id {row['id']}", key)
            else:
                add("誤推", it, "應推清單（strategy_actions）沒有這一筆", f"訊息 {it['msg_id']}：{it['line'][:60]}", key)
            continue
        row = exact[0]
        if it.get("timing") and row.get("act_timing") and it["timing"] != row["act_timing"]:
            add("時點不符", it, f"{TM[row['act_timing']]}（strategy_actions id {row['id']}）",
                f"訊息 {it['msg_id']} 推 {TM.get(it['timing'])}", key)
        for got, want in check_row(row, cal, cfg):
            add("時點不符", it, want, f"資料列 id {row['id']} {got}", key)
        # 成對一致（防錯清單 A7、事故 9）：進場列記的出場日＝出場列的執行日；不一致又沒推【更正】→ 進場訊息寫的出場日是錯的
        other = "exit" if role == "entry" else "entry"
        for o in idx.get((sid, it["code"], other, side), []):
            if o["act_date"] != row.get("pair_date") or o.get("pair_date") == row["act_date"]:
                continue
            ent_r, ext_r = (row, o) if role == "entry" else (o, row)
            pair = (ent_r["id"], ext_r["id"])
            if pair in pairs_seen or corrected(dict(it, sent=dt.datetime.min.replace(tzinfo=TPE)), ext_r):
                continue
            pairs_seen.add(pair)
            add("時點不符", it, f"出場 {md(ext_r['act_date'])}（出場列 id {ext_r['id']}）；改期後應推【更正】並同步進場列",
                f"進場列 id {ent_r['id']} 記出場 {md(ent_r['pair_date'])}，與出場列不一致，推播紀錄沒有更正", key)
        if row.get("ignored") and not row.get("checked"):
            canc = any(f["sid"] == sid and f["code"] == it["code"] and f["action"] == "取消" for f in fixes)
            if not canc:
                add("誤推", it, "訊號已被策略取消，應推【取消】", f"資料列 id {row['id']} ignored=true、checked=false", key)

    # 010 盤中提醒：沒有收盤進場列＝盤中提醒、收盤沒成立。報價有「現＜停」才算確定沒鎖；報價暫缺仍推＝誤推
    entries010 = {(a["company_code"], a["act_date"]) for a in rows
                  if a["strategy_id"] == "010" and a["role"] == "entry" and not (a.get("ignored") and not a.get("checked"))}
    for it in trade:
        if it["sid"] != "010" or it["mode"] != "intraday":
            continue
        key = ("010", it["code"], it["action"], it.get("act_date"))
        m = INTRA_PX.search(it["line"])
        if m and float(m.group(1)) < float(m.group(2)):
            if (it["code"], it.get("act_date")) not in entries010:
                na["010 盤中提醒（盤中確實未鎖，收盤又鎖住，策略不成立；提醒本身正確）"] = \
                    na.get("010 盤中提醒（盤中確實未鎖，收盤又鎖住，策略不成立；提醒本身正確）", 0) + 1
            continue
        add("誤推", it, "盤中確定沒鎖漲停（有成交價且低於漲停價）才推；報價暫缺應不推、下一輪再判斷",
            f"訊息 {it['msg_id']}：{it['line'][:60]}", key)

    # ---- 3 重複發送（同一事件、同一時段送兩次以上；只算 LINE 200） ----
    slot = {}
    for it in trade:
        if it.get("status") != 200:
            continue
        sl = "盤中" if it["mode"] == "intraday" else "前一晚"
        k = (sl, it["sid"], it["code"], it["action"], it.get("act_date") if sl == "前一晚" else it["sent"].date().isoformat())
        slot.setdefault(k, []).append(it)
    for k, its in slot.items():
        its.sort(key=lambda x: x["sent"])
        for it in its[1:]:
            if it["msg_id"] == its[0]["msg_id"]:
                continue
            add_msg("誤推", it, f"已於 {its[0]['sent']:%m/%d %H:%M}（訊息 {its[0]['msg_id']}）送出，同一事件同一時段不重複發送",
                    f"重複發送：訊息 {it['msg_id']}（{MODE_TXT.get(it['mode'], it['mode'])} {it['sent']:%m/%d %H:%M}）")

    # ---- 3 漏推（沿用既有應推口徑：export_push_log.expected） ----
    pushed = set()
    for it in trade:
        if it.get("status") != 200:
            continue
        act = "放空" if it["sid"] == "010" and it["mode"] == "intraday" else it["action"]
        pushed.add((it["sid"], it["code"], act, it.get("act_date")))
    def fixed_to(e):
        """應推項目的日期是推播後才順延的：有【更正】推到新日期就算已通知。"""
        d = D(e["act_date"])
        return any(f.get("status") == 200 and f["action"] == "更正" and f["sid"] == e["strategy_id"]
                   and f["code"] == e["company_code"] and (d.month, d.day) in
                   {(int(a), int(b)) for a, b in FIX_TO.findall(f["line"])} for f in fixes)

    for e in expected or []:
        k = (e["strategy_id"], e["company_code"], e["action"], e["act_date"])
        if k in pushed or fixed_to(e):
            continue
        it = {"sid": e["strategy_id"], "code": e["company_code"], "name": e.get("company_name"), "action": e["action"],
              "act_date": e["act_date"], "timing": e.get("act_timing"), "msg_id": "-", "line": ""}
        window = (f"{md(e['act_date'])} 盤中～13:30（010 盤中通知）" if e["strategy_id"] == "010" and e["action"] == "放空"
                  else f"{md(e['push_day'])} 19:00～{md(e['act_date'])} 08:30 推播")
        add("漏推", it, window, f"strategy_actions 應推、推播紀錄沒有{'（網站隱藏，非取消）' if e.get('hidden') else ''}", k)

    for (kind, mid, want, why), its in grouped.items():
        names = "、".join(f"{x['sid']} {x.get('name') or ''} {x['code']}".replace("  ", " ") for x in its[:3])
        acts = {x["action"] for x in its}
        days = {x.get("act_date") for x in its}
        diffs.append({"類型": kind, "策略": "、".join(sorted({x["sid"] for x in its})),
                      "股票": names + (f" 等 {len(its)} 項" if len(its) > 3 else ""),
                      "動作": acts.pop() if len(acts) == 1 else "多項", "執行日": days.pop() if len(days) == 1 else "多日",
                      "時點": "", "推播時間": f"{its[0]['sent']:%m/%d %H:%M}", "應為何值": want, "證據": why})

    # ---- 訊息內警告：程式不判斷真假，列給人工 ----
    warnings = []
    for m in messages:
        for ln in m["text"].splitlines():
            if ln.startswith("⚠"):
                warnings.append(f"{tpe(m['sent_at']):%m/%d %H:%M} 訊息 {m['id']}：{ln}")

    counts = {t: sum(1 for d in diffs if d["類型"] == t) for t in TYPES}
    return {"diffs": diffs, "by_key": {k: "、".join(t for t in TYPES if t in v) for k, v in by_key.items()},
            "counts": counts, "n_items": len(items), "n_trade": len(trade), "n_expected": len(expected or []),
            "na": na, "warnings": warnings, "vr_lines": vr_lines, "notes": notes, "snapshot": cfg.get("snapshot")}


def result_for(res, strategy, code, action, act_date):
    """ledger 列的「比對結果」：正常／表外推播／時點不符／漏推／誤推（多項以「、」連接）；舊板塊不適用。"""
    act = "放空" if action == "開板放空" else action
    for k in ((strategy, code, action, act_date), (strategy, code, act, act_date)):
        if k in res["by_key"]:
            return res["by_key"][k]
    if strategy == "IPO" or action in ("盯盤", "注意"):
        return "不適用"
    return "正常"


def render_section(res):
    c, out = res["counts"], ["## 程式比對結果\n"]
    total = sum(c.values())
    out.append(f"- 依據：總表快照 config/push_compare.json（{res['snapshot']}）、strategy_actions、推播紀錄、交易日曆；"
               "本節由匯出程式自動產生，只檢查、不修正。")
    out.append(f"- 比對筆數：推播項目 {res['n_items']} 項（交易項目 {res['n_trade']}、不適用 {sum(res['na'].values())}），"
               f"應推項目 {res['n_expected']} 項。")
    if total:
        out.append(f"- ⚠ 三項比對 {total} 筆差異：" + "、".join(f"{t} {c[t]}" for t in TYPES if c[t]) + "。")
    else:
        out.append("- 三項比對 0 筆差異。")
    out.append("")
    if total:
        cols = ["類型", "策略", "股票", "動作", "執行日", "時點", "推播時間", "應為何值", "證據"]
        out += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for d in sorted(res["diffs"], key=lambda d: (TYPES.index(d["類型"]), d["執行日"], d["策略"], d["股票"])):
            out.append("| " + " | ".join(str(d[k]).replace("|", "／") for k in cols) + " |")
        out.append("")
    if res["na"]:
        out.append("不適用（不是可執行策略的買賣項目，不列比對）：" + "；".join(f"{k} {v} 項" for k, v in res["na"].items()) + "\n")
    if res["vr_lines"]:
        out.append("選股設定核對（V/R）：\n")
        out += [f"- {x}" for x in res["vr_lines"]]
        out.append("")
    if res["warnings"]:
        out.append("訊息內警告（程式不判斷真偽，需人工核實是否誤警、是否漏訊號）：\n")
        out += [f"- {w}" for w in res["warnings"]]
        out.append("")
    for n in res["notes"]:
        out.append(f"- 註：{n}")
    out.append("- 程式限制：進場日依公告的事件型策略（004、019、A02、A03、A06…）只核對持有天數與開收盤，"
               "不重抓公告；來源事件沒偵測到的漏訊號仍須以官方清單外部比對。推播「開始時間」沒有紀錄，以送出時間判斷。\n")
    return "\n".join(out)
