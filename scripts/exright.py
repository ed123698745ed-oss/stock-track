"""A11 大幅除權息（總表 A1）

資料：上市 TWT48U_ALL、上櫃 tpex_exright_prepost（除權除息預告表）；面額取公司基本資料。
  除權息日 T0，以 T-6 收盤 P 試算（回測用 T-1 收盤，實際進場前拿不到，會有偏差）：
    參考價 = (P − 現金股利 + 認購價 × 現增配股率) ÷ (1 + 無償配股率 + 現增配股率)
    幅度   = (P − 參考價) ÷ P ≥ 15%
    稅拖曳 = (現金股利 + 無償配股率 × 面額) ÷ P ≤ 5%
  進出場：T-5 開盤買進 → T0 收盤賣出
  幅度落在 13~17%、或稅拖曳落在 4~6% → 標「接近門檻」

用法：python3 scripts/exright.py；DRY_RUN=1 只印不寫；PREVIEW=1 用最新收盤試算還沒到 T-6 的事件
"""
import datetime as dt
import json
import os
import re

from calendar_signals import Cal, leg, supa
from cash_issue import _get

TPE = dt.timezone(dt.timedelta(hours=8))
STAT = {"name": "大幅除權息", "n": 85, "win": 65.9, "p": 0.000047}
DROP, DRAG = 0.15, 0.05


def num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return None


def roc8(s):
    s = str(s).strip()
    return dt.date(int(s[:-4]) + 1911, int(s[-4:-2]), int(s[-2:]))


def events():
    """[{code, name, t0, cash, stock, sub, sub_px}]；欄位空白當 0，認購價未公告 → None。"""
    out = []
    tw = json.loads(_get("https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL", hdr={"Accept": "application/json"}))
    for r in tw:
        out.append({"code": r["Code"].strip(), "name": r["Name"].strip(), "t0": roc8(r["Date"]),
                    "cash": r["CashDividend"], "stock": r["StockDividendRatio"],
                    "sub": r["SubscriptionRatio"], "sub_px": r["SubscriptionPricePerShare"]})
    tp = json.loads(_get("https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost", hdr={"Accept": "application/json"}))
    for r in tp:
        out.append({"code": r["SecuritiesCompanyCode"].strip(), "name": r["CompanyName"].strip(),
                    "t0": roc8(r["ExRrightsExDividendDate"]), "cash": r["CashDividend"],
                    "stock": r["StockDividendRatio"], "sub": r["SubscriptionRatioToNewSharesIssued"],
                    "sub_px": r["SubscriptionPricePerShare"]})
    for e in out:
        for k in ("cash", "stock", "sub"):
            v = str(e[k]).strip()
            e[k] = 0.0 if v in ("", "-") else num(v)  # 「尚未公告」→ None
        e["sub_px"] = 0.0 if not e["sub"] else num(e["sub_px"])
    return out


def face_values():
    fv = {}
    for u, kc, kf in (("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "公司代號", "普通股每股面額"),
                      ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "SecuritiesCompanyCode", "ParValueOfCommonStock")):
        try:
            for r in json.loads(_get(u, hdr={"Accept": "application/json"})):
                m = re.search(r"新台幣\s*([\d.]+)", str(r.get(kf) or ""))
                if m:
                    fv[str(r[kc]).strip()] = float(m.group(1))
        except Exception as e:
            print(f"  面額資料抓取失敗 {u}：{e}")
    return fv


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    today = dt.datetime.now(TPE).date()
    cal = Cal([dt.date.fromisoformat(r["market_date"]) for r in supa("holidays?select=market_date&limit=5000")])
    evs = [e for e in events() if e["t0"] > today and cal.known(e["t0"])]
    print(f"預告表未來除權息 {len(evs)} 筆")
    need = {cal.shift(e["t0"], -6) for e in evs}
    closes = {}
    for d in sorted(x for x in need if x <= today):
        r = supa(f"market_days?select=stocks&d=eq.{d.isoformat()}")
        if r:
            closes[d] = {c: s.get("c") for c, s in r[0]["stocks"].items()}
    preview = os.environ.get("PREVIEW") == "1"  # 測試用：還沒到 T-6 的也用最新收盤試算
    if preview:
        r = supa("market_days?select=d,stocks&order=d.desc&limit=1")[0]
        latest = {c: s.get("c") for c, s in r["stocks"].items()}
    fv = face_values()

    rows = []
    for e in sorted(evs, key=lambda e: e["t0"]):
        t5, t6 = cal.shift(e["t0"], -5), cal.shift(e["t0"], -6)
        if t5 <= today:
            continue  # 進場日已過或就是今天
        if t6 > today and not preview:
            continue  # T-6 收盤還沒出來，之後的晚上再算
        p = (closes.get(t6) or (latest if preview else {})).get(e["code"])
        if p is None:
            continue  # 非普通股（ETF 等）或當天沒行情
        if None in (e["cash"], e["stock"], e["sub"], e["sub_px"]):
            print(f"  {e['code']} {e['name']} T0={e['t0']}：股利或認購價尚未公告，無法試算")
            continue
        p = float(p)
        ref = (p - e["cash"] + e["sub_px"] * e["sub"]) / (1 + e["stock"] + e["sub"])
        drop = (p - ref) / p
        face = fv.get(e["code"])
        if face is None:
            if e["stock"]:
                print(f"  {e['code']} {e['name']} T0={e['t0']}：查不到面額，配股的稅拖曳算不出來，略過（不推估）")
                continue
            face = 10.0  # 沒有配股時面額不影響稅拖曳
        drag = (e["cash"] + e["stock"] * face) / p
        near = abs(drop - DROP) <= 0.02 or abs(drag - DRAG) <= 0.01
        ok = drop >= DROP and drag <= DRAG
        tag = f"T-6 收盤 {p:g}：幅度 {drop:.1%}、稅拖曳 {drag:.1%}" + (f"（面額 {face:g}）" if face != 10 else "")
        if not ok:
            if drop >= 0.10:
                print(f"  {e['code']} {e['name']} T0={e['t0']} {tag} → 不符合")
            continue
        print(f"  {e['code']} {e['name']} T0={e['t0']} {tag} → A11 符合{'（接近門檻）' if near else ''}")
        rs = leg("A11", "大幅除權息", e["code"], e["name"], e["t0"].isoformat(), "long", t5, "open", e["t0"], "close", STAT)
        for x in rs:
            x["detail"] = (("⚠ 接近門檻（回測用 T-1 收盤，結果可能翻轉）｜" if near else "") +
                           "T-6 試算版（回測統計為 T-1 版，兩者篩選結果可能不同）｜" +
                           f"{e['t0']:%m/%d} 除權息｜{tag}｜" + x["detail"])
        rows += rs

    if dry:
        print(f"DRY_RUN：不寫入（{len(rows)} 列）")
        return
    if rows:
        supa("strategy_actions?on_conflict=strategy_id,variant,company_code,cycle,role",
             "POST", rows, prefer="resolution=merge-duplicates,return=minimal")
    print(f"已寫入 {len(rows)} 列")


if __name__ == "__main__":
    main()
