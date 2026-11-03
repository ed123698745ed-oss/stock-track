"""離線回放程式比對：讀 export_push_log.py（RAW=1）輸出的 raw.json，不連 Supabase、不送 LINE。

用法：
  python3 scripts/push_compare_replay.py raw.json            # 印「程式比對結果」一節
  python3 scripts/push_compare_replay.py raw.json --inject   # 先植入五種錯誤再比對（驗收用）

--inject 植入（只改記憶體裡的測試資料）：
  ① 表外股票：009 推一檔不在名單的 2603
  ② 執行日差一個交易日：第一筆主推播策略項目的執行日往後挪一個交易日
  ③ 開盤收盤顛倒：第二筆主推播策略項目的開收盤對調
  ④ 應推未推：應推清單加一筆沒有推播的 019
  ⑤ 重複發送：第一則主推播整則再送一次（新訊息編號）
"""
import copy
import datetime as dt
import json
import sys

from calendar_signals import Cal
from push_compare import compare, earlier_fixes, render_section
from push_report import parse

INJECT_NOTE = "植入測試"


def inject(raw, cal):
    raw = copy.deepcopy(raw)
    msgs, plog = raw["messages"], raw["push_log"]
    mains = [m for m in msgs if m["mode"] == "main" and m.get("status") == 200]
    m0 = mains[0]
    rows0 = [r for r in plog if r["message_id"] == m0["id"] and r.get("act_date") and r.get("action") in ("買進", "賣出", "放空", "回補")]
    # ② 執行日差一個交易日
    a = rows0[0]
    a["act_date"] = cal.shift(dt.date.fromisoformat(a["act_date"]), 1).isoformat()
    # ③ 開盤收盤顛倒
    b = rows0[1]
    b["act_timing"] = {"open": "close", "close": "open"}[b["act_timing"]]
    # ① 表外股票：009 名單外
    plog.append({"message_id": m0["id"], "source": "009", "code": "2603", "name": "長榮", "action": "放空",
                 "act_date": a["act_date"], "act_timing": "open", "line": f"【{INJECT_NOTE}】009 長榮 2603"})
    # ④ 應推未推
    d = rows0[0]["act_date"]
    raw["expected"].append({"strategy_id": "019", "company_code": "9999", "company_name": INJECT_NOTE, "role": "entry",
                            "side": "short", "act_date": d, "act_timing": "open", "action": "放空",
                            "push_day": cal.shift(dt.date.fromisoformat(d), -1).isoformat(), "hidden": False})
    # ⑤ 重複發送：同一則主推播 10 分鐘後再送一次
    dup = dict(m0, id=900001, sent_at=(dt.datetime.fromisoformat(m0["sent_at"].replace("Z", "+00:00"))
                                       + dt.timedelta(minutes=10)).isoformat())
    msgs.append(dup)
    plog += [dict(r, message_id=900001) for r in plog if r["message_id"] == m0["id"]
             and r.get("line", "").find(INJECT_NOTE) < 0]
    msgs.sort(key=lambda m: m["sent_at"])
    return raw, {"②": (a["source"], a["code"]), "③": (b["source"], b["code"]), "①": ("009", "2603"),
                 "④": ("019", "9999"), "⑤": m0["id"]}


def run(raw, do_inject=False):
    cal = Cal([dt.date.fromisoformat(x) for x in raw["holidays"]])
    planted = None
    if do_inject:
        raw, planted = inject(raw, cal)
    now = dt.datetime.fromisoformat(raw["as_of"])
    res = compare(raw["messages"], raw["push_log"], raw["actions"], raw["expected"], cal, now, parse,
                  prior_fixes=earlier_fixes(raw.get("prior_fixes")))
    return res, planted


if __name__ == "__main__":
    raw = json.load(open(sys.argv[1], encoding="utf-8"))
    res, planted = run(raw, "--inject" in sys.argv)
    print(render_section(res))
    if planted:
        print("植入：", planted)
