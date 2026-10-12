import json, re, sys
sys.path.insert(0, "scripts")
from cash_issue import _get
def j(u):
    try:
        s = _get(u, hdr={"Accept": "application/json"}); print("==", u, len(s)); return s
    except Exception as e: print("==", u, "ERR", e); return ""
s = j("https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL")
try:
    r = json.loads(s); print(len(r)); print(json.dumps(r[:3], ensure_ascii=False))
except Exception as e: print(s[:500])
s = j("https://www.twse.com.tw/rwd/zh/exRight/TWT48U?response=json")
print(s[:2500])
sw = j("https://www.tpex.org.tw/openapi/swagger.json")
for p in re.findall(r'"(/[^"]*(?:exright|dividend|Exright|xr)[^"]*)"', sw): print("tpex path", p)
for p in ["tpex_exright_prepost_schedule", "tpex_exright_daily", "tpex_exdividend_schedule"]:
    s = j("https://www.tpex.org.tw/openapi/v1/" + p); print(s[:1200])
s = j("https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?response=json")
print(s[:1500])
for u in ["https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"]:
    s = j(u)
    try: print(list(json.loads(s)[0].items()))
    except Exception as e: print(e)
