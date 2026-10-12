import re, sys
sys.path.insert(0, "scripts")
from cash_issue import _get, _text, _post_ov
_get("https://mopsov.twse.com.tw/mops/web/t56sb12_q1")
for day in ["08", "06"]:
    h = _post_ov("ajax_t56sb12", {"run": "", "step": "2", "year": "115", "month": "10", "day": day, "report": "SY", "firstin": "true"})
    print("== day", day, len(h))
    trs = re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S)
    print("rows", len(trs))
    for tr in trs[:14]:
        cells = [_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        print(" | ".join(cells)[:600])
    i = h.find("<table"); print(re.sub(r"\s+", " ", h[i:i+3000]))
