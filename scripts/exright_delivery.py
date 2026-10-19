"""A11 配股出場：查配股官方可賣日，另寫一筆「配股收盤賣」提醒（R04 規則）

R04：原股 T0 收盤賣；配股於官方最早可賣日收盤賣（休市或無成交順延到下一交易日）。
來源（與 Elon R04 相同）：
  上市：證交所 LT185「上市普通股股數增減公告」
        種類含 增資新股上市／新股權利證書上市／權利證書終止上市增資股上市
  上櫃：櫃買中心 bulletin/tdr「股票增減資上櫃掛牌公告」
        種類含 增資新股櫃檯買賣／新股權利證書上櫃／權利證書下櫃增資股票上櫃
  主旨需與除權配股有關（除權、配股、盈餘、公積、股票股利、無償、增資股、權利證書），
  排除 現金增資、減資、員工、限制、私募、轉換、庫藏、更名、面額。
  取 T0 之後、150 天內生效日最早的一則（有權利證書時取權利證書那一批）。
查不到就不寫，不推估日期；之後每天再查。

對象：strategy_actions 中 A11 的原股出場列（detail 有「配股 x 股／股」），T0 在近 150 天內。
用法：python3 scripts/exright_delivery.py；DRY_RUN=1 只印不寫
"""
import datetime as dt
import json
import os
import re
import time
import urllib.request

from calendar_signals import Cal, supa

TPE = dt.timezone(dt.timedelta(hours=8))
SID, VAR = "A11", "大幅除權息・配股"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0 Safari/537.36"}
KIND = re.compile(r"增資新股|新股權利證書|權利證書.*增資股")
DIV = re.compile(r"除權|配股|盈餘|公積|股票股利|無償|增資股|權利證書")
EXCL = re.compile(r"現金增資|減資|員工|限制|私募|轉換|庫藏|更名|面額")
DATE = re.compile(r"(\d{2,3})\s*[年/]\s*(\d{1,2})\s*[月/]\s*(\d{1,2})")  # 證交所「114年11月28日」、櫃買「114/09/02」


def get_json(url, ref=None):
    h = dict(UA, **({"Referer": ref} if ref else {}))
    for i in range(3):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60).read())
        except Exception as e:
            last = e
            time.sleep(5 * (i + 1))
    raise last


def roc(s):
    m = DATE.search(str(s or ""))
    return dt.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))) if m else None


def months(a, b):
    d = a.replace(day=1)
    while d <= b:
        e = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        yield d, min(e, b)
        d = e + dt.timedelta(days=1)


def lt185(a, b):
    """[(代號, 種類, 主旨, 生效日)]"""
    out = []
    for s, e in months(a, b):
        j = get_json("https://www.twse.com.tw/rwd/zh/announcement/LT185?response=json&selectType="
                     f"&startDate1={s:%Y%m%d}&endDate1={e:%Y%m%d}&startDate2=&endDate2=&stockNo=&checkedtdr=false",
                     "https://www.twse.com.tw/zh/page/announcement/LT185.html")
        f = j.get("fields") or []
        for r in j.get("data") or []:
            d = dict(zip(f, r))
            out.append((str(d.get("公司代號", "")).strip(), str(d.get("公告種類", "")), str(d.get("主旨", "")),
                        roc(d.get("普通股數/TDR單位數增減生效日期"))))
        time.sleep(3)
    return out


def tpex(a, b):
    out = []
    for s, e in months(a, b):
        j = get_json(f"https://www.tpex.org.tw/www/zh-tw/bulletin/tdr?startDate={s:%Y/%m/%d}"
                     f"&endDate={e:%Y/%m/%d}&mkt=O&sect=&code=&response=json")
        for t in j.get("tables") or [j]:
            f = t.get("fields") or []
            for r in t.get("data") or []:
                d = dict(zip(f, r))
                code = next((str(v).strip() for k, v in d.items() if "代號" in k), "")
                kind = next((str(v) for k, v in d.items() if "種類" in k), "")
                subj = next((str(v) for k, v in d.items() if "主旨" in k or "說明" in k or "內容" in k), "")
                eff = next((roc(v) for k, v in d.items() if "生效" in k or "買賣日" in k or "上櫃日" in k), None)
                out.append((code, kind, subj, eff))
        time.sleep(1.5)
    return out


def selftest(spec):
    """TEST="代號:T0,代號:T0"：不讀資料庫，只查公告並印出配股可賣日（對照 Elon R04 明細用）。"""
    cases = [(c, dt.date.fromisoformat(d)) for c, d in (x.split(":") for x in spec.split(","))]
    lo, hi = min(d for _, d in cases), max(d for _, d in cases) + dt.timedelta(days=100)
    ann = []
    for name, fn in (("證交所 LT185", lt185), ("櫃買公告", tpex)):
        got = fn(lo, hi)
        print(f"{name} {len(got)} 則；樣本：{got[:2]}")
        ann += [(name,) + x for x in got]
    for code, t0 in cases:
        hits = sorted((eff, src, kind, subj[:40]) for src, c, kind, subj, eff in ann
                      if c == code and eff and t0 < eff <= t0 + dt.timedelta(days=150)
                      and KIND.search(kind) and DIV.search(subj + kind) and not EXCL.search(subj))
        print(code, t0, "→", hits[:3] or "查無")


def main():
    if os.environ.get("TEST"):
        return selftest(os.environ["TEST"])
    dry = os.environ.get("DRY_RUN") == "1"
    today = dt.datetime.now(TPE).date()
    cal = Cal([dt.date.fromisoformat(r["market_date"]) for r in supa("holidays?select=market_date&limit=5000")])
    since = (today - dt.timedelta(days=150)).isoformat()
    exits = [r for r in supa(f"strategy_actions?select=*&strategy_id=eq.{SID}&variant=eq.%E5%A4%A7%E5%B9%85%E9%99%A4%E6%AC%8A%E6%81%AF"
                             f"&role=eq.exit&ignored=is.false&act_date=gte.{since}") or []
             if re.search(r"配股 [\d.]+ 股／股", r.get("detail") or "")]
    done = {(r["company_code"], r["cycle"]) for r in
            supa(f"strategy_actions?select=company_code,cycle&strategy_id=eq.{SID}&variant=eq.{urllib.request.quote(VAR)}") or []}
    todo = [r for r in exits if (r["company_code"], r["cycle"]) not in done and r["act_date"] <= today.isoformat()]
    print(f"A11 有配股、原股已出場、尚未找到配股可賣日 {len(todo)} 筆")
    if not todo:
        return
    lo = min(dt.date.fromisoformat(r["act_date"]) for r in todo)
    ann = []
    for name, fn in (("證交所 LT185", lt185), ("櫃買公告", tpex)):
        try:
            # 迄日放到 45 天後：LT185 的日期區間若是以「生效日」篩選，只查到今天會漏掉明天才生效的配股
            got = fn(lo, today + dt.timedelta(days=45))
            print(f"  {name} {len(got)} 則")
            ann += [(name,) + x for x in got]
        except Exception as e:
            print(f"  ⚠ {name} 抓取失敗：{e}")
    rows = []
    for r in todo:
        t0 = dt.date.fromisoformat(r["act_date"])
        hits = sorted((eff, src, kind) for src, code, kind, subj, eff in ann
                      if code == r["company_code"] and eff and t0 < eff <= t0 + dt.timedelta(days=150)
                      and KIND.search(kind) and DIV.search(subj + kind) and not EXCL.search(subj))
        if not hits:
            print(f"  {r['company_code']} {r['company_name']} T0 {t0}：還沒有配股上市（櫃）公告")
            continue
        cert = [h for h in hits if "權利證書" in h[2]]
        eff, src, kind = (cert or hits)[0]
        sell = eff if cal.is_trading(eff) else cal.shift(eff, 1)
        r0 = re.search(r"配股 ([\d.]+) 股／股", r["detail"]).group(1)
        print(f"  {r['company_code']} {r['company_name']} T0 {t0} → 配股可賣 {eff}（{src}：{kind}）→ {sell} 收盤賣")
        rows.append({"strategy_id": SID, "strategy_name": r["strategy_name"], "variant": VAR,
                     "company_code": r["company_code"], "company_name": r["company_name"], "cycle": r["cycle"],
                     "role": "exit", "side": "long", "act_date": sell.isoformat(), "act_timing": "close",
                     "pair_date": r.get("pair_date"), "pair_timing": r.get("pair_timing"),
                     "detail": f"配股 {r0} 股／股｜{src}「{kind}」生效 {eff:%m/%d}"
                               + ("（休市順延）" if sell != eff else "") + f"｜原股已於 {t0:%m/%d} 賣出"})
    if dry:
        print(f"DRY_RUN：不寫入（{len(rows)} 列）")
        return
    if rows:
        supa("strategy_actions?on_conflict=strategy_id,variant,company_code,cycle,role",
             "POST", rows, prefer="resolution=merge-duplicates,return=minimal")
    print(f"已寫入 {len(rows)} 列")


if __name__ == "__main__":
    main()
