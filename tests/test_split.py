"""分割股東會日測試（2026-10-28 印能 7734 事故）。不連網、不碰資料庫。

事故：「董事會決議召開股東臨時會」公告的發布日 10/08 被當成股東會日，實際開會日是內文的 11/26。
"""
import datetime as dt
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
# split_mops 匯入時需要 cash_issue（會連網的模組）；測試只用純函式，先放替身
sys.modules.setdefault("cash_issue", types.SimpleNamespace(_text=lambda x: x, mops=None))
import split_mops as sm  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    if not ok:
        FAIL.append(f"{name}：得到 {got}，應為 {want}")
    print(("✓ " if ok else "✗ ") + name)


# 1. 股東會日合理性
check("印能：股東會日＝宣告日 → 可疑", sm.suspicious_meeting("2026-10-08", "2026-10-08"), True)
check("宣告後 14 天 → 可疑", sm.suspicious_meeting("2026-10-08", "2026-10-22"), True)
check("印能正確值 11/26 → 正常", sm.suspicious_meeting("2026-10-08", "2026-11-26"), False)
check("騰雲 8/31→10/19 → 正常", sm.suspicious_meeting("2026-08-31", "2026-10-19"), False)
check("沒有股東會日 → 不算可疑（由 need_meeting 處理）", sm.suspicious_meeting("2026-10-08", None), False)

# 2. 召開股東會公告：主旨命中，開會日取內文欄位，不取公告日
subj = "印能科技董事會決議召開115年第一次股東臨時會公告"
body = "1.董事會決議日期:115/10/08 2.股東臨時會召開日期:115/11/26 3.股東臨時會召開地點:新竹市"
check("主旨判為召開股東會", bool(sm.MEET_SUBJ.search(subj)), True)
check("開會日取內文 115/11/26", sm.d(sm.F_MEETING.search(body)), dt.date(2026, 11, 26))
body2 = "1.董事會決議日期：115/08/31 2.股東臨時會召開日期：115/10/19"
check("騰雲內文 115/10/19", sm.d(sm.F_MEETING.search(body2)), dt.date(2026, 10, 19))

if FAIL:
    print("\n失敗：\n" + "\n".join(FAIL))
    sys.exit(1)
print("\n全部通過")
