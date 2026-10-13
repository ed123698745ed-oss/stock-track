import datetime as dt, re, sys
sys.path.insert(0, "scripts")
import cash_issue as C
C._get("https://mops.twse.com.tw/mops/")
anns = C.list_announcements(dt.date(2026, 6, 1), dt.date(2026, 10, 12))
for subj, seq, tm, d8, co, typ, name in anns:
    if co != "6980":
        continue
    print("==", d8, tm, subj)
    if not C.SUBJ.search(subj):
        continue
    txt = C._text(C.mops({"step": 2, "firstin": 1, "off": 1, "seq_no": seq, "spoke_time": tm, "spoke_date": d8, "co_id": co, "TYPEK": typ}))
    for m in re.finditer(r"每[壹一]?[仟千]股|認購|繳款|繳納", txt):
        print("  ...", txt[max(0, m.start()-60):m.end()+100])
    print("  parse_detail:", C.parse_detail(txt, co))
    print("  已發行股數:", C.issued_shares(co))
