"""臨時：(1) 策略參數表 (2) 分割換股公告的發布時間 (3) sent:* 鍵現況。不寫入。"""
import json, re, sys, time
sys.path.insert(0, "scripts")
from calendar_signals import supa
from cash_issue import mops, _text

print("=== strategies ===")
for r in supa("strategies?select=*") or []:
    print(json.dumps(r, ensure_ascii=False, default=str))
print("=== sent 鍵 ===")
print(supa("intraday_alerts?select=d,key,created_at&key=like.sent:*&limit=20"))
print("=== 換股公告時間 ===")
SW = re.compile(r"換發股票(?:基準日|作業計畫)|換股作業計畫|面額變更.*換發")
for co, months in (("5904", (6, 7)), ("4747", (7,)), ("6949", (8,)), ("8937", ()), ):
    for m in months:
        h = mops({"step": 1, "firstin": 1, "off": 1, "keyword4": "", "code1": "", "TYPEK2": "",
                  "checkbtn": "", "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
                  "co_id": co, "year": "115", "month": f"{m:02d}", "b_date": "01", "e_date": "31"})
        for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
            cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(cells) >= 5 and (SW.search(cells[4]) or "面額" in cells[4]):
                print(co, cells[2], cells[3], cells[4][:60])
        time.sleep(2)
