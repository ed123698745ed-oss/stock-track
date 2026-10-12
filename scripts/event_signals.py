"""事件型策略訊號：從 market_days（每日行情）判斷，寫入 strategy_actions。

  A08 大盤-5%        加權指數單日 ≤ −5% → 當日收盤買進，第 5 個交易日收盤賣出
  014 跌停群聚        上市＋上櫃普通股收跌停 ≥ 100 家，且不在前一事件起算 40 交易日內
                     → 當日收盤買進指數，持有 5 日／15 日（兩組）
  010 連續漲停開板    連續 ≥ 4 天收漲停後，第一個沒收漲停的交易日收盤放空，下一交易日收盤回補
  020 融資大減        二次群聚日的下一交易日開盤，等權買進當日全部訊號股，群聚日後第 20 個交易日收盤賣出

A08、014、010 都是「訊號日當天收盤進場」：晚間推播時進場已過，靠盤中提醒（scripts/intraday.py）。
晚間這裡負責：記錄事件、產生出場提醒、列出 010 明天要盯的股票。

用法：
  python3 scripts/event_signals.py            # 寫入 Supabase
  DRY_RUN=1 python3 scripts/event_signals.py  # 只印出
"""
import datetime as dt
import json
import os
import pathlib

from calendar_signals import Cal, leg, supa

TPE = dt.timezone(dt.timedelta(hours=8))
ROOT = pathlib.Path(__file__).resolve().parent.parent
D = dt.date

STAT = {
    "A08": {"name": "大盤-5%", "n": 21, "win": 66.7, "p": 0.0420},
    "014_5": {"name": "崩盤跌停群聚消退反彈", "n": 8, "win": 100.0, "p": 0.0290},
    "014_15": {"name": "崩盤跌停群聚消退反彈", "n": 8, "win": 100.0, "p": 0.0090},
    "010": {"name": "連續漲停開板反轉", "n": 900, "win": 67.0, "p": "<0.001"},
    "020": {"name": "個股融資大減", "n": 34, "win": 79.41, "p": "<0.0001"},
}
A08_TH = -5.0
C014_TH, C014_GAP = 100, 40
C010_STREAK = 4
M020 = {"look": 120, "ratio": 0.60, "dedupe": 20, "cluster": 0.02, "window": 20, "hold": 20,
        "min_base": 300}


def _d(x):
    return D.fromisoformat(x) if isinstance(x, str) else x


# ---------------- A08 ----------------
def a08(days, cal):
    rows = []
    for r in days:
        if r.get("taiex_pct") is not None and float(r["taiex_pct"]) <= A08_TH:
            t = _d(r["d"])
            rows += leg("A08", "單日≤−5%", "TAIEX", "加權指數", t.isoformat(), "long",
                        t, "close", cal.shift(t, 5), "close",
                        dict(STAT["A08"], name=STAT["A08"]["name"]))
            rows[-2]["detail"] = f"當日 {float(r['taiex_pct']):+.2f}%｜" + rows[-2]["detail"]
            rows[-1]["detail"] = rows[-2]["detail"]
    return rows


# ---------------- 014 ----------------
def c014(days, cal):
    """事件窗：前一事件日起算 40 個交易日內的新事件不算（不重新起算）。"""
    rows, last = [], None
    for i, r in enumerate(days):
        if r.get("ld_tpex") is None:
            continue  # 上櫃資料缺，家數不完整，不判斷
        n = (r.get("ld_twse") or 0) + r["ld_tpex"]
        if n < C014_TH:
            continue
        if last is not None and i - last < C014_GAP:
            continue
        last = i
        t = _d(r["d"])
        for hold in (5, 15):
            st = STAT[f"014_{hold}"]
            rs = leg("014", f"持有{hold}日", "TAIEX", "加權指數", t.isoformat(), "long",
                     t, "close", cal.shift(t, hold), "close", st)
            for x in rs:
                x["detail"] = f"跌停 {n} 家｜" + x["detail"]
            rows += rs
    return rows


# ---------------- 010 ----------------
def streaks(days, cal=None):
    """每檔股票截至每一天的連續收漲停天數。缺資料（停牌）或漲停未知 → 中斷。
    以 market_days 的列當交易日序列（休市日表沒有颱風假、舊年度，不能拿來判斷缺日）。"""
    out, cur = [], {}
    for r in days:
        nxt = {}
        for code, s in r["stocks"].items():
            nxt[code] = cur.get(code, 0) + 1 if s.get("lu") else 0
        out.append(nxt)
        cur = nxt
    return out


def c010(days, cal):
    rows = []
    st = streaks(days, cal)
    for i in range(1, len(days)):
        t = _d(days[i]["d"])
        for code, s in days[i]["stocks"].items():
            prev = st[i - 1].get(code, 0)
            if prev >= C010_STREAK and s.get("lu") is False:  # 漲停未知（None）不算開板
                rs = leg("010", "開板放空", code, s.get("n") or code, t.isoformat(), "short",
                         t, "close", cal.shift(t, 1), "close", STAT["010"])
                for x in rs:
                    x["detail"] = f"連 {prev} 根漲停後開板｜" + x["detail"]
                rows += rs
    return rows


def watch010(days, cal=None):
    """截至最後一天、已連續 ≥ 4 天收漲停的股票：下一交易日若收盤沒漲停 → 收盤放空。"""
    if not days:
        return []
    st = streaks(days, cal)[-1]
    last = days[-1]["stocks"]
    return sorted(({"code": c, "name": last[c].get("n") or c, "streak": n, "close": last[c]["c"]}
                   for c, n in st.items() if n >= C010_STREAK), key=lambda x: -x["streak"])


# ---------------- 020 ----------------
def c020(days, cal, today=None):
    """依 020 策略包 V01/R04 定義：
    個股訊號（每檔用自己的有效行情日：有開收盤價且成交量 > 0，且有融資餘額）
      1. 鏈接後融資餘額 ≤ 近 120 個有效行情日（含當天）最高值 × 60%
      2. 前一個有效行情日未達門檻（用前一日自己的 120 日高點判斷）
      3. 距同一檔上次被採計的訊號滿 20 個有效行情日；未滿的直接丟掉，不重新起算
      該股要有超過 120 筆資料才開始判斷。
    鏈接：當日「前日餘額」≠ 前一有效日「今日餘額」（減資、分割、調帳）→ 歷史餘額按比例調整。
    分母（有融資股票）：當日同時符合
      a. 普通股（四碼、非 00 開頭）  b. 當日是有效行情日且有融資資料列
      c. 已累積超過 120 個這樣的資料日（第 121 筆起）  d. 近 120 日鏈接後融資餘額最高值 > 0
      分母 < 300 檔時不計算觸發比例。分子只從進得了分母的股票產生。
    群聚日：當日訊號檔數 ≥ 分母 × 2%。
    二次群聚日：當日是群聚日，且前 20 個市場交易日內已有群聚日。
    進出場：二次群聚日 T 的下一市場交易日開盤等權買進 T 的全部訊號股；T 後第 20 個市場交易日收盤賣出。
    """
    M = M020
    hist = {}      # 代號 → 鏈接後餘額序列（只含有效行情日）
    lastraw = {}   # 代號 → 前一有效日的「今日餘額」（未鏈接）
    lastsig = {}   # 代號 → 上次被採計訊號時的有效日序號
    prevhit = {}   # 代號 → 前一有效日是否達門檻
    cluster_idx, rows, notes = [], [], []
    for i, r in enumerate(days):
        if not r.get("has_margin"):
            notes.append(f"{r['d']} 融資資料不完整，020 當天不判斷")
            continue
        sigs, base = [], 0
        for code, s in r["stocks"].items():
            mb = s.get("mb")
            if mb is None:
                continue
            h = hist.setdefault(code, [])
            # 鏈接：每個有融資資料的日子都比對，避免非有效日的餘額變動被誤當成減資／分割
            mp = s.get("mp")
            if h and mp is not None and lastraw.get(code) and mp != lastraw[code]:
                f = mp / lastraw[code]
                h[:] = [x * f for x in h]
            lastraw[code] = mb
            if not s.get("v"):
                continue
            h.append(float(mb))
            k = len(h) - 1
            if len(h) < M["look"]:
                continue  # 120 日高點還算不出來
            hi = max(h[-M["look"]:])
            hit = hi > 0 and h[-1] <= hi * M["ratio"]
            was = prevhit.get(code)
            prevhit[code] = hit
            if len(h) <= M["look"] or hi <= 0:
                continue  # 要超過 120 筆，且 120 日高點 > 0，才進得了分母
            base += 1
            if was is None:
                continue
            if hit and not was:
                if code in lastsig and k - lastsig[code] < M["dedupe"]:
                    continue
                lastsig[code] = k
                sigs.append(code)
        if base < M["min_base"]:
            if base:
                notes.append(f"{r['d']} 020 分母 {base} 檔 < {M['min_base']}，不計算觸發比例")
            continue
        if len(sigs) < base * M["cluster"]:
            continue
        second = any(i - j <= M["window"] for j in cluster_idx)
        cluster_idx.append(i)
        notes.append(f"群聚日 {r['d']}：訊號 {len(sigs)} 檔／分母 {base} 檔 = {len(sigs) / base:.2%}"
                     f"{'　← 二次群聚日' if second else ''}")
        if not second:
            continue
        t = _d(r["d"])
        names = "、".join(f"{r['stocks'][c].get('n') or c}{c}" for c in sigs)  # 完整名單，不截斷
        more = ""
        rs = leg("020", "二次群聚日", "BASKET", f"融資大減籃 {len(sigs)} 檔", t.isoformat(), "long",
                 cal.shift(t, 1), "open", cal.shift(t, M["hold"]), "close", STAT["020"])
        for x in rs:
            x["detail"] = f"E-Test 候選｜等權買進：{names}{more}｜" + x["detail"]
        rows += rs
    return rows, notes


def build(days, cal):
    days = sorted(days, key=lambda r: r["d"])
    r020, notes = c020(days, cal)
    return a08(days, cal) + c014(days, cal) + c010(days, cal) + r020, watch010(days, cal), notes


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    hol = [D.fromisoformat(r["market_date"]) for r in supa("holidays?select=market_date&limit=5000")]
    cal = Cal(hol)
    today = dt.datetime.now(TPE).date()
    days = supa("market_days?select=d,taiex,taiex_pct,ld_twse,ld_tpex,has_otc,has_margin,stocks"
                "&order=d.desc&limit=330")
    if not days:
        print("market_days 沒有資料，先跑 scripts/market.py")
        return
    rows, watch, notes = build(days, cal)
    rows = [r for r in rows if r["act_date"] >= today.isoformat()]
    print(f"行情 {len(days)} 天：{min(x['d'] for x in days)} ~ {max(x['d'] for x in days)}")
    for r in sorted(rows, key=lambda r: r["act_date"]):
        print(f"  {r['act_date']} {r['act_timing']:5} {r['role']:5} {r['side']:5} "
              f"{r['strategy_id']} {r['variant']} {r['company_name']}｜{r['detail'][:80]}")
    print(f"010 明天盯盤：{[(w['name'], w['streak']) for w in watch]}")
    print("020 群聚日（與策略包原始數據明細對帳用）：")
    for n in [n for n in notes if n.startswith("群聚日")] or ["  （這段期間沒有群聚日）"]:
        print("  " + n)
    for n in [n for n in notes if not n.startswith("群聚日")][-3:]:
        print("  " + n)
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "watch010.json").write_text(json.dumps(watch, ensure_ascii=False), "utf-8")
    last = max(days, key=lambda x: x["d"])
    (out / "market_status.json").write_text(json.dumps({
        "d": last["d"], "has_otc": last.get("has_otc"), "has_margin": last.get("has_margin"),
        "taiex_pct": last.get("taiex_pct"),
        "limit_down": (last.get("ld_twse") or 0) + (last.get("ld_tpex") or 0)}, ensure_ascii=False), "utf-8")
    if dry:
        print("DRY_RUN：不寫入")
        return
    for i in range(0, len(rows), 50):
        supa("strategy_actions?on_conflict=strategy_id,variant,company_code,cycle,role",
             "POST", rows[i:i + 50], prefer="resolution=merge-duplicates,return=minimal")
    print(f"已寫入 {len(rows)} 列")


if __name__ == "__main__":
    main()
