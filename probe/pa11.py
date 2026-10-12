import json, sys
sys.path.insert(0, "scripts")
from cash_issue import _get
for u in ["https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost", "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"]:
    r = json.loads(_get(u, hdr={"Accept": "application/json"}))
    print("==", u, len(r)); print(json.dumps(r[:2], ensure_ascii=False))
    ks = list(r[0]); print(ks)
    for x in r:
        if any(k in x and str(x[k]).strip() not in ("", "0", "0.0", "0.00000000", "0.000000") for k in ks if "Stock" in k or "Subscri" in k or "配股" in k):
            print("  stock/sub:", json.dumps(x, ensure_ascii=False))
    print("dates", sorted({x.get("Date") or x.get("ExRightsExDividendDate") or "" for x in r})[:40])
