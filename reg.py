import json, os, sys, urllib.request
U, K = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Content-Type": "application/json"}
def req(path, body=None, method=None):
    r = urllib.request.Request(U + "/rest/v1/" + path, data=None if body is None else json.dumps(body).encode(),
                               headers=H, method=method or ("POST" if body is not None else "GET"))
    try:
        with urllib.request.urlopen(r, timeout=30) as f:
            t = f.read().decode(); return f.status, (json.loads(t) if t else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:500]
def show(t, x):
    print("=====", t); print(json.dumps(x, ensure_ascii=False, default=str)[:3000])
mode = sys.argv[1].strip()
LIST = [("3189", "景碩", "sii"), ("8046", "南電", "sii"), ("6274", "台燿", "otc")]
show("events 欄位樣本", req("events?select=*&order=id.desc&limit=2"))
show("events 市場別分布樣本", req("events?select=market&limit=2000")[1] and sorted({x.get("market") for x in req("events?select=market&order=id.desc&limit=2000")[1]}))
for c, n, m in LIST:
    show(f"既有 events {c}", req(f"events?select=*&company_code=eq.{c}&order=id.desc&limit=5"))
show("signals msci", req("signals?select=*&strategy_code=eq.msci&order=id.desc&limit=5"))
# 市場別核對（TWSE 上市清單／TPEx 上櫃清單）
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as f:
            return json.loads(f.read().decode())
    except Exception as e:
        return str(e)
tw = get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
tp = get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes")
twc = {x.get("Code") for x in tw} if isinstance(tw, list) else set()
tpc = {x.get("SecuritiesCompanyCode") for x in tp} if isinstance(tp, list) else set()
for c, n, m in LIST:
    print(f"市場核對 {c} {n}：上市={c in twc} 上櫃={c in tpc} 預定={m}（清單筆數 上市{len(twc)} 上櫃{len(tpc)}）")
payload = [dict(p_strategy="msci", p_code=c, p_name=n, p_event_date="2026-11-12", p_entry_date="2026-11-12",
                p_exit_date="2026-11-30", p_market=m, p_summary="MSCI 2026-11 半年度調整新增（台灣 11/12 公布、11/30 收盤生效）；Ed 2026-11-14 同意登錄，Emit 補登")
           for c, n, m in LIST]
show("預定呼叫 add_manual_signal", payload)
if mode == "write":
    for p in payload:
        show(f"寫入 {p['p_code']}", req("rpc/add_manual_signal", p))
    show("寫入後 signals msci", req("signals?select=*&strategy_code=eq.msci&order=id.desc&limit=5"))
    show("寫入後 v_tomorrow msci", req("v_tomorrow?select=*&block_code=eq.msci"))
else:
    print("DRY RUN：未寫入")
