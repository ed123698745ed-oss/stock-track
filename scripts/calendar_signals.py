"""日曆型策略訊號：只靠交易日曆就能算出進出場日的策略。

涵蓋（對照 2026-10-09 兩份策略總表）：
  A01 台股開紅盤、A09 台股上中下旬(7 組)、A10 航空股景氣(2 組)、
  009 產業旺季前預期效應(5 檔)、021 台積電法說會前後（法說日需手動填）

交易日 = 週一到週五，且不在 Supabase holidays 表內。
某一年的休市日還沒公布（holidays 表沒有那一年）→ 那一年的訊號不產生，
不用推估日期填補。

用法：
  python3 scripts/calendar_signals.py            # 寫入 Supabase
  DRY_RUN=1 python3 scripts/calendar_signals.py  # 只印出，不寫入
"""
import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

D = dt.date
ROOT = pathlib.Path(__file__).resolve().parent.parent

# 統計數字直接取自策略總表，推播與網頁顯示用；空白欄位保持 None，不倒推。
META = {
    "A01": {"name": "台股開紅盤", "n": 37, "win": 73.0, "p": 0.003079},
    "A10": {"name": "航空股景氣"},
    "021": {"name": "台積電法說會前後", "n": 67, "win": 65.7, "p": 0.0020},
}
A09 = [  # (變體名稱, 月, 起日, 迄日(None=月底), 方向, n, 勝率, p)
    ("十二月下旬", 12, 21, None, "long", 39, 79.5, 0.0039),
    ("四月上旬", 4, 1, 10, "long", 40, 72.5, 0.0321),
    ("二月上旬", 2, 1, 10, "long", 39, 74.4, 0.0115),
    ("二月中旬", 2, 11, 20, "long", 39, 76.9, 0.0066),
    ("一月中旬", 1, 11, 20, "long", 40, 70.0, 0.0370),
    ("九月下旬", 9, 21, None, "short", 39, None, 0.0984),
    ("十二月中旬", 12, 11, 20, "short", 39, None, 0.0832),
]
S009 = [  # (代號, 名稱, 方向, n, 勝率, p)
    ("2731", "雄獅", "short", 12, 100.0, 0.0007),
    ("2719", "燦星旅", "short", 13, 76.9, 0.0104),
    ("2745", "五福", "short", 8, 87.5, 0.0200),
    ("3008", "大立光", "long", 16, 75.0, 0.0092),
    ("2910", "統領", "short", 14, 78.6, 0.0085),
]


class Cal:
    """交易日曆。years = holidays 表裡有資料的年份（= 已公布的年份）。"""

    def __init__(self, holidays):
        self.hol = set(holidays)
        self.years = {d.year for d in self.hol}

    def known(self, *days):
        return all(d.year in self.years for d in days)

    def is_trading(self, d):
        return d.weekday() < 5 and d not in self.hol

    def days(self, start, end):
        """start~end（含）之間的交易日。"""
        out, d = [], start
        while d <= end:
            if self.is_trading(d):
                out.append(d)
            d += dt.timedelta(days=1)
        return out

    def shift(self, d, n):
        """d 往後(n>0)或往前(n<0)數 n 個交易日；d 本身不算。"""
        step = 1 if n > 0 else -1
        left = abs(n)
        while left:
            d += dt.timedelta(days=step)
            if self.is_trading(d):
                left -= 1
        return d

    def month_days(self, y, m):
        end = D(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
        return self.days(D(y, m, 1), end)

    def lny_close(self, y):
        """農曆年封關日：1/10~3/5 之間，休市空檔最長的那一段之前的最後交易日。
        空檔至少 5 個日曆天才算（一般週末 3 天、連假 4 天）。"""
        td = self.days(D(y, 1, 10), D(y, 3, 5))
        best = max(zip(td, td[1:]), key=lambda p: (p[1] - p[0]).days, default=None)
        if not best or (best[1] - best[0]).days < 5:
            return None, None
        return best  # (封關日, 開紅盤日)


def leg(sid, variant, code, name, cycle, side, entry, entry_t, exit_, exit_t, stat):
    """一筆交易 → 進場、出場兩列。timing=None 代表原表沒寫開盤或收盤。"""
    rows = []
    for role, d, t, pair, pt in (("entry", entry, entry_t, exit_, exit_t),
                                 ("exit", exit_, exit_t, entry, entry_t)):
        if d is None:  # 出場日還算不出來（休市日未公布）：先只提醒進場，不推估
            continue
        rows.append({
            "strategy_id": sid,
            "strategy_name": META.get(sid, {}).get("name") or stat.get("name"),
            "variant": variant, "company_code": code, "company_name": name,
            "cycle": cycle, "role": role, "side": side,
            "act_date": d.isoformat(), "act_timing": t,
            "pair_date": pair.isoformat() if pair else None, "pair_timing": pt if pair else None,
            "detail": stat_text(stat),
        })
    return rows


def stat_text(s):
    parts = []
    if s.get("n"):
        parts.append(f"n={s['n']}")
    if s.get("win") is not None:
        parts.append(f"勝率{s['win']:g}%")
    if s.get("p") is not None:
        parts.append(f"p={s['p']:.4f}")
    return " ".join(parts)


def build(cal, years, tsmc_calls=()):
    """產生 years 各年度的所有日曆策略訊號列。日期涉及未公布年份者略過。"""
    rows, skipped = [], []

    def add(label, days, make):
        if all(days) and cal.known(*days):
            rows.extend(make())
        else:
            skipped.append(label)

    for y in years:
        # A01：封關日收盤買 → 開紅盤日開盤賣
        close, reopen = cal.lny_close(y) if cal.known(D(y, 1, 1)) else (None, None)
        add(f"A01 {y}", [close, reopen], lambda: leg(
            "A01", "封關→開紅盤", "TAIEX", "加權指數", str(y), "long",
            close, "close", reopen, "open", META["A01"]))

        # 009 統領：封關日前第 21 個交易日開盤空 → 封關日收盤回補
        if close:
            st = cal.shift(close, -21)
            code, nm, side, n, win, p = S009[4]
            add(f"009 {nm} {y}", [st, close], lambda: leg(
                "009", f"{nm}{code}", code, nm, str(y), side, st, "open", close, "close",
                {"name": "產業旺季前預期效應", "n": n, "win": win, "p": p}))
        else:
            skipped.append(f"009 統領 {y}")

        # A09：時段內每個交易日的報酬歸戶 → 時段前一交易日收盤進、時段最後交易日收盤出
        for var, m, d1, d2, side, n, win, p in A09:
            if not cal.known(D(y, m, 1)):
                skipped.append(f"A09 {var} {y}"); continue
            md = cal.month_days(y, m)
            span = [d for d in md if d.day >= d1 and (d2 is None or d.day <= d2)]
            if not span:
                skipped.append(f"A09 {var} {y}"); continue
            ent, ext = cal.shift(span[0], -1), span[-1]
            add(f"A09 {var} {y}", [ent, ext], lambda: leg(
                "A09", var, "TAIEX", "加權指數", str(y), side, ent, "close", ext, "close",
                {"name": "台股上中下旬", "n": n, "win": win, "p": p}))

        # A10 長榮航冬季：10 月第 10 交易日 → 隔年 1 月第 8 交易日（開盤買、開盤賣）
        # 進場日只需要 10 月的休市日；隔年 1 月還沒公布時先只提醒進場，出場日之後補上
        if cal.known(D(y, 10, 1)):
            ent = cal.month_days(y, 10)[9]
            ext = cal.month_days(y + 1, 1)[7] if cal.known(D(y + 1, 1, 1)) else None
            rows.extend(leg("A10", "長榮航冬季", "2618", "長榮航", str(y), "long",
                            ent, "open", ext, "open", {"n": 16, "win": 81.3, "p": 0.0053}))
            if ext is None:
                skipped.append(f"A10 長榮航 {y} 出場日（隔年休市日未公布，僅提醒進場）")
        else:
            skipped.append(f"A10 長榮航 {y}")
        # A10 華航夏季：5 月第 15 交易日開盤買 → 6 月第 1 交易日收盤賣
        if cal.known(D(y, 5, 1)):
            ent, ext = cal.month_days(y, 5)[14], cal.month_days(y, 6)[0]
            rows.extend(leg("A10", "華航夏季", "2610", "華航", str(y), "long",
                            ent, "open", ext, "close", {"n": 17, "win": 70.6, "p": 0.0273}))
        else:
            skipped.append(f"A10 華航 {y}")

        if cal.known(D(y, 6, 1)):
            # 009 旅遊三檔：7 月第一交易日開盤空 → 8 月最後交易日收盤回補
            ent, ext = cal.month_days(y, 7)[0], cal.month_days(y, 8)[-1]
            for code, nm, side, n, win, p in S009[:3]:
                rows.extend(leg("009", f"{nm}{code}", code, nm, str(y), side,
                                ent, "open", ext, "close",
                                {"name": "產業旺季前預期效應", "n": n, "win": win, "p": p}))
            # 009 大立光：6 月最後交易日前第 42 個交易日開盤買 → 6 月最後交易日收盤賣
            code, nm, side, n, win, p = S009[3]
            ext = cal.month_days(y, 6)[-1]
            ent = cal.shift(ext, -42)
            add(f"009 {nm} {y}", [ent], lambda: leg(
                "009", f"{nm}{code}", code, nm, str(y), side, ent, "open", ext, "close",
                {"name": "產業旺季前預期效應", "n": n, "win": win, "p": p}))
        else:
            skipped.append(f"009 旅遊/大立光 {y}")

    # 021：法說日前第 10 個交易日收盤買 2330 → 法說日收盤賣（法說日手動維護）
    for s in tsmc_calls:
        call = D.fromisoformat(s)
        if not cal.known(call) or not cal.is_trading(call):
            skipped.append(f"021 {s}（休市日未公布或非交易日）"); continue
        ent = cal.shift(call, -10)
        rows.extend(leg("021", "法說前10日", "2330", "台積電", s, "long",
                        ent, "close", call, "close", META["021"]))
    return rows, skipped


# ---------------- Supabase ----------------
def supa(path, method="GET", payload=None, prefer="return=minimal"):
    url = os.environ["SUPABASE_URL"].strip().rstrip("/") + "/rest/v1/" + path
    key = os.environ["SUPABASE_SERVICE_KEY"].strip()
    req = urllib.request.Request(
        url, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json", "Prefer": prefer})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read()
                return json.loads(body) if body.strip() else None
        except urllib.error.HTTPError as e:
            last = f"{e.code}: {e.read()[:300]!r}"
            if e.code not in (502, 503, 504):
                break
        except Exception as e:  # 網路抖動
            last = f"{type(e).__name__}: {e}"
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Supabase {method} {path} -> {last}")


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    hol = [D.fromisoformat(r["market_date"])
           for r in supa("holidays?select=market_date&limit=5000")]
    if not hol:
        sys.exit("holidays 表是空的，無法判斷交易日，不寫入")
    cal = Cal(hol)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    manual = json.loads((ROOT / "config" / "manual_events.json").read_text("utf-8"))

    rows, skipped = build(cal, [today.year - 1, today.year, today.year + 1],
                          manual.get("tsmc_earnings_calls", []))
    # 只寫今天以後的列。訊號通常提前數月就寫入，過去的列留在表裡（保留勾選狀態）；
    # 第一次上線時也不會把早就過去的進出場當成「未處理」冒出來。
    rows = [r for r in rows if r["act_date"] >= today.isoformat()]
    skipped = [x for x in skipped if not x.startswith(("A", "009")) or str(today.year - 1) not in x]

    print(f"已公布休市日年份：{sorted(cal.years)}")
    for r in sorted(rows, key=lambda r: r["act_date"]):
        print(f"  {r['act_date']} {r['act_timing'] or '時點?':5} {r['role']:5} {r['side']:5} "
              f"{r['strategy_id']} {r['variant']} {r['company_name']}")
    if skipped:
        print("略過（休市日未公布或日期無法判定）：" + "、".join(skipped))
    if dry:
        print("DRY_RUN：不寫入")
        return
    # 只送計算欄位；checked / ignored / note 是使用者在網頁上勾的，upsert 不會覆蓋
    for i in range(0, len(rows), 50):
        supa("strategy_actions?on_conflict=strategy_id,variant,company_code,cycle,role",
             "POST", rows[i:i + 50], prefer="resolution=merge-duplicates,return=minimal")
    print(f"已寫入 {len(rows)} 列")


if __name__ == "__main__":
    main()
