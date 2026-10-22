// Officina avatars · "Cappa in costume", Light level (hat + 1 prop).
// Flat style: one plain fill per part. No gradients, rim light, gloss, grain or cast shadow.
// Use: avatarSVG(name, {size, state, still}) -> "<svg ...>" string.
//   name : a team member's name (config.json team). The coordinator (first member) and names that contain
//          modeller / judge / folder / procurer / cad|fusion / tech get their costume; unknown -> neutral Cappa
//   state: idle thinking working reading writing talking briefing away  (also busy->working, starting->thinking, waiting->idle, offline->away)
//   still: true = no animation (long lists, e.g. chat history)
// Gradients/filters live once per agent in a hidden <svg> sprite (ids "cav-<who>-*"), so many avatars on one page never clash
// and the markup of one avatar is always the same string (the board patcher does not re-render it each poll).
(() => {
  if (window.avatarSVG) return;
  const T = {
    coord:    { n: 'Coordinator',    g: ['#e9a097', '#c23b2e', '#8f2a20'] },
    modeller: { n: 'Modeller',       g: ['#f3d78f', '#e3b13b', '#a87d1c'] },
    judge:    { n: 'Judge',          g: ['#d6d3cc', '#a9a59d', '#6f6c66'] },
    folder:   { n: 'Folder Manager', g: ['#a9c0e0', '#3f6fb0', '#284c80'] },
    procurer: { n: 'Procurer',       g: ['#f1c39e', '#e07f3a', '#a85520'] },
    fusion:   { n: 'CAD',            g: ['#bcd3b1', '#6b9a5a', '#466b3a'] },
    tech:     { n: 'Tech',           g: ['#bdb4cc', '#8a7fa3', '#5f5577'] },
    neutral:  { n: '',               g: ['#efe9df', '#cbc1b1', '#978c7b'] },
  };
  const OFF = window.OFFICINA || { coord: 'Coordinator', team: [] };
  const ROLEWORDS = [[/model/i, 'modeller'], [/judge|review/i, 'judge'], [/folder|fil(e|ing)/i, 'folder'], [/procur|purchas|supplier/i, 'procurer'],
    [/cad|fusion|mechanic/i, 'fusion'], [/tech|tool/i, 'tech']];
  const ALIAS = { [String(OFF.coord).toLowerCase()]: 'coord', coordinator: 'coord', 'folder mgr': 'folder' };
  (OFF.team || []).slice(1).forEach(m => { const hit = ROLEWORDS.find(([rx]) => rx.test(m.name)) || ROLEWORDS.find(([rx]) => rx.test((m.role || '').split(/[·,]/)[0])); if (hit) ALIAS[m.name.toLowerCase()] = hit[1]; });
  ROLEWORDS.forEach(([, k]) => { ALIAS[k] = ALIAS[k] || k; });
  const who = n => ALIAS[String(n || '').trim().toLowerCase()] || 'neutral';
  const STATE = { idle: 'idle', thinking: 'thinking', working: 'working', reading: 'reading', writing: 'writing', talking: 'talking',
    briefing: 'briefing', away: 'away', busy: 'working', running: 'working', starting: 'thinking', waiting: 'idle', offline: 'away', off: 'away', stopped: 'away' };
  const stateOf = s => STATE[String(s || '').trim().toLowerCase()] || 'idle';

  const P = 'M24,100 V62 a40,40 0 0 1 80,0 V100 q0,12 -12,12 H36 q-12,0 -12,-12z';
  const IN = 'M31,98 V63 a33,33 0 0 1 66,0 V98 q0,7 -7,7 H38 q-7,0 -7,-7z';
  const JCAP = 'M23,55 C20,28 41,15 64,15 C87,15 108,28 105,55 Q97,46.5 86,44.6 Q64,41 42,44.6 Q31,46.5 23,55Z';

  /* ---------- CSS (namespaced: .cav / .cv-*) ---------- */
  const CSS = `
  svg.cav{overflow:visible;display:block;flex:0 0 auto}
  .cav :is(.cv-sh,.cv-br,.cv-bl,.cv-glow,.cv-talk,.cv-cue,.cv-gear,.cv-swing,.cv-scan,.cv-pen,.cv-td circle,.cv-zz text,.cv-wave,.cv-tap){transform-box:fill-box}
  .cav .cv-fl{animation:cvfl 4.2s ease-in-out infinite}
  @keyframes cvfl{50%{transform:translateY(-2.6px)}}
  .cav .cv-sh{transform-origin:center;animation:cvsh 4.2s ease-in-out infinite}
  @keyframes cvsh{50%{transform:scaleX(.9);opacity:.75}}
  .cav .cv-br{transform-origin:50% 100%;animation:cvbr 4.2s ease-in-out infinite}
  @keyframes cvbr{50%{transform:scale(1.012,1.028)}}
  .cav .cv-bl{transform-origin:center;animation:cvbl 4.6s infinite}
  @keyframes cvbl{0%,91%,100%{transform:scaleY(1)}94%{transform:scaleY(.08)}}
  .cav .cv-scan{animation:cvscan 2.2s ease-in-out infinite}
  @keyframes cvscan{0%,100%{transform:translateX(-3.5px)}45%,55%{transform:translateX(3.5px)}}
  .cav .cv-orb{transform-box:view-box;transform-origin:64px 64px;animation:cvorb 2.6s linear infinite}
  @keyframes cvorb{to{transform:rotate(360deg)}}
  .cav .cv-glow{transform-origin:center;animation:cvglow 1.8s ease-in-out infinite}
  @keyframes cvglow{0%,100%{opacity:.18;transform:scale(.96)}50%{opacity:.55;transform:scale(1.05)}}
  .cav .cv-talk{transform-origin:center;animation:cvtalk .34s ease-in-out infinite alternate}
  @keyframes cvtalk{from{transform:scaleY(.35)}to{transform:scaleY(1.1)}}
  .cav .cv-td circle{animation:cvtd 1.2s ease-in-out infinite}
  .cav .cv-td circle:nth-child(2){animation-delay:.2s}.cav .cv-td circle:nth-child(3){animation-delay:.4s}
  @keyframes cvtd{0%{opacity:0;transform:translateX(-4px)}40%{opacity:1}100%{opacity:0;transform:translateX(6px)}}
  .cav .cv-pen{animation:cvpen 2.4s ease-in-out infinite}
  @keyframes cvpen{0%{transform:translateX(0)}80%,100%{transform:translateX(36px)}}
  .cav .cv-ink{stroke-dasharray:44;animation:cvink 2.4s ease-in-out infinite}
  @keyframes cvink{0%{stroke-dashoffset:44}80%,100%{stroke-dashoffset:0}}
  .cav .cv-zz text{animation:cvzz 3s ease-in infinite;opacity:0}
  .cav .cv-zz text:nth-child(2){animation-delay:1s}.cav .cv-zz text:nth-child(3){animation-delay:2s}
  @keyframes cvzz{0%{opacity:0;transform:translate(0,4px)}25%{opacity:1}100%{opacity:0;transform:translate(6px,-10px)}}
  .cav .cv-card line{animation:cvcard 2.4s ease-out infinite;opacity:0}
  .cav .cv-card line:nth-child(3){animation-delay:.3s}.cav .cv-card line:nth-child(4){animation-delay:.6s}
  @keyframes cvcard{0%{opacity:0}20%,80%{opacity:1}100%{opacity:0}}
  .cav .cv-cue{transform-origin:center;animation:cvcue 4.2s ease-in-out infinite}
  @keyframes cvcue{50%{transform:translateY(-1.6px) rotate(4deg)}}
  .cav .cv-gear{transform-origin:center;animation:cvorb 9s linear infinite}
  .cav.s-working .cv-gear{animation-duration:2.4s}
  .cav .cv-swing{transform-origin:50% 0;animation:cvswing 3.4s ease-in-out infinite}
  @keyframes cvswing{50%{transform:rotate(9deg)}}
  .cav .cv-wave{transform-origin:50% 100%;animation:cvwave 3.4s ease-in-out infinite}
  @keyframes cvwave{0%,100%{transform:rotate(0)}50%{transform:rotate(-10deg)}}
  .cav:is(.s-talking,.s-briefing) .cv-wave{animation-duration:1s}
  .cav .cv-tap{transform-origin:100% 50%;animation:cvtap 3.2s ease-in infinite}
  @keyframes cvtap{0%,72%,100%{transform:rotate(0)}82%{transform:rotate(26deg)}90%{transform:rotate(-3deg)}}
  .cav.s-working .cv-tap{animation-duration:1.4s}
  .cav .cv-gl1{animation:cvgl 1.6s steps(1) infinite}.cav .cv-gl2{animation:cvgl 1.6s steps(1) infinite -.8s}
  @keyframes cvgl{0%{opacity:1}50%{opacity:0}}
  .cav .cv-type ellipse{transform-box:fill-box;animation:cvtype .32s ease-in-out infinite alternate}
  .cav .cv-type ellipse:nth-child(2){animation-delay:-.16s}
  @keyframes cvtype{to{transform:translateY(-2.2px)}}
  .cav .cv-code{stroke-dasharray:14;animation:cvcode 1.6s linear infinite}
  @keyframes cvcode{0%{stroke-dashoffset:14}70%,100%{stroke-dashoffset:0}}
  .cav.s-away .cv-fl,.cav.s-away .cv-br{animation-duration:7s}
  .cav.s-away .cv-body{filter:saturate(.25) brightness(1.04)}
  .cav.s-away :is(.cv-wave,.cv-tap,.cv-gear,.cv-swing,.cv-cue){animation-play-state:paused}
  .cav.still *{animation:none!important}
  @media (prefers-reduced-motion:reduce){.cav *{animation:none!important}}`;

  /* ---------- shared defs (one sprite, ids per agent) ---------- */
  const lg = (id, cs) => `<linearGradient id="${id}"><stop offset="0" stop-color="${cs[Math.floor(cs.length / 2)]}"/></linearGradient>`;
  function defs(w) {
    const k = 'cav-' + w + '-';
    return lg(k + 'g', [T[w].g[1]]);
  }
  function common() {
    const k = 'cav-';
    return `${lg(k + 'gold', ['#e8b04e'])}
    <clipPath id="${k}wc"><path d="${JCAP}"/></clipPath>
    ${lg(k + 'hh', ['#fff4b0', '#ffd23e', '#e39a12'], .2, 0, .8, 1)}${lg(k + 'hhb', ['#ffd94e', '#e7a516', '#b97c0c'])}
    ${lg(k + 'wood', ['#e7b98a', '#b0723e', '#7a4422'], 0, 0, 1, 1)}${lg(k + 'beam', ['#ffe8c2', '#f2cc92'])}
    ${lg(k + 'wig', ['#ffffff', '#f1eadc', '#d9ccb2'])}${lg(k + 'visor', ['#7fd39b', '#3f9e63', '#256b42'])}
    ${lg(k + 'kraft', ['#ecd2a6', '#d4b07a', '#b98f55'])}${lg(k + 'cap', ['#a8b56c', '#7a8a46', '#4f5c2a'], .2, 0, .8, 1)}
    ${lg(k + 'capb', ['#6c7a3a', '#3f4a1e'])}${lg(k + 'steel', ['#ffffff', '#c9d0d5', '#7f8a92'], 0, 0, 1, 1)}
    ${lg(k + 'lens', ['#d8f6f2', '#7cc6c9', '#2f7f8f'], .2, 0, .8, 1)}${lg(k + 'dark', ['#4a4450', '#25212b'])}`;
  }
  let sprite = null;
  const done = new Set();
  function ensure(w) {
    if (!document.body) return;
    if (!sprite) {
      const st = document.createElement('style'); st.id = 'cav-css'; st.textContent = CSS; document.head.appendChild(st);
      sprite = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      sprite.setAttribute('aria-hidden', 'true'); sprite.id = 'cav-defs';
      sprite.setAttribute('style', 'position:absolute;width:0;height:0;overflow:hidden;pointer-events:none');
      sprite.innerHTML = '<defs>' + common() + '</defs>';
      document.body.prepend(sprite);
    }
    if (done.has(w)) return; done.add(w);
    sprite.querySelector('defs').insertAdjacentHTML('beforeend', defs(w));
  }
  if (!document.body) document.addEventListener('DOMContentLoaded', () => { const ws = [...done]; done.clear(); ws.forEach(ensure); if (!ws.length) ensure('neutral'); });

  /* ---------- gear ---------- */
  function gearPath(cx, cy, ro, ri, n) {
    let d = '';
    for (let i = 0; i < n * 2; i++) {
      const a0 = (i / (n * 2)) * Math.PI * 2, a1 = ((i + 1) / (n * 2)) * Math.PI * 2, r = i % 2 ? ri : ro;
      const p = (a, rr) => (cx + rr * Math.cos(a)).toFixed(2) + ',' + (cy + rr * Math.sin(a)).toFixed(2);
      d += (i ? 'L' : 'M') + p(a0 + .06, r) + 'L' + p(a1 - .06, r);
    }
    return d + 'Z';
  }
  const GEAR = gearPath(0, 0, 9.5, 7.2, 8);

  /* ---------- face ---------- */
  const INK = '#211a1f';
  function eye(kind, x, y, tiny) {
    if (kind === 'closed') return `<path d="M${x - 4.2},${y - 1} q4.2,4.6 8.4,0" fill="none" stroke="${INK}" stroke-width="2" stroke-linecap="round"/>`;
    if (kind === 'happy') return `<path d="M${x - 4},${y + 1.5} q4,-5.4 8,0" fill="none" stroke="${INK}" stroke-width="2.1" stroke-linecap="round"/>`;
    if (kind === 'focus') return `<path d="M${x - 4},${y - 1.2} h8 a4,3.6 0 0 1 -8,0z" fill="${INK}"/>`;
    return `<g class="cv-bl"><ellipse cx="${x}" cy="${y}" rx="3.5" ry="4" fill="${INK}"/></g>`;
  }
  function mouth(state, y) {
    const x = 64, s = d => `<path d="${d}" fill="none" stroke="${INK}" stroke-width="1.9" stroke-linecap="round"/>`;
    switch (state) {
      case 'thinking': return s(`M${x - 3},${y + 1} l6,-1.6`);
      case 'working': return s(`M${x - 3},${y} h6`);
      case 'writing': return s(`M${x - 2.5},${y + .4} q2.5,1.2 5,0`);
      case 'reading': return s(`M${x - 2.4},${y} q2.4,1.6 4.8,0`);
      case 'talking': return `<g class="cv-talk"><ellipse cx="${x}" cy="${y + .6}" rx="3.1" ry="2.5" fill="${INK}"/></g>`;
      case 'briefing': return `<path d="M${x - 4.6},${y - .6} q4.6,5.4 9.2,0z" fill="${INK}"/>`;
      case 'away': return s(`M${x - 2},${y + .4} h4`);
      default: return s(`M${x - 4},${y - .4} q4,3.2 8,0`);
    }
  }
  function face(w, state, cy, tiny) {
    const kind = state === 'away' ? 'closed' : state === 'working' ? 'focus' : state === 'briefing' ? 'happy' : 'open';
    const off = state === 'thinking' ? '2.5,-4' : state === 'writing' ? '0,3' : state === 'reading' ? '0,1.5' : '0,0';
    const lx = 54.5, rx = 73.5;
    let eyes = eye(kind, lx, cy, tiny) + eye(kind, rx, cy, tiny), wear = '';
    if (w === 'judge' && !tiny) wear = `<circle cx="${rx}" cy="${cy}" r="7.6" fill="none" stroke="url(#cav-gold)" stroke-width="2.1"/><path d="M${rx + 6},${cy + 4.5} q5,12 -1,24" fill="none" stroke="#e8b04e" stroke-width=".9" opacity=".9"/>`;
    if (w === 'folder' && !tiny) wear = `<g fill="none" stroke="#4a2e20" stroke-width="1.9"><circle cx="${lx}" cy="${cy}" r="7.8"/><circle cx="${rx}" cy="${cy}" r="7.8"/></g><path d="M${lx + 7.6},${cy - 1.4} q2.4,-2.2 4.2,0 M${lx - 7.7},${cy - 1} l-6,-2 M${rx + 7.7},${cy - 1} l6,-2" fill="none" stroke="#4a2e20" stroke-width="1.6" stroke-linecap="round"/>`;
    if (w === 'tech') {
      const fr = tiny ? 2.4 : 1.9, r = 8;
      wear = `<g fill="none" stroke="${INK}" stroke-width="${fr}"><circle cx="${lx}" cy="${cy}" r="${r}"/><circle cx="${rx}" cy="${cy}" r="${r}"/><path d="M${lx + r},${cy - 1} q${(rx - lx - 2 * r) / 2},-2.6 ${rx - lx - 2 * r},0"/></g>`;
      if (state === 'thinking' && !tiny) wear += `<g stroke="#fffaf0" stroke-width="1.8" stroke-linecap="round"><path class="cv-gl1" d="M${lx + 1.5},${cy - 5.5} l3.4,3.4"/><path class="cv-gl2" d="M${rx + 1.5},${cy - 5.5} l3.4,3.4"/></g>`;
    }
    const blush = w === 'coord' ? `<ellipse cx="47" cy="${cy + 8}" rx="4.6" ry="2.6" fill="#ff8a8a" opacity=".38"/><ellipse cx="81" cy="${cy + 8}" rx="4.6" ry="2.6" fill="#ff8a8a" opacity=".38"/>` : '';
    const out = `<g transform="translate(${off})"><g class="${state === 'reading' ? 'cv-scan' : ''}">${eyes}${w === 'judge' ? wear : ''}</g>${w === 'tech' ? wear : ''}</g>${w === 'folder' ? wear : ''}${blush}${mouth(state, cy + 10)}`;
    return T[w].ink ? out.split(INK).join(T[w].ink) : out;
  }

  /* ---------- costume (Light: hat + 1 prop). hat(tiny): tiny = silhouette only ---------- */
  const C = {
    coord: {
      hat: tiny => tiny
        ? `<path d="M23,61 A41,41 0 0 1 105,61" fill="none" stroke="#24212a" stroke-width="4" stroke-linecap="round"/>
           <rect x="15.5" y="52" width="12" height="17" rx="5.5" fill="url(#cav-dark)"/><rect x="100.5" y="52" width="12" height="17" rx="5.5" fill="url(#cav-dark)"/>
           <path d="M59.5,24 L64,3 L68.5,24z" fill="url(#cav-gold)"/>`
        : `<path d="M23,61 A41,41 0 0 1 105,61" fill="none" stroke="#24212a" stroke-width="2.8" stroke-linecap="round"/>
    <rect x="16.5" y="53" width="10" height="15" rx="4.6" fill="url(#cav-dark)"/>
    <rect x="101.5" y="53" width="10" height="15" rx="4.6" fill="url(#cav-dark)"/>
    <circle cx="21.5" cy="57.6" r="1.25" fill="#8ef09a"/>
    <path d="M22,66 Q25,82 40.5,82.5" fill="none" stroke="#24212a" stroke-width="1.9" stroke-linecap="round"/>
    <rect x="39" y="79.6" width="8" height="5.6" rx="2.8" fill="url(#cav-dark)"/>
    <g class="cv-cue"><path d="M61,23.5 L64,5.5 L67,23.5 z" fill="url(#cav-gold)"/><path d="M57.5,24.2 h13" stroke="#b97a2a" stroke-width="1.8" stroke-linecap="round"/><path d="M59.8,20.6 h8.4" stroke="#b97a2a" stroke-width="1" stroke-linecap="round" opacity=".7"/><circle cx="64" cy="5.4" r="3" fill="url(#cav-gold)"/></g>`,
      front: () => `<g transform="translate(97 106) rotate(46)"><g class="cv-wave">
    <path d="M-1.3,-4 L-.5,-32 L.5,-32 L1.3,-4Z" fill="#2b2620"/>
    <circle cx="0" cy="-32" r="1.3" fill="#fffaf0" stroke="#2b2620" stroke-width=".5"/>
    <path d="M-3,-3.6 Q-4.2,2.4 0,5 Q4.2,2.4 3,-3.6Z" fill="url(#cav-wood)"/><rect x="-2" y="-5.4" width="4" height="2.2" rx=".6" fill="url(#cav-gold)"/></g></g>`,
    },
    modeller: {
      hat: tiny => tiny
        ? `<path d="M30,45.5 C30,23 46,12.5 64,12.5 C82,12.5 98,23 98,45.5Z" fill="url(#cav-hh)"/>
           <path d="M17,46.6 Q64,35.4 111,46.6 Q113.4,52.6 105,53 Q64,45.2 23,53 Q14.6,52.6 17,46.6Z" fill="url(#cav-hhb)"/>`
        : `<g transform="translate(101 52) rotate(50)">
      <rect x="-2.2" y="-13" width="4.4" height="21" fill="#4f7896"/>
      <path d="M-2.2,8 L0,13.4 L2.2,8Z" fill="#f2d3a0"/><path d="M-.75,11.6 L0,13.4 L.75,11.6Z" fill="#2b2620"/>
      <rect x="-2.2" y="-14.4" width="4.4" height="1.8" fill="#c9ccd0"/><rect x="-2.2" y="-17.4" width="4.4" height="3.2" rx="1" fill="#ef8f8f"/></g>
    <path d="M30,45.5 C30,23 46,12.5 64,12.5 C82,12.5 98,23 98,45.5Z" fill="url(#cav-hh)"/>
    <path d="M58,14 L56.6,44.6 M70,14 L71.4,44.6" stroke="#a86e08" stroke-opacity=".5" stroke-width="1"/>
    <g transform="translate(64 31)"><path d="M0,-4.6 L4,-2.3 L4,2.3 L0,4.6 L-4,2.3 L-4,-2.3Z" fill="#c23b2e"/></g>
    <path d="M30,45.5 C30,23 46,12.5 64,12.5 C82,12.5 98,23 98,45.5" fill="none" stroke="#a86e08" stroke-opacity=".35" stroke-width=".9"/>
    <path d="M19,46.6 Q64,36.4 109,46.6 Q111.4,51.6 105,52 Q64,44.2 23,52 Q16.6,51.6 19,46.6Z" fill="url(#cav-hhb)"/>`,
      front: () => `<g class="cv-cue"><g transform="translate(96 9) scale(1.3) rotate(-4)">
    <path d="M0,0 L13.9,8 L9.5,10.5 L-4.3,2.5Z" fill="url(#cav-beam)"/>
    <path d="M-4.3,2.5 L9.5,10.5 L9.5,15.5 L-4.3,7.5Z" fill="#e5b06e"/>
    <path d="M9.5,10.5 L13.9,8 L13.9,13 L9.5,15.5Z" fill="#c4834a"/></g></g>`,
    },
    judge: {
      hat: tiny => {
        let rolls = '';
        for (const sx of [21.5, 106.5]) for (let i = 0; i < 3; i++) {
          const y = 54 + i * 7.2, f = sx < 64 ? 1 : -1;
          rolls += tiny
            ? `<ellipse cx="${sx}" cy="${y}" rx="6.8" ry="4.2" fill="url(#cav-wig)"/>`
            : `<ellipse cx="${sx}" cy="${y}" rx="6.4" ry="3.9" fill="url(#cav-wig)" stroke="#c4b596" stroke-width=".8"/><path d="M${sx - 3 * f},${y + .4} a2.6,2 0 1 ${f > 0 ? 1 : 0} ${3.4 * f},-1.6" fill="none" stroke="#c4b596" stroke-width=".8"/>`;
        }
        if (tiny) return `${rolls}<path d="${JCAP}" fill="url(#cav-wig)" stroke="#bfae8c" stroke-width="1.2"/>`;
        let rows = '';
        [[21.5, 44, 84], [28.5, 33, 95], [35.5, 27, 101], [42, 24, 104]].forEach(([y, x1, x2]) => {
          let d = `M${x1},${y}`; for (let x = x1; x < x2; x += 5.2) d += ' a2.6,2.6 0 0 1 5.2,0';
          rows += `<path d="${d}" fill="none" stroke="#c4b596" stroke-width=".95"/>`;
        });
        return `${rolls}<path d="${JCAP}" fill="url(#cav-wig)"/>
      <g clip-path="url(#cav-wc)">${rows}</g>
      <path d="${JCAP}" fill="none" stroke="#bfae8c" stroke-width=".8"/>`;
      },
      front: () => `<g transform="translate(117 101) rotate(52)"><g class="cv-tap">
    <rect x="-19" y="-1.7" width="20.6" height="3.4" rx="1.7" fill="url(#cav-wood)"/><circle cx="1.4" cy="0" r="2.3" fill="#7a4422"/>
    <rect x="-27" y="-8" width="9.4" height="16" rx="2.4" fill="url(#cav-wood)"/>
    <rect x="-27.6" y="-8.4" width="10.6" height="2.4" rx="1.2" fill="#5a3018"/><rect x="-27.6" y="6" width="10.6" height="2.4" rx="1.2" fill="#5a3018"/>
    <rect x="-27" y="-3.2" width="9.4" height="1.5" fill="url(#cav-gold)"/><rect x="-27" y="1.7" width="9.4" height="1.5" fill="url(#cav-gold)"/></g></g>`,
    },
    folder: {
      hat: tiny => tiny
        ? `<path d="M19,48.5 Q64,35 109,48.5 L100,61 Q64,50 28,61Z" fill="url(#cav-visor)"/>`
        : `<path d="M24.5,50.5 Q64,39.5 103.5,50.5" fill="none" stroke="#1f4a30" stroke-width="3.2" stroke-linecap="round"/>
    <path d="M21,49 Q64,37 107,49 L99,60 Q64,49.6 29,60Z" fill="url(#cav-visor)"/>
    <path d="M29,60 Q64,49.6 99,60" fill="none" stroke="#1f5a36" stroke-width="1.5" stroke-linecap="round"/>`,
      front: () => `<g transform="translate(7 84)">
    <rect x="5" y="-2" width="10" height="12" rx="1.4" fill="#c23b2e"/><rect x="6" y="-4" width="5" height="3" rx="1" fill="#c23b2e"/>
    <rect x="10" y="0" width="10" height="10" rx="1.4" fill="#3f6fb0"/><rect x="14" y="-2" width="5" height="3" rx="1" fill="#3f6fb0"/>
    <rect x="15" y="2" width="9" height="8" rx="1.4" fill="#e3b13b"/>
    <rect x="2" y="6" width="24" height="22" rx="1.6" fill="url(#cav-kraft)"/>
    <rect x="8" y="13" width="12" height="7" rx="1" fill="#fffdf6" stroke="#9c7a48" stroke-width=".7"/>
    <path d="M10,15.6 h8 M10,17.8 h5" stroke="#3f6fb0" stroke-width=".9"/>
    <rect x="10" y="23" width="8" height="2.2" rx="1.1" fill="#7a5a30" opacity=".6"/></g>`,
    },
    procurer: {
      hat: tiny => tiny
        ? `<path d="M30,46 C30,24 45,14.5 64,14.5 C83,14.5 98,24 98,46Z" fill="url(#cav-cap)"/>
           <path d="M25,45.4 Q64,35.6 103,45.4 Q107,54.6 95.6,55.6 Q64,49 32.4,55.6 Q21,54.6 25,45.4Z" fill="url(#cav-capb)"/>`
        : `<path d="M30,46 C30,24 45,14.5 64,14.5 C83,14.5 98,24 98,46Z" fill="url(#cav-cap)"/>
    <path d="M64,15 V44 M47,18.5 Q41,30 41.5,45 M81,18.5 Q87,30 86.5,45" stroke="#3d4820" stroke-opacity=".5" stroke-width=".9" fill="none"/>
    <circle cx="64" cy="15" r="2.3" fill="#5c6a30"/>
    <rect x="56.6" y="27" width="14.8" height="10.4" rx="2" fill="url(#cav-gold)"/>
    <path d="M60.4,30.4 h7.2 v4.6 h-7.2Z M60.4,30.4 l3.6,-1.6 3.6,1.6 M64,28.8 v6.2" fill="none" stroke="#5a3a10" stroke-width=".9" stroke-linejoin="round"/>
    <path d="M27,45.4 Q64,36.6 101,45.4 Q105,53.6 94.6,54.6 Q64,48 33.4,54.6 Q23,53.6 27,45.4Z" fill="url(#cav-capb)"/>`,
      front: () => `<g transform="translate(91 84)">
    <rect x="0" y="23" width="28" height="3" rx=".6" fill="#c4904e"/><rect x="1" y="26" width="4.6" height="3.4" fill="#9a6a34"/><rect x="11.7" y="26" width="4.6" height="3.4" fill="#9a6a34"/><rect x="22.4" y="26" width="4.6" height="3.4" fill="#9a6a34"/>
    <rect x="2" y="5" width="24" height="18" rx="1" fill="#e9bd80"/>
    <path d="M2,5 h24 v18 h-24Z M5,8 h18 v12 h-18Z" fill="#c78a48" fill-rule="evenodd"/>
    <path d="M5.6,19.4 L22.4,8.6" stroke="#c78a48" stroke-width="3"/>
    <g fill="#8a5a2a"><circle cx="3.5" cy="6.5" r=".6"/><circle cx="24.5" cy="6.5" r=".6"/><circle cx="3.5" cy="21.5" r=".6"/><circle cx="24.5" cy="21.5" r=".6"/></g>
    <g transform="translate(26 6)"><g class="cv-swing"><path d="M0,0 q2.6,4 2.2,9" fill="none" stroke="#6b5a40" stroke-width=".8"/>
      <g transform="translate(2.2 9) rotate(-8)"><path d="M-4,1.6 L0,-1.6 L6,-1.6 Q7,-1.6 7,-.6 V11 Q7,12 6,12 H-3 Q-4,12 -4,11Z" fill="#fffaf0" stroke="#e8b04e" stroke-width=".8"/><circle cx="0" cy=".6" r=".9" fill="#c39a4a"/><path d="M-2,5 h6.4 M-2,7.6 h4.4" stroke="#5634b8" stroke-width="1" stroke-linecap="round"/></g></g></g></g>`,
    },
    fusion: {
      hat: tiny => {
        const gog = x => tiny
          ? `<g transform="translate(${x} 43.4)"><circle r="10" fill="url(#cav-steel)"/><circle r="7" fill="url(#cav-lens)"/></g>`
          : `<g transform="translate(${x} 43.4)"><circle r="9.4" fill="url(#cav-steel)"/><circle r="9.4" fill="none" stroke="#6a747b" stroke-width=".8"/><circle r="6.6" fill="url(#cav-lens)"/></g>`;
        return `<path d="M23.5,52.5 Q64,35 104.5,52.5" fill="none" stroke="#2b2620" stroke-width="${tiny ? 6 : 5}" stroke-linecap="round"/>
    ${tiny ? '' : '<path d="M58,42.6 Q64,39.6 70,42.6" fill="none" stroke="#5a5560" stroke-width="3"/>'}
    ${gog(49.4)}${gog(78.6)}`;
      },
      front: () => `<g transform="translate(29 18)"><g class="cv-gear"><path d="${GEAR}" fill="url(#cav-gold)" stroke="#a8792e" stroke-width=".6"/><circle r="3" fill="#3d3a33"/><circle r="1.5" fill="#d9c38a"/></g></g>`,
    },
    tech: {
      // over-ear headphones (band over the cappa, round cups, no mic); round glasses live in face(); small laptop held at the right side
      hat: tiny => {
        const cup = (x, f) => tiny
          ? `<ellipse cx="${x}" cy="63" rx="8" ry="10" fill="#3a3540"/>`
          : `<ellipse cx="${x}" cy="63" rx="7.2" ry="9.4" fill="#3a3540"/><ellipse cx="${x + 2.6 * f}" cy="63" rx="3" ry="6.4" fill="#e9e2d6"/>`;
        if (tiny) return `<path d="M21,62 A43,43 0 0 1 107,62" fill="none" stroke="#3a3540" stroke-width="5" stroke-linecap="round"/>${cup(21, 1)}${cup(107, -1)}`;
        return `<path d="M21,62 A43,43 0 0 1 107,62" fill="none" stroke="#3a3540" stroke-width="3.4" stroke-linecap="round"/>
    <path d="M50,21.4 A43,43 0 0 1 78,21.4" fill="none" stroke="#a87a2e" stroke-width="4.6" stroke-linecap="round"/>
    ${cup(21, 1)}${cup(107, -1)}`;
      },
      front: state => {
        const away = state === 'away', lid = away ? 6 : 15;
        const sticker = away ? '' : `<circle cx="9" cy="${-lid / 2}" r="2" fill="#c23b2e"/><path d="M13,${-lid / 2 - 2} L15.2,${-lid / 2 + 2} H10.8Z" fill="#e3b13b"/><rect x="16" y="${-lid / 2 - 1.9}" width="3.8" height="3.8" fill="#3f6fb0"/>`;
        const glow = state === 'working' ? `<path class="cv-glow" d="M3,${-lid - 1.6} H22" stroke="#d9e8d0" stroke-width="2" stroke-linecap="round"/>` : '';
        const hand = `<g class="${state === 'working' ? 'cv-type' : ''}"><ellipse cx="2" cy="1.6" rx="3.6" ry="2.6" fill="#5f5577"/></g>`;
        return `<g transform="translate(89 104) rotate(-6) scale(1.3)">${glow}
    <rect x="1" y="${-lid}" width="23" height="${lid}" rx="1.6" fill="#c9c4bb"/><rect x="1" y="${-lid}" width="23" height="${lid}" rx="1.6" fill="none" stroke="#8f8a82" stroke-width=".8"/>${sticker}
    <path d="M-1,0 H26 L24.6,2.6 Q24.2,3.2 23.4,3.2 H1.6 Q.8,3.2 .4,2.6Z" fill="#a9a49b"/>${hand}</g>`;
      },
    },
    neutral: { hat: () => '', front: () => '' },
  };

  /* ---------- state extras ---------- */
  function extras(state, t) {
    if (state === 'thinking') return `<g class="cv-orb"><circle cx="64" cy="9" r="3.4" fill="url(#cav-gold)"/></g>`;
    if (state === 'talking') return `<g class="cv-td" fill="${t.g[1]}"><circle cx="113" cy="62" r="2.4"/><circle cx="120" cy="62" r="2.4"/><circle cx="127" cy="62" r="2.4"/></g>`;
    if (state === 'briefing') return `<g transform="translate(106 26) rotate(6)" class="cv-card"><rect x="0" y="0" width="22" height="26" rx="3.5" fill="#fffdf8" stroke="#e5dccd"/><rect x="0" y="0" width="22" height="26" rx="3.5" fill="none"/><line x1="5" y1="8" x2="17" y2="8" stroke="${t.g[1]}" stroke-width="2" stroke-linecap="round"/><line x1="5" y1="13.5" x2="15" y2="13.5" stroke="#c9bfae" stroke-width="2" stroke-linecap="round"/><line x1="5" y1="19" x2="13" y2="19" stroke="#c9bfae" stroke-width="2" stroke-linecap="round"/></g>`;
    if (state === 'away') return `<g class="cv-zz" fill="#e2a440" font-family="Geist,system-ui,sans-serif" font-weight="600"><text x="100" y="36" font-size="11">z</text><text x="107" y="27" font-size="14">z</text><text x="115" y="16" font-size="17">z</text></g>`;
    return '';
  }
  const writing = t => `<path class="cv-ink" d="M44,98 q4.5,-4 9,0 t9,0 t9,0 t9,0" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" opacity=".95"/>
  <g class="cv-pen"><g transform="translate(44 98) rotate(38)"><rect x="-1.8" y="-16" width="3.6" height="13" rx="1" fill="${t.ink ? '#c9ccd0' : '#2b2620'}"/><path d="M-1.8,-3 L0,1.2 L1.8,-3z" fill="#e8b04e"/><rect x="-1.8" y="-16" width="3.6" height="3" rx="1" fill="${t.g[2]}"/></g></g>`;

  const hash = s => { let h = 7; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 9973; return h; };

  /* ---------- one avatar ---------- */
  /* ---------- minis: sub-agents (helpers) of a leader. Same body colour, own work clothes; chunky shapes for 14-16 px ---------- */
  const MV = { coord: 'headset', modeller: 'cap', judge: 'clerk', folder: 'box', procurer: 'tag', fusion: 'wrench', tech: 'laptop', neutral: 'headset' };
  function miniVariant(name, desc, type) {
    const s = (String(desc || '') + ' ' + String(type || '')).toLowerCase();
    // reviewer personas (Judge) and any helper: match the role words first, then the leader's default mini
    if (/\bste\b|ste100|simplified technical/.test(s)) return 'ste';
    if (/graphic/.test(s)) return 'graphic';
    if (/technical designer|draft(er|sman|ing)|detailer/.test(s)) return 'drafter';
    if (/mechanical|\bcnc\b|machinist|machining/.test(s)) return 'machinist';
    if (/producer|fabricat|welder|workshop/.test(s)) return 'welder';
    if (/installer|erector|fitter|assembler/.test(s)) return 'installer';
    if (/structural|engineer/.test(s)) return 'structural';
    if (/packing|packer|logistic|crate|shipping/.test(s)) return 'packer';
    if (/first[- ]?glance|fresh eyes|reader|layman/.test(s)) return 'reader';
    if (/designer|\bux\b|\bui\b/.test(s)) return 'designer';
    return MV[who(name)];
  }
  const D = '#2b2620';
  const MINI = {
    designer: `<ellipse cx="60" cy="27" rx="41" ry="12.5" fill="${D}" transform="rotate(-9 60 27)"/><circle cx="57" cy="12" r="5.5" fill="${D}"/>
      <g transform="translate(110 72) rotate(28)"><rect x="-6.5" y="-34" width="13" height="52" fill="#e8b04e"/><rect x="-6.5" y="-43" width="13" height="10" fill="#ef8f8f"/><path d="M-6.5,18 L0,35 L6.5,18Z" fill="#f2d3a0"/><path d="M-2.6,28 L0,35 L2.6,28Z" fill="${D}"/></g>`,
    drafter: `<g transform="translate(36 30) rotate(-45)"><rect x="-6" y="-28" width="12" height="42" fill="#e8b04e"/><rect x="-6" y="-34" width="12" height="7" fill="#ef8f8f"/><path d="M-6,14 L0,28 L6,14Z" fill="#f2d3a0"/><path d="M-2.4,22 L0,28 L2.4,22Z" fill="${D}"/></g>
      <path d="M86,120 H124 L86,76Z M96,110 H108 L96,96Z" fill="#3f6fb0" fill-rule="evenodd"/>`,
    welder: `<path d="M28,46 Q28,8 64,8 Q100,8 100,46Z" fill="#3d3c38"/><rect x="44" y="20" width="40" height="11" fill="#e3b13b"/><rect x="24" y="42" width="80" height="6" fill="#2b2620"/>
      <g transform="translate(108 100)" fill="#e07f3a"><path d="M0,-16 L4,-4 L16,0 L4,4 L0,16 L-4,4 L-16,0 L-4,-4Z"/></g>`,
    installer: `<path d="M28,46 C28,18 46,8 64,8 C82,8 100,18 100,46Z" fill="#e3b13b"/><rect x="58" y="10" width="12" height="34" fill="#c08a1c"/><rect x="18" y="42" width="92" height="8" fill="#c08a1c"/>
      <g transform="translate(70 100) rotate(-8)"><rect x="0" y="0" width="56" height="15" fill="#6b9a5a"/><rect x="20" y="3.5" width="16" height="8" rx="3" fill="#e9f2c8"/></g>`,
    structural: `<g transform="translate(90 72)" fill="#4f7896"><rect x="0" y="0" width="34" height="9"/><rect x="12.5" y="9" width="9" height="30"/><rect x="0" y="39" width="34" height="9"/></g>`,
    packer: `<path d="M27,49 C27,22 46,11 64,11 C82,11 101,22 101,49Z" fill="#e07f3a"/><path d="M70,42 H10 Q3,43 7,51 H70Z" fill="#b65f22"/>
      <g transform="translate(80 78)"><rect x="0" y="0" width="44" height="40" fill="#c4904e"/><path d="M0,0 H44 V40 H0Z M6,6 V34 H38 V6Z" fill="#8a5a2a" fill-rule="evenodd"/><path d="M6,6 L38,34" stroke="#8a5a2a" stroke-width="6"/></g>`,
    reader: `<g fill="none" stroke="${D}" stroke-width="5"><circle cx="50" cy="68" r="13"/><circle cx="78" cy="68" r="13"/><path d="M63,66 H65"/></g>
      <g transform="translate(84 84) rotate(8)"><rect width="40" height="34" fill="#fffaf0" stroke="#8f8a82" stroke-width="3"/><rect x="6" y="6" width="28" height="7" fill="${D}"/><rect x="6" y="18" width="12" height="10" fill="#a7a49d"/><rect x="22" y="18" width="12" height="4" fill="#a7a49d"/><rect x="22" y="24" width="12" height="4" fill="#a7a49d"/></g>`,
    graphic: `<ellipse cx="60" cy="27" rx="41" ry="12.5" fill="#c23b2e" transform="rotate(-9 60 27)"/><circle cx="57" cy="12" r="5.5" fill="#c23b2e"/>
      <g transform="translate(102 98)"><ellipse rx="23" ry="18" fill="#f2e6cf" stroke="#c9bfae" stroke-width="2"/><circle cx="-10" cy="-5" r="5" fill="#c23b2e"/><circle cx="2" cy="-10" r="5" fill="#3f6fb0"/><circle cx="12" cy="-2" r="5" fill="#e3b13b"/><circle cx="-2" cy="8" r="5" fill="#6b9a5a"/></g>`,
    machinist: `<rect x="20" y="36" width="88" height="6" fill="${D}"/><g transform="translate(48 39)"><circle r="12" fill="#6f7a82"/><circle r="7.5" fill="#9fd0e0"/></g><g transform="translate(80 39)"><circle r="12" fill="#6f7a82"/><circle r="7.5" fill="#9fd0e0"/></g>
      <g transform="translate(84 82)" fill="#6f7a82"><rect x="0" y="0" width="40" height="8"/><rect x="0" y="0" width="8" height="30"/><rect x="22" y="0" width="8" height="22"/><rect x="10" y="2" width="10" height="4" fill="#e9e2d6"/></g>`,
    ste: `<g transform="translate(82 80) rotate(-6)"><rect width="38" height="42" fill="#2c5a98"/><rect x="5" y="36" width="33" height="6" fill="#fffaf0"/><rect x="9" y="10" width="20" height="6" fill="#fffaf0"/></g>
      <g transform="translate(108 70) rotate(32)"><rect x="-5" y="-32" width="10" height="36" fill="#c23b2e"/><rect x="-5" y="-32" width="10" height="7" fill="#7a1d16"/><path d="M-5,4 L0,14 L5,4Z" fill="${D}"/></g>`,
    headset: `<path d="M22,64 A42,42 0 0 1 106,64" fill="none" stroke="${D}" stroke-width="9"/><rect x="11" y="53" width="19" height="25" rx="7" fill="${D}"/><rect x="98" y="53" width="19" height="25" rx="7" fill="${D}"/>
      <path d="M21,76 Q24,95 44,95" fill="none" stroke="${D}" stroke-width="6" stroke-linecap="round"/><circle cx="47" cy="95" r="7" fill="${D}"/>`,
    cap: `<path d="M27,49 C27,22 46,11 64,11 C82,11 101,22 101,49Z" fill="#4f7896"/><path d="M58,42 H118 Q125,43 121,51 H58Z" fill="#35556c"/>
      <g transform="translate(2 100) rotate(-20)"><rect x="0" y="0" width="62" height="17" fill="#c4834a"/><rect x="0" y="0" width="62" height="6" fill="#e5b06e"/></g>`,
    clerk: `<path d="M64,99 L46,90 V108Z M64,99 L82,90 V108Z" fill="${D}"/><circle cx="64" cy="99" r="5" fill="${D}"/>
      <g transform="translate(88 64) rotate(10) scale(1.2)"><rect x="0" y="0" width="32" height="42" rx="3" fill="#7a4422"/><rect x="4.5" y="7" width="23" height="31" fill="#fffaf0"/><rect x="9" y="-5" width="14" height="10" rx="2.5" fill="#c9ccd0"/><rect x="9" y="16" width="14" height="4.5" fill="#8f8a82"/><rect x="9" y="25" width="10" height="4.5" fill="#8f8a82"/></g>`,
    box: `<rect x="30" y="74" width="68" height="44" fill="#d4b07a"/><rect x="30" y="74" width="68" height="10" fill="#b98f55"/><rect x="57" y="74" width="14" height="44" fill="#ecd2a6"/>`,
    tag: `<path d="M96,64 q14,6 15,20" fill="none" stroke="#6b5a40" stroke-width="3.5"/>
      <g transform="translate(108 82) rotate(-10) scale(1.35)"><path d="M-14,6 L0,-6 L16,-6 V30 H-14Z" fill="#fffaf0" stroke="#e8b04e" stroke-width="4" stroke-linejoin="round"/><circle cx="0" cy="3" r="3" fill="#a87a2e"/><rect x="-8" y="13" width="18" height="4.5" fill="#e07f3a"/></g>`,
    wrench: `<g transform="translate(106 86) rotate(-38) scale(1.2)"><rect x="-6" y="-4" width="12" height="44" rx="5" fill="#6f7a82"/><path d="M-15,-6 A16,16 0 1 1 15,-6 L7,-6 L7,-20 L-7,-20 L-7,-6Z" fill="#6f7a82" transform="rotate(180 0 -8)"/></g>`,
    laptop: `<g transform="translate(60 74) rotate(-4) scale(1.3)"><rect x="0" y="0" width="46" height="30" rx="3" fill="#c9c4bb"/><rect x="-5" y="30" width="56" height="8" rx="2.5" fill="#8f8a82"/><circle cx="23" cy="15" r="5" fill="#c23b2e"/></g>`,
  };
  function miniSVG(name, o = {}) {
    const w = who(name), size = +o.size || 16, v = MINI[o.variant] ? o.variant : MV[w];
    ensure(w);
    const d = (hash(String(o.seed || v)) % 13) * -0.37;
    const title = o.title ? `<title>${String(o.title).replace(/[&<>]/g, '')}</title>` : '';
    const eyes = `<circle cx="52" cy="68" r="6.5" fill="${INK}"/><circle cx="76" cy="68" r="6.5" fill="${INK}"/>`;
    return `<svg class="cav mini${o.still ? ' still' : ''}" data-who="${w}" data-v="${v}" width="${size}" height="${size}" viewBox="4 2 124 124" aria-hidden="true">${title}
    <g class="cv-fl" style="animation-delay:${d}s"><path d="${P}" fill="url(#cav-${w}-g)"/>${eyes}${MINI[v]}</g></svg>`;
  }

  function avatarSVG(name, o = {}) {
    if (o.mini) return miniSVG(name, o);
    const w = who(name), t = T[w], c = C[w], size = +o.size || 22, state = stateOf(o.state);
    const tiny = size <= 18, small = size < 40;
    ensure(w);
    const k = 'cav-' + w + '-', d = (hash(w + size) % 13) * -0.37;
    const fs = size <= 24 ? 1.45 : small ? 1.3 : 1, cy = 66;
    // tiny: hat silhouette only, no props, no state props that would turn into specks
    const ex = tiny ? (state === 'away' ? '' : state === 'talking' ? extras(state, t) : '') : extras(state, t);
    const body = `<path d="${P}" fill="url(#${k}g)"/>
    ${c.hat(tiny)}`;
    const glow = state === 'working' && !tiny ? `<path class="cv-glow" d="${P}" fill="none" stroke="${t.g[1]}" stroke-width="5"/>` : '';
    const faceG = `<g transform="translate(64 ${cy}) scale(${fs}) translate(-64 -${cy})">${face(w, state, cy, tiny)}</g>`;
    const title = o.title ? `<title>${String(o.title).replace(/[&<>]/g, '')}</title>` : '';
    return `<svg class="cav s-${state}${o.still ? ' still' : ''}${tiny ? ' tiny' : ''}" data-who="${w}" width="${size}" height="${size}" viewBox="${small ? '8 1 113 113' : '2 0 124 124'}" aria-hidden="true">${title}
    <g class="cv-fl" style="animation-delay:${d}s"><g class="cv-body">
      ${glow}
      <g class="cv-br" style="animation-delay:${d}s">${body}</g>
      ${faceG}${tiny ? '' : c.front(state)}${state === 'writing' && !tiny ? writing(t) : ''}
    </g>${ex}</g></svg>`;
  }

  window.avatarSVG = avatarSVG;
  window.avatarState = stateOf;
  window.avatarMiniVariant = miniVariant;
  window.avatarWho = who;
  window.AVATAR_COLORS = Object.fromEntries((OFF.team || []).map(m => [m.name, m.color || '#8a8478']));
})();
