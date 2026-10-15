"""臨時：看 A02–A05 訊號的實際進出場日期怎麼算。不寫入。"""
import json, os, sys, urllib.request
sys.path.insert(0, "scripts")
from calendar_signals import supa

key = os.environ["SUPABASE_SERVICE_KEY"].strip()
spec = json.loads(urllib.request.urlopen(urllib.request.Request(
    os.environ["SUPABASE_URL"].strip().rstrip("/") + "/rest/v1/",
    headers={"apikey": key, "Authorization": f"Bearer {key}"}), timeout=40).read())
for k in ("signals", "v_positions", "v_tomorrow", "disposals", "v_disposals", "events"):
    print("TABLE", k, list(spec.get("definitions", {}).get(k, {}).get("properties", {}).keys()))
for p, v in spec["paths"].items():
    if p.startswith("/rpc/") and any(w in p for w in ("signal", "ingest", "disposal", "manual", "position", "recalc")):
        print(p, json.dumps(v.get("post", {}).get("parameters", [{}])[0].get("schema", {}).get("properties", {}), ensure_ascii=False)[:300])
for code in ("buyback", "tw50", "msci", "disposal", "split"):
    print(f"=== signals {code} ===")
    try:
        for r in supa(f"signals?select=*&strategy_code=eq.{code}&order=event_date.desc&limit=6") or []:
            print(json.dumps({k: r[k] for k in r if k not in ("raw", "p_raw")}, ensure_ascii=False, default=str)[:400])
    except Exception as e:
        print("ERR", e)
print("=== v_tomorrow ===")
for r in supa("v_tomorrow?select=*&limit=5") or []:
    print(json.dumps(r, ensure_ascii=False, default=str)[:400])
print("=== v_disposals 處置中 ===")
for r in supa("v_disposals?select=*&limit=6") or []:
    print(json.dumps(r, ensure_ascii=False, default=str)[:400])
