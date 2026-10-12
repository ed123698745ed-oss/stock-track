import json, re, sys
sys.path.insert(0, "scripts")
from cash_issue import _get, _text
H = {"Content-Type": "application/json", "Origin": "https://mops.twse.com.tw", "Referer": "https://mops.twse.com.tw/mops/"}
def old(api, p):
    r = json.loads(_get("https://mops.twse.com.tw/mops/api/redirectToOld", json.dumps({"apiName": api, "parameters": p}).encode(), H))
    return _get(r["result"]["url"], hdr={"Referer": "https://mops.twse.com.tw/"})
for u in ["https://mopsov.twse.com.tw/mops/web/t56sb12", "https://mopsov.twse.com.tw/mops/web/t56sb12_q1"]:
    try:
        h = _get(u)
        print("==", u, len(h))
        for m in re.findall(r"<(?:input|select|form)[^>]*>", h): print("  ", m[:200])
        for m in re.findall(r"(?:name|id)=['\"]?(\w+)", h): pass
        i = h.find("民國"); print(_text(h[max(0,i-800):i+800])[:1200])
    except Exception as e: print(u, "ERR", e)
for p in [{"step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "date1": "115/10/08"},
          {"step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "year": "115", "month": "10", "day": "08", "date1": "1151008"},
          {"step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "year": "115", "month": "10", "sday": "08", "eday": "08"},
          {"step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "s_date": "115/10/08", "e_date": "115/10/08"}]:
    try: print("== ", p, _text(old("ajax_t56sb12", p))[:1500])
    except Exception as e: print(p, "ERR", e)
