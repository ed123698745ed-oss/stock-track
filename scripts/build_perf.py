"""把「可執行策略總表」（Google 試算表下載成 xlsx）轉成 config/perf.json，網站與 LINE 共用。

用法：python3 scripts/build_perf.py 可執行策略總表.xlsx
  只搬數字，不補算；唯一的換算是半凱利 = 凱利 ÷ 2（定義，不是推估）。
  空白、N/A 一律存 null，另記原因。總表更新後重跑一次即可。
"""
import datetime as dt
import json
import math
import pathlib
import re
import sys

import openpyxl

OUT = pathlib.Path(__file__).resolve().parent.parent / "config" / "perf.json"
STATUS = {"A07": "暫停"}           # Ed 指示暫停的策略
REMIND = {"015": "提醒型（名單人工確認）"}


def variant(sid, name, rule):
    """對到 strategy_actions.variant；單一情境的策略用 "*"。"""
    if sid == "A09":
        return re.split(r"[(（]", rule)[0].strip()
    if sid == "A10":
        return "長榮航冬季" if "長榮航" in rule else "華航夏季"
    if sid == "009":
        return name.split("｜")[1].strip()
    if sid == "014":
        return f"持有{re.search(r'持有(\d+)交易日', rule).group(1)}日"
    if sid == "015":
        tail = name.split("｜")[1]
        return {"MSCI台灣多空": "MSCI多空", "台灣50多空": "台灣50多空", "MSCI新增股": "MSCI新增股放空"}[tail]
    return "*"


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if math.isnan(v) else float(v)
    s = str(v).strip()
    try:
        return float(s)
    except ValueError:
        return None


def hold(v):
    """'10.41 日曆日（平均）' → (10.41, 日曆日)；純數字 → 交易日。"""
    if isinstance(v, (int, float)):
        return float(v), "交易日"
    m = re.match(r"([\d.]+)\s*(交易日|日曆日)", str(v or ""))
    return (float(m.group(1)), m.group(2)) if m else (None, None)


def rows(ws, cols):
    head = None
    for r in ws.iter_rows(values_only=True):
        if r and r[0] == "策略編號":
            head = [str(x or "").strip() for x in r]
            continue
        if head and r[0]:
            d = dict(zip(head, r))
            yield {k: d.get(v) for k, v in cols.items()}


COLS = {"sid": "策略編號", "name": "策略名稱", "side": "方向", "n": "樣本數 n", "avg": "平均報酬",
        "hold": "持有時間", "ann": "單利年化", "win": "勝率", "R": "賠率R", "kelly": "凱利值",
        "half": "半凱利", "sd": "標準差", "t": "t 值", "p": "雙尾 p 值", "freq": "交易頻率",
        "period": "樣本期間", "cost": "交易成本與滑價", "risk": "風險與待確認說明", "filter": "篩選條件"}


def main(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    out = {}
    for sheet, group, rule_col, src_col in (("完整策略績效", "A", "進出場", "來源檔／工作表／儲存格"),
                                           ("Bot可執行策略", "Bot", "測試版本／進出場", "來源檔／連結")):
        cols = dict(COLS, rule=rule_col, source=src_col)
        if group == "Bot":
            cols["status_note"] = "驗證狀態"
        for r in rows(wb[sheet], cols):
            sid = str(r["sid"]).strip()
            name = str(r["name"]).strip()
            h, unit = hold(r["hold"])
            kelly = num(r["kelly"])
            half = num(r["half"]) if r.get("half") is not None else (kelly / 2 if kelly is not None else None)
            na = "無虧損樣本" if str(r["R"]).strip().upper() == "N/A" else None
            p = r["p"] if isinstance(r["p"], str) else num(r["p"])
            sc = {
                "label": str(r["rule"]).split("｜")[0] if group == "Bot" else str(r["rule"]),
                "rule": str(r["rule"] or ""), "filter": str(r["filter"] or ""),
                "side": r["side"], "n": int(num(r["n"])) if num(r["n"]) else None,
                "avg": num(r["avg"]), "hold": h, "hold_unit": unit, "ann": num(r["ann"]),
                "win": num(r["win"]), "R": num(r["R"]), "kelly": kelly, "half": half,
                "sd": num(r["sd"]), "t": num(r["t"]), "p": p, "na_reason": na,
                "freq": r["freq"], "period": r["period"], "cost": r["cost"],
                "source": str(r["source"] or ""), "risk": r["risk"], "verify": r.get("status_note"),
            }
            s = out.setdefault(sid, {"name": name.split("｜")[0], "group": group,
                                     "status": STATUS.get(sid) or REMIND.get(sid) or "上線測試中",
                                     "scenarios": {}})
            s["scenarios"][variant(sid, name, sc["rule"])] = sc
    doc = {"_source": "可執行策略總表（Google 試算表）", "_built": dt.date.today().isoformat(),
           "_note": "數字照總表搬，空白存 null；半凱利＝凱利÷2。", "strategies": out}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", "utf-8")
    n = sum(len(s["scenarios"]) for s in out.values())
    print(f"寫入 {OUT}：{len(out)} 項策略、{n} 個情境")


if __name__ == "__main__":
    main(sys.argv[1])
