import json, re, sys
sys.path.insert(0, "scripts")
from cash_issue import _get, _text
H = {"Content-Type": "application/json", "Origin": "https://mops.twse.com.tw", "Referer": "https://mops.twse.com.tw/mops/"}
def old(api, p):
    r = json.loads(_get("https://mops.twse.com.tw/mops/api/redirectToOld", json.dumps({"apiName": api, "parameters": p}).encode(), H))
    return _get(r["result"]["url"], hdr={"Referer": "https://mops.twse.com.tw/"})
h = _get("https://mopsov.twse.com.tw/mops/web/t56sb12")
i = h.find('id="form1"'); print(h[i:i+3000])
for p in [{"step": 0, "firstin": "ture", "off": 1, "year": "115", "month": "10", "day": "08"},
          {"step": 1, "firstin": "ture", "off": 1, "year": "115", "month": "10", "day": "8"},
          {"step": 1, "firstin": 1, "off": 1, "year": "115", "month": "10", "day": "08"}]:
    try:
        s = old("ajax_t56sb12_q1", p); print("== q1", p, len(s)); print(_text(s)[:2500])
    except Exception as e: print(p, "ERR", e)
