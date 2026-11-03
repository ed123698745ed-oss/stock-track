"""分割追蹤資料更正（split_watch）：只改宣告拆股日、股東會日、備註、忽略四個欄位。

給 Ed 指出錯誤後的人工更正用，先 DRY_RUN=1 看改前改後，再實際寫入；寫入後重讀確認。
環境變數：CODE（股票代號，必填）、DECLARE、MEETING（YYYY-MM-DD）、NOTE、IGNORED（true/false）
空白的欄位不動。
"""
import datetime as dt
import json
import os
import sys

from calendar_signals import supa


def main():
    code = (os.environ.get("CODE") or "").strip()
    if not code.isdigit():
        sys.exit("CODE 要填股票代號")
    patch = {}
    for env, col in (("DECLARE", "declare_date"), ("MEETING", "meeting_date")):
        v = (os.environ.get(env) or "").strip()
        if v:
            dt.date.fromisoformat(v)  # 格式不對直接報錯
            patch[col] = v
    if (os.environ.get("NOTE") or "").strip():
        patch["note"] = os.environ["NOTE"].strip()
    if (os.environ.get("IGNORED") or "").strip() in ("true", "false"):
        patch["ignored"] = os.environ["IGNORED"].strip() == "true"
    cols = "company_code,company_name,declare_date,meeting_date,swap_date,listing_date,ignored,note"
    before = supa(f"split_watch?select={cols}&company_code=eq.{code}") or []
    if len(before) != 1:
        sys.exit(f"split_watch 找到 {len(before)} 列 {code}，不處理")
    print("改前：" + json.dumps(before[0], ensure_ascii=False))
    print("要改：" + json.dumps(patch, ensure_ascii=False))
    if not patch:
        sys.exit("沒有要改的欄位")
    if os.environ.get("DRY_RUN") == "1":
        print("DRY_RUN：不寫入")
        return
    supa(f"split_watch?company_code=eq.{code}", "PATCH", patch)
    after = supa(f"split_watch?select={cols}&company_code=eq.{code}")[0]
    print("改後：" + json.dumps(after, ensure_ascii=False))
    bad = [k for k, v in patch.items() if after.get(k) != v]
    if bad:
        sys.exit(f"❌ 寫入後重讀不一致：{bad}（可能被資料庫觸發器或函式蓋回），需人工處理")
    print("✓ 已更正並重讀確認")


if __name__ == "__main__":
    main()
