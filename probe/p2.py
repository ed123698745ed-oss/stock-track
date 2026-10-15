"""臨時：(1) 用 RPC 補 7734（Ed 授權）(2) 看上櫃分割案的換股公告原文，寫解析規則用。"""
import json, re, sys, time
sys.path.insert(0, "scripts")
from calendar_signals import supa
from cash_issue import mops, _text

print("=== 1. 補 7734 ===")
supa("rpc/upsert_split_watch", "POST", {"p_code": "7734", "p_ratio": 4, "p_declare": "2026-10-08",
     "p_meeting": "2026-11-26", "p_note": "10/08 董事會：面額 10→2.5 元（一拆4）；11/26 股東臨時會"})
print(json.dumps(supa("v_split?company_code=eq.7734"), ensure_ascii=False))

KW = re.compile(r"面額|換發|換股|停止買賣|恢復買賣|上櫃買賣|上市買賣|新股")
for co in ("6949", "6696", "5904", "4747"):
    print(f"=== {co} ===")
    print(json.dumps(supa(f"v_split?company_code=eq.{co}"), ensure_ascii=False))
    for m in range(5, 11):
        h = mops({"step": 1, "firstin": 1, "off": 1, "keyword4": "", "code1": "", "TYPEK2": "",
                  "checkbtn": "", "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
                  "co_id": co, "year": "115", "month": f"{m:02d}", "b_date": "01", "e_date": "31"})
        for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
            oc = re.search(r"seq_no.value='(\d+)'.*?spoke_time.value='(\d+)'.*?spoke_date.value='(\d+)'"
                           r".*?co_id.value='(\w+)'.*?TYPEK.value='(\w+)'", tr)
            cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if not (oc and len(cells) >= 5 and KW.search(cells[4])):
                continue
            seq, tm, d8, c, typ = oc.groups()
            txt = _text(mops({"step": 2, "firstin": 1, "off": 1, "seq_no": seq,
                              "spoke_time": tm, "spoke_date": d8, "co_id": c, "TYPEK": typ}))
            i = txt.find("說明")
            body = (txt[i:] if i >= 0 else txt).split("以上資料均由各公司")[0]
            print(f"--- {d8} {typ} {cells[4]}\n{body[:900]}")
            time.sleep(1.5)
        time.sleep(1.5)
