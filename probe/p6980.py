import re, sys
sys.path.insert(0, "scripts")
import cash_issue as C
C._get("https://mops.twse.com.tw/mops/")
for m in ("06", "07", "08", "09", "10"):
    print("== 月份", m, flush=True)
    try:
        html = C.mops({"step": 1, "firstin": 1, "off": 1, "keyword4": "", "code1": "", "TYPEK2": "",
                       "checkbtn": "", "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
                       "co_id": "6980", "year": "115", "month": m, "b_date": "01", "e_date": "31"})
    except Exception as e:
        print("  ERR", e); continue
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, re.S):
        t = C._text(tr)
        if "增資" in t or "認股" in t or "繳款" in t:
            print("  ", t[:200])
            args = dict(re.findall(r"\.(\w+)\.value\s*=\s*['\"]([^'\"]*)['\"]", tr))
            if args.get("seq_no"):
                txt = C._text(C.mops({"step": 2, "firstin": 1, "off": 1, "seq_no": args["seq_no"],
                     "spoke_time": args.get("spoke_time"), "spoke_date": args.get("spoke_date"),
                     "co_id": "6980", "TYPEK": args.get("TYPEK", "all")}))
                for mm in re.finditer(r"每[壹一]?[仟千]股|原股東", txt):
                    print("     ...", txt[max(0, mm.start()-60):mm.end()+90])
                print("     parse:", C.parse_detail(txt, "6980"), flush=True)
