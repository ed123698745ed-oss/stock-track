"""一次性探測：t56sb12 上櫃的 report 代碼（只讀，不寫資料庫）。"""
import re, time
from cash_issue import _get, _post_ov, _text
page = _get("https://mopsov.twse.com.tw/mops/web/t56sb12_q1")
print("== 表單選項 ==")
for m in re.findall(r'<input[^>]*name=["\']?report["\']?[^>]*>[^<]{0,20}', page): print(m)
for m in re.findall(r'<option[^>]*value=["\']?(\w+)["\']?[^>]*>([^<]{0,15})', page)[:40]: print(m)
for rep in ("SY", "OY", "RY", "TY", "otc", "OTC"):
    for day in ("30", "05"):
        mo = "10" if day == "30" else "11"
        try:
            h = _post_ov("ajax_t56sb12", {"run": "", "step": "2", "year": "115", "month": mo, "day": day,
                                          "report": rep, "firstin": "true"})
        except Exception as e:
            print(rep, mo, day, "ERR", e); continue
        h = h.replace("</d>", "</td>")
        rows = []
        for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
            cells = [_text(c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(cells) >= 8 and re.fullmatch(r"\d{2,3}/\d{1,2}/\d{1,2}", cells[1]):
                rows.append(cells[2] + cells[3] + "|" + cells[5][:12] + "|" + cells[6][:10])
        print(f"{rep} 115/{mo}/{day}: {len(rows)} 列；含4939={any(r.startswith('4939') for r in rows)} 含6204={any(r.startswith('6204') for r in rows)} 含3006={any(r.startswith('3006') for r in rows)}")
        print("   ", rows[:6])
        time.sleep(1.5)
