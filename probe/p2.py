"""臨時：(1) 補印能科技 7734 分割資料（Ed 授權）(2) 找櫃買中心變更面額的資料來源。"""
import json, sys
sys.path.insert(0, "scripts")
from calendar_signals import supa
from cash_issue import _get

print("=== 1. 補 7734 ===")
supa("split_watch?company_code=eq.7734", "PATCH",
     {"ratio": 4, "declare_date": "2026-10-08", "meeting_date": "2026-11-26",
      "note": "10/08 董事會：面額 10→2.5 元（一拆4），11/26 股東臨時會（重大訊息）"})
print(json.dumps(supa("v_split?company_code=eq.7734"), ensure_ascii=False, indent=1))

print("=== 2. 櫃買 OpenAPI 端點 ===")
d = json.loads(_get("https://www.tpex.org.tw/openapi/swagger.json", hdr={"Accept": "application/json"}))
for p, v in d["paths"].items():
    s = json.dumps(v, ensure_ascii=False)
    if any(k in s for k in ("面額", "停止買賣", "恢復買賣", "換發", "減資", "停止過戶")):
        print(p, "|", (v.get("get") or {}).get("summary"))
