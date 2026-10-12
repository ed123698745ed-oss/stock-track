import re, sys
sys.path.insert(0, "scripts")
from cash_issue import _get, _text, _post_ov
_get("https://mopsov.twse.com.tw/mops/web/t56sb12_q1")
for p in [{"encodeURIComponent": 1, "step": 1, "firstin": "ture", "off": 1, "year": "115", "month": "10", "day": "08"},
          {"encodeURIComponent": 1, "step": 0, "firstin": "ture", "off": 1, "year": "115", "month": "10", "day": "08"}]:
    h = _post_ov("ajax_t56sb12_q1", p)
    print("== RAW", p, len(h)); print(re.sub(r"try \{.*", "", h, flags=re.S)[:2500])
    fields = dict(re.findall(r"<input type='hidden' name='(\w+)' value='([^']*)'", h))
    print("fields", fields, "rpt", re.findall(r"rpt\.value='(\w+)'", h), re.findall(r'action="?([^" >]+)', h)[:5])
    for rpt in re.findall(r"rpt\.value='(\w+)'", h)[:2]:
        x = _post_ov("ajax_t56sb12_q1", {**fields, "rpt": rpt}); print("== rpt", rpt, len(x)); print(_text(x)[:3000])
