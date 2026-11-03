"""成對日期同步（scripts/pair_sync.py）：進場列記的出場日與出場列不一致就改；取消的不動。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import pair_sync  # noqa: E402


def r(i, role, act, pair, at="close", pt="close", **kw):
    return dict({"id": i, "strategy_id": "004", "variant": "大額現增放空", "company_code": "6917", "company_name": "竟天",
                 "cycle": "2026-09-18", "role": role, "act_date": act, "act_timing": at, "pair_date": pair,
                 "pair_timing": pt, "ignored": False, "checked": False}, **kw)


def test_entry_pair_follows_exit():
    rows = [r(35, "entry", "2026-10-19", "2026-11-02", at="open"), r(36, "exit", "2026-11-03", "2026-10-19", pt="open")]
    out = pair_sync.plan(rows)
    assert [(i, p) for i, p, _ in out] == [(35, {"pair_date": "2026-11-03"})]


def test_consistent_pair_untouched():
    rows = [r(1, "entry", "2026-10-19", "2026-11-03", at="open"), r(2, "exit", "2026-11-03", "2026-10-19", pt="open")]
    assert pair_sync.plan(rows) == []


def test_cancelled_group_untouched_hidden_synced():
    rows = [r(1, "entry", "2026-10-19", "2026-11-02", at="open"),
            r(2, "exit", "2026-11-03", "2026-10-19", pt="open", ignored=True)]
    assert pair_sync.plan(rows) == []  # 策略取消：不動
    rows[1]["checked"] = True  # 網站隱藏（ignored+checked）不是取消，照樣同步
    assert [i for i, _, _ in pair_sync.plan(rows)] == [1]


def test_exit_pair_and_timing():
    rows = [r(1, "entry", "2026-10-20", "2026-11-03", at="open"), r(2, "exit", "2026-11-03", "2026-10-19", pt="close")]
    assert [(i, p) for i, p, _ in pair_sync.plan(rows)] == [(2, {"pair_date": "2026-10-20", "pair_timing": "open"})]


def test_single_leg_skipped():
    assert pair_sync.plan([r(1, "exit", "2026-11-03", "2026-10-19", variant="大幅除權息・配股")]) == []
