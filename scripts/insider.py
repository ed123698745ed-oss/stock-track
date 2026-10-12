"""019 內部人申報轉讓（E-Test C02）

資料：公開資訊觀測站「內部人持股轉讓事前申報日報表」（t56sb12_q1 → ajax_t56sb12 step=2）。
  申報日 T（當日 17:30 前輸入，視為收盤後才看得到）：
    ・轉讓方式只有「一般交易」（排除鉅額逐筆、盤後定價、多種方式、贈與、信託、洽特定人…）
    ・「本單為變更」不算新事件
    ・申報人是法人：姓名含 公司／投資／基金／銀行／專戶／有限／株式／Limited／Ltd／Inc／Corp／LLC
    ・同一檔、同一申報日多筆合併成一個訊號
  大盤濾網：T（非交易日取之前最近交易日）加權收盤 < 近 20 日收盤平均
  進出場：T 後第 1 個交易日開盤放空，進場日算第 1 天、第 5 個交易日收盤回補
  同一檔還在持有（含出場當天）→ 新訊號略過（只看本策略自己的持倉）

用法：
  python3 scripts/insider.py                 # 掃最近 7 天
  DAYS=60 DRY_RUN=1 python3 scripts/insider.py
"""
import datetime as dt
import os
import re
import time
import unicodedata

from calendar_signals import Cal, leg, supa
from cash_issue import _get, _post_ov, _text, roc

TPE = dt.timezone(dt.timedelta(hours=8))
STAT019 = {"name": "內部人申報轉讓", "n": 757, "win": 59.8, "p": None}
HOLD019 = 5
MA = 20
CORP = re.compile(r"公司|投資|基金|銀行|專戶|有限|株式|limited|ltd|inc|corp|llc", re.I)


def fetch_day(d):
    """某一天的申報列：[{date, code, name, who, method, change}]"""
    y, m, dd = f"{d.year - 1911}", f"{d.month:02d}", f"{d.day:02d}"
    h = _post_ov("ajax_t56sb12", {"run": "", "step": "2", "year": y, "month": m, "day": dd,
                                  "report": "SY", "firstin": "true"})
    h = h.replace("</d>", "</td>")  # 觀測站第一欄的結尾標籤打錯
    out = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        cells = [_text(c).replace(" ", " ").strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(cells) < 8 or not re.fullmatch(r"\d{2,3}/\d{1,2}/\d{1,2}", cells[1]):
            continue
        out.append({"change": cells[0], "date": roc(cells[1]), "code": cells[2], "name": cells[3],
                    "role": cells[4], "who": unicodedata.normalize("NFKC", cells[5]), "method": cells[6]})
    return out


def qualifies(r):
    if "變更" in r["change"]:
        return False
    method = re.sub(r"\(每日得轉讓股數限制\)|（每日得轉讓股數限制）", "", r["method"]).strip()
    if method != "一般交易":  # 勾了其他方式或兩種以上都會多出文字
        return False
    return bool(CORP.search(r["who"]))


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    today = dt.datetime.now(TPE).date()
    days = int(os.environ.get("DAYS") or 7)
    cal = Cal([dt.date.fromisoformat(r["market_date"]) for r in supa("holidays?select=market_date&limit=5000")])
    mk = supa(f"market_days?select=d,taiex&order=d.desc&limit={days + MA + 40}")
    taiex = {dt.date.fromisoformat(r["d"]): float(r["taiex"]) for r in mk if r.get("taiex")}
    tdays = sorted(taiex)

    _get("https://mopsov.twse.com.tw/mops/web/t56sb12_q1")
    events = {}
    d = today - dt.timedelta(days=days)
    while d <= today:
        if d.weekday() < 5:
            try:
                rs = fetch_day(d)
            except Exception as e:
                print(f"  {d} 抓取失敗：{e}")
                rs = []
            for r in rs:
                if qualifies(r):
                    events.setdefault((r["date"], r["code"]), []).append(r)
            time.sleep(1.2)
        d += dt.timedelta(days=1)
    print(f"符合（一般交易＋法人、非變更）事件 {len(events)} 個")

    held = {}  # 本策略自己的持倉：code → 最後出場日
    for x in supa("strategy_actions?select=company_code,act_date&strategy_id=eq.019&role=eq.exit"):
        c, e = x["company_code"], dt.date.fromisoformat(x["act_date"])
        held[c] = max(held.get(c, e), e)

    rows = []
    for (t, code), rs in sorted(events.items()):
        r0 = rs[0]
        base = max((x for x in tdays if x <= t), default=None)
        hist = [taiex[x] for x in tdays if x <= t][-MA:] if base else []
        if len(hist) < MA:
            print(f"  {t} {code} {r0['name']}：加權指數歷史不足，略過")
            continue
        ma = sum(hist) / MA
        if taiex[base] >= ma:
            print(f"  {t} {code} {r0['name']}：加權 {taiex[base]:.0f} ≥ 月線 {ma:.0f}，不做")
            continue
        ent = cal.shift(t, 1) if cal.known(t) else None
        if not ent or not cal.known(ent):
            print(f"  {t} {code} {r0['name']}：休市日未公布，略過")
            continue
        if code in held and ent <= held[code]:
            print(f"  {t} {code} {r0['name']}：持有中（到 {held[code]}），略過")
            continue
        ext = cal.shift(ent, HOLD019 - 1)
        who = "、".join(sorted({x["who"][:20] for x in rs}))
        print(f"  {t} {code} {r0['name']} → 019 放空 {ent} 開盤、{ext} 收盤回補｜{who}")
        legs = leg("019", "內部人申報轉讓", code, r0["name"], t.isoformat(), "short", ent, "open", ext, "close", STAT019)
        for x in legs:
            x["detail"] = (f"{t:%m/%d} 申報一般交易轉讓：{who}｜加權在月線下｜"
                           f"先確認券源、平盤下可否放空；開盤沒成交就放棄｜" + x["detail"])
        rows += legs
        held[code] = ext

    rows = [r for r in rows if r["act_date"] >= today.isoformat()]
    if dry:
        print(f"DRY_RUN：不寫入（{len(rows)} 列）")
        return
    if rows:
        supa("strategy_actions?on_conflict=strategy_id,variant,company_code,cycle,role",
             "POST", rows, prefer="resolution=merge-duplicates,return=minimal")
    print(f"已寫入 {len(rows)} 列")


if __name__ == "__main__":
    main()
