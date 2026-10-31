"""A11 大幅除權息（A11 R04，Eve 2026-10-17 複審通過）

資料：上市 TWT48U_ALL、上櫃 tpex_exright_prepost（除權除息預告表）；面額取公司基本資料。
  除權息日 T0，T-6 收盤後以當時已公告的股利與 T-6 收盤 P 試算：
    幅度   = 1 − (P − C) ÷ ((1 + r) × P)（R04：同期現增當獨立事件，認股權不計入幅度與報酬）
    稅拖曳 = (現金股利 + 無償配股率 × 面額) ÷ P
    兩者先四捨五入到 0.01%，幅度 ≥ 15.00% 且稅拖曳 ≤ 5.00% 才入選（R01：14.9997% 算 15.00%）
  進出場：T-5 開盤買進 → 原股 T0 收盤賣出；配股在官方上市（櫃）可賣日收盤賣出
    （配股可賣日由 scripts/exright_delivery.py 從 TWSE LT185／TPEx 公告補上，另成一筆出場提醒）
  幅度落在 13~17%、或稅拖曳落在 4~6% → 標「接近門檻」

用法：python3 scripts/exright.py；DRY_RUN=1 只印不寫；PREVIEW=1 用最新收盤試算還沒到 T-6 的事件
"""
import datetime as dt
import json
import os
import pathlib
import re
import sys

from calendar_signals import Cal, leg, supa
from cash_issue import _get

TPE = dt.timezone(dt.timedelta(hours=8))
STAT = {"name": "大幅除權息", "n": 83, "win": 72.3, "p": 0.0000041}  # R04（推播顯示以 perf.json 為準）
DROP, DRAG = 0.15, 0.05


def num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return None


def roc8(s):
    s = str(s).strip()
    return dt.date(int(s[:-4]) + 1911, int(s[-4:-2]), int(s[-2:]))


SOURCES = {"twse": "上市", "tpex": "上櫃"}


def _rows(body):
    """預告表回應 → list；不是 JSON 陣列（被擋時回 HTML、錯誤訊息物件）當解析失敗，交給 _get 重試。"""
    j = json.loads(body)
    if not isinstance(j, list):
        raise ValueError(f"預期 JSON 陣列，收到 {type(j).__name__}")
    return j


def _twse():
    return [{"mkt": "上市", "code": r["Code"].strip(), "name": r["Name"].strip(), "t0": roc8(r["Date"]),
             "cash": r["CashDividend"], "stock": r["StockDividendRatio"],
             "sub": r["SubscriptionRatio"], "sub_px": r["SubscriptionPricePerShare"]}
            for r in _get("https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL",
                          hdr={"Accept": "application/json"}, parse=_rows)]


def _tpex():
    return [{"mkt": "上櫃", "code": r["SecuritiesCompanyCode"].strip(), "name": r["CompanyName"].strip(),
             "t0": roc8(r["ExRrightsExDividendDate"]), "cash": r["CashDividend"],
             "stock": r["StockDividendRatio"], "sub": r["SubscriptionRatioToNewSharesIssued"],
             "sub_px": r["SubscriptionPricePerShare"]}
            for r in _get("https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost",
                          hdr={"Accept": "application/json"}, parse=_rows)]


def events(failed=None):
    """[{mkt, code, name, t0, cash, stock, sub, sub_px}]；欄位空白當 0，認購價未公告 → None。
    上市、上櫃各自抓：一邊失敗不影響另一邊，失敗的來源（twse／tpex）記到 failed；
    沒給 failed 且兩邊都失敗才丟例外。"""
    out, err, cnt = [], None, []
    for src, fetch in (("twse", _twse), ("tpex", _tpex)):
        try:
            got = fetch()
            out += got
            cnt.append(f"{SOURCES[src]}預告表 {len(got)} 筆")
        except Exception as e:
            err = e
            cnt.append(f"{SOURCES[src]}預告表抓取失敗")
            print(f"  {SOURCES[src]}除權息預告表抓取失敗：{type(e).__name__}: {str(e)[:200]}")
            if failed is not None:
                failed.append(src)
    print("、".join(cnt))
    if failed is None and err is not None and not out:
        raise err
    for e in out:
        for k in ("cash", "stock", "sub"):
            v = str(e[k]).strip()
            e[k] = 0.0 if v in ("", "-") else num(v)  # 「尚未公告」→ None
        e["sub_px"] = 0.0 if not e["sub"] else num(e["sub_px"])
    return out


def write_status(today, failed):
    """這一輪哪些來源失敗 → out/exright_status.json，給 daily_push.py 判斷警告要怎麼寫。"""
    try:
        d = pathlib.Path(__file__).resolve().parent.parent / "out"
        d.mkdir(exist_ok=True)
        (d / "exright_status.json").write_text(
            json.dumps({"d": today.isoformat(), "failed": failed}, ensure_ascii=False), "utf-8")
    except Exception as e:
        print(f"⚠ A11 狀態檔寫入失敗：{e}")


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
    failed = []
    evs = [e for e in events(failed) if e["t0"] > today and cal.known(e["t0"])]
    write_status(today, failed)
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
        head = f"  {e.get('mkt', '')} {e['code']} {e['name']} T0={e['t0']} T-5={t5} T-6={t6}"
        if t5 <= today:
            print(f"{head} 略過：T-5<=今天（進場日已過或就是今天）")
            continue
        if t6 > today and not preview:
            print(f"{head} 略過：T-6>今天（T-6 收盤還沒出來，之後的晚上再算）")
            continue
        p = (closes.get(t6) or (latest if preview else {})).get(e["code"])
        if p is None:
            print(f"{head} 略過：無 T-6 收盤（非普通股或無行情）")
            continue
        if None in (e["cash"], e["stock"]):
            print(f"{head} 略過：股利尚未公告，無法試算")
            continue
        p = float(p)
        # R04：同期現金增資當獨立事件，認股權不進幅度也不計報酬 → 幅度只看現金股利與無償配股
        drop = 1 - (p - e["cash"]) / ((1 + e["stock"]) * p)
        face = fv.get(e["code"])
        if face is None:
            if e["stock"]:
                print(f"{head} T-6收盤={p:g} 幅度={drop:.2%} 略過：查不到面額，配股的稅拖曳算不出來（不推估）")
                continue
            face = 10.0  # 沒有配股時面額不影響稅拖曳
        drag = (e["cash"] + e["stock"] * face) / p
        near = abs(drop - DROP) <= 0.02 or abs(drag - DRAG) <= 0.01
        ok = round(drop, 4) >= DROP and round(drag, 4) <= DRAG  # R01：先四捨五入到 0.01% 再比
        print(f"{head} T-6收盤={p:g} 現金={e['cash']:g} 配股={e['stock']:g} "
              f"幅度={drop:.2%} 稅拖曳={drag:.2%} → {'符合' if ok else '不符合'}")
        tag = f"T-6 收盤 {p:g}：幅度 {drop:.1%}、稅拖曳 {drag:.1%}" + (f"（面額 {face:g}）" if face != 10 else "")
        if not ok:
            continue
        print(f"  {e['code']} {e['name']} T0={e['t0']} {tag} → A11 符合{'（接近門檻）' if near else ''}")
        rs = leg("A11", "大幅除權息", e["code"], e["name"], e["t0"].isoformat(), "long", t5, "open", e["t0"], "close", STAT)
        for x in rs:
            x["detail"] = (("⚠ 接近門檻（股利若更正可能翻轉）｜" if near else "") +
                           f"{e['t0']:%m/%d} 除權息｜{tag}｜" +
                           (f"同期現增（認購率 {e['sub']:g}，不計入幅度）｜" if e.get("sub") else "") +
                           (f"原股 T0 收盤賣；配股 {e['stock']:g} 股／股等官方可賣日收盤賣（公告後另推提醒）｜"
                            if e["stock"] else "") + x["detail"])
        rows += rs

    if dry:
        print(f"DRY_RUN：不寫入（{len(rows)} 列）")
    else:
        if rows:
            supa("strategy_actions?on_conflict=strategy_id,variant,company_code,cycle,role",
                 "POST", rows, prefer="resolution=merge-duplicates,return=minimal")
        print(f"已寫入 {len(rows)} 列")
        # 當天成功標記：同一天稍晚重跑（補推）抓失敗時，daily_push.py 看到這個就不再推「抓取失敗」警告。
        # T-6 收盤（今天）還沒進資料庫時不記：那一輪的試算不完整，之後重跑失敗仍要警告。
        ok = [src for src in SOURCES if src not in failed]
        if ok and all(d in closes for d in need if d <= today):
            try:
                supa("intraday_alerts?on_conflict=d,key", "POST",
                     [{"d": today.isoformat(), "key": f"ok:A11:{src}"} for src in ok],
                     prefer="resolution=ignore-duplicates,return=minimal")
            except Exception as e:
                print(f"⚠ A11 成功標記寫入失敗：{e}")
    if failed:
        print(f"{'、'.join(SOURCES[x] for x in failed)}除權息預告表抓取失敗（另一邊照常試算）")
        sys.exit(1)  # 讓 workflow 的 EXRIGHT_OUTCOME 變 failure，推播帶警告


if __name__ == "__main__":
    main()
