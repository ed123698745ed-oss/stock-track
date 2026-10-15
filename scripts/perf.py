"""策略績效（config/perf.json，由 build_perf.py 從可執行策略總表產生）。網站讀同一份檔。"""
import json
import pathlib

_P = pathlib.Path(__file__).resolve().parent.parent / "config" / "perf.json"
SMALL_N = 30
# 既有板塊（v_tomorrow.block_code）→ A 系列編號
BLOCK_SID = {"disposal": "A02", "buyback": "A03", "msci": "A04", "tw50": "A05"}
# 提醒日程和回測情境對不上的板塊：不套績效，直接說明（網站讀 app.js 同名設定）
PENDING = {}
# 績效和實際提醒的情境有落差、但仍顯示數字的：附一行說明（網站讀 app.js 同名設定）
NOTES = {"A11": "績效是 T−1 收盤篩選、面額 10 元的回測；實際用 T−6 收盤、實際面額事前試算，名單可能不同",
         "A02": "總表標題寫「出關日收盤」，來源公式實為處置最後一天收盤賣（本提醒依公式）"}

try:
    STRATS = json.loads(_P.read_text("utf-8"))["strategies"]
except Exception as e:  # 檔案壞掉不能拖垮推播：四指標改顯示「未提供」
    print(f"⚠ 讀不到 {_P.name}：{e}")
    STRATS = {}


def lookup(sid, variant=None):
    sc = (STRATS.get(sid) or {}).get("scenarios") or {}
    return sc.get(variant) or sc.get("*")


def pct(x, sign=False):
    return "未提供" if x is None else (f"{x * 100:+.2f}%" if sign else f"{x * 100:.0f}%")


def summary(sid, variant=None):
    """'平均+1.88%｜持有10交易日｜年化47%｜凱利0.27(半0.13)｜n=958'；查不到回 None。"""
    s = lookup(sid, variant)
    if not s:
        return None
    hold = "未提供" if s["hold"] is None else f"{round(s['hold'], 1):g}{s['hold_unit']}"
    if s["kelly"] is not None:
        kelly = f"凱利{s['kelly']:.2f}(半{s['half']:.2f})"
    else:
        kelly = f"凱利{s.get('na_reason') or '未提供'}"
    n = "n未提供" if s["n"] is None else f"n={s['n']}" + ("⚠小樣本" if s["n"] < SMALL_N else "")
    return "｜".join([f"平均{pct(s['avg'], True)}", f"持有{hold}", f"年化{pct(s['ann'])}", kelly, n])
