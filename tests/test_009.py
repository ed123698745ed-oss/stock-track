"""009 大立光進場日測試：7 月第一個交易日往前第 42 個交易日開盤買、6 月最後交易日收盤賣，
固定持有 42 個交易日（進場日與出場日都算），依 009 執行策略清單 V03。

不連網、不碰資料庫：python3 tests/test_009.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from calendar_signals import Cal, build  # noqa: E402

D = dt.date.fromisoformat
FAIL = []

# 測試用休市日（只求每年都有資料、且 5～6 月含一個休市日，不代表官方日曆）
HOL = [D(x) for x in ("2025-01-01", "2025-05-30", "2026-01-01", "2026-06-19",
                      "2027-01-01", "2027-06-09")]
cal = Cal(HOL)

for y in (2025, 2026, 2027):
    rows, _ = build(cal, [y])
    lg = {r["role"]: D(r["act_date"]) for r in rows
          if r["strategy_id"] == "009" and r["company_code"] == "3008"}
    jul1 = cal.month_days(y, 7)[0]
    want_ent = cal.shift(jul1, -42)
    want_ext = cal.month_days(y, 6)[-1]
    held = len(cal.days(lg.get("entry"), lg.get("exit"))) if lg.get("entry") and lg.get("exit") else None
    for name, got, want in ((f"{y} 進場日", lg.get("entry"), want_ent),
                            (f"{y} 出場日", lg.get("exit"), want_ext),
                            (f"{y} 持有交易日數", held, 42)):
        ok = got == want
        print(("✓ " if ok else "✗ ") + f"{name}：{got}")
        if not ok:
            FAIL.append(f"{name}：得到 {got}，應為 {want}")

if FAIL:
    sys.exit("失敗：\n" + "\n".join(FAIL))
print("全部通過")
