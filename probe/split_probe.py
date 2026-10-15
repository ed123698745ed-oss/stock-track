"""臨時查核：某檔分割事件在資料庫與官方來源的現況（不寫入任何資料）。"""
import json, os, re, sys, time, urllib.parse
sys.path.insert(0, "scripts")
from calendar_signals import supa
from cash_issue import _get, mops, _text

CODE = os.environ.get("CODE", "7734")
q = urllib.parse.quote
print("=== 資料庫 ===")
for path in (f"split_watch?company_code=eq.{CODE}", f"v_split?company_code=eq.{CODE}",
             f"v_split_leads?company_code=eq.{CODE}", f"split_leads?company_code=eq.{CODE}",
             f"detections?company_code=eq.{CODE}&order=detected_date.desc&limit=10"):
    try:
        print(path, json.dumps(supa(path), ensure_ascii=False, default=str, indent=1))
    except Exception as e:
        print(path, "ERR", e)

print("=== 證交所 變更面額預告表 TWTB7U ===")
try:
    raw = json.loads(_get("https://www.twse.com.tw/rwd/zh/change/TWTB7U?response=json",
                          hdr={"Referer": "https://www.twse.com.tw/zh/announcement/change/twtb7u.html"}))
    print(raw.get("fields"))
    for r in raw.get("data") or []:
        if CODE in str(r[:3]):
            print(r)
    print("共", len(raw.get("data") or []), "筆")
except Exception as e:
    print("ERR", e)

print("=== 觀測站重大訊息（2026/06～10，面額／分割相關）===")
for m in range(6, 11):
    try:
        h = mops({"step": 1, "firstin": 1, "off": 1, "keyword4": "", "code1": "", "TYPEK2": "",
                  "checkbtn": "", "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
                  "co_id": CODE, "year": "115", "month": f"{m:02d}", "b_date": "01", "e_date": "31"})
        for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
            cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(cells) >= 5:
                print(m, "月", cells[:5])
    except Exception as e:
        print(m, "月 ERR", e)
    time.sleep(2)

print("=== 10/08 公告內文 ===")
h = mops({"step": 1, "firstin": 1, "off": 1, "keyword4": "", "code1": "", "TYPEK2": "",
          "checkbtn": "", "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
          "co_id": CODE, "year": "115", "month": "10", "b_date": "01", "e_date": "31"})
for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
    oc = re.search(r"seq_no.value='(\d+)'.*?spoke_time.value='(\d+)'.*?spoke_date.value='(\d+)'"
                   r".*?co_id.value='(\w+)'.*?TYPEK.value='(\w+)'", tr)
    cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
    if oc and len(cells) >= 5 and re.search(r"面額|股東臨時會", cells[4]):
        seq, tm, d8, co, typ = oc.groups()
        txt = _text(mops({"step": 2, "firstin": 1, "off": 1, "seq_no": seq,
                          "spoke_time": tm, "spoke_date": d8, "co_id": co, "TYPEK": typ}))
        i = txt.find("說明")
        print("---", cells[4], typ)
        print(txt[i:i + 1800] if i >= 0 else txt[:1800])
        time.sleep(2)

print("=== 目前面額（上市／上櫃基本資料）===")
for u, kc, kf in (("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "公司代號", "普通股每股面額"),
                  ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "SecuritiesCompanyCode", "ParValueOfCommonStock")):
    try:
        for r in json.loads(_get(u, hdr={"Accept": "application/json"})):
            if str(r.get(kc)).strip() == CODE:
                print(u.split("/")[-1], r.get(kf))
    except Exception as e:
        print(u, "ERR", e)
