import json, re, sys
sys.path.insert(0, "scripts")
from cash_issue import _get, _text
H = {"Content-Type": "application/json", "Origin": "https://mops.twse.com.tw", "Referer": "https://mops.twse.com.tw/mops/"}
def show(tag, s):
    t = _text(s)
    print(f"== {tag} len={len(s)}\n{t[:1500]}\n")
def old(api, p):
    r = json.loads(_get("https://mops.twse.com.tw/mops/api/redirectToOld", json.dumps({"apiName": api, "parameters": p}).encode(), H))
    print(api, r.get("result", {}).get("url") if isinstance(r.get("result"), dict) else r)
    return _get(r["result"]["url"], hdr={"Referer": "https://mops.twse.com.tw/"})
try: _get("https://mops.twse.com.tw/mops/")
except Exception as e: print(e)
for api in ["ajax_t56sb12", "ajax_t56sb12_q1"]:
    for p in [{"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "year": "115", "month": "10", "day": "08"},
              {"step": 1, "firstin": 1, "off": 1, "TYPEK": "sii", "year": "115", "month": "10", "b_date": "08", "e_date": "08"}]:
        try: show(f"{api} {p}", old(api, p))
        except Exception as e: print(api, p, "ERR", e)
for path in ["t56sb12", "t56sb12_q1"]:
    for body in [{"companyId": "", "year": "115", "month": "10", "day": "08", "marketKind": "sii"}, {"year": "115", "month": "10"}]:
        try: show(f"new {path} {body}", _get(f"https://mops.twse.com.tw/mops/api/{path}", json.dumps(body).encode(), H))
        except Exception as e: print("new", path, body, "ERR", e)
