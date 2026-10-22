// Officina · agent profile page.
// Opens in the centre-left pane (artifacts split stays), full screen on the phone.
// Entry points: hover card "Profile", right-click a team row, ⌘K "Profile: <agent>", route /?profile=<name>, Esc closes.
// Reads GET /api/profile?name=… · writes ONLY via POST /api/profile/perm after an explicit confirm dialog.
(() => {
  if (window.Profile) return;
  const g = (k) => { try { return eval(k) } catch (e) { return undefined } };   // index.html globals (let B, agents, cur …)
  const E = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const Q = (s) => document.querySelector(s);
  const POST = (u, b) => fetch(u, { method: "POST", body: JSON.stringify(b) });
  const say = (m) => (window.toast ? toast(m) : console.log(m));
  const LAB = (n) => n;
  const COLOR = (n) => (window.AVATAR_COLORS && AVATAR_COLORS[n]) || "#8a8478";
  const AV = (n, size, state) => (window.avatarSVG ? avatarSVG(n, { size, state: state || "idle" }) : "");
  const MINI = (n, s, size) => (window.avatarSVG ? avatarSVG(n, { mini: true, size, variant: window.avatarMiniVariant ? avatarMiniVariant(n, s.desc, s.type) : "", seed: s.id || s.desc }) : "");
  const isMob = () => matchMedia("(max-width:760px)").matches;
  const agoS = (s) => { s = Math.max(0, Math.round(s)); return s < 60 ? "now" : s < 3600 ? Math.floor(s / 60) + "m" : s < 86400 ? Math.floor(s / 3600) + "h" : Math.floor(s / 86400) + "d" };
  const dur = (s) => s == null ? "–" : s < 60 ? Math.round(s) + " s" : s < 3600 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1) + " h";
  const tok = (n) => n == null ? "" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : Math.round(n / 1000) + "k";
  const md = (t) => { try { return DOMPurify.sanitize(marked.parse(String(t || ""))) } catch (e) { return "<pre>" + E(t) + "</pre>" } };
  const LSg = (k, d) => { try { const v = localStorage.getItem("officina.pp." + k); return v == null ? d : JSON.parse(v) } catch (e) { return d } };
  const LSs = (k, v) => { try { localStorage.setItem("officina.pp." + k, JSON.stringify(v)) } catch (e) {} };
  const ROLE_FALLBACK = { "{{COORD}}": "Coordinator" };
  const IC = {
    term: '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5l3.5 3.5L3 11.5M8.5 12h4.5"/></svg>',
  };

  const P = { name: null, data: null, key: "", timer: 0, pane: null, prevCur: null, fetching: false };
  const OPEN = LSg("open", { score: true, sub: true, act: true, work: true, open: true, msgs: false, tools: false, perm: true, card: true, notes: false, mem: false });

  function pane() {
    if (P.pane) return P.pane;
    const lp = Q("#lpane"); if (!lp) return null;
    const el = document.createElement("div"); el.className = "pane"; el.id = "ppane"; el.tabIndex = -1;
    el.innerHTML = '<div class="pp-top" id="pptop"></div><div class="pp-scroll" id="ppscroll"><div class="pp-in" id="ppin"></div></div>';
    lp.appendChild(el); P.pane = el;
    el.addEventListener("click", onClick);
    el.addEventListener("toggle", (e) => { const d = e.target; if (d.tagName === "DETAILS" && d.dataset.k) { OPEN[d.dataset.k] = d.open; LSs("open", OPEN) } if (d.tagName === "DETAILS" && d.dataset.lsk) LSs(d.dataset.lsk, d.open) }, true);
    el.addEventListener("keydown", onKey);
    el.addEventListener("mouseover", (e) => { const r = e.target.closest && e.target.closest(".hz"); if (r) tipShow(r.dataset.hd, r.getBoundingClientRect()) });
    el.addEventListener("mouseout", (e) => { if (e.target.closest && e.target.closest(".pp-chart") && !(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest(".pp-chart"))) { const t = Q("#pptip"); if (t) t.style.display = "none"; document.querySelectorAll(".pp-chart .hz.on").forEach((r) => r.classList.remove("on")) } });
    Q("#ppscroll").addEventListener("scroll", navSpy, { passive: true });
    return el;
  }

  // ---------- open / close ----------
  function open(name) {
    if (!name) return;
    if (window.hcHide) try { hcHide(true) } catch (e) {}
    const p = pane(); if (!p) return;
    if (P.name !== name) { P.data = null; P.key = ""; Q("#ppin").innerHTML = '<div class="pp-empty" style="padding:60px 0">Reading ' + E(LAB(name)) + '…</div>'; Q("#ppscroll").scrollTop = 0 }
    P.name = name;
    Q("#lpane").classList.add("prof");
    if (isMob() && window.mset) mset("feed");
    { const A = g("ART"); if (A && A.max && window.artApply) { try { A.max = false; artApply() } catch (e) {} } }
    top(); fetchP(); clearInterval(P.timer); P.timer = setInterval(fetchP, 5000);
    const u = new URL(location.href); u.searchParams.set("profile", LAB(name)); history.replaceState(null, "", u);
    setTimeout(() => p.focus({ preventScroll: true }), 30);
  }
  function close(silent) {
    if (!P.name) return;
    P.name = null; clearInterval(P.timer);
    const lp = Q("#lpane"); if (lp) lp.classList.remove("prof");
    const u = new URL(location.href); if (u.searchParams.has("profile")) { u.searchParams.delete("profile"); history.replaceState(null, "", u) }
    if (!silent) { if (isMob() && window.mset) mset("team"); else if (window.show) show(g("cur") || "term") }
  }
  async function fetchP() {
    const n = P.name; if (!n || P.fetching) return; P.fetching = true;
    try {
      const r = await fetch("/api/profile?name=" + encodeURIComponent(n)); const d = await r.json();
      if (n !== P.name) return;
      if (!d.ok) { Q("#ppin").innerHTML = '<div class="pp-empty" style="padding:60px 0">No profile for ' + E(LAB(n)) + '.</div>'; return }
      const k = JSON.stringify(d); if (k === P.key) return;
      const ae = document.activeElement;
      if (P.pane.contains(ae) && /^(INPUT|SELECT|TEXTAREA)$/.test(ae.tagName) && ae.value) { P.data = d; return }   // never wipe what {{HUMAN}} types
      P.key = k; P.data = d; render();
    } catch (e) { if (!P.data) Q("#ppin").innerHTML = '<div class="pp-empty" style="padding:60px 0">Could not read the profile. The server is not answering.</div>' }
    finally { P.fetching = false }
  }

  // ---------- render ----------
  function top() {
    const n = P.name;
    Q("#pptop").innerHTML = `<button class="pp-back" data-pa="back">‹ Team</button><span class="crumb">Team / <b>${E(LAB(n))}</b> · profile</span>`
      + `<span class="pp-x"><button class="btn ghost sm pp-close" data-pa="close" title="Close profile · Esc">Close</button><kbd>esc</kbd></span>`;
  }
  const sec = (k, title, n, body, cls = "") => `<details class="pp-b ${cls}" id="pp-${k}" data-k="${k}"${OPEN[k] !== false ? " open" : ""}><summary>${title}${n != null && n !== "" ? `<span class="n">${n}</span>` : ""}</summary><div class="pp-body">${body}</div></details>`;

  function render() {
    const d = P.data; if (!d) return;
    const sc = Q("#ppscroll"), y = sc.scrollTop;
    const n = d.name, c = d.color || COLOR(n);
    P.pane.style.setProperty("--c", c);
    const st = window.agState ? agState(n) : d.state;
    const s = d.session || {}, tx = d.tx || {};
    const live = d.state === "offline" ? `<span>not running</span>` : d.live && /yes|trust|attention/i.test(d.live) ? `<span class="alert">${E(d.live)}</span>` : d.state === "working" ? `<span class="on">working</span>` : `<span>idle</span>`;
    const up = s.started ? `<span title="session started ${new Date(s.started * 1000).toLocaleString()}"><b>up</b>${agoS(Date.now() / 1000 - s.started)}</span>` : "";
    const facts = [live, up,
      s.tmux ? `<span title="tmux session"><b>tmux</b>${E(s.tmux)}</span>` : (d.where ? `<span>${E(d.where)}</span>` : ""),
      s.model ? `<span><b>model</b>${E(s.model.replace(/^claude-/, ""))}</span>` : "",
      s.ctx ? `<span class="${s.ctx > 800000 ? "alert" : s.ctx > 500000 ? "warn" : ""}" title="tokens in the live session context"><b>context</b>${tok(s.ctx)}</span>` : "",
      s.mode ? `<span title="permission mode of the session"><b>mode</b>${E(s.mode)}</span>` : ""].filter(Boolean).join("");
    const dn = (d.doing || "").replace(/^last:\s*/i, "").trim();
    const needs = d.needs && d.needs.trim() && !/^[-–—·]+$/.test(d.needs.trim());
    const hd = `<div class="pp-hd"><div class="pp-av">${AV(n, 132, st)}</div><div style="min-width:0">`
      + `<div class="pp-nm">${E(d.label)}</div><div class="pp-role">${E(d.role || ROLE_FALLBACK[n] || "agent")}${d.slug ? " · " + E(d.slug) : ""}</div>`
      + `<div class="pp-facts">${facts}</div>`
      + (dn && !/^idle\.?$/i.test(dn) ? `<div class="pp-doing">${E(dn)}</div>` : "")
      + (needs ? `<div class="pp-need">${E(d.needs)}</div>` : "")
      + `<div class="pp-acts"><button class="btn sm" data-pa="term">${isMob() ? "Open feed" : "Open terminal"}</button>`
      + `<input id="ppmsg" placeholder="${n === "{{COORD}}" ? "Message {{COORD}}…" : "Message " + E(d.label) + " via {{COORD}}…"}" autocomplete="off">`
      + `<button class="btn ghost sm" data-pa="notes"${d.notes && d.notes.exists ? "" : " disabled title=\"no notes file yet\""}>View notes</button>`
      + `<button class="btn ghost sm" data-pa="fresh" title="Ask {{COORD}} to restart this agent fresh (role card + /clear)">Fresh session</button></div>`
      + `</div></div>`;

    const op = d.open || {}, nOpen = (op.tasks || []).length + (op.cards || []).length + (needs ? 1 : 0);
    const helpersN = (d.running || []).length;
    const nav = [["open", "Open items", nOpen], ["score", "Feedback", fbN(d) || ""], ["sub", "Sub-agents", helpersN || ""], ["act", "Activity"], ["work", "Deliverables"],
      ["msgs", "Messages"], ["tools", "Tools"], ["perm", "Permissions"], ["card", "Role card"], ["notes", "Notes"], ["mem", "Memory"]];
    const navH = `<nav class="pp-nav" id="ppnav">${nav.map(([k, t, x]) => `<a data-go="${k}">${t}${x ? `<i>${x}</i>` : ""}</a>`).join("")}</nav>`;

    const body = `<div class="pp-grid">`
      + `<div class="wide">${sec("open", "Open items", nOpen || "none", openItems(d, needs))}</div>`
      + `<div class="wide">${sec("score", "Feedback", "what helps · what is needed · own trend", `${helps(d)}<div class="pp-grid pp-sgrid"><div>${score(d)}</div><div>${trend(d)}</div></div>`)}</div>`
      + `<div class="wide">${sec("act", "Activity", tx.ready === false ? "reading history…" : "", activity(d))}</div>`
      + `<div class="wide">${sec("sub", "Sub-agents", (tx.helperTotal ? tx.helperTotal + " in 7 days" : "") + (helpersN ? " · " + helpersN + " running" : ""), subs(d))}</div>`
      + `<div class="wide">${sec("work", "Deliverables", ((d.deliver || {}).artifacts || []).length + " filed · " + ((d.deliver || {}).outTotal || 0) + " in out/", work(d))}</div>`
      + `<div>${sec("msgs", "Messages", (d.msgs || []).length || "", msgs(d))}</div>`
      + `<div>${sec("tools", "Tools", (tx.tools || []).reduce((a, x) => a + x[1], 0) ? (tx.tools || []).reduce((a, x) => a + x[1], 0) + " calls · 7 days" : "", tools(d))}</div>`
      + `<div class="wide">${sec("perm", "Permissions", "", perm(d))}</div>`
      + `<div class="wide">${sec("card", "Role card", d.card && d.card.exists ? E(d.card.path) : "", card(d))}</div>`
      + `<div>${sec("notes", "Notes", d.notes && d.notes.entries ? d.notes.entries.length + " last entries" : "", notesH(d))}</div>`
      + `<div>${sec("mem", "Memory rules", (d.memory || []).length || "", mem(d))}</div>`
      + `</div>`;
    const inp = Q("#ppmsg"), v = inp ? inp.value : "", foc = document.activeElement === inp;
    Q("#ppin").innerHTML = hd + navH + body;
    if (v || foc) { const i = Q("#ppmsg"); i.value = v; if (foc) i.focus() }
    sc.scrollTop = y; navSpy();
  }

  function openItems(d, needs) {
    const op = d.open || {}; let h = "";
    if (needs) h += `<div class="pp-row"><span class="pp-pill wait">needs you</span><span class="t">${E(d.needs)}</span><span></span></div>`;
    (op.cards || []).forEach((c) => h += `<div class="pp-row click" data-card="${E(c.id)}" title="${E(c.context || "")}"><span class="pp-pill bad">question</span><span class="t">${E(c.q)}</span><span class="m">${E(c.at || "")}</span></div>`);
    (op.tasks || []).forEach((t) => h += `<div class="pp-row"><span class="pp-pill ${t.state === "blocked" ? "bad" : t.state === "waiting" ? "wait" : "info"}">${E(t.state)}</span><span class="t">${E(t.title)}</span><span class="m">${E(t.updated || "")}</span></div>`);
    if (!h) h = `<div class="pp-empty">Nothing waits on you from ${E(d.label)}. No open tasks.</div>`;
    if (op.card && op.card.md) h += `<details class="pp-mem" style="margin-top:8px"><summary><span>Its own open list <span class="d">from the role card · ${E(op.card.title)}</span></span><span class="pp-pill">show</span></summary><div class="pp-md">${md(op.card.md)}</div></details>`;
    return h;
  }

  const pct = (x) => x == null || x === "" || isNaN(+x) ? null : (+x <= 10 ? +x * 10 : +x);      // peers / {{HUMAN}} come as 1–10, formula as 0–100
  // ---------- what helps / what is needed (first: feedback, not a contest) ----------
  const vName = (v) => v;
  const vAv = (v) => v === "{{HUMAN}}" ? `<span class="pp-eav" title="{{HUMAN}}">{{HUMAN_INITIAL}}</span>` : `<span class="tav">${AV(vName(v), 18, "idle")}</span>`;
  function fbList(d) {
    let f = (d.feedback || []).filter((x) => x && (x.helped || x.needs));
    if (!f.length && d.score) f = (d.score.votes || []).filter((v) => v && v.voter && (v.why || v.helped || v.needs)).map((v) => ({ voter: v.voter, helped: v.helped || v.why || "", needs: v.needs || "" }));
    return f;
  }
  function techNeeds(d) {            // -> [[group, [text…]]]  accepts list of strings, list of objects, or {group: [..]}
    const n = d.techNeeds || (d.score && d.score.needs); if (!n) return [];
    const txt = (x) => typeof x === "string" ? x : x && (x.text || x.need || x.proposal || x.title || x.what) || "";
    const g = {};
    const add = (k, x) => { const t = txt(x); if (t) (g[k] = g[k] || []).push(t + (x && x.count > 1 ? ` (${x.count}×)` : "")) };
    if (Array.isArray(n)) n.forEach((x) => add(typeof x === "string" ? "Proposals" : (x.group || x.kind || x.type || "Proposals"), x));
    else if (typeof n === "object") Object.entries(n).forEach(([k, v]) => (Array.isArray(v) ? v : [v]).forEach((x) => add(k, x)));
    else if (typeof n === "string") add("Proposals", n);
    return Object.entries(g);
  }
  const fbN = (d) => fbList(d).length + techNeeds(d).reduce((a, [, v]) => a + v.length, 0);
  function helps(d) {
    const f = fbList(d), tn = techNeeds(d), nm = (k) => k.replace(/_/g, " ").replace(/^\w/, (x) => x.toUpperCase());
    const row = (x, t) => `<div class="pp-fb">${vAv(x.voter)}<span class="w"><b>${E(LAB(x.voter))}</b>${E(t)}</span>${x.day && x.day !== (d.hist || {}).today ? `<span class="dd">${E(x.day.slice(8) + "/" + x.day.slice(5, 7))}</span>` : ""}</div>`;
    const needs = f.filter((x) => x.needs), helped = f.filter((x) => x.helped);
    const col = (title, sub, inner, empty) => `<div><div class="pp-k">${title} <span class="pp-ks">${sub}</span></div>${inner || `<div class="pp-empty">${empty}</div>`}</div>`;
    let h = `<div class="pp-helps">`
      + col("What is needed", "tools · context · from peers and {{HUMAN}}", needs.map((x) => row(x, x.needs)).join("")
        + (tn.length ? tn.map(([k, v]) => `<div class="pp-tn"><div class="g">Tech · ${E(nm(k))}</div><ul class="pp-tips">${v.map((t) => `<li>${E(t)}</li>`).join("")}</ul></div>`).join("") : ""),
        "Nothing asked yet. Peers and {{HUMAN}} add it with their daily note.")
      + col("What helped", "keep doing", helped.map((x) => row(x, x.helped)).join(""), "No notes yet.")
      + `</div>`;
    return h;
  }

  function score(d) {
    const s = d.score;
    let h = "";
    const mv = d.myVote || {}, dr = P.voteDraft && P.voteDraft.name === d.name ? P.voteDraft : null, cur = dr ? dr.score : mv.score;
    const rate = `<div class="pp-k">Your note today${mv.score ? ` · saved ${E(mv.score)}/10${mv.at ? " at " + E(mv.at) : ""}` : ""}</div>`
      + `<div class="pp-rate" role="radiogroup" aria-label="your rating 1 to 10">${[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((k) => `<button data-rate="${k}" role="radio" aria-checked="${cur === k}" class="${cur === k ? "on" : ""}${cur && k <= cur ? " in" : ""}">${k}</button>`).join("")}</div>`
      + `<form class="pp-add pp-vf" id="ppvote"><input id="pphelped" placeholder="What helped (optional), e.g. clear drawing list" autocomplete="off" value="${E(dr ? dr.helped || "" : mv.helped || mv.why || "")}"><input id="ppneeds" placeholder="What does ${E(LAB(d.name))} need? (optional), e.g. the bolt catalogue" autocomplete="off" value="${E(dr ? dr.needs || "" : mv.needs || "")}"><button class="btn" type="submit"${cur ? "" : " disabled"}>${mv.score ? "Update note" : "Save note"}</button></form>`
      + `<div class="pp-hint">One note per agent per day; a new one replaces it. The rating counts 20 % of the own trend.</div>`;

    if (!s) h = `<div class="pp-empty"><b>No trend yet.</b> The Tech agent writes scores to scores.json in the office folder. {{COORD}} asks Tech for the first one.</div>` + rate;
    else {
      const tr = +s.trend || 0, cls = tr > 0 ? "up" : tr < 0 ? "down" : "same";
      const arrow = tr > 0 ? "+" + tr : tr < 0 ? "−" + Math.abs(tr) : "same";
      const lv = (v) => v >= 75 ? "hi" : v >= 55 ? "mid" : "lo";
      const nm = (k) => k.replace(/_/g, " ").replace(/^\w/, (x) => x.toUpperCase());
      const f = pct(s.formula), pe = pct(s.peers), er = pct(s.human);
      const parts = f != null || pe != null || er != null;
      const seg = (v, w, c, t) => v == null ? "" : `<i style="width:${(v * w).toFixed(2)}%;background:${c}" title="${t}"></i>`;
      h += `<div class="pp-k">Own trend <span class="pp-ks">this agent against itself${s.updated ? " · Tech " + E(s.updated) : ""}</span></div>`
        + `<div class="pp-score"><div><div class="pp-big">${E(s.overall ?? "–")}<small>/100</small></div><div class="pp-trend" title="own value last week">${arrow} vs own last week</div></div><div>`
        + (parts ? `<div class="pp-stack">${seg(f, .5, "var(--c)", "Tech formula × 50 %")}${seg(pe, .3, "var(--info)", "Peer votes × 30 %")}${seg(er, .2, "var(--ink)", "{{HUMAN}} × 20 %")}</div>`
          + `<div class="pp-parts"><span><i style="background:var(--c)"></i>Formula <b>${f ?? "–"}</b><em>50 %</em></span><span><i style="background:var(--info)"></i>Peers <b>${s.peers ?? "–"}</b><em>30 %</em></span><span><i style="background:var(--ink)"></i>{{HUMAN}} <b>${s.human ?? "–"}</b><em>20 %</em></span></div>`
          : `<div class="pp-bar ${lv(+s.overall || 0)}" style="height:8px"><i style="width:${Math.max(0, Math.min(100, +s.overall || 0))}%"></i></div>`)
        + `</div></div>`;
      h += rate;
      const mets = Object.entries(s.metrics || {}).map(([k, m]) => { const v = Math.max(0, Math.min(100, +(m && m.score) || 0));
        return `<div class="pp-m"><div class="pp-mh"><span>${E(nm(k))}</span><b>${v}</b></div><div class="pp-bar ${lv(v)}"><i style="width:${v}%"></i></div>${m && m.evidence ? `<div class="pp-ev">${E(m.evidence)}</div>` : ""}</div>` }).join("");
      if (mets) h += `<details class="pp-mem" style="margin-top:10px"${LSg("metsOpen", false) ? " open" : ""} data-lsk="metsOpen"><summary><span>Formula sub-scores <span class="d">Tech's evidence per metric</span></span><span class="pp-pill">${Object.keys(s.metrics || {}).length}</span></summary>${mets}</details>`;
      if (s.tips && s.tips.length) h += `<div class="pp-k">Tips from Tech</div><ul class="pp-tips">${s.tips.slice(0, 3).map((t) => `<li>${E(t)}</li>`).join("")}</ul>`;
    }
    return h;
  }

  function strip(arr, cells, labels) {
    const mx = Math.max(1, ...arr);
    return `<div class="pp-strip" style="grid-template-columns:repeat(${cells},minmax(0,1fr))">${arr.map((v, i) => `<i class="${v ? (v > mx * .66 ? "b3" : v > mx * .33 ? "b2" : "b1") : ""}"></i>`).join("")}</div><div class="pp-axis">${labels.map((l) => `<span>${l}</span>`).join("")}</div>`;
  }
  function activity(d) {
    const tx = d.tx || {}, day = tx.day || [], wk = tx.week || [];
    const busyH = (day.filter((x) => x).length * 10 / 60).toFixed(1);
    const now = new Date(), dl = [];
    for (let i = 6; i >= 0; i--) { const t = new Date(now - i * 86400000); dl.push(i === 0 ? "today" : t.toLocaleDateString("en-GB", { weekday: "short" })) }
    const hh = (h) => { const t = new Date(now - h * 3600000); return String(t.getHours()).padStart(2, "0") + ":00" };
    const steps = (tx.steps || []).slice(0, 10).map((x) => `<em>${agoS(Date.now() / 1000 - x.ts)}</em><b>${E(x.tool)}</b><span title="${E(x.text)}">${E(x.text)}</span>`).join("");
    return `<div class="pp-k" style="margin-top:0">Last 24 h · busy about ${busyH} h</div>${strip(day, 144, [hh(24), hh(18), hh(12), hh(6), "now"])}`
      + `<div class="pp-k">Last 7 days</div>${strip(wk, 168, dl)}`
      + `<div class="pp-k">Last 10 steps</div>` + (steps ? `<div class="pp-steps">${steps}</div>` : `<div class="pp-empty">No steps in the last 7 days.</div>`);
  }

  function subs(d) {
    const n = d.name, run = d.running || [], tx = d.tx || {}, hl = tx.helpers || [];
    let h = `<div class="pp-k" style="margin-top:0">Running now</div>`;
    h += run.length ? run.map((s) => `<div class="pp-h">${MINI(n, s, 20)}<span class="t" title="${E(s.desc)}">${E(s.desc)}</span><span class="m">${E(s.type || "")}</span><span class="m">${agoS(Date.now() / 1000 - s.since)}</span></div>`).join("")
      : `<div class="pp-empty">No helper runs now.</div>`;
    h += `<div class="pp-k">Last 7 days · description · runs · avg time · avg tokens · last</div>`;
    h += hl.length ? hl.slice(0, 14).map((s) => `<div class="pp-h" title="${E(s.type || "")}${s.fail ? " · " + s.fail + " stopped/failed" : ""}">${MINI(n, s, 20)}<span class="t">${E(s.desc)}${s.fail ? ` <span class="pp-pill bad">${s.fail} stopped</span>` : ""}</span><span class="cnt">${s.count}×</span><span class="m">${dur(s.avg)}${s.avgTokens ? " · " + tok(s.avgTokens) : ""} · ${agoS(Date.now() / 1000 - s.last)}</span></div>`).join("")
      + (hl.length > 14 ? `<div class="pp-empty" style="padding-top:6px">+${hl.length - 14} more kinds</div>` : "")
      : `<div class="pp-empty">${tx.ready === false ? "Reading its transcript…" : "No sub-agents in the last 7 days."}</div>`;
    if ((d.personas || []).length) h += `<div class="pp-k">Reviewer personas (role card)</div><div class="pp-chips">${d.personas.map((p) => `<span class="pp-chip" title="${E(p.what)}">${E(p.name)}</span>`).join("")}</div>`;
    if (d.subcard && d.subcard.md) h += `<details class="pp-mem" style="margin-top:10px"><summary><span>Its helper kinds <span class="d">from the role card · ${E(d.subcard.title)}</span></span><span class="pp-pill">show</span></summary><div class="pp-md">${md(d.subcard.md)}</div></details>`;
    return h;
  }

  const KIND = (p) => { const e = (String(p).match(/\.([a-z0-9]{2,4})$/i) || [, ""])[1].toLowerCase(); return e };
  function work(d) {
    const w = d.deliver || {}; let h = "";
    const pill = (s) => { s = String(s || ""); const l = s.toLowerCase(); const c = /supersed/.test(l) ? "" : /sent|filed|pass|issued/.test(l) ? "ok" : /approval|wait|hold|ready/.test(l) ? "wait" : "info"; return `<span class="pp-pill ${c}" title="${E(s)}">${E(s.length > 26 ? s.slice(0, 25) + "…" : s || "–")}</span>` };
    h += `<div class="pp-k" style="margin-top:0">Filed artifacts it worked on</div>`;
    h += (w.artifacts || []).length ? w.artifacts.map((a) => `<div class="pp-row click" data-open="${E(a.path || "")}" data-url="${E(a.url || "")}" data-title="${E(a.title)}"><span class="pp-pill">${E(KIND(a.path) || "dir")}</span><span class="t" title="${E(a.title)}">${E(a.title)}</span>${pill(a.status)}</div>`).join("")
      : `<div class="pp-empty">No filed artifact matches its files in the last 7 days.</div>`;
    h += `<div class="pp-k">Newest in its out/ folders</div>`;
    h += (w.out || []).length ? w.out.map((f) => `<div class="pp-row click" data-open="${E(f.path)}" data-title="${E(f.path.split("/").pop())}"><span class="pp-pill">${E(KIND(f.path))}</span><span class="t" title="${E(f.path)}">${E(f.path.split("/").pop())} <span class="s">· ${E(f.task)}</span></span><span class="m">${agoS(Date.now() / 1000 - f.mtime)}</span></div>`).join("")
      : `<div class="pp-empty">No out/ folder for this agent.</div>`;
    return h;
  }

  function msgs(d) {
    const L = d.msgs || [];
    if (!L.length) return `<div class="pp-empty">No messages with peers in the last 7 days.</div>`;
    return L.slice(0, 14).map((m) => `<div class="pp-msg" title="${E(m.text)}"><i>${m.dir === "out" ? "↗" : "↙"}</i><span class="tav">${AV(m.peer, 20, "idle")}</span><span class="t">${m.dir === "out" ? "to" : "from"} ${E(LAB(m.peer))} · ${E(m.text)}</span><em>${agoS(Date.now() / 1000 - m.ts)}</em></div>`).join("");
  }

  function tools(d) {
    const tx = d.tx || {}, t = tx.tools || [], m = tx.mcp || [];
    if (!t.length) return `<div class="pp-empty">No tool calls in the last 7 days.</div>`;
    const mx = Math.max(...t.map((x) => x[1]));
    const nm = (k) => k.startsWith("mcp__") ? k.split("__").slice(1).join(" · ").replace(/claude_ai_/g, "").replace(/_/g, " ") : k;
    let h = t.slice(0, 10).map(([k, v]) => `<div class="pp-tool"><span title="${E(k)}">${E(nm(k))}</span><div class="pp-bar"><i style="width:${(v / mx * 100).toFixed(1)}%"></i></div><b>${v}</b></div>`).join("");
    if (m.length) h += `<div class="pp-k">Connectors (MCP)</div><div class="pp-chips">${m.map(([k, v]) => `<span class="pp-chip">${E(k.replace(/claude_ai_/, "").replace(/_/g, " "))} · ${v}</span>`).join("")}</div>`;
    return h;
  }

  function perm(d) {
    const p = d.perm || {}, ov = p.overrides || { allow: [], deny: [] };
    const lvl = (l) => `<span class="pp-lv ${l}">${l.toUpperCase()}</span>`;
    const groups = {}; (p.rules || []).forEach((r) => (groups[r.group] = groups[r.group] || []).push(r));
    const order = ["Files", "Shell", "Web", "Connectors", "Agents", "Other", "Not a rule"];
    let eff = order.filter((k) => groups[k]).map((k) => `<div class="pp-pg">${E(k)}</div>` + groups[k].map((r) => `<div class="pp-perm${r.valid ? "" : " bad"}">${lvl(r.list)}<div style="min-width:0"><span class="p">${E(r.plain)}</span><span class="r" title="${E(r.rule)}">${E(r.rule)}</span></div><span class="src" title="${E(r.file)}">${E(r.src.split(" · ")[0])}</span></div>`).join("")).join("");
    if (!eff) eff = `<div class="pp-empty">No allow / deny rules in your settings files.</div>`;
    const modeTxt = { auto: "auto: the safety classifier decides each step; risky steps still need a Yes", default: "default: asks before risky steps", acceptEdits: "accept edits: file edits without asking", plan: "plan: read only", bypassPermissions: "bypass: no questions (not recommended)" };
    const md0 = (d.session || {}).mode || p.defaultMode;
    const top = `<div class="pp-hint" style="margin-top:0">These rules apply to <b>every</b> agent. ${md0 ? `Session mode — ${E(modeTxt[md0] || md0)}.` : ""} ${p.dirs && p.dirs.length ? `Extra folders it can reach: ${p.dirs.map((x) => `<code>${E(x)}</code>`).join(" ")}.` : ""} Read only here: edit the settings files yourself if you need a change for all agents.</div>`;
    const ovRow = (r, list) => `<div class="pp-perm${r.valid ? "" : " bad"}">${lvl(list)}<div style="min-width:0"><span class="p">${E(r.plain)}</span><span class="r">${E(r.rule)}</span></div><button class="x" data-prm="${E(list)}" data-rule="${E(r.rule)}" title="Remove this rule (asks first)" aria-label="remove rule">×</button></div>`;
    const ovs = (ov.allow || []).map((r) => ovRow(r, "allow")).join("") + (ov.deny || []).map((r) => ovRow(r, "deny")).join("");
    const hard = p.hard && p.hard.md ? `<div class="pp-md">${md(p.hard.md)}</div>` : `<div class="pp-empty">No "Hard rules" section in its role card${d.card && d.card.exists ? "" : " (no role card yet)"}.</div>`;
    return `<div class="pp-grid"><div>`
      + `<div class="pp-k" style="margin-top:0">Only for ${E(d.label)} · overrides</div>`
      + (ovs || `<div class="pp-empty">No overrides. ${E(d.label)} uses the shared rules only.</div>`)
      + `<form class="pp-add" id="ppadd"><select id="pplist" aria-label="list"><option value="allow">Allow</option><option value="deny">Deny</option></select><input id="pprule" placeholder="Bash(git status:*)  ·  Read(~/Documents/**)  ·  mcp__rhino" autocomplete="off" spellcheck="false"><button class="btn ghost" type="submit">Add…</button></form>`
      + `<div class="pp-hint">You confirm each change. It goes only to <code>${E(ov.path || "")}</code> and works at the agent's <b>next restart</b>. Nothing is added by itself.</div>`
      + (p.log && p.log.length ? `<div class="pp-k">Recent changes</div><pre class="pp-log">${E(p.log.join("\n"))}</pre>` : "")
      + `<div class="pp-k">Hard rules (role card)</div>${hard}`
      + `</div><div><div class="pp-k" style="margin-top:0">Shared rules · effective now</div>${top}${eff}</div></div>`;
  }

  function card(d) {
    const c = d.card || {};
    if (!c.exists) return `<div class="pp-empty"><b>No role card yet.</b> {{COORD}} asks ${E(d.label)} to write <code>${E(c.path || "")}</code>.</div>`;
    const long = (c.md || "").length > 2500 && !P.cardAll;
    return `<div class="pp-md${long ? " clamp" : ""}">${md(c.md)}</div>` + (long ? `<button class="btn ghost sm pp-more" data-pa="cardall">Show all</button>` : "")
      + (c.mtime ? `<div class="pp-hint">Updated ${agoS(Date.now() / 1000 - c.mtime)} ago</div>` : "");
  }
  function notesH(d) {
    const nt = d.notes || {};
    if (!nt.exists) return `<div class="pp-empty">No notes file yet (<code>${E((nt.path || "").replace(/^\/Users\/[^/]+/, "~"))}</code>).</div>`;
    return (nt.entries || []).map((e) => `<div class="pp-note pp-md">${md(e)}</div>`).join("") || `<div class="pp-empty">The notes file is empty.</div>`;
  }
  function mem(d) {
    const L = d.memory || [];
    if (!L.length) return `<div class="pp-empty">No memory rules named in its role card.</div>`;
    return L.map((m) => `<details class="pp-mem"><summary><span style="min-width:0">${E(m.title)}<span class="d">${E(m.desc || (m.exists ? "" : "file not found"))}</span></span><span class="pp-pill${m.from === "card" ? " info" : ""}">${m.from === "card" ? "card" : "mentions"}</span></summary>${m.body ? `<div class="pp-md">${md(m.body)}</div>` : ""}</details>`).join("");
  }


  // ---------- score history chart (inline SVG, flat) ----------
  const dayList = (n) => { const out = [], t = new Date(); t.setHours(12, 0, 0, 0); for (let i = n - 1; i >= 0; i--) { const d = new Date(t - i * 86400000); out.push(d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0")) } return out };
  const dShort = (k) => { const d = new Date(k + "T12:00:00"); return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric" }) };
  function linePath(vals, X, Y) { let p = "", pen = false; vals.forEach((v, i) => { if (v == null) { pen = false; return } p += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); pen = true }); return p }
  const teamOrder = (t) => Object.entries(t).sort((a, b) => LAB(a[0]).localeCompare(LAB(b[0])));
  function trend(d) {
    const H = d.hist || {}, pts = H.points || [], n = LSg("range", 7), days = dayList(n), by = {}; pts.forEach((p) => by[p.day] = p);
    const rng = `<span class="pp-seg">${[7, 30].map((k) => `<button data-range="${k}" class="${k === n ? "on" : ""}">${k} d</button>`).join("")}</span>`;
    if (!pts.length && !(H.team && Object.keys(H.team).length)) return `<div class="pp-k" style="margin-top:0">Own trend · daily ${rng}</div><div class="pp-empty">No daily history yet. Tech keeps it in ~/.claude/office/scores-history.json. The line starts with the first day.</div>`;
    const W = 440, Ht = 150, L = 26, R = 10, T = 10, B = 22, X = (i) => L + (days.length === 1 ? 0 : i * (W - L - R) / (days.length - 1)), Y = (v) => T + (100 - v) * (Ht - T - B) / 100;
    const c = d.color || COLOR(d.name), met = P.metric && pts.some((p) => p.metrics && p.metrics[P.metric] != null) ? P.metric : null;
    let s = `<svg class="pp-chart" viewBox="0 0 ${W} ${Ht}" role="img" aria-label="daily trend, last ${n} days">`;
    [0, 25, 50, 75, 100].forEach((v) => s += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" class="gl"/><text x="${L - 6}" y="${Y(v) + 3.5}" class="ax" text-anchor="end">${v}</text>`);
    const step = n > 10 ? 5 : 1;
    days.forEach((k, i) => { if ((days.length - 1 - i) % step === 0) s += `<text x="${X(i)}" y="${Ht - 6}" class="ax${i === days.length - 1 ? " td" : ""}" text-anchor="middle">${i === days.length - 1 ? "today" : n > 10 ? k.slice(8) + "/" + k.slice(5, 7) : dShort(k).split(" ")[0]}</text>` });
    if (H.team && Object.keys(H.team).length && LSg("teamview", true)) {          // {{COORD}}'s profile: team comparison
      teamOrder(H.team).forEach(([nm, arr]) => { const m = {}; arr.forEach((p) => m[p.day] = p.overall); const v = days.map((k) => m[k] ?? null);
        s += `<path d="${linePath(v, X, Y)}" fill="none" stroke="${COLOR(nm)}" stroke-width="1.8" stroke-linejoin="round"/>`;
        const li = v.map((x, i) => x == null ? -1 : i).filter((i) => i >= 0).pop(); if (li != null && li >= 0) s += `<circle cx="${X(li)}" cy="${Y(v[li])}" r="2.6" fill="${COLOR(nm)}"/>` });
    } else {
      const v = days.map((k) => by[k] ? by[k].overall : null);
      if (met) s += `<path d="${linePath(days.map((k) => by[k] && by[k].metrics ? by[k].metrics[met] ?? null : null), X, Y)}" fill="none" stroke="var(--ink2)" stroke-width="1.4" stroke-dasharray="4 3"/>`;
      if (LSg("parts", true)) [["formula", "var(--c)"], ["peers", "var(--info)"], ["human", "var(--ink)"]].forEach(([k, col]) => { const v = days.map((dd) => by[dd] ? pct(by[dd][k]) : null); if (v.some((x) => x != null)) s += `<path d="${linePath(v, X, Y)}" fill="none" stroke="${col}" stroke-width="1" opacity=".75"/>` });
      s += `<path d="${linePath(v, X, Y)}" fill="none" stroke="${c}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="square"/>`;
      v.forEach((x, i) => { if (x == null) return; const td = i === days.length - 1; s += td ? `<rect x="${X(i) - 5}" y="${Y(x) - 5}" width="10" height="10" fill="${c}"/><rect x="${X(i) - 8.5}" y="${Y(x) - 8.5}" width="17" height="17" fill="none" stroke="${c}" stroke-width="1.2"/>` : `<rect x="${X(i) - 2.8}" y="${Y(x) - 2.8}" width="5.6" height="5.6" fill="#fff" stroke="${c}" stroke-width="1.6"/>` });
    }
    const cw = (W - L - R) / Math.max(1, days.length - 1);
    days.forEach((k, i) => s += `<rect class="hz" data-hd="${k}" x="${X(i) - cw / 2}" y="0" width="${cw}" height="${Ht}"/>`);
    s += `</svg>`;
    const teamTog = H.team && Object.keys(H.team).length ? `<span class="pp-seg"><button data-tv="1" class="${LSg("teamview", true) ? "on" : ""}">Team</button><button data-tv="0" class="${LSg("teamview", true) ? "" : "on"}">{{COORD}}</button></span>` : "";
    const legend = H.team && LSg("teamview", true) ? `<div class="pp-legend">${teamOrder(H.team).map(([nm]) => `<span><i style="background:${COLOR(nm)}"></i>${E(LAB(nm))}</span>`).join("")}</div>` : "";
    const keys = [...new Set(pts.flatMap((p) => Object.keys(p.metrics || {})))];
    const sm = keys.length && !(H.team && LSg("teamview", true)) ? `<div class="pp-sm">${keys.map((k) => { const v = days.map((dd) => by[dd] && by[dd].metrics ? by[dd].metrics[k] ?? null : null), last = v.filter((x) => x != null).pop();
        const w = 120, h = 26, sx = (i) => days.length === 1 ? w : i * w / (days.length - 1), sy = (x) => 2 + (100 - x) * (h - 4) / 100;
        return `<button class="pp-mini${met === k ? " on" : ""}" data-met="${E(k)}" title="show ${E(k.replace(/_/g, " "))} on the chart"><span class="l">${E(k.replace(/_/g, " "))}</span><b>${last ?? "–"}</b><svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path d="${linePath(v, sx, sy)}" fill="none" stroke="${c}" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg></button>` }).join("")}</div>` : "";
    const hasParts = pts.some((p) => p.formula != null || p.peers != null || p.human != null) && !(H.team && LSg("teamview", true));
    const partsTog = hasParts ? `<span class="pp-seg"><button data-parts="1" class="${LSg("parts", true) ? "on" : ""}" title="thin lines: formula · peers · {{HUMAN}}">Parts</button></span>` : "";
    const tv = H.team && Object.keys(H.team).length && LSg("teamview", true);
    return `<div class="pp-k" style="margin-top:0;display:flex;align-items:center;gap:8px">${tv ? "Team trend" : "Own trend · daily"}${met ? ` · <span style="text-transform:none;letter-spacing:0">dashed = ${E(met.replace(/_/g, " "))}</span>` : ""}<span style="margin-left:auto;display:flex;gap:6px">${partsTog}${teamTog}${rng}</span></div>`
      + `<div class="pp-cw">${s}<div class="pp-tip" id="pptip"></div></div>${legend}${sm}`;
  }
  function tipShow(k, rect) {
    const d = P.data; if (!d) return; const H = d.hist || {}, p = (H.points || []).find((x) => x.day === k), tip = Q("#pptip"); if (!tip) return;
    let h = `<b>${E(dShort(k))}${k === H.today ? " · today" : ""}</b>`;
    if (H.team && LSg("teamview", true)) { const rows = Object.entries(H.team).map(([nm, a]) => [nm, (a.find((x) => x.day === k) || {}).overall]).filter((x) => x[1] != null).sort((a, b) => LAB(a[0]).localeCompare(LAB(b[0])));
      h += rows.length ? rows.map(([nm, v]) => `<div class="r"><span>${E(LAB(nm))}</span><span>${v}</span></div>`).join("") : `<div class="e">no score this day</div>` }
    else if (!p) h += `<div class="e">no score this day</div>`;
    else { h += `<div class="r big"><span>Overall</span><span>${p.overall}</span></div>` + ["formula", "peers", "human"].filter((k) => p[k] != null).map((k) => `<div class="r"><span>${k === "human" ? "{{HUMAN}}" : k}</span><span>${p[k]}</span></div>`).join("") + Object.entries(p.metrics || {}).map(([m, v]) => `<div class="r"><span>${E(m.replace(/_/g, " "))}</span><span>${v ?? "–"}</span></div>`).join("");
      const ev = Object.entries(p.evidence || {}); if (ev.length) h += `<div class="ev">${ev.slice(0, 3).map(([m, t]) => `<div>${E(t)}</div>`).join("")}</div>`;
      if ((p.tips || []).length) h += `<div class="ev tips">${p.tips.slice(0, 2).map((t) => `<div>→ ${E(t)}</div>`).join("")}</div>` }
    tip.innerHTML = h; tip.style.display = "block";
    const box = tip.parentElement.getBoundingClientRect(); let x = rect.left - box.left + rect.width / 2 + 10; if (x + tip.offsetWidth > box.width) x = rect.left - box.left + rect.width / 2 - tip.offsetWidth - 10;
    tip.style.left = Math.max(0, x) + "px"; tip.style.top = "6px";
    tip.parentElement.querySelectorAll(".hz").forEach((r) => r.classList.toggle("on", r.dataset.hd === k));
  }

  // ---------- section nav ----------
  function navSpy() {
    const sc = Q("#ppscroll"), nav = Q("#ppnav"); if (!sc || !nav) return;
    const y = sc.getBoundingClientRect().top + nav.offsetHeight + 12; let on = null;
    nav.querySelectorAll("a").forEach((a) => { const s = document.getElementById("pp-" + a.dataset.go); if (s && s.getBoundingClientRect().top <= y) on = a.dataset.go });
    nav.querySelectorAll("a").forEach((a) => a.classList.toggle("on", a.dataset.go === on));
  }
  function go(k) {
    const s = document.getElementById("pp-" + k); if (!s) return; if (!s.open) s.open = true;
    const sc = Q("#ppscroll"); sc.scrollTo({ top: s.offsetTop - Q("#ppnav").offsetHeight - 4, behavior: "smooth" });
  }

  // ---------- confirm dialog ----------
  function confirmBox({ title, lines, code, ok, danger }) {
    return new Promise((res) => {
      const w = document.createElement("div"); w.className = "pp-dlg"; w.setAttribute("role", "dialog"); w.setAttribute("aria-modal", "true");
      w.innerHTML = `<div class="pp-dbox"><h3>${E(title)}</h3>${code ? `<pre>${E(code)}</pre>` : ""}${lines.map((l) => `<p>${l}</p>`).join("")}<div class="row"><button class="btn ghost" data-r="0">Cancel</button><button class="btn${danger ? "" : ""}" data-r="1">${E(ok)}</button></div></div>`;
      const done = (v) => { w.remove(); document.removeEventListener("keydown", kd, true); res(v) };
      const kd = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); done(false) } };
      w.addEventListener("click", (e) => { const b = e.target.closest("[data-r]"); if (b) done(b.dataset.r === "1"); else if (e.target === w) done(false) });
      document.addEventListener("keydown", kd, true); document.body.appendChild(w); w.querySelector('[data-r="0"]').focus();   // Cancel has focus: Enter never confirms by accident
    });
  }
  async function permChange(op, list, rule) {
    const d = P.data; if (!d) return;
    const ok = await confirmBox({
      title: `${op === "add" ? "Add" : "Remove"} ${list.toUpperCase()} rule for ${d.label}?`, code: rule, ok: op === "add" ? "Add rule" : "Remove rule",
      lines: [op === "add" ? (list === "allow" ? `${E(d.label)} may do this without asking.` : `${E(d.label)} may never do this.`) : `This rule goes away for ${E(d.label)}.`,
        `File: <code>${E((d.perm.overrides || {}).path || "")}</code> (only this agent).`, "It works at the agent's next restart. {{COORD}} gets a note."]
    });
    if (!ok) return false;
    const r = await POST("/api/profile/perm", { slug: d.slug, op, list, rule, confirmed: true }); let j = {}; try { j = await r.json() } catch (e) {}
    if (!r.ok || !j.ok) { say(j.error || "Could not save the rule"); return false }
    say(j.same ? "No change: the rule was already like that" : (op === "add" ? "Rule added · works at next restart" : "Rule removed · works at next restart"));
    P.key = ""; fetchP(); return true;
  }

  // ---------- events ----------
  async function onClick(e) {
    const a = e.target.closest("[data-pa]");
    if (a) {
      const k = a.dataset.pa, n = P.name;
      if (k === "close" || k === "back") return close();
      if (k === "term") { const nn = n; close(true); if (window.openMember) openMember(nn); else if (window.show) show(nn === "{{COORD}}" ? "term" : nn); return }
      if (k === "notes" && P.data && P.data.notes && P.data.notes.exists) { if (window.openArt) openArt(P.data.notes.path, LAB(n) + " notes"); return }
      if (k === "cardall") { P.cardAll = true; render(); return }
      if (k === "fresh") {
        const ok = await confirmBox({ title: `Fresh session for ${LAB(n)}?`, ok: "Ask {{COORD}}", lines: [`{{COORD}} saves the open items, updates the role card, then clears ${E(LAB(n))} and briefs it again.`, "Nothing happens without {{COORD}}. You see the result in the chat."] });
        if (!ok) return; const r = await POST("/api/say", { text: `[profile] {{HUMAN}} asks: fresh session for ${LAB(n)} (save open items, role card, /clear, re-brief).` });
        say(r.ok ? "Asked {{COORD}} for a fresh " + LAB(n) : "Could not send"); return
      }
    }
    const rt = e.target.closest("[data-rate]"); if (rt) { const a = Q("#pphelped"), b = Q("#ppneeds"); P.voteDraft = { name: P.name, score: +rt.dataset.rate, helped: a ? a.value : "", needs: b ? b.value : "" }; render(); const w2 = Q("#pphelped"); if (w2) w2.focus(); return }
    const rg = e.target.closest("[data-range]"); if (rg) { LSs("range", +rg.dataset.range); render(); return }
    const pa = e.target.closest("[data-parts]"); if (pa) { LSs("parts", !LSg("parts", true)); render(); return }
    const tv = e.target.closest("[data-tv]"); if (tv) { LSs("teamview", tv.dataset.tv === "1"); render(); return }
    const mt = e.target.closest("[data-met]"); if (mt) { P.metric = P.metric === mt.dataset.met ? null : mt.dataset.met; render(); return }
    const go_ = e.target.closest("[data-go]"); if (go_) { e.preventDefault(); return go(go_.dataset.go) }
    const x = e.target.closest("[data-prm]"); if (x) return permChange("remove", x.dataset.prm, x.dataset.rule);
    const o = e.target.closest("[data-open]");
    if (o) { const p = o.dataset.open; if (p && window.openArt) openArt(p, o.dataset.title); else if (o.dataset.url) window.open(o.dataset.url); return }
    const c = e.target.closest("[data-card]"); if (c && window.flash) { close(); setTimeout(() => flash(document.querySelector("#fy li.q") || null), 80) }
  }
  async function onKey(e) {
    if (e.target.id === "ppmsg" && e.key === "Enter" && e.target.value.trim()) {
      const n = P.name, t = e.target.value.trim(); const r = await POST("/api/say", n === "{{COORD}}" ? { text: t } : { text: t, to: n });
      if (r.ok) { e.target.value = ""; say(n === "{{COORD}}" ? "Sent to {{COORD}}" : "Sent to {{COORD}} → " + LAB(n)) } else say("Could not send"); return
    }
    if (e.target.id === "ppmsg" && e.key === "Escape") { e.target.value = ""; e.target.blur(); return }
  }
  document.addEventListener("submit", async (e) => {
    if (e.target.id !== "ppvote") return; e.preventDefault();
    const d = P.data, sc = P.voteDraft && P.voteDraft.name === P.name ? P.voteDraft.score : (d.myVote || {}).score; if (!sc) return;
    const helped = (Q("#pphelped") || {}).value || "", needs = (Q("#ppneeds") || {}).value || "";
    const r = await POST("/api/profile/vote", { name: P.name, score: sc, helped, needs }); let j = {}; try { j = await r.json() } catch (x) {}
    if (r.ok && j.ok) { say(`Note for ${LAB(P.name)} saved`); P.voteDraft = null; document.activeElement && document.activeElement.blur && document.activeElement.blur(); P.key = ""; fetchP() } else say("Could not save the rating");
  }, true);
  document.addEventListener("submit", (e) => {
    if (e.target.id !== "ppadd") return; e.preventDefault();
    const rule = Q("#pprule").value.trim(), list = Q("#pplist").value; if (!rule) { Q("#pprule").focus(); return }
    if (!/^[A-Za-z_][\w.-]*(\(.+\))?$/.test(rule)) { say("Use Tool or Tool(pattern), e.g. Bash(git status:*)"); Q("#pprule").focus(); return }
    permChange("add", list, rule).then((ok) => { if (ok) { const i = Q("#pprule"); if (i) i.value = "" } });
  }, true);
  addEventListener("keydown", (e) => {
    if (!P.name || e.key !== "Escape" || document.querySelector(".pp-dlg")) return;
    const t = e.target; if (/^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName) && t.value) return;
    if (Q("#pal") && Q("#pal").classList.contains("open")) return;
    { const h = g("hc"); if (h && h.name) return; }
    e.preventDefault(); e.stopImmediatePropagation(); close();
  }, true);

  // ---------- wiring into index.html (no edits needed there beyond loading this file) ----------
  // 1. any navigation through show() leaves the profile
  if (typeof window.show === "function") { const _show = window.show; window.show = function (t) { if (P.name) close(true); return _show.apply(this, arguments) } }
  // 2. hover card: "Profile" button next to "Open terminal"
  if (typeof window.hcDraw === "function") {
    const _hd = window.hcDraw;
    window.hcDraw = function () { const r = _hd.apply(this, arguments); const ha = document.querySelector("#hcard .ha");
      if (ha && !ha.querySelector("#hcprof")) { const b = document.createElement("button"); b.className = "btn ghost sm"; b.id = "hcprof"; b.textContent = "Profile"; b.title = "Agent profile · right-click a team row"; ha.appendChild(b) } return r };
    document.addEventListener("click", (e) => { const h = g("hc"); if (e.target.id === "hcprof" && h && h.name) open(h.name) });
  }
  // 3. right-click a team row: small menu (desktop) · phone keeps long-press = hover card, which has the Profile button
  let ctx = null;
  const ctxHide = () => { if (ctx) { ctx.remove(); ctx = null } };
  document.addEventListener("contextmenu", (e) => {
    const r = e.target.closest && e.target.closest("#team .agent"); if (!r || isMob()) return;
    e.preventDefault(); ctxHide(); if (window.hcHide) try { hcHide(true) } catch (x) {}
    const n = r.dataset.name; ctx = document.createElement("div"); ctx.className = "pp-ctx"; ctx.setAttribute("role", "menu");
    ctx.innerHTML = `<button data-c="prof" role="menuitem">Profile</button><button data-c="term" role="menuitem">Open terminal</button><button data-c="msg" role="menuitem">Message via {{COORD}}…</button>`;
    document.body.appendChild(ctx);
    const x = Math.min(e.clientX, innerWidth - ctx.offsetWidth - 8), y = Math.min(e.clientY, innerHeight - ctx.offsetHeight - 8);
    ctx.style.left = x + "px"; ctx.style.top = y + "px"; ctx.querySelector("button").focus();
    ctx.addEventListener("click", (ev) => { const b = ev.target.closest("[data-c]"); if (!b) return; const c = b.dataset.c; ctxHide();
      if (c === "prof") open(n); else if (c === "term") { if (window.openMember) openMember(n) } else if (c === "msg") { open(n); setTimeout(() => { const i = Q("#ppmsg"); if (i) i.focus() }, 400) } });
    ctx.addEventListener("keydown", (ev) => { const bs = [...ctx.querySelectorAll("button")], i = bs.indexOf(document.activeElement);
      if (ev.key === "ArrowDown") { ev.preventDefault(); bs[(i + 1) % bs.length].focus() } else if (ev.key === "ArrowUp") { ev.preventDefault(); bs[(i - 1 + bs.length) % bs.length].focus() } else if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); ctxHide() } });
  });
  document.addEventListener("pointerdown", (e) => { if (ctx && !ctx.contains(e.target)) ctxHide() }, true);
  addEventListener("blur", ctxHide); addEventListener("resize", ctxHide);
  // 4. ⌘K: "Profile: <agent>"
  if (typeof window.palItems === "function") {
    const _pi = window.palItems;
    window.palItems = function (qs) {
      const r = _pi.apply(this, arguments), ws = String(qs || "").toLowerCase().split(/\s+/).filter(Boolean);
      const team = ((g("B") || {}).team || []).map((a) => a.name);
      const names = team.length ? team : (window.OFFICINA ? OFFICINA.team.map((m) => m.name) : []);
      const items = names.map((n) => ({ g: "Profiles", ic: `<span class="tav" style="--c:${COLOR(n)}">${AV(n, 20, "idle")}</span>`, t: "Profile: " + LAB(n), s: "permissions · score · helpers", txt: "profile " + LAB(n) + " " + n + " permissions score helpers sub-agents role card", run: () => open(n) }));
      const hit = (x) => ws.every((w) => (x.txt + " " + x.t).toLowerCase().includes(w));
      const add = ws.length ? items.filter(hit) : [];
      if (!add.length) return r;
      const i = r.findIndex((x) => x.g !== "Go to"); const at = i < 0 ? r.length : i;
      return r.slice(0, at).concat(add, r.slice(at)).slice(0, 44);
    };
  }
  // 5. route /?profile=<name>
  const want = new URLSearchParams(location.search).get("profile");
  if (want && !new URLSearchParams(location.search).get("pane")) {
    const nm = (window.OFFICINA ? OFFICINA.team.map((m) => m.name) : []).find((n) => [n.toLowerCase(), n.toLowerCase().replace(/\s+/g, "-")].includes(want.toLowerCase())) || want;
    setTimeout(() => open(nm), 250);
  }
  window.Profile = { open, close, get name() { return P.name } };
})();
