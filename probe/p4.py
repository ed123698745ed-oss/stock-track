"""臨時：對照處置期間與系統進出場日；看庫藏股與指數調整的實際訊號。不寫入。"""
import json, sys
sys.path.insert(0, "scripts")
from calendar_signals import supa

pos = supa("v_positions?select=strategy_code,company_code,company_name,event_date,entry_date,entry_timing,exit_date,exit_timing,grp,total_days&order=entry_date.desc&limit=200") or []
dsp = {}
for r in supa("disposals?select=company_code,start_date,end_date&order=start_date.desc&limit=300") or []:
    dsp.setdefault(r["company_code"], []).append((r["start_date"], r["end_date"]))
print("=== 處置：處置期間 vs 系統進出場 ===")
for p in [x for x in pos if x["strategy_code"] == "disposal"][:15]:
    print(p["company_code"], p["company_name"], "進", p["entry_date"], "出", p["exit_date"], "共", p["total_days"],
          "｜處置期間", dsp.get(p["company_code"], [])[:2])
for code in ("buyback", "tw50", "msci"):
    print(f"=== {code} ===")
    for p in [x for x in pos if x["strategy_code"] == code][:5]:
        print(json.dumps(p, ensure_ascii=False))
