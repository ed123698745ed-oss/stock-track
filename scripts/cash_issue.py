"""現金增資策略 004：原股東現增繳款截止日開盤放空，進場日起算第 10 個交易日收盤回補。

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
TH004 = 50.0  # 每仟股可認購股數 > 50（認購比例 > 5%）
HOLD004 = 10  # 進場日起算第 10 個交易日收盤回補

SUBJ = re.compile(r"認股基準日|繳款期間|繳納期間")
SKIP = re.compile(r"初次|延長募集|募集期間|特定人|子公司")

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE
_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                  urllib.request.HTTPSHandler(context=_ctx))


def _get(url, data=None, hdr=None):
    h = {"User-Agent": UA}
    h.update(hdr or {})
    with _op.open(urllib.request.Request(url, data=data, headers=h), timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def mops(params):
    body = json.dumps({"apiName": "ajax_t05st01", "parameters": params}).encode()
    r = json.loads(_get("https://mops.twse.com.tw/mops/api/redirectToOld", body,
                        {"Content-Type": "application/json", "Origin": "https://mops.twse.com.tw",
                         "Referer": "https://mops.twse.com.tw/mops/"}))
    return _get(r["result"]["url"], hdr={"Referer": "https://mops.twse.com.tw/"})


def _text(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>|&nbsp;", " ", h)).strip()


def roc(s):
    m = re.fullmatch(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", s.strip())
    return dt.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))) if m else None


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


def parse_detail(text):
    """內文 → {ratio 每仟股認購股數, pay_start, pay_end 原股東繳款期間, base 認股基準日}；
    延後作業（待訂定）回傳 None。"""
    if re.search(r"待訂定後另行公告|延後原定|延後.{0,6}作業日程", text):
        return None
    r = re.search(r"每[仟千]股[^0-9]{0,12}?([\d,]+(?:\.\d+)?)\s*股", text)
    p = re.search(r"原股東[^0-9]{0,30}?(?:繳款|繳納)[^0-9]{0,12}?"
                  r"(\d{2,3}/\d{1,2}/\d{1,2})\s*[~～至\-－]\s*(\d{2,3}/\d{1,2}/\d{1,2})", text)
    if not p:  # 只寫「股款繳納期間」沒有分原股東的格式
        p = re.search(r"股款繳納期間[^0-9]{0,40}?(\d{2,3}/\d{1,2}/\d{1,2})\s*[~～至\-－]\s*"
                      r"(\d{2,3}/\d{1,2}/\d{1,2})", text)
    b = re.search(r"認股基準日\s*[:：]\s*(\d{2,3}/\d{1,2}/\d{1,2})", text)
    if not (r and p):
        return None
    return {"ratio": float(r.group(1).replace(",", "")), "pay_start": roc(p.group(1)),
            "pay_end": roc(p.group(2)), "base": roc(b.group(1)) if b else None}


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
        x["detail"] = (f"每仟股認購 {info['ratio']:.2f} 股（{info['ratio'] / 10:.1f}%）｜"
                       f"繳款 {info['pay_start']:%m/%d}~{info['pay_end']:%m/%d}｜先確認券源、借券費｜" + x["detail"])
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
    print(f"重大訊息 {len(anns)} 筆，現增認股／繳款類 {len(cand)} 筆")
    rows, seen = [], {}
    for subj, seq, tm, d8, co, typ, name in sorted(cand, key=lambda a: (a[3], a[2])):
        try:
            info = parse_detail(_text(mops({"step": 2, "firstin": 1, "off": 1, "seq_no": seq,
                                            "spoke_time": tm, "spoke_date": d8, "co_id": co, "TYPEK": typ})))
        except Exception as e:
            print(f"  {co} {name} 內文抓取失敗：{e}")
            continue
        time.sleep(1.5)
        if not info:
            print(f"  {co} {name} 略過（延後作業或無法解析）：{subj[:50]}")
            continue
        ok = info["ratio"] > TH004
        print(f"  {co} {name} 每仟股 {info['ratio']:.2f} 股 繳款 {info['pay_start']}~{info['pay_end']} "
              f"{'→ 004 符合' if ok else '（未達 50 股）'}")
        if ok:
            seen[co] = build004(cal, co, name, info)  # 同一家公司後面的公告覆蓋前面的
    for rs in seen.values():
        rows += rs
    rows = [r for r in rows if r["act_date"] >= today.isoformat()]
    for r in sorted(rows, key=lambda r: r["act_date"]):
        print(f"  {r['act_date']} {r['act_timing']:5} {r['role']:5} 004 {r['company_name']}{r['company_code']}")
    if dry:
        print("DRY_RUN：不寫入")
        return
    if rows:
        supa("strategy_actions?on_conflict=strategy_id,variant,company_code,cycle,role",
             "POST", rows, prefer="resolution=merge-duplicates,return=minimal")
    print(f"已寫入 {len(rows)} 列")


if __name__ == "__main__":
    main()
