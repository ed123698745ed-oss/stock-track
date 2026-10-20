const SUPABASE_URL = "https://cvjjzboacbileqikwgcy.supabase.co";
const GH = "https://github.com/ed123698745ed-oss/stock-track/actions";

const $ = id => document.getElementById(id);
let SUPABASE_KEY = "";
try { SUPABASE_KEY = localStorage.getItem("sb_key") || ""; } catch (e) {}
const sb = SUPABASE_KEY ? supabase.createClient(SUPABASE_URL, SUPABASE_KEY) : null;

const W = ["日", "一", "二", "三", "四", "五", "六"];
let CAL = [], STG = [];

const iso = d => d.toISOString().slice(0, 10);
// 一律用台北時間（UTC+8）；用 UTC 日期的話，早上 8 點前會變成昨天。
// 每次載入（重新整理、切回頁面）都重算，頁面開著跨過收盤或午夜也會換日。
let TODAY, NOW_MIN;
function refreshNow() {
  const t = new Date(Date.now() + 8 * 36e5);
  TODAY = iso(t);
  NOW_MIN = t.getUTCHours() * 60 + t.getUTCMinutes();
}
refreshNow();
const CLOSE_MIN = 13 * 60 + 30;  // 收盤後畫面切到下一個交易日
const addDays = (d, n) => iso(new Date(new Date(d + "T00:00:00Z").getTime() + n * 864e5));
let HOL = null, HOL_YEARS = null;  // 休市日 Set、已公布休市日的年份；讀不到時只排除週末
const isTrading = d => {
  const w = new Date(d + "T00:00:00Z").getUTCDay();
  return w !== 0 && w !== 6 && !(HOL && HOL.has(d));
};
// 下一個交易日；該年度休市日還沒公布就回 null（顯示「日期待確認」，不猜）
const yearKnown = d => !HOL_YEARS || HOL_YEARS.has(d.slice(0, 4));
const nextTrading = d => {
  let x = addDays(d, 1);
  while (yearKnown(x) && !isTrading(x)) x = addDays(x, 1);
  return yearKnown(x) ? x : null;
};
const tradingGap = (a, b) => { let n = 0, x = a; while (x < b) { x = addDays(x, 1); if (isTrading(x)) n++; } return n; };

function fmt(d) {
  if (!d) return "—";
  const t = new Date(d + "T00:00:00");
  return `${t.getMonth() + 1}/${t.getDate()}(${W[t.getDay()]})`;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
let toastTimer;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("on"), 2200);
}

// ---------- 策略績效（config/perf.json，由可執行策略總表產生，LINE 讀同一份）----------
let PERF = {};
const BLOCK_SID = { disposal: "A02", buyback: "A03", msci: "A04", tw50: "A05" };
// 提醒日程和回測情境對不上的板塊：不套績效（scripts/perf.py 同名設定）
const PENDING = {};
// 績效和實際提醒情境有落差、仍顯示數字的說明（scripts/perf.py 同名設定）
const NOTES = {
  A11: "年化以資金加權持有11.98交易日計（T−5～T0全額，之後只計配股與現金股利占用），不是帳戶年報酬；2025年17筆平均僅+0.08%",
};
const SMALL_N = 30;
async function loadPerf() {
  try {
    const r = await fetch("config/perf.json", { cache: "no-cache" });
    PERF = (await r.json()).strategies || {};
  } catch (e) { PERF = {}; }
}
const perfOf = (sid, v) => { const sc = PERF[sid]?.scenarios || {}; return sc[v] || sc["*"] || null; };
const pct = (x, sign) => x == null ? "未提供"
  : `${sign && x >= 0 ? "+" : ""}${(x * 100).toFixed(sign ? 2 : 0)}%`;
const holdTxt = s => s.hold == null ? "未提供" : `${+s.hold.toFixed(1)} ${s.hold_unit}`;
const kellyTxt = s => s.kelly == null ? (s.na_reason || "未提供")
  : `${s.kelly.toFixed(2)}（半 ${s.half.toFixed(2)}）`;
// 訊號產生時寫進 detail 的舊統計（n=… 勝率…% p…），改顯示四指標
const OLD_STAT = /n=\d+(?: 勝率[\d.]+%)?(?: p[=<][\d.e-]+)?/;
const cleanDetail = (d, has) => has
  ? String(d || "").replace(OLD_STAT, "").split("｜").filter(x => x.trim()).join("｜") : (d || "");
function m4(s) {
  if (!s) return `<div class="meta">績效：總表未提供</div>`;
  const small = s.n != null && s.n < SMALL_N;
  return `<div class="m4">
      <div><i>平均報酬</i><b>${pct(s.avg, true)}</b></div>
      <div><i>持有</i><b>${holdTxt(s)}</b></div>
      <div><i>單利年化</i><b>${pct(s.ann)}</b></div>
      <div><i>凱利</i><b>${kellyTxt(s)}</b></div>
    </div>
    <div class="meta">回測 n=${s.n ?? "未提供"}${small ? `　<b style="color:var(--warn)">⚠ 小樣本</b>` : ""}</div>`;
}

// ---------- 板塊 ----------
const BLOCKS = {
  disposal: { name: "處置股", color: "#f59e0b" },
  ipo:      { name: "IPO",    color: "#22d3ee" },
  split:    { name: "分割",   color: "#a78bfa" },
  buyback:  { name: "庫藏股", color: "#34d399" },
  tw50:     { name: "0050",   color: "#60a5fa" },
  msci:     { name: "MSCI",   color: "#f472b6" },
  cb:       { name: "可轉債", color: "#0d9488" },
  strategy: { name: "策略",   color: "#84cc16" },
};
const blkColor = c => (BLOCKS[c] || {}).color || "var(--dim)";

// ---------- 動態插入區塊與樣式（index.html 不用改）----------
function ensureSections() {
  if ($("blocksReady")) return;
  document.head.insertAdjacentHTML("beforeend", `<style>
    /* 分頁 */
    .tabs{display:flex;gap:6px;margin-top:10px}
    .tabs button{flex:1;padding:8px 0;border-radius:10px}
    .tabs button.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
    .wrap>.offtab,.nav[hidden]{display:none!important}
    .note{display:flex;gap:8px;margin-top:10px;align-items:center}
    .note button{flex:none;white-space:nowrap}
    .note input{padding:7px 10px}
    .flt{display:flex;gap:6px;margin:4px 0 10px}
    .flt button{padding:5px 12px;font-size:13px;border-radius:999px}
    .flt button.on{border-color:var(--ink)}
    .hist{border:1px solid var(--warn);background:var(--warn-bg);color:var(--warn);
      border-radius:10px;padding:10px 12px;font-size:14px;margin:10px 0}

    /* 四指標：桌機一排四格，手機 2×2 */
    .m4{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px}
    .m4 div{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:6px 8px;min-width:0}
    .m4 i{display:block;font-style:normal;font-size:11px;color:var(--dim)}
    .m4 b{font-variant-numeric:tabular-nums;font-size:14px;word-break:break-all}
    @media (max-width:520px){.m4{grid-template-columns:1fr 1fr}}
    .stats{display:grid;grid-template-columns:1fr 1fr;gap:4px 14px;font-size:13px;margin-top:8px;
      font-variant-numeric:tabular-nums}
    .stats span{color:var(--dim)}
    .kv{font-size:13px;margin-top:6px;line-height:1.5;word-break:break-word}
    .kv span{color:var(--dim)}
    .ctl{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
    .ctl input{grid-column:1/-1}

    /* 板塊標題與色條 */
    h2.blk{display:flex;align-items:center;gap:8px}
    h2.blk::before{content:"";width:11px;height:11px;border-radius:3px;
      background:var(--c);flex:none}
    .card.blkline{border-left:4px solid var(--c)}
    .tag.blk{color:var(--c);border:1px solid var(--c);background:transparent}

    .mini{font-size:13px;padding:10px 12px;margin-bottom:8px}
    .mini .name{font-size:15px;margin:4px 0 2px}

    .nodes{display:grid;grid-template-columns:repeat(auto-fit,minmax(88px,1fr));
      gap:6px;margin-top:10px;font-size:12px}
    .node{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:6px}
    .node i{display:block;color:var(--dim);font-style:normal;font-size:11px}
    .node b{font-variant-numeric:tabular-nums;font-weight:600}
    .node.on{border-color:var(--accent)}

    details.grp{margin-bottom:10px}
    details.grp>summary{font-size:14px}
    .subj{font-size:13px;line-height:1.45;margin-top:6px}
    .edit{display:grid;grid-template-columns:1fr 1fr auto;gap:8px;margin-top:10px;
      align-items:end}
    .edit label{font-size:12px;color:var(--dim);display:block;margin-bottom:3px}
    .edit input{padding:8px 10px;font-size:15px}

    /* 處置進度條 */
    .bar{height:6px;border-radius:99px;background:var(--line);margin-top:8px;overflow:hidden}
    .bar i{display:block;height:100%;background:#f59e0b}

    /* 條件標籤（撮合／圈存／期貨）*/
    .chips{display:flex;gap:5px;flex-wrap:wrap;margin:9px 0 2px}
    .chip{font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px;
      border:1px solid var(--line);color:var(--dim);background:var(--bg);
      letter-spacing:.03em}
    .chip.on  {color:#fff;background:var(--c);border-color:var(--c)}
    .chip.warn{color:#fff;background:#f59e0b;border-color:#f59e0b}
    .chip.hot {color:#fff;background:var(--buy);border-color:var(--buy)}
    .chip.fut {color:#fff;background:#6366f1;border-color:#6366f1}
    .dhead{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}

    /* 分割流程圖 */
    .flow{display:flex;margin:14px 0 2px}
    .step{flex:1 1 0;min-width:0;text-align:center;position:relative;padding-top:4px}
    .step::before{content:"";position:absolute;top:13px;right:50%;width:100%;height:2px;
      background:var(--line)}
    .step:first-child::before{display:none}
    .step.done::before{background:var(--fc,#a78bfa)}
    .step i{display:block;width:18px;height:18px;border-radius:50%;margin:0 auto 7px;
      border:2px solid var(--line);background:var(--card);position:relative;z-index:1}
    .step.done i{background:var(--fc,#a78bfa);border-color:var(--fc,#a78bfa)}
    .step.cur i{border-color:var(--fc,#a78bfa);border-width:3px}
    .step u{display:block;text-decoration:none;font-size:10px;color:var(--dim);
      line-height:1.25;word-break:keep-all}
    .step b{display:block;font-size:10.5px;font-variant-numeric:tabular-nums;
      font-weight:600;margin-top:3px;color:var(--dim)}
    .step.done b,.step.cur b{color:var(--ink)}
    .step.cur u{color:var(--fc,#a78bfa);font-weight:700}

    /* 快速跳轉列 */
    .nav{display:flex;gap:6px;overflow-x:auto;margin-top:10px;padding-bottom:2px;
      scrollbar-width:none}
    .nav::-webkit-scrollbar{display:none}
    .nav button{flex:none;padding:6px 12px;font-size:13px;border-radius:999px;
      display:flex;align-items:center;gap:6px}
    .nav button i{width:8px;height:8px;border-radius:2px;background:var(--c);
      font-style:normal;flex:none}
    .nav button.on{border-color:var(--ink)}
    .nav button em{font-style:normal;font-variant-numeric:tabular-nums;
      color:var(--dim);font-size:12px}
  </style>`);

  $("actionTitle").textContent = "交易提醒";
  $("actions").insertAdjacentHTML("afterend", `<div id="history"></div>`);
  // 「進行中部位」跟各板塊的「持有中」重複，整段收起來
  $("holding").previousElementSibling.hidden = true;
  $("holding").hidden = true;
  // 行事曆的內容全都是 0050／MSCI，搬進「指數調整」板塊
  $("calendar").previousElementSibling.hidden = true;

  $("holding").insertAdjacentHTML("afterend", `
    <hr id="blocksReady">
    <h2 class="blk" id="dspTitle" style="--c:${BLOCKS.disposal.color}">處置股</h2>
    <div id="disposals"></div>
    <h2 class="blk" id="ipoTitle" style="--c:${BLOCKS.ipo.color}">IPO 新股</h2>
    <div id="ipos"></div>
    <h2 class="blk" id="cbTitle" style="--c:${BLOCKS.cb.color}">可轉債發行</h2>
    <div id="cb"></div>
    <h2 class="blk" id="splitTitle" style="--c:${BLOCKS.split.color}">分割策略</h2>
    <div id="split"></div>
    <h2 class="blk" id="bbTitle" style="--c:${BLOCKS.buyback.color}">庫藏股</h2>
    <div id="buyback"></div>
    <h2 class="blk" id="idxTitle" style="--c:${BLOCKS.tw50.color}">指數調整</h2>
    <div id="indexPos"></div>
    <div id="indexCal"></div>
    <h2 class="blk" id="stgTitle" style="--c:${BLOCKS.strategy.color}">策略排程</h2>
    <div id="stgPlan"></div>
    <h2 id="detTitle" hidden>其他偵測公告</h2><div id="detections"></div>`);

  $("indexCal").appendChild($("calendar"));
  $("stgTitle").textContent = "定期交易（之後的進出場）";
  buildNav();
  buildTabs();
}

// ---------- 分頁：交易提醒／策略一覽 ----------
let TAB = "main";
try { TAB = localStorage.getItem("tab") || "main"; } catch (e) {}
function buildTabs() {
  $("nav").insertAdjacentHTML("beforebegin", `<div class="tabs" id="tabs">
    <button data-tab="main">交易提醒</button><button data-tab="perf">策略一覽</button></div>`);
  const body = document.querySelector("#app > .wrap");
  body.insertAdjacentHTML("afterbegin", `<div id="perfTab" data-tab="perf"></div>`);
  $("tabs").querySelectorAll("button").forEach(b => b.onclick = () => setTab(b.dataset.tab));
  setTab(TAB);
}
function setTab(t) {
  TAB = t;
  try { localStorage.setItem("tab", t); } catch (e) {}
  $("tabs").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  $("nav").hidden = t !== "main";
  [...document.querySelector("#app > .wrap").children].forEach(el =>
    el.classList.toggle("offtab", (el.dataset.tab || "main") !== t));
  window.scrollTo({ top: 0 });
}

// ---------- 快速跳轉列 ----------
const NAV = [
  { id: "top",      label: "提醒",   c: "var(--buy)" },
  { id: "dspTitle", label: "處置股", c: BLOCKS.disposal.color },
  { id: "ipoTitle", label: "IPO",    c: BLOCKS.ipo.color },
  { id: "cbTitle",  label: "可轉債", c: BLOCKS.cb.color },
  { id: "splitTitle", label: "分割", c: BLOCKS.split.color },
  { id: "bbTitle",  label: "庫藏股", c: BLOCKS.buyback.color },
  { id: "idxTitle", label: "指數調整", c: BLOCKS.tw50.color },
  { id: "stgTitle", label: "定期交易", c: BLOCKS.strategy.color },
];

function buildNav() {
  $("status").insertAdjacentHTML("afterend",
    `<div class="nav" id="nav">${NAV.map(n =>
      `<button data-go="${n.id}"><i style="--c:${n.c}"></i>${n.label}<em data-n="${n.id}"></em></button>`
    ).join("")}</div>`);

  $("nav").querySelectorAll("[data-go]").forEach(btn => {
    btn.onclick = () => {
      const id = btn.dataset.go;
      if (id === "top") { window.scrollTo({ top: 0, behavior: "smooth" }); return; }
      const el = $(id);
      if (!el) return;
      const head = document.querySelector("header");
      const y = el.getBoundingClientRect().top + window.scrollY - (head?.offsetHeight || 0) - 10;
      window.scrollTo({ top: y, behavior: "smooth" });
    };
  });
}

function navCount(id, n) {
  const el = document.querySelector(`#nav em[data-n="${id}"]`);
  if (el) el.textContent = n ? String(n) : "";
}

// ---------- 金鑰 / 登入 ----------
$("btnKey").onclick = () => {
  const v = $("key").value.trim();
  if (!v) return;
  try { localStorage.setItem("sb_key", v); } catch (e) {}
  location.reload();
};

async function boot() {
  if (!sb) { $("setup").hidden = false; return; }
  const { data: { session } } = await sb.auth.getSession();
  if (session) {
    $("login").hidden = true; $("app").hidden = false;
    ensureSections(); load();
  } else { $("app").hidden = true; $("login").hidden = false; }
}
$("btnLogin").onclick = async () => {
  $("loginErr").textContent = "";
  const { error } = await sb.auth.signInWithPassword({
    email: $("email").value.trim(), password: $("pw").value });
  if (error) $("loginErr").textContent = "登入失敗：" + error.message;
  else boot();
};
$("pw").addEventListener("keydown", e => { if (e.key === "Enter") $("btnLogin").click(); });
$("btnLogout").onclick = async () => { await sb.auth.signOut(); boot(); };
$("btnRefresh").onclick = () => load();
$("btnRun").onclick = () => window.open(GH, "_blank");

// ---------- 載入 ----------
async function load() {
  refreshNow();
  const until = iso(new Date(Date.now() + 400 * 864e5));
  const [tmr, run, stg, cal, dsp, spl, det, ipo, pos, cbs, lds] = await Promise.all([
    sb.from("v_tomorrow").select("*").order("sort_key"),
    sb.from("runs").select("*").order("started_at", { ascending: false }).limit(1),
    sb.from("strategies").select("*").order("name"),
    sb.from("calendar").select("*").gte("event_date", TODAY)
      .lte("event_date", until).order("event_date"),
    sb.from("v_disposals").select("*"),
    sb.from("v_split").select("*"),
    sb.from("detections").select("*").eq("handled", false)
      .order("detected_date", { ascending: false }).limit(30),
    sb.from("v_ipos").select("*"),
    sb.from("v_positions").select("*"),
    sb.from("v_cb").select("*"),
    // 已在追蹤清單的線索不再列（追蹤卡已有流程圖）；只留還沒處理的新線索
    sb.from("v_split_leads").select("*").eq("tracked", false).limit(40),
  ]);
  const err = [tmr, run, stg, cal, dsp, spl, det, ipo, pos, cbs, lds].map(r => r.error).find(Boolean);
  if (err) {
    $("actions").innerHTML = `<div class="card">讀取失敗：${esc(err.message)}</div>`;
    return;
  }
  CAL = cal.data || [];
  STG = stg.data || [];
  const detAll = det.data || [];
  const detSplit = detAll.filter(r => r.strategy_code === "split");
  const detOther = detAll.filter(r => r.strategy_code !== "split");

  const POS = pos.data || [];
  // 目標交易日：盤中（13:30 前）看今天，收盤後看下一個交易日；LINE 連結的 ?d= 優先
  const [hol] = await Promise.all([
    sb.from("holidays").select("market_date").gte("market_date", addDays(TODAY, -60)).limit(1000),
    PERF && Object.keys(PERF).length ? null : loadPerf(),
  ]);
  HOL = hol.error ? null : new Set((hol.data || []).map(r => r.market_date));
  HOL_YEARS = HOL ? new Set([...HOL].map(d => d.slice(0, 4))) : null;
  const auto = isTrading(TODAY) && NOW_MIN < CLOSE_MIN ? TODAY : nextTrading(TODAY);
  const qd = new URLSearchParams(location.search).get("d");
  const target = /^\d{4}-\d{2}-\d{2}$/.test(qd || "") ? qd : auto;
  if (!target) {  // 下一年度休市日未公布：不給確定的交易日
    renderStatus(run.data?.[0]);
    $("actionTitle").textContent = "交易提醒｜日期待確認";
    $("actions").innerHTML = `<div class="hist">下一個交易日落在休市日還沒公布的年度，無法確定日期。
      請到 Actions 執行「休市日」更新後再看。</div>`;
    $("history").innerHTML = "";
    return;
  }
  // 策略訊號另外讀：sql/001 還沒執行時不要拖垮整頁
  const [sDay, sPlan, wl] = await Promise.all([
    sb.from("strategy_actions").select("*").eq("ignored", false)
      .gte("act_date", addDays(target, -14)).lte("act_date", target).order("act_date"),
    sb.from("strategy_actions").select("*").eq("ignored", false).gt("act_date", target)
      .lte("act_date", addDays(target, 60)).order("act_date"),
    // 010 盯盤名單：主推播送出時寫進推播紀錄（sql/004），網站直接讀
    sb.from("push_log").select("code,name,line,act_date").eq("source", "010盯盤").eq("act_date", target),
  ]);
  WATCH = wl.error ? null : wl.data || [];
  renderStatus(run.data?.[0]);
  renderTrade(target, auto, tmr.data || [], sDay.data || [], sDay.error,
    !!hol.error || !(hol.data || []).length);  // 讀不到或空表都要講，不能當成沒有休市日
  renderStrategyPlan(sPlan.data || [], sDay.error || sPlan.error, target);
  renderPerfTab();
  renderCalendar(CAL);
  renderDisposals((dsp.data || []).filter(r => r.grp !== "出關觀察"));  // Ed 不看出關
  renderIpos(ipo.data || []);
  renderCb(cbs.data || []);
  renderSplit(spl.data || [], detSplit, lds.data || []);
  renderPositions(POS.filter(r => r.strategy_code === "buyback"),
                  "buyback", "bbTitle", "庫藏股", BLOCKS.buyback.color);
  renderPositions(POS.filter(r => ["tw50", "msci"].includes(r.strategy_code)),
                  "indexPos", "idxTitle", "指數調整", BLOCKS.tw50.color);
  renderDetections(detOther);
  renderStrategies(STG);
  fillForm();
}

function renderStatus(r) {
  const el = $("status");
  if (!r) { el.innerHTML = `<span class="dot warn"></span>尚無執行紀錄`; return; }
  const t = new Date(r.finished_at || r.started_at);
  const hrs = (Date.now() - t) / 36e5;
  const label = { success: "正常", partial: "部分失敗", failed: "失敗", running: "執行中" }[r.status] || r.status;
  let cls = r.status === "success" ? "" : (r.status === "running" ? "warn" : "bad");
  let stale = "";
  if (hrs > 30 && r.status === "success") { cls = "warn"; stale = "（資料可能過期）"; }
  const ts = `${t.getMonth() + 1}/${t.getDate()} ` +
    `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
  el.innerHTML = `<span class="dot ${cls}"></span>最後更新 ${ts}・${label}${stale}`;
}

// ---------- 交易提醒（目標交易日）----------
let FILTER = "all", WATCH = [];
const KIND = { entry: "進場", exit: "出場", watch: "觀察" };

function watchCard(w) {
  return `
    <div class="card blkline" style="--c:var(--warn)">
      <span class="tag warn">觀察・盤中</span>
      <span class="tag blk" style="--c:${BLOCKS.strategy.color}">010 連續漲停開板反轉</span>
      <div class="name">${esc(w.name || "")} <span class="code">${esc(w.code)}</span></div>
      <div class="meta">${esc(w.line || "")}｜條件未成立：收盤沒鎖漲停才成立 → 收盤放空、下一交易日收盤回補（13:05 盤中會再提醒）</div>
      ${m4(perfOf("010"))}
    </div>`;
}

function stgCard(r) {
  const s = perfOf(r.strategy_id, r.variant);
  const kind = (r.role === "entry") === (r.side === "long") ? "buy" : "sell";
  const c = BLOCKS.strategy.color;
  const meta = [stgVar(r), stgPair(r), r.role === "exit" ? "若有持倉" : "",
                cleanDetail(r.detail, !!s)].filter(Boolean).join("｜");
  return `
    <div class="card blkline ${kind}" style="--c:${c}">
      <span class="tag ${kind}">${stgAction(r)}・${timingOf(r.act_timing)}</span>
      <span class="tag blk" style="--c:${c}">${esc(r.strategy_id)} ${esc(r.strategy_name)}</span>
      <div class="name">${esc(r.company_name)} <span class="code">${esc(r.company_code)}</span></div>
      <div class="meta">${esc(meta)}</div>
      ${m4(s)}
      ${s && NOTES[r.strategy_id] ? `<div class="meta">※ ${esc(NOTES[r.strategy_id])}</div>` : ""}
      ${noteBlock("strategy_actions", r)}
    </div>`;
}

function boardCard(r) {
  const c = blkColor(r.block_code);
  const cls = r.act_kind === "buy" ? "buy" : (r.act_kind === "sell" ? "sell" : "");
  const sid = BLOCK_SID[r.block_code];
  const isTrade = ["buy", "sell"].includes(r.act_kind);
  const trade = sid && isTrade;
  const hold = /賣出|回補/.test(r.action || "") ? "若有持倉｜" : "";
  return `
    <div class="card blkline ${cls}" style="--c:${c}">
      <span class="tag ${cls || "warn"}">${esc(r.action)}</span>
      <span class="tag blk" style="--c:${c}">${trade ? esc(sid) + " " : ""}${esc(r.block)}</span>
      <div class="name">${esc(r.company_name || "")} <span class="code">${esc(r.company_code)}</span></div>
      <div class="meta">${esc(hold + (r.detail || ""))}</div>
      ${isTrade && PENDING[r.block_code] ? `<div class="hist">${esc(PENDING[r.block_code])}</div>` : (trade ? m4(perfOf(sid)) : "")}
      ${noteBlock(r.src_table, { id: r.src_id, checked: r.checked, note: r.note })}
    </div>`;
}

// ---------- 分組顯示（Ed 2026-10-20：與 LINE 推播相同，同策略放一起、買進賣出分開）----------
const ACT_ORD = { "賣出": 0, "回補": 1, "買進": 2, "放空": 3 };
const T_ORD = { "開盤": 0, "收盤": 1, "盤中": 2 };
const BLOCK_TIMING = /^(開盤|收盤)(買進|賣出|放空|回補)$/;
const splitFr = (s, sep) => String(s || "").split(sep).map(x => x.trim()).filter(Boolean);

function stgEntry(r) {
  const s = perfOf(r.strategy_id, r.variant);
  const v = stgVar(r);
  return { g: `S|${r.strategy_id}|${r.variant}`, title: `${r.strategy_id} ${r.strategy_name}${v ? "・" + v : ""}`,
    color: BLOCKS.strategy.color, s, stat: true, note: s && NOTES[r.strategy_id],
    timing: timingOf(r.act_timing), action: stgAction(r), kind: r.role,
    cls: (r.role === "entry") === (r.side === "long") ? "buy" : "sell", exit: r.role === "exit",
    name: r.company_name, code: r.company_code,
    frags: [stgPair(r), ...splitFr(cleanDetail(r.detail, !!s), "｜")].filter(Boolean),
    memo: r.note, ctl: noteBlock("strategy_actions", r) };
}
function boardEntry(r) {
  const sid = BLOCK_SID[r.block_code];
  const isTrade = ["buy", "sell"].includes(r.act_kind);
  let frags = splitFr(r.detail, "　").map(x => x.replace(/承銷價 (0\.0|0|None)(?=[^\d.]|$)/, "承銷價 未定")), timing = "";
  const m = frags.length && frags[0].match(BLOCK_TIMING);
  if (m) { timing = m[1]; frags = frags.slice(1); }
  return { g: `B|${r.block_code}`, title: `${sid && isTrade ? sid + " " : ""}${r.block || ""}`,
    color: blkColor(r.block_code), s: sid && isTrade && !PENDING[r.block_code] ? perfOf(sid) : null,
    stat: !!(sid && isTrade), pending: isTrade && PENDING[r.block_code],
    timing, action: r.action || "注意", kind: boardKind(r),
    cls: r.act_kind === "buy" ? "buy" : (r.act_kind === "sell" ? "sell" : ""), exit: /賣出|回補/.test(r.action || ""),
    name: r.company_name || "", code: r.company_code, frags, memo: r.note,
    ctl: noteBlock(r.src_table, { id: r.src_id, checked: r.checked, note: r.note }) };
}
function watchEntry(w) {
  return { g: "W", title: "010 連續漲停開板反轉・盯盤", color: "var(--warn)", s: perfOf("010"), stat: true,
    hint: "條件未成立：收盤沒鎖漲停才成立 → 收盤放空、下一交易日收盤回補（13:05 盤中會再提醒）",
    timing: "盤中", action: "觀察", kind: "watch", cls: "warn", exit: false,
    name: w.name || "", code: w.code, frags: splitFr(w.line, "｜"), ctl: "" };
}

function groupHtml(es) {
  const e0 = es[0];
  const subs = new Map();
  es.forEach(e => { const k = e.timing + "|" + e.action; if (!subs.has(k)) subs.set(k, []); subs.get(k).push(e); });
  const order = [...subs.values()].sort((a, b) =>
    (T_ORD[a[0].timing] ?? 3) - (T_ORD[b[0].timing] ?? 3) ||
    (ACT_ORD[a[0].action] ?? 9) - (ACT_ORD[b[0].action] ?? 9) || a[0].action.localeCompare(b[0].action));
  const body = order.map(xs => {
    const x0 = xs[0];
    const common = xs.length > 1 ? x0.frags.filter(f => xs.every(x => x.frags.includes(f))) : [];
    const when = x0.timing in T_ORD && x0.timing !== "盤中" ? `${x0.action}・${x0.timing}`
      : (x0.timing ? `${x0.action}・${x0.timing}` : x0.action);
    return `<div class="sub"><span class="tag ${x0.cls || "warn"}">${esc(when)}</span>
        <span class="cnt">${xs.length} 檔${x0.exit ? "・若有持倉" : ""}</span></div>
      ${common.length ? `<div class="meta">${esc(common.join("｜"))}</div>` : ""}
      <div class="li">${xs.map(x => {
        const rest = x.frags.filter(f => !common.includes(f)).join("｜");
        return `<div class="lr"><div class="ln">${esc(x.name)} <span class="code">${esc(x.code)}</span>
            ${rest ? `<div class="meta">${esc(rest)}</div>` : ""}</div>
          ${x.ctl ? `<details class="ctl"><summary>${x.memo ? "📝 " + esc(x.memo) : "備註・忽略"}</summary>${x.ctl}</details>` : ""}</div>`;
      }).join("")}</div>`;
  }).join("");
  return `
    <div class="card blkline" style="--c:${e0.color}">
      <span class="tag blk" style="--c:${e0.color}">${esc(e0.title)}</span>
      ${e0.pending ? `<div class="hist">${esc(e0.pending)}</div>` : (e0.stat ? m4(e0.s) : "")}
      ${e0.note ? `<div class="meta">※ ${esc(e0.note)}</div>` : ""}
      ${e0.hint ? `<div class="meta">${esc(e0.hint)}</div>` : ""}
      ${body}
    </div>`;
}

function groupedHtml(ents) {
  const groups = new Map();
  ents.forEach(e => { if (!groups.has(e.g)) groups.set(e.g, []); groups.get(e.g).push(e); });
  return [...groups.values()].sort((a, b) =>
    (a[0].kind === "watch") - (b[0].kind === "watch") ||
    Math.min(...a.map(e => T_ORD[e.timing] ?? 3)) - Math.min(...b.map(e => T_ORD[e.timing] ?? 3)) ||
    a[0].title.localeCompare(b[0].title)).map(groupHtml).join("");
}

// 舊板塊的處置、分割買賣和總表規則不同，改看 A02／A06（strategy_actions）；與 daily_push.old_trade 一致
const OLD_DISPOSAL = r => (r.block_code === "disposal" && r.src_table === "signals")
  || (r.block_code === "split" && ["buy", "sell"].includes(r.act_kind));
const boardKind = r => /買進|放空/.test(r.action || "") ? "entry" : (/賣出|回補/.test(r.action || "") ? "exit" : "other");

function renderTrade(target, auto, board, stg, err, holErr) {
  const box = $("actions");
  const history = target < auto;
  const nt = nextTrading(TODAY);
  const label = target === TODAY ? "今天" : (target === nt
    ? (target === addDays(TODAY, 1) ? "明天" : "下一交易日") : "");
  $("actionTitle").textContent = `交易提醒｜${fmt(target)}${label ? " " + label : ""}`;

  // 既有板塊（v_tomorrow）只有「今天／明天／未處理」三組，對不上目標日就不顯示
  const bLabel = target === TODAY ? "今天" : (target === nt ? "明天" : null);
  const items = [
    ...board.filter(r => bLabel && r.due_label === bLabel && !OLD_DISPOSAL(r)).map(boardEntry),
    ...stg.filter(r => r.act_date === target).map(stgEntry),
    ...(WATCH || []).map(watchEntry),
  ];
  navCount("top", items.length);

  const notes = [];
  if (history) notes.push(`這是 ${fmt(target)} 的通知內容，日期已過，只供查閱，不是新的訊號。` +
    `<a href="./" style="color:inherit">回到目前日期</a>`);
  if (holErr) notes.push("休市日讀取失敗，目標日只排除週末，可能不準。");
  if (err) notes.push(`策略訊號讀取失敗：${esc(err.message)}（不代表沒有訊號）`);
  if (WATCH === null) notes.push("010 盯盤名單讀取失敗（推播紀錄），請看 LINE。");
  if (!bLabel) notes.push("處置股、庫藏股等既有板塊只保留今天／明天，這一天的板塊項目請看 LINE 原訊息。");

  const shown = items.filter(i => FILTER === "all" || i.kind === FILTER);
  box.innerHTML = notes.map(n => `<div class="hist">${n}</div>`).join("") +
    `<div class="flt" id="flt">${[["all", "全部"], ["entry", "進場"], ["exit", "出場"], ["watch", "觀察"]].map(([k, l]) =>
      `<button data-f="${k}" class="${FILTER === k ? "on" : ""}">${l} ${
        k === "all" ? items.length : items.filter(i => i.kind === k).length}</button>`).join("")}</div>` +
    (shown.length ? groupedHtml(shown)
      : `<div class="empty">${err ? "讀取失敗，無法判斷有沒有訊號。" :
          `${fmt(target)} 沒有${FILTER === "all" ? "要進出場的部位" : KIND[FILTER] + "項目"}。`}</div>`);
  box.querySelectorAll("#flt button").forEach(b => b.onclick = () => {
    FILTER = b.dataset.f; renderTrade(target, auto, board, stg, err, holErr);
  });
  bindRows(box);

  // 日期已過的提醒：移出主清單，保留查閱；不推定成交，也不順延成新訊號
  const old = [
    ...stg.filter(r => r.act_date < target).map(r => ({ d: r.act_date, r, stg: true })),
    ...board.filter(r => r.due_label === "未處理" && !OLD_DISPOSAL(r)).map(r => ({ d: r.event_date, r, stg: false })),
  ].sort((a, b) => String(b.d).localeCompare(String(a.d)));
  $("history").innerHTML = old.length ? `<details class="grp"><summary>日期已過（近 14 天）　${old.length}
      <span class="meta">　只供查閱，不代表已成交</span></summary>
      ${old.map(({ d, r, stg }) => `<div class="card mini">
        <span class="tag" style="color:var(--dim)">${fmt(d)}</span>
        <span class="tag" style="color:var(--dim)">${stg ? esc(stgAction(r) + "・" + timingOf(r.act_timing)) : esc(r.action || "")}</span>
        <span class="tag" style="color:var(--dim)">${stg ? esc(r.strategy_id + " " + r.strategy_name) : esc(r.block || "")}</span>
        <div class="name" style="font-size:15px">${esc(r.company_name || "")} <span class="code">${esc(r.company_code)}</span></div>
        ${stg && r.pair_date ? `<div class="meta">${esc(stgPair(r))}</div>` : ""}
      </div>`).join("")}</details>` : "";
}

// ---------- 策略一覽（config/perf.json）----------
const PV = { q: "", grp: "all", sort: "id" };
const SORTS = {
  id: ["編號", null], avg: ["平均報酬", s => s.avg], ann: ["單利年化", s => s.ann],
  kelly: ["凱利", s => s.kelly], hold: ["持有天數（短到長）", s => s.hold == null ? null : -s.hold],
};
const fnum = (x, d = 2) => x == null ? "未提供" : (typeof x === "number" ? +x.toFixed(d) + "" : esc(x));
const fp = p => p == null ? "未提供" : (typeof p === "string" ? esc(p) : (p < 0.0001 ? p.toExponential(1) : +p.toFixed(4) + ""));
const links = t => esc(t).replace(/https?:\/\/\S+/g, u => `<a href="${u}" target="_blank" rel="noopener">連結</a>`);

function scenarioHtml(sid, st, v, s, showName) {
  const title = showName ? `${esc(sid)} ${esc(st.name)}${v === "*" ? "" : "・" + esc(v)}` : (v === "*" ? "" : esc(v));
  return `<div style="margin-top:12px">
    ${title ? `<div style="font-weight:700">${title}</div>` : ""}
    <div class="meta">${esc(s.side || "")}｜${esc(s.label)}</div>
    ${m4(s)}
    ${NOTES[sid] ? `<div class="meta">※ ${esc(NOTES[sid])}</div>` : ""}
    <details style="margin-top:8px;padding:10px"><summary style="font-size:13px">完整統計與來源</summary>
      <div class="stats">
        <div><span>樣本數</span> ${s.n ?? "未提供"}</div><div><span>平均報酬</span> ${pct(s.avg, true)}</div>
        <div><span>勝率</span> ${s.win == null ? "未提供" : (s.win * 100).toFixed(1) + "%"}</div>
        <div><span>賠率 R</span> ${s.R == null ? (s.na_reason || "未提供") : fnum(s.R)}</div>
        <div><span>凱利</span> ${s.kelly == null ? (s.na_reason || "未提供") : fnum(s.kelly)}</div>
        <div><span>半凱利</span> ${s.half == null ? (s.na_reason || "未提供") : fnum(s.half)}</div>
        <div><span>標準差</span> ${s.sd == null ? "未提供" : (s.sd * 100).toFixed(2) + "%"}</div>
        <div><span>t 值</span> ${fnum(s.t)}</div>
        <div><span>雙尾 p</span> ${fp(s.p)}</div>
        <div><span>平均持有</span> ${holdTxt(s)}</div>
        <div><span>單利年化</span> ${pct(s.ann)}</div>
      </div>
      <div class="kv"><span>進出場：</span>${esc(s.rule)}</div>
      ${s.filter ? `<div class="kv"><span>篩選：</span>${esc(s.filter)}</div>` : ""}
      <div class="kv"><span>樣本期間：</span>${esc(s.period || "未提供")}　<span>頻率：</span>${esc(s.freq || "未提供")}</div>
      <div class="kv"><span>成本與滑價：</span>${esc(s.cost || "未提供")}</div>
      ${s.verify ? `<div class="kv"><span>驗證：</span>${esc(s.verify)}</div>` : ""}
      ${s.risk ? `<div class="kv"><span>風險：</span>${esc(s.risk)}</div>` : ""}
      <div class="kv"><span>來源：</span>${links(s.source || "未提供")}</div>
      <div class="kv"><span>註：</span>單利年化＝單筆周轉換算，不是帳戶實際年化；凱利只是歷史統計，不是下單比例。</div>
    </details></div>`;
}

function renderPerfTab() {
  const box = $("perfTab");
  if (!box) return;
  const ids = Object.keys(PERF);
  if (!ids.length) { box.innerHTML = `<h2>策略一覽</h2><div class="empty">讀不到策略績效檔（config/perf.json）。</div>`; return; }
  const q = PV.q.trim().toLowerCase();
  const ok = sid => (PV.grp === "all" || PERF[sid].group === PV.grp) &&
    (!q || (sid + PERF[sid].name + Object.keys(PERF[sid].scenarios).join("")).toLowerCase().includes(q));
  const live = ids.filter(sid => ok(sid) && PERF[sid].status !== "暫停");
  const paused = ids.filter(sid => ok(sid) && PERF[sid].status === "暫停");

  const card = sid => {
    const st = PERF[sid];
    const sc = Object.entries(st.scenarios);
    return `<div class="card">
      <span class="tag" style="color:var(--dim)">${st.group === "A" ? "A 系列" : "Bot"}</span>
      <span class="tag ${st.status === "上線測試中" ? "" : "warn"}" style="${st.status === "上線測試中" ? "color:var(--dim)" : ""}">${esc(st.status)}</span>
      ${sc.length > 1 ? `<span class="tag" style="color:var(--dim)">${sc.length} 個情境</span>` : ""}
      <div class="name">${esc(sid)} ${esc(st.name)}</div>
      ${sc.map(([v, s]) => scenarioHtml(sid, st, v, s, false)).join("")}
    </div>`;
  };

  let body;
  if (PV.sort === "id") {
    body = live.map(card).join("") || `<div class="empty">沒有符合的策略。</div>`;
  } else {
    // 依指標排序時每個情境分開排，不拿最佳情境代表整個策略；缺值排最後
    const [label, key] = SORTS[PV.sort];
    const flat = live.flatMap(sid => Object.entries(PERF[sid].scenarios).map(([v, s]) => ({ sid, v, s, x: key(s) })));
    flat.sort((a, b) => (a.x == null) - (b.x == null) || (b.x ?? 0) - (a.x ?? 0));
    body = `<div class="meta" style="margin-bottom:8px">依「${label}」排序，每個情境分開排；缺值排最後。持有天數的交易日與日曆日混排，請看單位。</div>` +
      flat.map(({ sid, v, s }) => `<div class="card">${scenarioHtml(sid, PERF[sid], v, s, true)}</div>`).join("");
  }
  box.innerHTML = `<h2>策略一覽</h2>
    <div class="ctl">
      <input type="text" id="pvQ" placeholder="搜尋編號或名稱" value="${esc(PV.q)}">
      <select id="pvG"><option value="all">全部</option><option value="A">A 系列</option><option value="Bot">Bot</option></select>
      <select id="pvS">${Object.entries(SORTS).map(([k, [l]]) => `<option value="${k}">排序：${l}</option>`).join("")}</select>
    </div>
    <div class="meta" style="margin-bottom:10px">數字來自「可執行策略總表」；空白＝原始資料不足，不推估。回測 n&lt;${SMALL_N} 標 ⚠ 小樣本。</div>
    ${body}
    ${paused.length ? `<details class="grp"><summary>暫停／封存　${paused.length}</summary>${paused.map(card).join("")}</details>` : ""}`;
  $("pvG").value = PV.grp; $("pvS").value = PV.sort;
  $("pvQ").oninput = e => { PV.q = e.target.value; renderPerfTab(); const i = $("pvQ"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); };
  $("pvG").onchange = e => { PV.grp = e.target.value; renderPerfTab(); };
  $("pvS").onchange = e => { PV.sort = e.target.value; renderPerfTab(); };
}

// ---------- 策略訊號（日曆型策略等，strategy_actions）----------
const TIMING = { open: "開盤", close: "收盤" };
const timingOf = t => TIMING[t] || "時點待確認";
const stgAction = r => r.action || (r.role === "entry"
  ? (r.side === "long" ? "買進" : "放空") : (r.side === "long" ? "賣出" : "回補"));
// 009 的變體名就是「名稱+代號」，重複就不顯示
const stgVar = r => r.variant === `${r.company_name}${r.company_code}` ? "" : r.variant;
const stgPair = r => r.pair_date
  ? `${r.role === "entry" ? "出場" : "進場"} ${fmt(r.pair_date)} ${timingOf(r.pair_timing)}` : "";

function renderStrategyPlan(rows, err, target) {
  const box = $("stgPlan");
  navCount("stgTitle", rows.length);
  if (err) {
    box.innerHTML = `<div class="empty">策略訊號讀取失敗：${esc(err.message)}
      <br>（第一次使用請先在 Supabase 執行 sql/001_strategy_actions.sql）</div>`;
    return;
  }
  if (!rows.length) { box.innerHTML = `<div class="empty">${fmt(target)} 之後 60 天沒有策略要進出場。</div>`; return; }
  const c = BLOCKS.strategy.color;
  const byDay = {};
  rows.forEach(r => (byDay[r.act_date] = byDay[r.act_date] || []).push(r));
  box.innerHTML = Object.entries(byDay).map(([d, list]) => {
    const days = tradingGap(target, d);
    const when = `${days} 個交易日後`;
    return `
    <div class="card blkline ${days <= 3 ? "soon" : ""}" style="--c:${c}">
      <span class="tag ${days <= 3 ? "warn" : ""}" style="${days <= 3 ? "" : "color:var(--dim)"}">${when}</span>
      <span class="tag" style="color:var(--dim)">${fmt(d)}</span>
      ${list.map(r => {
        const act = stgAction(r);
        const kind = (r.role === "entry") === (r.side === "long") ? "buy" : "sell";
        return `<div style="margin-top:10px">
          <span class="tag ${kind}">${act}・${timingOf(r.act_timing)}</span>
          <span class="tag blk" style="--c:${c}">${esc(r.strategy_id)} ${esc(r.strategy_name)}</span>
          <div class="name" style="font-size:16px">${esc(r.company_name)}
            <span class="code">${esc(r.company_code)}</span></div>
          <div class="meta">${esc([stgVar(r), stgPair(r), cleanDetail(r.detail, !!perfOf(r.strategy_id, r.variant))].filter(Boolean).join("｜"))}</div>
        </div>`;
      }).join("")}
    </div>`;
  }).join("");
}

// ---------- 近期行事曆 ----------
// calendar 的 MSCI 公布日是美東日期；台灣隔天清晨才看到名單，A04 回測的公布日是台灣那天（行事曆表唯讀，顯示端修正標題）
const MSCI_US = r => r.strategy_code === "msci" && r.kind === "announce";
function renderCalendar(rows) {
  const box = $("calendar");
  const open = rows.filter(r => !r.done);
  const near = open.filter(r =>
    (new Date(r.event_date) - new Date(TODAY)) / 864e5 <= 45).slice(0, 4);
  const show = near.length ? near : open.slice(0, 1);
  if (!show.length) { box.innerHTML = `<div class="empty">近期沒有要注意的日子。</div>`; return; }
  box.innerHTML = show.map(r => {
    const days = Math.round((new Date(r.event_date) - new Date(TODAY)) / 864e5);
    const soon = days <= 7;
    const when = days === 0 ? "就是今天" : (days === 1 ? "明天" : `還有 ${days} 天`);
    const c = blkColor(r.strategy_code);
    return `
    <div class="card blkline ${soon ? "soon" : ""}" style="--c:${c}">
      <span class="tag ${soon ? "warn" : ""}" style="${soon ? "" : "color:var(--dim)"}">${when}</span>
      <span class="tag blk" style="--c:${c}">${esc((BLOCKS[r.strategy_code] || {}).name || r.strategy_code || "")}</span>
      <div class="name" style="font-size:16px">${esc(MSCI_US(r) ? "MSCI 公布調整名單（美東日期）" : r.title)}</div>
      <div class="meta">${fmt(r.event_date)}${MSCI_US(r) ? "｜台灣隔天清晨看到名單 → 台灣公布日收盤買（A04），前一晚推播會提醒" : ""}</div>
      ${r.detail ? `<div class="meta">${esc(r.detail)}</div>` : ""}
      <div class="row">
        <label class="chk"><input type="checkbox" data-t="calendar" data-f="done"
          data-id="${r.id}" ${r.done ? "checked" : ""}> 已處理</label>
      </div>
    </div>`;
  }).join("");
  bindRows(box);
}

// ---------- 處置股 ----------
function renderDisposals(rows) {
  const box = $("disposals");
  const C = BLOCKS.disposal.color;
  const fresh = rows.filter(r => r.grp === "即將處置").length;
  $("dspTitle").innerHTML = `處置股${rows.length ? `　${rows.length}` : ""}` +
    (fresh ? `　<span style="color:${C}">新 ${fresh}</span>` : "");
  navCount("dspTitle", rows.length);
  if (!rows.length) { box.innerHTML = `<div class="empty">目前沒有追蹤中的處置股。</div>`; return; }

  const groups = {};
  rows.forEach(r => (groups[r.grp] = groups[r.grp] || []).push(r));
  // 即將處置：新公告排前面；其餘：新到舊
  (groups["即將處置"] || []).sort((a, b) =>
    (b.is_new ? 1 : 0) - (a.is_new ? 1 : 0) ||
    String(a.start_date).localeCompare(String(b.start_date)));
  ["處置中", "出關觀察", "已再處置", "已結束"].forEach(g =>
    (groups[g] || []).sort((a, b) => String(b.start_date).localeCompare(String(a.start_date))));

  const card = r => {
    let progress = "";
    if (r.grp === "處置中" && r.day_no && r.total_days) {
      const pct = Math.round(r.day_no / r.total_days * 100);
      progress = `<div class="meta">目前 <b style="color:${C}">第 ${r.day_no} 天</b>
        ／共 ${r.total_days} 個交易日</div>
        <div class="bar"><i style="width:${pct}%"></i></div>`;
    }
    // 圈存：只標「全部預收」那種（官方公告原文判定）。
    // 大單門檻那種對實際下單影響不大，依 Ed 要求不顯示。
    // 標籤只在「有」的時候出現。沒有期貨、沒有小型期、不用圈存＝不顯示，
    // 不再用灰框佔位 —— 一眼看到的框框都是要注意的事。
    const tags = [];
    if (r.match_mode) tags.push(`<span class="chip on">${esc(r.match_mode)}</span>`);
    // 圈存只標「全部預收」那種（官方公告原文判定）。
    // 大單門檻那種對實際下單影響不大，依 Ed 要求不顯示。
    if (r.prepay === "全部") tags.push(`<span class="chip hot">圈存</span>`);
    if (r.has_futures) tags.push(`<span class="chip fut">期貨${
      r.futures_contract ? " " + esc(r.futures_contract) : ""}</span>`);
    if (r.has_mini) tags.push(`<span class="chip fut">小型期${
      r.futures_contract_mini ? " " + esc(r.futures_contract_mini) : ""}</span>`);
    const chips = tags.length ? `<div class="chips">${tags.join("")}</div>` : "";
    return `
    <div class="card mini blkline ${r.is_focus ? "soon" : ""}" style="--c:${C}">
      <div class="dhead">
        <div>
          <div class="name">${esc(r.company_name)} <span class="code">${esc(r.company_code)}</span></div>
          <div class="meta" style="margin-top:2px">${esc(r.market)}${
            r.cum_count ? `・累計 ${r.cum_count} 次` : ""}${
            r.is_new ? `　<b style="color:var(--buy)">新公告</b>` : ""}</div>
        </div>
        <span class="tag ${r.is_focus ? "warn" : ""}"
          style="${r.is_focus ? "" : "color:var(--dim)"};flex:none">${esc(r.phase || "")}</span>
      </div>
      ${chips}
      <div class="meta">處置 ${fmt(r.start_date)} ～ ${fmt(r.end_date)}</div>
      ${progress}
      ${noteBlock("disposals", r)}
    </div>`;
  };

  const order = ["即將處置", "處置中", "出關觀察", "已再處置", "已結束"];
  box.innerHTML = order.filter(g => groups[g]).map(g => {
    const list = groups[g];
    const open = g === "即將處置" || g === "處置中";
    const star = list.filter(x => x.is_focus).length;
    return `<details class="grp" ${open ? "open" : ""}>
      <summary>${g}　${list.length} 檔${star ? `　★${star}` : ""}</summary>
      ${list.map(card).join("")}
    </details>`;
  }).join("");
  bindRows(box);
}

// ---------- IPO 新股 ----------
function renderIpos(rows) {
  const box = $("ipos");
  const C = BLOCKS.ipo.color;
  const hot = rows.filter(r => r.grp === "今日重點").length;
  $("ipoTitle").innerHTML = `IPO 新股${rows.length ? `　${rows.length}` : ""}` +
    (hot ? `　<span style="color:${C}">★${hot}</span>` : "");
  navCount("ipoTitle", rows.filter(r => r.grp !== "已掛牌").length);
  if (!rows.length) { box.innerHTML = `<div class="empty">目前沒有初上市／初上櫃案件。</div>`; return; }
  const rank = { "今日重點": 0, "進行中": 1, "已掛牌": 2 };
  rows.sort((a, b) => (rank[a.grp] ?? 9) - (rank[b.grp] ?? 9) ||
    String(a.listing_date || "9999").localeCompare(String(b.listing_date || "9999")));

  const range = (a, b) => a && b ? `${fmt(a)}～${fmt(b)}` : "—";
  box.innerHTML = rows.map(r => {
    const isHot = String(r.status || "").startsWith("★");
    const node = (label, val, on) =>
      `<div class="node ${on ? "on" : ""}"><i>${label}</i><b>${val}</b></div>`;
    return `
    <div class="card mini blkline ${isHot ? "soon" : ""}" style="--c:${C}">
      <span class="tag ${isHot ? "warn" : ""}" style="${isHot ? "" : "color:var(--dim)"}">${esc(r.status)}</span>
      <span class="tag" style="color:var(--dim)">${esc(r.market || "")}</span>
      ${r.underwriter ? `<span class="tag" style="color:var(--dim)">${esc(r.underwriter)}</span>` : ""}
      <div class="name">${esc(r.company_name || "")} <span class="code">${esc(r.company_code)}</span></div>
      <div class="meta">承銷價 <b>${Number(r.offer_price) > 0 ? r.offer_price : "未定"}</b>
        ・掛牌 <b>${fmt(r.listing_date)}</b>
        ${r.next_focus ? `・下個觀察 <b>${esc(r.next_focus)}</b>` : ""}</div>
      <div class="nodes">
        ${node("競拍投標", range(r.auction_start, r.auction_end), !!r.auction_start)}
        ${node("開標", r.auction_open ? fmt(r.auction_open) : "—", !!r.auction_open)}
        ${node("申購期間", range(r.sub_start, r.sub_end), !!r.sub_start)}
        ${node("抽籤", r.lottery_date ? fmt(r.lottery_date) : "—", !!r.lottery_date)}
        ${node("掛牌", r.listing_date ? fmt(r.listing_date) : "—", !!r.listing_date)}
      </div>
      ${noteBlock("ipos", r)}
    </div>`;
  }).join("");
  bindRows(box);
}

// ---------- 共用：節點流程圖 ----------
//  已走過＝有日期且已經過去；目前＝第一個未來的日期；
//  全部日期都過去了就沒有「目前」，只剩沒填的節點等著補
function flowHtml(steps, color) {
  let cur = steps.findIndex(s => s[1] && s[1] > TODAY);
  if (cur < 0) {
    const last = steps[steps.length - 1][1];
    cur = (last && last <= TODAY) ? -1 : steps.findIndex(s => !s[1]);
  }
  return `<div class="flow" style="--fc:${color}">${steps.map(([label, d], i) => {
    const cls = (d && d <= TODAY) ? "done" : (i === cur ? "cur" : "");
    return `<div class="step ${cls}"><i></i><u>${label}</u>
      <b>${d ? fmt(d) : "待補"}</b></div>`;
  }).join("")}</div>`;
}

// ---------- 可轉債發行（純觀察，只看近期要發行的）----------
function renderCb(rows) {
  const box = $("cb");
  const C = BLOCKS.cb.color;
  const soonN = rows.filter(r => r.grp === "即將掛牌").length;
  $("cbTitle").innerHTML = `可轉債發行${rows.length ? `　${rows.length}` : ""}` +
    (soonN ? `　<span style="color:${C}">即將掛牌 ${soonN}</span>` : "");
  navCount("cbTitle", rows.length);
  if (!rows.length) {
    box.innerHTML = `<div class="empty">近期沒有要發行的可轉債。</div>`;
    return;
  }
  const rank = { "即將掛牌": 0, "發行作業中": 1, "凍結期中": 2, "可轉換": 3 };
  rows.sort((a, b) => (rank[a.grp] ?? 9) - (rank[b.grp] ?? 9) ||
    String(a.listing_date || "9999").localeCompare(String(b.listing_date || "9999")));

  const card = r => {
    const hot = String(r.status || "").startsWith("★");
    return `
    <div class="card mini blkline ${hot ? "soon" : ""}" style="--c:${C}">
      <span class="tag ${hot ? "warn" : ""}" style="${hot ? "" : "color:var(--dim)"}">${esc(r.status)}</span>
      ${r.guaranteed ? `<span class="tag" style="color:var(--dim)">${esc(r.guaranteed)}</span>` : ""}
      ${r.amount_yi ? `<span class="tag" style="color:var(--dim)">${r.amount_yi} 億</span>` : ""}
      <div class="name">${esc(r.cb_name || (r.stock_name || "") + " CB")}
        <span class="code">${esc(r.cb_code || "未掛牌")}</span></div>
      <div class="meta">正股 ${esc(r.stock_code)} ${esc(r.stock_name || "")}
        ${r.convert_price ? `・轉換價 <b>${r.convert_price}</b>` : ""}
        ${r.next_focus ? `・下個觀察 <b>${esc(r.next_focus)}</b>` : ""}</div>
      ${flowHtml([
        ["董事會決議", r.board_date],
        ["訂價", r.pricing_date],
        ["掛牌上櫃", r.listing_date],
        ["轉換起始", r.convert_start],
      ], C)}
      ${noteBlock("cb_issues", r)}
    </div>`;
  };

  const order = ["即將掛牌", "發行作業中", "凍結期中", "可轉換"];
  const groups = {};
  rows.forEach(r => (groups[r.grp] = groups[r.grp] || []).push(r));
  box.innerHTML = order.filter(g => groups[g]).map(g => {
    const list = groups[g];
    const open = g === "即將掛牌" || g === "發行作業中";
    return `<details class="grp" ${open ? "open" : ""}>
      <summary>${g}　${list.length} 檔</summary>${list.map(card).join("")}
    </details>`;
  }).join("");
  bindRows(box);
}

// ---------- 分割策略（偵測公告 ＋ 六節點流程圖）----------
function renderSplit(rows, det, leads) {
  const box = $("split");
  const C = BLOCKS.split.color;
  // 已在追蹤清單裡的就不要在「待確認」再列一次
  const tracked = new Set(rows.map(r => r.company_code));
  const detections = det.filter(d => !tracked.has(d.company_code));
  const L = leads || [];
  const pending = detections.length + L.length;
  // 已完成（第5日收盤賣已過）或勾了已處理 → 不佔版面，收進最下面摺疊區
  const done = r => r.status === "已完成" || r.checked;
  const shown = rows.filter(r => !done(r)), hidden = rows.filter(done);
  $("splitTitle").innerHTML = `分割策略${shown.length ? `　${shown.length}` : ""}` +
    (pending ? `　<span style="color:${C}">待確認 ${pending}</span>` : "");
  navCount("splitTitle", shown.length + pending);

  // 1) 偵測到但還沒納入追蹤的公告
  const detHtml = detections.map(r => `
    <div class="card mini blkline" style="--c:${C}">
      <span class="tag buy">${esc(r.matched || "偵測到分割公告")}</span>
      <span class="tag" style="color:var(--dim)">${fmt(r.detected_date)}</span>
      <div class="name">${esc(r.company_name || "")} <span class="code">${esc(r.company_code)}</span></div>
      <div class="subj">${esc(r.subject)}</div>
      <div class="row">
        <button class="small" data-addsplit="${esc(r.company_code)}"
          data-name="${esc(r.company_name || "")}">加入追蹤</button>
        <label class="chk"><input type="checkbox" data-t="detections" data-f="handled"
          data-id="${r.id}"> 不追蹤</label>
      </div>
    </div>`).join("");

  // 分割線索：每小時掃重訊（主旨＋說明兩層判定）＋ 每日面額對帳
  const leadHtml = L.map(r => `
    <div class="card mini blkline" style="--c:${C}">
      <span class="chip ${r.confidence === "強" ? "hot" : "warn"}">${esc(r.confidence)}命中</span>
      <span class="chip on" style="--c:${C}">${esc(r.kind)}</span>
      ${r.ratio ? `<span class="chip">一拆${r.ratio}</span>` : ""}
      ${r.tracked ? `<span class="chip">已在追蹤</span>` : ""}
      <div class="name" style="margin-top:8px">${esc(r.company_name || "")}
        <span class="code">${esc(r.company_code)}</span>
        <span class="code" style="font-size:12px">${esc(r.market || "")}・${fmt(r.lead_date)}</span></div>
      <div class="subj">${esc(r.subject || "")}</div>
      <div class="row">
        <label class="chk"><input type="checkbox" data-t="split_leads" data-f="handled"
          data-id="${r.id}"> 已看過</label>
        ${r.tracked ? "" : `<button class="small" data-addsplit="${esc(r.company_code)}"
          data-name="${esc(r.company_name || "")}">加入追蹤</button>`}
      </div>
    </div>`).join("");

  if (!rows.length && !detections.length && !L.length) {
    box.innerHTML = `<div class="empty">沒有追蹤中的分割標的。</div>`;
    return;
  }

  const rank = { buy: 0, sell: 0, hold: 1, watch: 2, other: 3 };
  rows.sort((a, b) => (rank[a.grp] ?? 9) - (rank[b.grp] ?? 9));

  // A06（總表 2026-10-15 修正版）：公告換股（盤後）→ 隔日開盤買 → 新股上市第 5 日收盤賣
  const flow = r => flowHtml([
    ["宣告拆股", r.declare_date],
    ["股東會", r.meeting_date],
    ["公告換股", r.swap_date],
    ["隔日開盤買", r.swap_date ? nextTrading(r.swap_date) : null],
    ["新股上市", r.listing_date],
    ["第5日收盤賣", r.sell_date],
  ], C);

  const splitCard = r => {
    const hot = String(r.status || "").startsWith("★");
    return `
    <div class="card blkline ${hot ? "soon" : ""}" style="--c:${C}">
      <span class="tag ${hot ? "warn" : ""}" style="${hot ? "" : "color:var(--dim)"}">${esc(r.status)}</span>
      ${r.ratio ? `<span class="tag" style="color:var(--dim)">一拆${r.ratio}</span>` : ""}
      <div class="name">${esc(r.company_name || "")} <span class="code">${esc(r.company_code)}</span></div>
      ${flow(r)}
      <div class="edit">
        <div><label>補公告換股日</label>
          <input type="date" data-split="${esc(r.company_code)}" data-k="swap"
                 value="${r.swap_date || ""}"></div>
        <div><label>補新股上市日</label>
          <input type="date" data-split="${esc(r.company_code)}" data-k="listing"
                 value="${r.listing_date || ""}"></div>
        <button class="small" data-splitsave="${esc(r.company_code)}">存</button>
      </div>
      ${noteBlock("split_watch", r)}
    </div>`;
  };
  box.innerHTML = leadHtml + detHtml + shown.map(splitCard).join("") +
    (hidden.length ? `<details class="grp"><summary>已完成／已處理　${hidden.length} 檔</summary>
      ${hidden.map(splitCard).join("")}</details>` : "");

  bindRows(box);
  box.querySelectorAll("[data-splitsave]").forEach(btn => {
    btn.onclick = async () => {
      const code = btn.dataset.splitsave;
      const get = k => box.querySelector(`[data-split="${code}"][data-k="${k}"]`).value || null;
      const { error } = await sb.rpc("upsert_split_watch", {
        p_code: code, p_swap: get("swap"), p_listing: get("listing") });
      toast(error ? "儲存失敗：" + error.message : "已更新節點");
      if (!error) load();
    };
  });
  box.querySelectorAll("[data-addsplit]").forEach(btn => {
    btn.onclick = async () => {
      const { error } = await sb.rpc("upsert_split_watch", {
        p_code: btn.dataset.addsplit, p_name: btn.dataset.name });
      toast(error ? "失敗：" + error.message : "已加入分割追蹤");
      if (!error) load();
    };
  });
}

// ---------- 庫藏股 / 指數調整（共用同一種卡片）----------
function renderPositions(rows, boxId, titleId, title, color) {
  const box = $(boxId);
  const live = rows.filter(r => r.grp !== "已結束").length;
  $(titleId).innerHTML = `${title}${live ? `　${live}` : ""}`;
  navCount(titleId, live);
  if (!rows.length) {
    box.innerHTML = `<div class="empty">目前沒有${title}的部位。</div>`;
    return;
  }
  const groups = {};
  rows.forEach(r => (groups[r.grp] = groups[r.grp] || []).push(r));

  const card = r => {
    const c = blkColor(r.strategy_code);
    const soon = r.grp === "持有中" && r.days_to_exit !== null && r.days_to_exit <= 2;
    let progress = "";
    if (r.grp === "持有中" && r.day_no && r.total_days) {
      const pct = Math.min(100, Math.round(r.day_no / r.total_days * 100));
      progress = `<div class="meta">持有 <b style="color:${color}">第 ${r.day_no} 天</b>
        ／共 ${r.total_days} 個交易日</div>
        <div class="bar"><i style="width:${pct}%;background:${color}"></i></div>`;
    }
    return `
    <div class="card mini blkline ${soon ? "soon" : ""}" style="--c:${c}">
      <span class="tag ${soon ? "warn" : ""}" style="${soon ? "" : "color:var(--dim)"}">${esc(r.grp)}</span>
      <span class="tag blk" style="--c:${c}">${esc(r.strategy_name)}</span>
      <div class="name">${esc(r.company_name || "")} <span class="code">${esc(r.company_code)}</span></div>
      <div class="meta">${fmt(r.entry_date)} ${r.entry_timing === "open" ? "開盤" : "收盤"}買
        　→　${fmt(r.exit_date)} ${r.exit_timing === "open" ? "開盤" : "收盤"}賣</div>
      ${progress}
      ${noteBlock("signals", r)}
    </div>`;
  };

  box.innerHTML = ["持有中", "待進場", "已結束"].filter(g => groups[g]).map(g => {
    const list = groups[g];
    const open = g !== "已結束";
    return `<details class="grp" ${open ? "open" : ""}>
      <summary>${g}　${list.length} 檔</summary>${list.map(card).join("")}
    </details>`;
  }).join("");
  bindRows(box);
}

// ---------- 其他偵測公告 ----------
function renderDetections(rows) {
  const box = $("detections");
  $("detTitle").hidden = rows.length === 0;
  if (!rows.length) { box.innerHTML = ""; return; }
  $("detTitle").textContent = `其他偵測公告　${rows.length}`;
  box.innerHTML = rows.map(r => `
    <div class="card mini">
      <span class="tag buy">${esc(r.matched || "命中")}</span>
      <span class="tag" style="color:var(--dim)">${esc(r.strategy_code || "")}</span>
      <div class="name">${esc(r.company_name || "")} <span class="code">${esc(r.company_code)}</span>
        <span class="code" style="font-size:12px">${fmt(r.detected_date)}</span></div>
      <div class="subj">${esc(r.subject)}</div>
      <div class="row">
        <label class="chk"><input type="checkbox" data-t="detections" data-f="handled"
          data-id="${r.id}"> 已處理</label>
      </div>
    </div>`).join("");
  bindRows(box);
}

// ---------- 共用：勾選與備註 ----------
function noteBlock(table, r) {
  const chk = table === "split_watch" ? `<label class="chk">
        <input type="checkbox" data-t="${table}" data-f="checked" data-id="${r.id}"
          ${r.checked ? "checked" : ""}> 已處理
      </label>` : "";
  const ign = ["signals", "disposals", "strategy_actions"].includes(table)
    ? `<button class="small" data-ignore="${table}:${r.id}">忽略</button>` : "";
  if (!chk) return `
    <div class="note">
      <input type="text" placeholder="備註" data-t="${table}" data-f="note" data-id="${r.id}"
             value="${esc(r.note || "")}">${ign}
    </div>`;
  return `<div class="row">${chk}</div>
    <div class="row">
      <input type="text" placeholder="備註" data-t="${table}" data-f="note" data-id="${r.id}"
             value="${esc(r.note || "")}">
    </div>`;
}

function bindRows(box) {
  box.querySelectorAll("input[type=checkbox][data-t]").forEach(el => {
    el.onchange = () => saveRow(el.dataset.t, el.dataset.id,
      { [el.dataset.f]: el.checked }, el.checked && el.dataset.f !== "checked" ? "已處理" : null);
  });
  box.querySelectorAll("input[type=text][data-f=note]").forEach(el => {
    el.onchange = () => saveRow(el.dataset.t, el.dataset.id, { note: el.value });
  });
  box.querySelectorAll("button[data-ignore]").forEach(el => {
    el.onclick = async () => {
      const [t, id] = el.dataset.ignore.split(":");
      // strategy_actions 的 checked 當「使用者手動忽略」記號：推播不會因此推「取消」
      await saveRow(t, id, t === "strategy_actions" ? { ignored: true, checked: true } : { ignored: true }, "已忽略（只隱藏，不代表策略取消）");
      load();
    };
  });
}

async function saveRow(table, id, patch, msg) {
  const { error } = await sb.from(table).update(patch).eq("id", id);
  toast(error ? "儲存失敗：" + error.message : (msg || "已同步"));
  if (!error && (patch.handled || patch.done || (table === "split_watch" && "checked" in patch))) load();
}

// ---------- 手動新增 ----------
function fillForm() {
  const sel = $("fStrategy");
  if (sel.options.length !== STG.length) {
    sel.innerHTML = STG.map(s => `<option value="${esc(s.code)}">${esc(s.name)}</option>`).join("");
    if (STG.some(s => s.code === "tw50")) sel.value = "tw50";
  }
  if (!$("fEvent").value) $("fEvent").value = TODAY;
  syncDates();
}

// A04／A05 依可執行策略總表：
//   MSCI（A04）：公布日收盤買 → 生效日收盤賣
//   0050（A05）：公布後週一收盤買 → 生效日收盤賣（週一休市順延到下一個交易日）
// 生效日取行事曆；查不到就要手動填，不用「持有 N 天」代替。
const INDEX_RULE = {
  msci: { name: "A04", entry: ev => isTrading(ev) ? ev : nextTrading(ev), label: "公布日收盤買" },
  tw50: { name: "A05", entry: ev => {
    const w = new Date(ev + "T00:00:00Z").getUTCDay();
    let x = addDays(ev, ((8 - w) % 7) || 7);  // 下一個週一
    while (x && !isTrading(x)) x = nextTrading(x);
    return x;
  }, label: "公布後週一收盤買" },
};
function syncDates() {
  const code = $("fStrategy").value, ev = $("fEvent").value;
  if (!ev || !code) return;
  const eff = CAL.find(c => c.strategy_code === code && c.kind === "effective" && c.event_date >= ev);
  const rule = INDEX_RULE[code];
  if (rule) {
    $("fEntry").value = rule.entry(ev) || "";
    $("fExit").value = eff ? eff.event_date : "";
    $("fHint").textContent = `${rule.name}（依總表）：${rule.label}${$("fEntry").value ? " " + fmt($("fEntry").value) : "（日期待確認）"}` +
      (eff ? ` → 生效日 ${fmt(eff.event_date)} 收盤賣。` : "。行事曆查不到生效日，請手動填出場日（生效日）。");
    return;
  }
  if (eff) {
    $("fExit").value = eff.event_date;
    $("fHint").textContent =
      `出場日已帶入行事曆上的生效日 ${fmt(eff.event_date)}。進場日留空會用策略參數推算。`;
  } else {
    $("fExit").value = "";
    $("fHint").textContent = "兩個日期都留空的話，會用策略參數（進場後持有 N 個交易日）推算。";
  }
  $("fEntry").value = "";
}
$("fStrategy").onchange = syncDates;
$("fEvent").onchange = syncDates;

$("btnAdd").onclick = async () => {
  const code = $("fCode").value.trim(), name = $("fName").value.trim(), ev = $("fEvent").value;
  if (!code || !ev) { toast("代號和事件日必填"); return; }
  if (INDEX_RULE[$("fStrategy").value] && (!$("fEntry").value || !$("fExit").value)) {
    toast("指數調整要有進場日和出場日（生效日），不用持有天數推算"); return;
  }
  const { data, error } = await sb.rpc("add_manual_signal", {
    p_strategy: $("fStrategy").value, p_code: code, p_name: name || code,
    p_event_date: ev, p_entry_date: $("fEntry").value || null,
    p_exit_date: $("fExit").value || null, p_market: "sii", p_summary: "手動新增",
  });
  if (error) { toast("新增失敗：" + error.message); return; }
  toast("已新增（訊號 #" + data + "）");
  $("fCode").value = ""; $("fName").value = "";
  load();
};

// ---------- 策略設定 ----------
function renderStrategies(rows) {
  $("strategies").innerHTML = rows.map(s => {
    const c = blkColor(s.code);
    return `
    <div class="card blkline" style="--c:${c}">
      <div class="name" style="font-size:16px">${esc(s.name)}
        <span class="code">${esc(s.code)}</span></div>
      <div class="grid" style="margin-top:12px">
        <div><label>事件後第幾個交易日進場</label>
          <input type="number" min="0" max="60" data-s="${esc(s.code)}"
                 data-f="entry_offset" value="${s.entry_offset}"></div>
        <div><label>持有幾個交易日（含進場日）</label>
          <input type="number" min="1" max="250" data-s="${esc(s.code)}"
                 data-f="holding_days" value="${s.holding_days}"></div>
      </div>
      <div class="row">
        <label class="chk"><input type="checkbox" data-s="${esc(s.code)}" data-f="enabled"
          ${s.enabled ? "checked" : ""}> 啟用</label>
        <span class="meta">進場 ${s.entry_timing === "open" ? "開盤" : "收盤"}
          ・出場 ${s.exit_timing === "open" ? "開盤" : "收盤"}</span>
      </div>
    </div>`;
  }).join("");

  $("strategies").querySelectorAll("[data-s]").forEach(el => {
    el.onchange = async () => {
      const v = el.type === "checkbox" ? el.checked : Number(el.value);
      const { error } = await sb.from("strategies")
        .update({ [el.dataset.f]: v, updated_at: new Date().toISOString() })
        .eq("code", el.dataset.s);
      toast(error ? "儲存失敗：" + error.message : "已更新策略參數");
    };
  });
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && !$("app").hidden) load();
});

// 可安裝成 App（手機「加入主畫面」、電腦網址列的「安裝」）
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}

boot();
