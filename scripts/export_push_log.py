"""匯出推播紀錄（每週彙整用）：依策略／板塊分組列出每天推了哪些標的。
DAYS=7（預設）；輸出在 ===BEGIN=== / ===END=== 之間，給每週彙整任務讀取。"""
import datetime as dt
import os
from collections import defaultdict

from calendar_signals import supa

TPE = dt.timezone(dt.timedelta(hours=8))
today = dt.datetime.now(TPE).date()
days = int(os.environ.get("DAYS") or 7)
start = today - dt.timedelta(days=days)
rows, off = [], 0
while True:
    part = supa(f"push_log?select=push_date,mode,source,code,name,action,act_date,act_timing"
                f"&push_date=gte.{start.isoformat()}&order=source,push_date,id&limit=1000&offset={off}")
    rows += part or []
    if not part or len(part) < 1000:
        break
    off += 1000
msgs = supa(f"push_messages?select=id,sent_at,mode,status&sent_at=gte.{start.isoformat()}&order=sent_at")
by = defaultdict(list)
for r in rows:
    by[r["source"]].append(r)
T = {"open": "開盤", "close": "收盤"}
print("===BEGIN===")
print(f"# 推播紀錄 {start:%Y/%m/%d}～{today:%Y/%m/%d}\n")
print(f"共 {len(msgs)} 則訊息、{len(rows)} 個項目。\n")
print("| 時間 | 類型 | LINE 回應 |\n|---|---|---|")
for m in msgs:
    t = dt.datetime.fromisoformat(m["sent_at"].replace("Z", "+00:00")).astimezone(TPE)
    print(f"| {t:%m/%d %H:%M} | {m['mode']} | {m['status']} |")
for src in sorted(by):
    print(f"\n## {src}（{len(by[src])} 項）\n")
    print("| 推播日 | 類型 | 標的 | 動作 | 執行日 | 時點 |\n|---|---|---|---|---|---|")
    for r in by[src]:
        print(f"| {r['push_date']} | {r['mode']} | {r.get('name') or ''} {r.get('code') or ''} | {r.get('action') or ''} "
              f"| {r.get('act_date') or ''} | {T.get(r.get('act_timing'), '')} |")
print("===END===")
