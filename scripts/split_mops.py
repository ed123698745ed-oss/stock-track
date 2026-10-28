"""分割追蹤：從公司重大訊息補換股日程（上市、上櫃、興櫃都適用）。

證交所的變更面額預告表（split.yml）只有上市公司；上櫃、興櫃的停止買賣與新股上市日
要等公司公告。這支每天把「追蹤中但日期還沒齊」的公司，逐家查觀測站重大訊息：
  ・主旨像換股時程（換發股票基準日／換發股票作業計畫…）→ 讀內文欄位
      換發股票時程(2)舊股票停止交易期間 → 停止買賣日（取起日）
      換發股票時程(8)新股票上市／上櫃買賣日 → 新股上市日
      公告日 → 公告換股日（A06 進場依據）
  ・主旨是召開股東會 → 讀內文「股東(臨時)會召開日期」
      還缺股東會日，或現有股東會日不合理（見 suspicious_meeting）時都讀，內文日期為準、覆蓋舊值
只寫查得到的欄位；「不適用」、沒寫的一律不填，不推估。

2026-10-28 事故：印能 7734 的「董事會決議召開股東臨時會」公告（10/08 發布）被當成
股東會本身，股東會日被填成公告日 10/08，實際開會日是內文寫的 11/26。股東會日已有值，
need_meeting 為假，這支就不再讀內文，錯誤一直留著。改為：公告日 ≠ 開會日，一律以內文為準，
並對「股東會日距宣告拆股不足 15 天」的資料重新核對（公開發行公司臨時會須 15 日前通知）。

用法：python3 scripts/split_mops.py；DRY_RUN=1 只印不寫
"""
import datetime as dt
import os
import re
import time

from calendar_signals import supa
from cash_issue import _text, mops

TPE = dt.timezone(dt.timedelta(hours=8))
# 2026-10-19：交易所核准後的換股公告主旨是「公告本公司股票面額由「新台幣10元」變更為「新台幣X元」，公告期間…」
#   （沛爾 8/6、仁新 8/5 都是這種），原本的字眼抓不到，上櫃案件會整個漏掉 A06 進場日。
SWAP_SUBJ = re.compile(r"換發股票(?:基準日|作業計畫)|換股作業計畫|面額變更.*換發|新股票上(?:市|櫃)買賣"
                       r"|股票面額由.{0,20}?變更為")
MEET_SUBJ = re.compile(r"召開.*股東(?:臨時|常)?會")
DATE = r"(?:民國)?\s*(\d{2,3})\s*[年/]\s*(\d{1,2})\s*[月/]\s*(\d{1,2})\s*日?"
F_SUSPEND = re.compile(r"舊股票停止(?:交易|買賣)期間\s*[:：]\s*" + DATE)
# 欄位也可能寫成「(6)新股票上市買賣日及舊股票終止上市買賣日：民國115年09月07日…」或
#   「新股票上櫃買賣日(115年09月07日)」，都取標籤後第一個日期
F_LISTING = re.compile(r"新股票上(?:市|櫃)買賣日(?:及舊股票終止上(?:市|櫃)買賣日)?\s*[:：(（]\s*" + DATE)
F_MEETING = re.compile(r"股東(?:臨時|常)?會召開日期\s*[:：]\s*" + DATE)


MIN_NOTICE = 15  # 公司法第 172 條：公開發行公司股東臨時會須 15 日前通知；常會 30 日前


def suspicious_meeting(declare, meeting):
    """股東會日不可能早於宣告日 + 15 天；同日或太近，多半是把公告日誤當開會日。"""
    if not meeting:
        return False
    m = dt.date.fromisoformat(meeting)
    if declare:
        return (m - dt.date.fromisoformat(declare)).days < MIN_NOTICE
    return False


def d(m):
    return dt.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))) if m else None


def announcements(code, months):
    """[(主旨, 公告日, step2 參數)]"""
    out = []
    for y, m in months:
        h = mops({"step": 1, "firstin": 1, "off": 1, "keyword4": "", "code1": "", "TYPEK2": "",
                  "checkbtn": "", "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
                  "co_id": code, "year": f"{y - 1911}", "month": f"{m:02d}", "b_date": "01", "e_date": "31"})
        for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
            oc = re.search(r"seq_no.value='(\d+)'.*?spoke_time.value='(\d+)'.*?spoke_date.value='(\d+)'"
                           r".*?co_id.value='(\w+)'.*?TYPEK.value='(\w+)'", tr)
            cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if oc and len(cells) >= 5:
                seq, tm, d8, co, typ = oc.groups()
                out.append((cells[4], dt.date(int(d8[:4]), int(d8[4:6]), int(d8[6:])),
                            {"seq_no": seq, "spoke_time": tm, "spoke_date": d8, "co_id": co, "TYPEK": typ}))
        time.sleep(1.5)
    return out


def body(args):
    txt = _text(mops({"step": 2, "firstin": 1, "off": 1, **args}))
    return txt.split("以上資料均由各公司")[0]


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    today = dt.datetime.now(TPE).date()
    prev = (today.replace(day=1) - dt.timedelta(days=1))
    months = [(prev.year, prev.month), (today.year, today.month)]
    # 缺新股上市日、股東會日，或缺公告換股日（A06 進場依據）且新股還沒上市滿 5 天的
    view = {r["company_code"]: r for r in
            supa("v_split?select=company_code,listing_date,declare_date,meeting_date") or []}
    listing = {c: r.get("listing_date") for c, r in view.items()}
    bad_meet = {c for c, r in view.items() if suspicious_meeting(r.get("declare_date"), r.get("meeting_date"))}
    for c in sorted(bad_meet):
        print(f"  ⚠ {c} 股東會日 {view[c]['meeting_date']} 距宣告日 {view[c]['declare_date']} 不足 {MIN_NOTICE} 天，重新核對公告內文")
    recent = (today - dt.timedelta(days=10)).isoformat()
    todo = [r for r in supa("v_split_missing?select=*&limit=50") or []
            if r.get("need_listing") or r.get("need_meeting") or r["company_code"] in bad_meet
            or (r.get("need_swap") and (listing.get(r["company_code"]) or "9999") >= recent)]
    print(f"日期未齊的追蹤公司 {len(todo)} 家")
    for r in todo:
        code, name = r["company_code"], r.get("company_name") or ""
        try:
            anns = announcements(code, months)
        except Exception as e:
            print(f"  {code} {name} 重大訊息查詢失敗：{e}")
            continue
        patch = {}
        for subj, day, args in sorted(anns, key=lambda a: a[1]):
            swap = SWAP_SUBJ.search(subj)
            meet = (r.get("need_meeting") or code in bad_meet) and MEET_SUBJ.search(subj)
            if not (swap or meet):
                continue
            try:
                txt = body(args)
            except Exception as e:
                print(f"  {code} {name} {day} 內文抓取失敗：{e}")
                continue
            time.sleep(1.5)
            if swap:
                s, l = d(F_SUSPEND.search(txt)), d(F_LISTING.search(txt))
                if s or l:  # 「不適用」的董事會決議不算換股公告
                    if r.get("need_swap"):
                        patch.setdefault("p_swap", day.isoformat())
                    if s:
                        patch["p_suspend"] = s.isoformat()
                    if l:
                        patch["p_listing"] = l.isoformat()
            if meet:
                m = d(F_MEETING.search(txt))
                if m:  # 內文的開會日為準；公告日（day）不是開會日
                    patch["p_meeting"] = m.isoformat()
                    old = (view.get(code) or {}).get("meeting_date")
                    if old and old != patch["p_meeting"]:
                        print(f"  ✎ {code} {name} 股東會日更正 {old} → {patch['p_meeting']}（公告 {day}）")
        if not patch:
            print(f"  {code} {name}：近兩個月沒有換股或股東會日程公告")
            continue
        print(f"  {code} {name} → {patch}")
        if not dry:
            supa("rpc/upsert_split_watch", "POST", {"p_code": code, **patch})
            # 寫入後重讀，確認真的蓋過舊值（upsert 若只補空欄，更正會默默失效）
            if "p_meeting" in patch:
                got = (supa(f"v_split?select=meeting_date&company_code=eq.{code}") or [{}])[0].get("meeting_date")
                if got != patch["p_meeting"]:
                    print(f"  ❌ {code} {name} 股東會日寫入後仍為 {got}，應為 {patch['p_meeting']}，需人工處理")
    if dry:
        print("DRY_RUN：不寫入")


if __name__ == "__main__":
    main()
