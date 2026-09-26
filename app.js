const SUPABASE_URL = "https://cvjjzboacbileqikwgcy.supabase.co";
const GH = "https://github.com/ed123698745ed-oss/stock-track/actions";

const $ = id => document.getElementById(id);
let SUPABASE_KEY = "";
try { SUPABASE_KEY = localStorage.getItem("sb_key") || ""; } catch (e) {}
const sb = SUPABASE_KEY ? supabase.createClient(SUPABASE_URL, SUPABASE_KEY) : null;

const W = ["日", "一", "二", "三", "四", "五", "六"];
let CAL = [], STG = [];

const iso = d => d.toISOString().slice(0, 10);
const TODAY = iso(new Date());

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

// ---------- 板塊 ----------
const BLOCKS = {
  disposal: { name: "處置股", color: "#f59e0b" },
  ipo:      { name: "IPO",    color: "#22d3ee" },
  split:    { name: "分割",   color: "#a78bfa" },
  buyback:  { name: "庫藏股", color: "#34d399" },
  tw50:     { name: "0050",   color: "#60a5fa" },
  msci:     { name: "MSCI",   color: "#f472b6" },
  cb:       { name: "可轉債", color: "#0d9488" },
};
const blkColor = c => (BLOCKS[c] || {}).color || "var(--dim)";

// ---------- 動態插入區塊與樣式（index.html 不用改）----------
function ensureSections() {
  if ($("blocksReady")) return;
  document.head.insertAdjacentHTML("beforeend", `<style>
    .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(54px,1fr));
      gap:6px;margin:14px 0 4px}
    .kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;
      padding:10px 8px;text-align:center}
    .kpi b{display:block;font-size:21px;font-variant-numeric:tabular-nums;line-height:1.2}
    .kpi span{font-size:11px;color:var(--dim)}
    .kpi.hot b{color:var(--buy)}

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

  $("actionTitle").textContent = "明日重點";
  $("actionTitle").insertAdjacentHTML("beforebegin", `<div class="kpis" id="kpis"></div>`);
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
    <h2 id="detTitle" hidden>其他偵測公告</h2><div id="detections"></div>`);

  $("indexCal").appendChild($("calendar"));
  buildNav();
}

// ---------- 快速跳轉列 ----------
const NAV = [
  { id: "top",      label: "待辦",   c: "var(--buy)" },
  { id: "dspTitle", label: "處置股", c: BLOCKS.disposal.color },
  { id: "ipoTitle", label: "IPO",    c: BLOCKS.ipo.color },
  { id: "cbTitle",  label: "可轉債", c: BLOCKS.cb.color },
  { id: "splitTitle", label: "分割", c: BLOCKS.split.color },
  { id: "bbTitle",  label: "庫藏股", c: BLOCKS.buyback.color },
  { id: "idxTitle", label: "指數調整", c: BLOCKS.tw50.color },
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
    sb.from("v_split_leads").select("*").limit(40),
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
  renderStatus(run.data?.[0]);
  renderTomorrow(tmr.data || []);
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
  renderKpis(tmr.data || [], dsp.data || [], ipo.data || [], detAll);
  fillForm();
}

function renderKpis(tmr, dsp, ipo, det) {
  const inDisp = dsp.filter(d => d.grp === "處置中").length;
  const newDisp = dsp.filter(d => d.is_new).length;
  const ipoHot = ipo.filter(r => r.grp === "今日重點").length;
  const late = tmr.filter(r => r.due_label === "未處理").length;
  $("kpis").innerHTML = `
    <div class="kpi ${tmr.length ? "hot" : ""}"><b>${tmr.length}</b><span>待辦</span></div>
    <div class="kpi ${late ? "hot" : ""}"><b>${late}</b><span>未處理</span></div>
    <div class="kpi ${newDisp ? "hot" : ""}"><b>${newDisp}</b><span>新處置</span></div>
    <div class="kpi"><b>${inDisp}</b><span>處置中</span></div>
    <div class="kpi ${ipoHot ? "hot" : ""}"><b>${ipo.filter(r => r.grp !== "已掛牌").length}</b><span>IPO</span></div>
    <div class="kpi ${det.length ? "hot" : ""}"><b>${det.length}</b><span>待看公告</span></div>`;
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

// ---------- 明日重點（所有板塊合併）----------
function renderTomorrow(rows) {
  const box = $("actions");
  if (!rows.length) {
    $("actionTitle").textContent = "待辦";
    navCount("top", 0);
    box.innerHTML = `<div class="empty">目前沒有要處理的事。</div>
      <h3 style="font-size:13px;color:var(--dim);margin:14px 0 8px;letter-spacing:.08em">今天　0</h3>
      <div class="empty">本日無新增處置</div>`;
    return;
  }
  const order = { "未處理": 0, "今天": 1, "明天": 2 };
  rows.sort((a, b) => (order[a.due_label] ?? 9) - (order[b.due_label] ?? 9) ||
    (a.act_kind === "sell" ? 0 : 1) - (b.act_kind === "sell" ? 0 : 1));
  const late = rows.filter(r => r.due_label === "未處理").length;
  $("actionTitle").textContent = `待辦　${rows.length}${late ? `（未處理 ${late}）` : ""}`;
  navCount("top", rows.length);

  const groups = {};
  rows.forEach(r => (groups[r.due_label] = groups[r.due_label] || []).push(r));

  const card = r => {
    const c = blkColor(r.block_code);
    const cls = r.act_kind === "buy" ? "buy" : (r.act_kind === "sell" ? "sell" : "");
    const actTag = r.act_kind === "buy" ? "buy" : (r.act_kind === "sell" ? "sell" : "warn");
    return `
    <div class="card blkline ${cls}" style="--c:${c}">
      <span class="tag ${actTag}">${esc(r.action)}</span>
      <span class="tag blk" style="--c:${c}">${esc(r.block)}</span>
      <span class="tag" style="color:var(--dim)">${fmt(r.event_date)}</span>
      <div class="name">${esc(r.company_name || "")} <span class="code">${esc(r.company_code)}</span></div>
      <div class="meta">${esc(r.detail || "")}</div>
      ${noteBlock(r.src_table, { id: r.src_id, checked: r.checked, note: r.note })}
    </div>`;
  };

  const head = { "未處理": "未處理（日子已經到了）", "今天": "今天", "明天": "明天" };
  // 「今天」這組一定要畫出來，就算沒事也要 —— 空白和「抓取失敗所以空白」
  // 看起來一模一樣，要有一句話把兩者分開。
  box.innerHTML = ["未處理", "今天", "明天"]
    .filter(g => groups[g] || g === "今天").map(g => {
      const list = groups[g] || [];
      const noDisp = g === "今天" && !list.some(r => r.block_code === "disposal");
      return `<h3 style="font-size:13px;color:var(--dim);margin:14px 0 8px;letter-spacing:.08em">
       ${head[g]}　${list.length}</h3>${
        noDisp ? `<div class="empty" style="margin-bottom:8px">本日無新增處置</div>` : ""
      }${list.map(card).join("")}`;
    }).join("");
  bindRows(box);
}

// ---------- 近期行事曆 ----------
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
      <div class="name" style="font-size:16px">${esc(r.title)}</div>
      <div class="meta">${fmt(r.event_date)}</div>
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
      <div class="meta">承銷價 <b>${r.offer_price ?? "—"}</b>
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
  // 已完成（滿5日賣出已過）或勾了已處理 → 不佔版面，收進最下面摺疊區
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

  const flow = r => flowHtml([
    ["宣告拆股", r.declare_date],
    ["股東會", r.meeting_date],
    ["公告換股", r.swap_date],
    ["停止買賣", r.suspend_date],
    ["上市收盤買", r.listing_date],
    ["滿5日賣出", r.sell_date],
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
  return `
    <div class="row">
      <label class="chk">
        <input type="checkbox" data-t="${table}" data-f="checked" data-id="${r.id}"
          ${r.checked ? "checked" : ""}> 已處理
      </label>
      ${table === "signals" || table === "disposals"
        ? `<button class="small" data-ignore="${table}:${r.id}">忽略</button>` : ""}
    </div>
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
      await saveRow(t, id, { ignored: true }, "已忽略");
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

function syncDates() {
  const code = $("fStrategy").value, ev = $("fEvent").value;
  if (!ev || !code) return;
  const eff = CAL.find(c => c.strategy_code === code && c.kind === "effective" && c.event_date >= ev);
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

boot();
