"""分割線索判定測試（2026-10-29 長科 6548 事故）。不連網、不碰資料庫。

事故：「公告本公司115年第三季合併自結損益(每股面額0.4元)」因主旨含「每股面額」
被判成強命中「宣告拆股」。括號裡只是現行面額附註，不是面額變更。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import split_classify as sc  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    if not ok:
        FAIL.append(f"{name}：得到 {got}，應為 {want}")
    print(("✓ " if ok else "✗ ") + name)


def conf(subj, detail="", code="9999", watch=()):
    return sc.classify({"code": code, "subject": subj, "detail": detail}, watch)[0]


# 1. 現行面額附註 → 不是分割線索
check("長科 6548 自結損益(每股面額0.4元) → 不命中",
      conf("公告本公司115年第三季合併自結損益(每股面額0.4元)", code="6548"), None)
check("全形括號（每股面額新台幣1元）→ 不命中",
      conf("公告本公司9月份營收（每股面額新台幣1元）"), None)
check("財報董事會決議(每股面額2.5元) → 不命中",
      conf("代子公司公告董事會決議通過115年第三季財務報告(每股面額2.5元)"), None)
check("附註不影響定向追蹤：已在追蹤的公司開股東會仍命中",
      conf("公告召開股東臨時會(每股面額0.4元)", code="6548", watch={"6548"}), "強")

# 2. 真分割 → 照樣命中（迴歸）
check("印能 7734 董事會決議面額由10元變更為2.5元 → 強",
      conf("公告本公司董事會決議變更每股面額由新台幣10元變更為新台幣2.5元"), "強")
check("股票面額由「新台幣10元」變更為「新台幣2.5元」→ 強",
      conf("公告本公司股票面額由「新台幣10元」變更為「新台幣2.5元」，公告期間…"), "強")
check("類別：決議變更面額 → 宣告拆股",
      sc.kind_of("公告本公司董事會決議變更每股面額由新台幣10元變更為新台幣2.5元"), "宣告拆股")
check("比例：10 元變 2.5 元 → 一拆4",
      sc.ratio_of("面額由新台幣10元變更為新台幣2.5元")[0], 4)
check("說明欄推得出面額變更 → 中",
      conf("公告本公司董事會重要決議", "擬將普通股每股面額由新台幣10元變更為新台幣1元"), "中")

# 3. 減資換股不算（2026-09-15 迴歸）
check("減資換股基準日 → 不命中",
      conf("公告本公司訂定減資換股基準日及換股作業計畫"), None)

if FAIL:
    print("\n失敗：\n" + "\n".join(FAIL))
    sys.exit(1)
print("\n全部通過")
