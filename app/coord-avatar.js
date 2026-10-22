// {{COORD}}'s live avatar for the Officina header: shows what it is doing now (/api/coord) and who it talks to.
(() => {
  const css = `
  .kav{display:flex;align-items:center;gap:8px;margin-left:4px;padding:3px 12px 3px 4px;border:1px solid var(--line2,#e6e5e2);border-radius:0;background:var(--panel,#fff);max-width:400px;min-width:0;flex:0 1 auto}
  .kav .kt{font:400 12.5px var(--sans,'Geist',system-ui,sans-serif);color:var(--ink2,#45423d);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
  .kav .kt b{color:var(--acc-ink,#a12e23);font-weight:600}
  .kav .wire{width:16px;height:2px;flex:0 0 16px;background:repeating-linear-gradient(90deg,var(--acc,#c23b2e) 0 3px,transparent 3px 6px);background-size:12px 2px;animation:kwire .6s linear infinite}
  @keyframes kwire{to{background-position:12px 0}}
  .kav .kslot{width:30px;height:30px;flex:0 0 30px;display:grid;place-items:center}
  .kav .peer{width:20px;height:20px;display:grid;place-items:center;flex:0 0 20px}
  .kav.away .kt{opacity:.7}
  .kav.pulse{box-shadow:0 0 0 3px rgba(194,59,46,.12)}
  @media(max-width:1380px){.kav{max-width:280px}}
  `;
  const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
  // {{COORD}}: Cappa in costume, Light level (Mole spire + headset + baton), drawn by /avatars.js.
  const draw = (who, size, state) => window.avatarSVG ? avatarSVG(who, { size, state }) : "";
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const VERB = { idle: "here", thinking: "thinking", working: "running", reading: "reading", writing: "editing", talking: "talking to",
                 briefing: "briefing a helper", away: "away" };
  function mount() {
    const head = document.querySelector("header"); if (!head || document.querySelector(".kav")) return;
    const el = document.createElement("div"); el.className = "kav idle"; el.title = "what {{COORD}} is doing now";
    el.innerHTML = `<span class="kslot">${draw("{{COORD}}", 30, "idle")}</span><span class="peerbox" style="display:contents"></span><span class="kt">{{COORD}}</span>`;
    const logo = head.querySelector(".logo"); logo ? logo.after(el) : head.prepend(el);
    let last = "";
    async function tick() {
      let d; try { d = await (await fetch("/api/coord")).json() } catch (e) { d = { state: "away", label: "office offline" } }
      const key = JSON.stringify(d); if (key === last) return; last = key;
      const state = window.avatarState ? avatarState(d.state) : (d.state || "idle");
      el.className = "kav " + state; el.classList.add("pulse"); setTimeout(() => el.classList.remove("pulse"), 600);
      el.querySelector(".kslot").innerHTML = draw("{{COORD}}", 30, state);
      window.COORD_STATE = state; dispatchEvent(new CustomEvent("coord-state", { detail: state }));
      const pb = el.querySelector(".peerbox"), who = d.with;
      if (d.state === "talking" && who) {
        pb.innerHTML = `<span class="wire"></span><span class="peer" title="${esc(who)}">${draw(who, 20, "reading")}</span>`;
      } else pb.innerHTML = "";
      const verb = VERB[d.state] || d.state, tool = d.tool && d.state === "working" ? ` <span style="color:var(--ok,#4b7f52)">${esc(d.tool)}</span>` : "";
      const txt = d.state === "talking" ? `<b>${verb} ${esc(who || "")}</b>${d.label ? " · " + esc(d.label) : ""}`
               : d.state === "idle" ? `<b>{{COORD}}</b> · ${esc(d.label || "here")}` : `<b>${verb}</b>${tool}${d.label ? " · " + esc(d.label) : ""}`;
      el.querySelector(".kt").innerHTML = txt; el.title = (d.label || verb);
    }
    tick(); setInterval(tick, 1500);
  }
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", mount) : mount();
})();
