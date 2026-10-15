"""臨時：(1) 查 upsert_split_watch 參數 (2) 找櫃買中心變更面額的資料來源。"""
import json, os, sys, urllib.request
sys.path.insert(0, "scripts")
from cash_issue import _get

key = os.environ["SUPABASE_SERVICE_KEY"].strip()
req = urllib.request.Request(os.environ["SUPABASE_URL"].strip().rstrip("/") + "/rest/v1/",
                             headers={"apikey": key, "Authorization": f"Bearer {key}"})
spec = json.loads(urllib.request.urlopen(req, timeout=40).read())
for p, v in spec.get("paths", {}).items():
    if "split" in p:
        print(p, json.dumps(v.get("post", {}).get("parameters", [{}])[0].get("schema", ""), ensure_ascii=False)[:600])
for k, v in spec.get("definitions", {}).items():
    if "split" in k:
        print("TABLE", k, list(v.get("properties", {}).keys()))

print("=== 櫃買 OpenAPI 端點 ===")
d = json.loads(_get("https://www.tpex.org.tw/openapi/swagger.json", hdr={"Accept": "application/json"}))
for p, v in d["paths"].items():
    s = json.dumps(v, ensure_ascii=False)
    if any(k in s for k in ("面額", "停止買賣", "恢復買賣", "換發", "減資", "停止過戶")):
        print(p, "|", (v.get("get") or {}).get("summary"))
