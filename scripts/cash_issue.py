"""現金增資策略
  004：原股東現增繳款截止日開盤放空，進場日起算第 10 個交易日收盤回補。
  017：新股（或股款繳納憑證）首次可交易日 D 的前一個交易日開盤放空，D 開盤回補。

資料來源：公開資訊觀測站重大訊息（ajax_t05st01）。
  主旨含「認股基準日／繳款期間」的公告 → 讀內文：
    「每仟股得認購 X 股」→ 認購比例（004 門檻：> 50 股，即 > 5%）
    「原股東…繳納期間：115/09/29~115/10/29」→ 繳款截止日
  初次上市櫃前的現增、延後作業（待訂定後另行公告）的公告略過。
  同一家公司後續的補充／更正公告會覆蓋前一次的日期（同一個 cycle）。

用法：
  python3 scripts/cash_issue.py              # 掃最近 7 天的公告，寫入 strategy_actions
  DAYS=45 DRY_RUN=1 python3 scripts/cash_issue.py
"""
import datetime as dt
import http.cookiejar
import json
import os
import re
import ssl
import time
import urllib.request

from calendar_signals import Cal, leg, supa

TPE = dt.timezone(dt.timedelta(hours=8))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
STAT004 = {"name": "菲比斯630大額現增放空", "n": 958, "win": 63.88, "p": "<0.0001"}
STAT017 = {"name": "現增上市賣壓與反彈", "n": 191, "win": 85.34, "p": "<0.0001"}
TH017 = 146.18  # 每仟股認購股數 ≥ 146.18（認購比例 ≥ 14.618%）
TH004 = 50.0  # 每仟股可認購股數 > 50（認購比例 > 5%）
HOLD004 = 10  # 進場日起算第 10 個交易日收盤回補

SUBJ = re.compile(r"認股基準日|繳款期間|繳納期間")
CANCEL = re.compile(r"現金增資.{0,30}(撤銷|暫緩|停止(?!轉換)|終止)|(撤銷|暫緩|停止(?!轉換)|終止).{0,30}現金增資")
POSTPONE = re.compile(r"原訂.{0,30}待訂定後另行公告|延後原定|延後.{0,6}作業日程|擬予?延後|另行訂定並公告")
SKIP = re.compile(r"初次|延長募集|募集期間|特定人|子公司|庫藏股|存託憑證")

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE
_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                  urllib.request.HTTPSHandler(context=_ctx))


def _get(url, data=None, hdr=None, tries=3):
    h = {"User-Agent": UA}
    h.update(hdr or {})
    last = None
    for i in range(tries):  # MOPS 偶爾逾時，重試
        try:
            with _op.open(urllib.request.Request(url, data=data, headers=h), timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(5 * (i + 1))
    raise last


def mops(params):
    body = json.dumps({"apiName": "ajax_t05st01", "parameters": params}).encode()
    r = json.loads(_get("https://mops.twse.com.tw/mops/api/redirectToOld", body,
                        {"Content-Type": "application/json", "Origin": "https://mops.twse.com.tw",
                         "Referer": "https://mops.twse.com.tw/mops/"}))
    return _get(r["result"]["url"], hdr={"Referer": "https://mops.twse.com.tw/"})


def _text(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>|&nbsp;", " ", h)).strip()


DATE = r"(\d{2,3})\s*[/年]\s*(\d{1,2})\s*[/月]\s*(\d{1,2})\s*日?/?"  # 115/09/29、115年9月29日


def roc(s):
    m = re.fullmatch(DATE, s.strip())
    return dt.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))) if m else None


_SHARES = {}


def issued_shares(code):
    """已發行普通股數（上市 t187ap03_L、上櫃 mopsfin_t187ap03_O）。欄位名稱自動辨識。"""
    if not _SHARES:
        for u in ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
                  "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"):
            try:
                rows = json.loads(_get(u, hdr={"Accept": "application/json"}))
            except Exception as e:
                print(f"  公司基本資料抓取失敗 {u}：{e}")
                continue
            if not rows:
                continue
            keys = list(rows[0])
            kc = next(k for k in keys if re.search(r"公司代號|SecuritiesCompanyCode|CompanyCode", k))
            ks = next((k for k in keys if re.search(r"已發行普通股|IssueShares|IssuedShares", k)), None)
            if not ks:
                print(f"  {u} 找不到已發行股數欄位：{keys}")
                continue
            for r in rows:
                v = re.sub(r"[^\d]", "", str(r.get(ks) or ""))
                if v:
                    _SHARES[str(r[kc]).strip()] = int(v)
        print(f"  已發行股數資料 {len(_SHARES)} 家")
    return _SHARES.get(code)


def list_announcements(start, end):
    """[(主旨, seq, time, date, co_id, TYPEK, 公司名稱)]，依月份分段查詢。"""
    out, cur = [], start
    while cur <= end:
        mend = (dt.date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1) - dt.timedelta(days=1))
        last = min(mend, end)
        html = mops({"step": 1, "firstin": 1, "off": 1, "keyword4": "", "code1": "", "TYPEK2": "",
                     "checkbtn": "", "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
                     "co_id": "", "year": f"{cur.year - 1911:03d}", "month": f"{cur.month:02d}",
                     "b_date": f"{cur.day:02d}", "e_date": f"{last.day:02d}"})
        for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, re.S):
            oc = re.search(r"seq_no.value='(\d+)'.*?spoke_time.value='(\d+)'.*?spoke_date.value='(\d+)'"
                           r".*?co_id.value='(\w+)'.*?TYPEK.value='(\w+)'", tr)
            cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if oc and len(cells) >= 5:
                out.append((cells[4], *oc.groups(), cells[1]))
        cur = last + dt.timedelta(days=1)
        time.sleep(2)
    return out


D_ = r"(\d{2,3}\s*[/年]\s*\d{1,2}\s*[/月]\s*\d{1,2}\s*日?/?)"
RANGE = D_ + r"\s*(?:起)?\s*[~～至\-－]\s*" + D_


def parse_detail(text, code=None):
    """內文 → {ratio 每仟股認購股數, ratio_src, pay_start, pay_end 原股東繳款期間, base 認股基準日}。
    繳款日程延後（待另行訂定）回傳 None；只有「發行價格待訂定」不算延後。"""
    if POSTPONE.search(text):
        return None
    p = re.search(r"原股東[^0-9]{0,30}?(?:繳款|繳納)[^0-9]{0,12}?" + RANGE, text)
    if not p:  # 只寫「股款繳納期間」沒有分原股東的格式
        p = re.search(r"股款繳納期間[^0-9]{0,40}?" + RANGE, text)
    if not p:
        return None
    b = re.search(r"認股基準日\s*[:：]\s*" + D_, text)
    # 標題常寫「(另請說明每仟股暫定得認購股數):2,700,000股」接著才是「每仟股得認購92.6股」：
    # 逐一比對，取第一個合理值（≤ 3000），總股數會被跳過
    ratio, src = None, None
    for r in re.finditer(r"每[壹一]?[仟千]股[^0-9]{0,12}?([\d,]+(?:\.\d+)?)\s*股", text):
        v = float(r.group(1).replace(",", ""))
        if v <= 3000:
            ratio, src = v, "公告"
            break
    if ratio is None and code:  # 公告沒寫每仟股：原股東認購股數 ÷ 已發行股數
        m = re.search(r"原股東認購比[率例][^計]{0,40}計\s*([\d,]+)\s*(仟)?股", text)
        sh = issued_shares(code)
        if m and sh:
            n = int(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
            ratio, src = n / sh * 1000, "原股東認購股數÷已發行股數"
    if ratio is None:
        return None
    return {"ratio": ratio, "ratio_src": src, "pay_start": roc(p.group(1)),
            "pay_end": roc(p.group(2)), "base": roc(b.group(1)) if b else None}


# ---------------- 017：公告查詢（股票核准上市櫃＝12、發行新股前公告＝11）----------------
SUBJ017 = re.compile(r"現金增資|現增")
SKIP017 = re.compile(r"初次|特別股|公司債|權利證書|終止|下市|下櫃|換發|註銷|盈餘|存託憑證")  # 海外存託憑證（GDR）現增：Ed 決定排除
D017 = re.compile(r"開始買賣日期\s*[：:]?\s*(?:民國)?\s*" + r"(\d{2,3})\s*[/年]\s*(\d{1,2})\s*[/月]\s*(\d{1,2})")
DATE_ANY = re.compile(r"(?:民國)?\s*(\d{2,3})\s*[/年]\s*(\d{1,2})\s*[/月]\s*(\d{1,2})\s*日?")


def _post_ov(path, params):
    import urllib.parse
    return _get("https://mopsov.twse.com.tw/mops/web/" + path, urllib.parse.urlencode(params).encode(),
                {"Referer": "https://mopsov.twse.com.tw/mops/web/t146sb10"})


def list017(period):
    """period：t146sb10 的 date 選項（3＝最近 1 週、4＝1 月、5＝3 月）。
    回傳 [(公告日, 代號, 名稱, 主旨, 內文端點, 參數)]"""
    _get("https://mopsov.twse.com.tw/mops/web/t146sb10")
    out = []
    for kind in ("12", "11"):
        for typek in ("sii", "otc"):
            first = _post_ov("ajax_t146sb10", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1,
                                                "scope": 2, "typek": typek, "selecttype": 0, "noticeDate": 2,
                                                "date": period, "noticeKind": kind, "sort": 1})
            fields = dict(re.findall(r"<input type='hidden' name='(\w+)' value='([^']*)'", first))
            for rpt in re.findall(r"rpt\.value='(\w+)'", first):
                h = _post_ov("ajax_t146sb10", {**fields, "rpt": rpt})
                for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
                    cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
                    act = re.search(r'action="/mops/web/(\w+)"', tr)
                    if len(cells) < 4 or not act:
                        continue
                    args = dict(re.findall(r"\.(\w+)\.value\s*=\s*['\"]([^'\"]*)['\"]", tr))
                    out.append((roc(cells[2]), cells[0], cells[1], cells[3], act.group(1), args))
                time.sleep(1.5)
    return out


def parse017(text, ann):
    """內文 → 首次可交易日 D。先抓制式欄位「開始買賣日期」；沒有時找緊接「上市／上櫃買賣、掛牌」的日期，
    排除函文日期（後面接「字第」）。同一則有多個日期取最早（較晚的通常是憑證換發新股）。"""
    ds = [dt.date(int(y) + 1911, int(m), int(d)) for y, m, d in D017.findall(text)]
    if not ds:
        for m in DATE_ANY.finditer(text):
            after = text[m.end():m.end() + 18]
            if "字第" in after or not re.search(r"上市|上櫃|掛牌|買賣", after):
                continue
            try:
                ds.append(dt.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))))
            except ValueError:
                continue
    ds = [d for d in ds if ann is None or d >= ann]
    return min(ds) if ds else None


def build017(cal, code, name, d, ratio, ann):
    """D-1 開盤放空 → D 開盤回補。公告日只有日期沒有時分，一律視為下一個交易日才可行動，
    所以要求「公告日的下一個交易日 ≤ D-1」。"""
    if not (cal.known(d) and cal.is_trading(d)):
        return [], "D 不是交易日或休市日未公布"
    ent = cal.shift(d, -1)
    if ann and cal.shift(ann, 1) > ent:
        return [], f"公告太晚（{ann} 公告，D-1 是 {ent}）"
    rows = leg("017", "現增上市放空", code, name, d.isoformat(), "short", ent, "open", d, "open", STAT017)
    for x in rows:
        x["detail"] = (f"每仟股認購 {ratio:.2f} 股｜首次可交易日 {d:%m/%d}｜"
                       f"先確認融券資格、非平盤下禁空、券源｜" + x["detail"])
    return rows, None


def build004(cal, code, name, info):
    """繳款截止日開盤放空 → 進場日起算第 10 個交易日收盤回補。"""
    ent = info["pay_end"]
    if not cal.known(ent):
        return []
    if not cal.is_trading(ent):  # 截止日遇休市：取下一個交易日開盤
        ent = cal.shift(ent, 1)
    ext = cal.shift(ent, HOLD004 - 1)
    cycle = (info["base"] or info["pay_end"]).isoformat()
    rows = leg("004", "大額現增放空", code, name, cycle, "short", ent, "open", ext, "close", STAT004)
    for x in rows:
        est = "" if info.get("ratio_src") == "公告" else "，依已發行股數換算"
        x["detail"] = (f"每仟股認購 {info['ratio']:.2f} 股（{info['ratio'] / 10:.1f}%{est}）｜"
                       f"繳款 {info['pay_start']:%m/%d}~{info['pay_end']:%m/%d}｜先確認券源、借券費｜" + x["detail"])
    return rows


def ratio_for(code, d, issues):
    """D 之前最近一次現增的每仟股認購股數：先看這次執行解析到的，再查 cash_issues 表。"""
    cands = [v for (c, _), v in issues.items() if c == code]
    try:
        cands += supa(f"cash_issues?select=*&company_code=eq.{code}&order=pay_end.desc&limit=3")
    except Exception:
        pass
    cands = [v for v in cands if v.get("pay_end") and v["pay_end"] <= d.isoformat()
             and (d - dt.date.fromisoformat(v["pay_end"])).days <= 120]
    return max(cands, key=lambda v: v["pay_end"])["ratio"] if cands else None


def run017(cal, today, issues):
    period = int(os.environ.get("PERIOD017") or 3)
    anns = [a for a in list017(period) if SUBJ017.search(a[3]) and not SKIP017.search(a[3])]
    print(f"017 公告查詢：現增上市類 {len(anns)} 則")
    best = {}  # 代號 → (公告日, D, 名稱)；公告改期以後一則為準
    for ann, code, name, subj, act, args in sorted(anns, key=lambda a: a[0] or dt.date.min):
        try:
            txt = _text(_post_ov(act, {"firstin": 1, "off": 1, "step": args.get("step", "2"), **args}))
        except Exception as e:
            print(f"  {code} {name} 內文抓取失敗：{e}")
            continue
        time.sleep(1.5)
        d = parse017(txt, ann)
        if not d:
            print(f"  {code} {name} 沒有可交易日（可能另行公告）：{subj[:40]}")
            continue
        best[code] = (ann, d, name)
    rows = []
    for code, (ann, d, name) in best.items():
        ratio = ratio_for(code, d, issues)
        if ratio is None:
            print(f"  {code} {name} D={d}：找不到認購比例，略過")
            continue
        if ratio < TH017:
            print(f"  {code} {name} D={d}：每仟股 {ratio:.2f} 股（未達 146.18）")
            continue
        rs, why = build017(cal, code, name, d, ratio, ann)
        print(f"  {code} {name} D={d} 每仟股 {ratio:.2f} → " + (why or "017 符合"))
        rows += rs
    return rows


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    today = dt.datetime.now(TPE).date()
    days = int(os.environ.get("DAYS") or 7)
    cal = Cal([dt.date.fromisoformat(r["market_date"]) for r in supa("holidays?select=market_date&limit=5000")])
    try:
        _get("https://mops.twse.com.tw/mops/")
    except Exception:
        pass
    anns = list_announcements(today - dt.timedelta(days=days), today)
    cand = [a for a in anns if SUBJ.search(a[0]) and not SKIP.search(a[0])]
    # 撤銷／暫緩現增 → 原 D 作廢（依 004 規則）
    # co → ((公告日, 時間), 主旨)：只有「比作廢公告更新」的正常公告才能恢復
    void = {}
    for a in sorted(anns, key=lambda a: (a[3], a[2])):
        if CANCEL.search(a[0]) and not SKIP.search(a[0]):
            void[a[4]] = ((a[3], a[2]), a[0])
    print(f"重大訊息 {len(anns)} 筆，現增認股／繳款類 {len(cand)} 筆")
    rows, seen, issues = [], {}, {}
    for subj, seq, tm, d8, co, typ, name in sorted(cand, key=lambda a: (a[3], a[2])):
        try:
            txt = _text(mops({"step": 2, "firstin": 1, "off": 1, "seq_no": seq,
                              "spoke_time": tm, "spoke_date": d8, "co_id": co, "TYPEK": typ}))
            info = parse_detail(txt, co)
        except Exception as e:
            print(f"  {co} {name} 內文抓取失敗：{e}")
            continue
        time.sleep(1.5)
        if not info and POSTPONE.search(txt):
            void[co] = ((d8, tm), subj)  # 繳款日程延後：原 D 作廢，等重訂後的新公告
            seen.pop(co, None)
        if not info:
            print(f"  {co} {name} 略過（延後作業或無法解析）：{subj[:50]}")
            if os.environ.get("DEBUG") == "1":
                i = txt.find("說明")
                print("     內文：", txt[i:i + 900])
            continue
        ok = info["ratio"] > TH004
        print(f"  {co} {name} 每仟股 {info['ratio']:.2f} 股（{info['ratio_src']}） 繳款 {info['pay_start']}~{info['pay_end']} "
              f"{'→ 004 符合' if ok else '（未達 50 股）'}")
        cyc = (info["base"] or info["pay_end"]).isoformat()
        issues[(co, cyc)] = {"company_code": co, "cycle": cyc, "company_name": name,
                             "ratio": round(info["ratio"], 4), "ratio_src": info["ratio_src"],
                             "pay_start": info["pay_start"].isoformat(), "pay_end": info["pay_end"].isoformat(),
                             "announced_on": roc(f"{int(d8[:4]) - 1911}/{d8[4:6]}/{d8[6:]}").isoformat()}
        if ok:
            seen[co] = build004(cal, co, name, info)  # 同一家公司後面的公告覆蓋前面的
            if co in void and void[co][0] < (d8, tm):
                void.pop(co)  # 比作廢更新的重訂公告 → 採新 D
        elif co in seen:
            seen.pop(co)  # 最新公告的比例更正到門檻以下：先前的訊號作廢
            void[co] = ((d8, tm), f"比例更正為每仟股 {info['ratio']:.2f} 股，未達 50 股")
    for co in void:
        seen.pop(co, None)
    for rs in seen.values():
        rows += rs

    # ---- 017 ----
    try:
        rows += run017(cal, today, issues)
    except Exception as e:
        print(f"⚠ 017 公告查詢失敗：{e}")
        if not dry:
            raise
    rows = [r for r in rows if r["act_date"] >= today.isoformat()]
    for r in sorted(rows, key=lambda r: r["act_date"]):
        print(f"  {r['act_date']} {r['act_timing']:5} {r['role']:5} 004 {r['company_name']}{r['company_code']}")
    for co, (_, subj) in void.items():
        print(f"  {co} 作廢原 004 日期：{subj[:60]}")
    if dry:
        print("DRY_RUN：不寫入")
        return
    for co in void:
        # 只作廢「還沒進場」的計畫：進場日在明天以後的進場列，以及其對應的出場列。
        # 已經進場（進場日 ≤ 今天）的部位，回補提醒保留，避免空單沒人提醒回補。
        t = today.isoformat()
        supa(f"strategy_actions?strategy_id=eq.004&company_code=eq.{co}&role=eq.entry&act_date=gt.{t}",
             "PATCH", {"ignored": True})
        supa(f"strategy_actions?strategy_id=eq.004&company_code=eq.{co}&role=eq.exit&pair_date=gt.{t}",
             "PATCH", {"ignored": True})
    if issues:
        supa("cash_issues?on_conflict=company_code,cycle", "POST", list(issues.values()),
             prefer="resolution=merge-duplicates,return=minimal")
    if rows:
        supa("strategy_actions?on_conflict=strategy_id,variant,company_code,cycle,role",
             "POST", rows, prefer="resolution=merge-duplicates,return=minimal")
    print(f"已寫入 {len(rows)} 列")


if __name__ == "__main__":
    main()
