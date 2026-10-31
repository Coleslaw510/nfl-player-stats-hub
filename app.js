(() => {
'use strict';
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const HEAD = 'https://static.www.nfl.com/image/upload/f_auto,q_auto/league/';
const PH = 'data:image/svg+xml;utf8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" fill="#1d2840"/><circle cx="20" cy="15" r="7" fill="#33405c"/><path d="M6 38c2-9 8-13 14-13s12 4 14 13" fill="#33405c"/></svg>');
const COLORS = ['#ff6b2c', '#3aa0ff', '#2ecc8f', '#c77dff'];
const GROUPS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'IDL', 'LB', 'CB', 'S'];
const GNAME = {QB:'Quarterbacks',RB:'Running backs',WR:'Wide receivers',TE:'Tight ends',OL:'Offensive line',EDGE:'Edge rushers',IDL:'Interior DL',LB:'Linebackers',CB:'Cornerbacks',S:'Safeties'};
const RADAR = {
  QB:['pass_ypg','epa_db','cpoe','ypa','anya','rating','pass_td','succ_db'],
  RB:['rush_ypg','ypc','epa_rush','succ_rush','ryoe_att','rec_ypg','scrim_ypg','total_td'],
  WR:['rec_ypg','ypdb','ypt','epa_tgt','catch_pct','tgt_share','yac','rec_td'],
  TE:['rec_ypg','ypdb','ypt','epa_tgt','catch_pct','tgt_share','yac','rec_td'],
  EDGE:['sacks','pressures','prs_100','qb_hits','tfl','tackles','ff','hurries'],
  IDL:['sacks','pressures','prs_100','qb_hits','tfl','tackles','ff','hurries'],
  LB:['tackles','tfl','sacks','pressures','pd','ints','missed_tkl_pct','rating_allowed'],
  CB:['ints','pd','rating_allowed','yds_allowed_tgt','cmp_allowed_pct','tackles','missed_tkl_pct','ff'],
  S:['ints','pd','tackles','rating_allowed','yds_allowed_tgt','tfl','missed_tkl_pct','ff'],
  OL:[]};
const QUICK = [['pass_ypg','QB'],['rush_ypg','RB'],['ypdb','WR'],['epa_db','QB'],['epa_rush','RB'],['epa_tgt','WR'],['prwr','EDGE'],['rswr','EDGE'],['pbwr','OL'],['rbwr','OL'],['sacks','EDGE'],['pressures','EDGE']];
const PRESETS = [
  {l:'QBs · EPA/dropback vs pass YPG',x:'pass_ypg',y:'epa_db',g:'QB'},
  {l:'RBs · EPA/rush vs rush YPG',x:'rush_ypg',y:'epa_rush',g:'RB'},
  {l:'WRs · EPA/target vs rec YPG',x:'rec_ypg',y:'epa_tgt',g:'WR'},
  {l:'WR/TE · YPRR proxy vs yards/target',x:'ypt',y:'ypdb',g:'WR'},
  {l:'QBs · CPOE vs aDOT',x:'adot',y:'cpoe',g:'QB'},
  {l:'Edge · sacks vs pressures',x:'pressures',y:'sacks',g:'EDGE'},
  {l:'CB · rating allowed vs targets',x:'tgt_allowed',y:'rating_allowed',g:'CB'}];

const cache = {}; let D, P, BY, ST, SEASON = 2026, charts = {};
const img = h => !h ? PH : h[0] === '~' ? HEAD + h.slice(1) : h;
const norm = s => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\b(jr|sr|ii|iii|iv)\b\.?/g, '').replace(/[^a-z ]/g, '').replace(/\s+/g, ' ').trim();
const slug = s => norm(s).replace(/ /g, '-');
function fv(k, v) { const s = ST[k]; if (v == null) return '—'; switch (s.fmt) {
  case 'int': return Math.round(v).toLocaleString(); case 'f1': return v.toFixed(1); case 'f2': return v.toFixed(2); case 'f3': return (v >= 0 ? '+' : '') + v.toFixed(3);
  case 'pct0': return Math.round(v) + '%'; case 'pct1': return v.toFixed(1) + '%'; default: return String(v); } }
const pctColor = p => `hsl(${Math.round(p * 1.25)},75%,52%)`;
const ord = n => n + (['th','st','nd','rd'][(n % 100 - 20) % 10] || ['th','st','nd','rd'][n % 100] || 'th');
function isQual(p, s) { if (s.q === 'none') return true; if (s.q === 'espn') return p.s[s.k] != null;
  return p.q.includes(s.q) && (s.q === 'snap' || p.q.includes('snap') || ['pass','rush','recv'].includes(s.q)); }
const qtext = q => D.meta.qualifiers[q] || '';
function toast(t) { const e = $('#toast'); e.textContent = t; e.classList.add('on'); setTimeout(() => e.classList.remove('on'), 1800); }

async function load(season) {
  if (!cache[season]) cache[season] = fetch(`data/players_${season}.json`).then(r => r.json()).then(d => {
    { const ord = [...new Set(d.stats.map(s => s.cat))]; d.stats = d.stats.map((s, i) => [ord.indexOf(s.cat), i, s]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(x => x[2]); }
    d.byId = Object.fromEntries(d.players.map(p => [p.id, p])); d.ST = Object.fromEntries(d.stats.map(s => [s.k, s]));
    d.players.forEach(p => { p._n = norm(p.n); p._toks = p._n.split(' '); p._snap = (p.s.off_snaps || 0) + (p.s.def_snaps || 0); }); return d; });
  return cache[season];
}
async function setSeason(s, keep) {
  SEASON = +s; D = await load(SEASON); P = D.players; BY = D.byId; ST = D.ST;
  $$('#season-seg button').forEach(b => b.setAttribute('aria-pressed', +b.dataset.s === SEASON));
  const m = D.meta; $('#asof').textContent = `${SEASON} regular season · through Week ${m.through_week} (${new Date(m.last_game + 'T12:00').toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'})})`;
  footer(); initLeaders(); initTable(); glossary(); loadTV().then(tvHow);
  if (!keep) route();
}

// ---------- search / typeahead ----------
function searchPlayers(q, n = 8) {
  q = norm(q); if (!q) return []; const qt = q.split(' ');
  const hits = [];
  for (const p of P) { let sc = 0;
    if (p._n === q) sc = 100; else if (p._n.startsWith(q)) sc = 80; else if (qt.every(t => p._toks.some(x => x.startsWith(t)))) sc = 60; else if (p._n.includes(q)) sc = 30;
    if (sc) hits.push([sc + Math.min(p._snap / 60, 15) + (p.g ? 5 : 0), p]); }
  return hits.sort((a, b) => b[0] - a[0]).slice(0, n).map(h => h[1]);
}
function typeahead(input, box, onPick) {
  let items = [], sel = 0;
  const render = () => { box.innerHTML = items.map((p, i) => `<div class="it ${i === sel ? 'sel' : ''}" data-i="${i}"><img loading="lazy" src="${img(p.h)}" onerror="this.src='${PH}'"><div><div class="nm">${p.n}</div><div class="sub">${p.p || p.gr} · ${p.t || 'FA'} · ${p.g} G${p.g ? '' : ' (no games this season)'}</div></div></div>`).join('');
    box.classList.toggle('on', items.length > 0); };
  input.addEventListener('input', () => { items = searchPlayers(input.value); sel = 0; render(); });
  input.addEventListener('keydown', e => { if (!items.length) return;
    if (e.key === 'ArrowDown') { sel = (sel + 1) % items.length; render(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { sel = (sel - 1 + items.length) % items.length; render(); e.preventDefault(); }
    else if (e.key === 'Enter') { pick(items[sel]); e.preventDefault(); } else if (e.key === 'Escape') { box.classList.remove('on'); } });
  box.addEventListener('mousedown', e => { const it = e.target.closest('.it'); if (it) { e.preventDefault(); pick(items[+it.dataset.i]); } });
  input.addEventListener('blur', () => setTimeout(() => box.classList.remove('on'), 120));
  function pick(p) { box.classList.remove('on'); input.value = ''; items = []; input.blur(); onPick(p); }
}

// ---------- routing ----------
let TAB = 'leaders';
function go(hash) { if (location.hash !== hash) location.hash = hash; else route(); }
function showTab(t) { TAB = t; $$('.tab').forEach(s => s.hidden = s.id !== 'tab-' + t); $$('#tabs a').forEach(a => a.classList.toggle('on', a.dataset.tab === t)); }
async function route() {
  const h = decodeURIComponent(location.hash.slice(1)); const [main, ...rest] = h.split('&');
  const params = Object.fromEntries(rest.map(x => x.split('=')));
  if (params.season && +params.season !== SEASON) { await setSeason(params.season, true); }
  const [tab, arg] = (main || 'leaders').split('=');
  const t = ['leaders','compare','player','table','trade','glossary'].includes(tab) ? tab : 'leaders';
  showTab(t);
  if (t === 'leaders') drawLeaders();
  if (t === 'player') { const p = arg ? resolve(arg) : null; renderPlayer(p); }
  if (t === 'compare') { cmpIds = (arg ? arg.split(',').map(resolve).filter(Boolean).map(p => p.id) : cmpIds).slice(0, 4); renderCompare(); }
  if (t === 'table') drawTable();
  if (t === 'trade') { await loadTV(); drawTV(); }
  if (t === 'glossary' && arg === 'trade') { await loadTV(); tvHow(); }
  window.scrollTo({top: 0, behavior: 'instant' in window ? 'instant' : 'auto'});
}
function resolve(tok) {
  if (BY[tok]) return BY[tok];
  const s = slug(tok.replace(/-/g, ' ')); let c = P.filter(p => slug(p.n) === s);
  if (!c.length) { const parts = s.split('-'); c = P.filter(p => parts.every(t => p._toks.includes(t))); }
  if (!c.length) c = searchPlayers(tok.replace(/-/g, ' '), 5);
  return c.sort((a, b) => fame(b) - fame(a))[0] || null;
}
function fame(p) { let f = p._snap + p.g * 10; for (const s of Object.values(cache)) {} // current season
  const o = otherSeason(); if (o) { const q = o.byId[p.id]; if (q) f += q._snap * 0.8; } return f; }
let OTHER = null; function otherSeason() { return OTHER && OTHER.meta.season !== SEASON ? OTHER : null; }
const sLink = () => SEASON !== 2026 ? `&season=${SEASON}` : '';
const shareSlug = p => slug(p.n);

// ---------- leaders ----------
function statOptions(sel, filter) {
  const cats = {}; D.stats.filter(filter || (() => true)).forEach(s => (cats[s.cat] ??= []).push(s));
  sel.innerHTML = Object.entries(cats).map(([c, ss]) => `<optgroup label="${c}">${ss.map(s => `<option value="${s.k}">${s.label}</option>`).join('')}</optgroup>`).join('');
}
function initLeaders() {
  statOptions($('#ld-stat'), s => s.hb !== null || s.k === 'ttt'); if (!ST[$('#ld-stat').dataset.v]) $('#ld-stat').value = 'pass_ypg'; else $('#ld-stat').value = $('#ld-stat').dataset.v;
  ldPos(); $('#sc-preset').innerHTML = PRESETS.map((p, i) => `<option value="${i}">${p.l}</option>`).join('') + '<option value="c">Custom…</option>';
  statOptions($('#sc-x')); statOptions($('#sc-y')); $('#sc-pos').innerHTML = GROUPS.map(g => `<option>${g}</option>`).join('');
  applyPreset(+($('#sc-preset').value || 0));
  // quick cards
  $('#quick').innerHTML = QUICK.map(([k, g]) => { const s = ST[k]; const l = leaders(k, g, 1, true)[0]; if (!l) return '';
    return `<div class="qc" data-k="${k}" data-g="${g}"><img loading="lazy" src="${img(l.h)}" onerror="this.src='${PH}'"><div><div class="l">${s.label.replace(' (ESPN)', '')}${s.q === 'espn' ? ' · ESPN' : ''}</div><div class="n">${l.n} <span class="muted small">${l.t}</span></div><div class="v">${fv(k, l.s[k])}</div></div></div>`; }).join('');
}
function ldPos() { const s = ST[$('#ld-stat').value]; const cur = $('#ld-pos').value;
  $('#ld-pos').innerHTML = (s.groups.length > 1 ? `<option value="all">All eligible (${s.groups.join('/')})</option>` : '') + s.groups.map(g => `<option value="${g}">${GNAME[g]}</option>`).join('');
  if ([...$('#ld-pos').options].some(o => o.value === cur)) $('#ld-pos').value = cur; }
function leaders(k, g, n, qual) { const s = ST[k];
  let xs = P.filter(p => p.s[k] != null && (g === 'all' ? s.groups.includes(p.gr) : p.gr === g) && (!qual || isQual(p, s)));
  const dir = s.hb === 0 ? 1 : -1; xs.sort((a, b) => dir * (a.s[k] - b.s[k]) || (s.q === 'espn' ? (a.wr[k].rank - b.wr[k].rank) : 0)); return xs.slice(0, n); }
function drawLeaders() {
  const k = $('#ld-stat').value, s = ST[k], g = $('#ld-pos').value, n = +$('#ld-n').value, qual = $('#ld-q').checked;
  const xs = leaders(k, g, n, qual);
  $('#ld-title').textContent = `${s.label} leaders`;
  let note = s.desc ? `<b>${s.desc}</b> ` : '';
  note += s.q === 'espn' ? `Source: <a href="${D.meta.espn.meta?.url}" target="_blank" rel="noopener">ESPN win rates</a>, ${D.meta.espn.meta?.updated || ''}. ESPN publishes only its top players for each list; everyone else is "not published".`
    : qual ? `Qualified: ${qtext(s.q)}${s.q !== 'snap' ? ' and ' + qtext('snap') : ''}.` : 'All players with a value.';
  if (s.hb === 0) note += ' Lower is better.';
  $('#ld-note').innerHTML = note;
  $('#ld-box').style.height = Math.max(240, xs.length * 34 + 60) + 'px';
  const data = { labels: xs.map(p => `${p.n} · ${p.t}`), datasets: [{ data: xs.map(p => p.s[k]), backgroundColor: xs.map((_, i) => `hsla(${18 + i * (190 / Math.max(xs.length, 1))},85%,58%,.9)`), borderRadius: 7, barThickness: 'flex', maxBarThickness: 26 }] };
  const opt = { indexAxis: 'y', responsive: true, maintainAspectRatio: false, animation: { duration: 350 },
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => { const p = xs[c.dataIndex]; const wr = p.wr && p.wr[k];
      return `${fv(k, c.raw)}${wr ? ` · ESPN ${wr.list} #${wr.rank} (${wr.wins}/${wr.plays})` : ''} · ${p.p} · ${p.g} G`; } } } },
    scales: { x: { grid: { color: '#1b2438' }, ticks: { color: '#8b97ad' }, beginAtZero: s.fmt !== 'f3' }, y: { grid: { display: false }, ticks: { color: '#eaf0fa', font: { size: 12, weight: 600 } } } },
    onClick: (e, els) => { if (els.length) go(`#player=${xs[els[0].index].id}${sLink()}`); } };
  if (charts.ld) { charts.ld.data = data; charts.ld.options = opt; charts.ld.update(); } else charts.ld = new Chart($('#ld-chart'), { type: 'bar', data, options: opt });
  drawScatter();
}
function applyPreset(i) { const p = PRESETS[i]; if (!p) return; $('#sc-x').value = p.x; $('#sc-y').value = p.y; $('#sc-pos').value = p.g; }
const labelPlugin = { id: 'lbl', afterDatasetsDraw(c) { const ds = c.data.datasets[0]; if (!ds || !ds._lbl) return; const ctx = c.ctx; ctx.save(); ctx.font = '600 11px Inter,system-ui,sans-serif'; ctx.fillStyle = '#eaf0fa';
  c.getDatasetMeta(0).data.forEach((pt, i) => { if (ds._lbl.has(i)) ctx.fillText(ds.data[i].p.n.split(' ').slice(-1)[0], pt.x + 6, pt.y - 6); }); ctx.restore(); } };
function drawScatter() {
  const x = $('#sc-x').value, y = $('#sc-y').value, g = $('#sc-pos').value, sx = ST[x], sy = ST[y];
  const xs = P.filter(p => (p.gr === g || (g === 'WR' && $('#sc-preset').value === '3' && p.gr === 'TE')) && p.s[x] != null && p.s[y] != null && isQual(p, sx) && isQual(p, sy));
  const pts = xs.map(p => ({ x: p.s[x], y: p.s[y], p }));
  const mx = pts.reduce((a, b) => a + b.x, 0) / (pts.length || 1), my = pts.reduce((a, b) => a + b.y, 0) / (pts.length || 1);
  const sdx = Math.sqrt(pts.reduce((a, b) => a + (b.x - mx) ** 2, 0) / (pts.length || 1)) || 1, sdy = Math.sqrt(pts.reduce((a, b) => a + (b.y - my) ** 2, 0) / (pts.length || 1)) || 1;
  const dx = sx.hb === 0 ? -1 : 1, dy = sy.hb === 0 ? -1 : 1;
  const score = pts.map((q, i) => [Math.abs((q.x - mx) / sdx) + Math.abs((q.y - my) / sdy) + ((q.x - mx) * dx / sdx + (q.y - my) * dy / sdy), i]).sort((a, b) => b[0] - a[0]);
  const lbl = new Set(score.slice(0, Math.min(14, pts.length)).map(s => s[1]));
  $('#sc-note').innerHTML = `${pts.length} qualified ${GNAME[g]?.toLowerCase() || g}${$('#sc-preset').value === '3' ? ' + TEs' : ''}. Dashed lines = group average. ${sx.desc && sx.q !== 'espn' ? sx.label + ': ' + sx.desc + ' ' : ''}${sy.desc ? sy.label + ': ' + sy.desc : ''}`;
  const data = { datasets: [{ data: pts, _lbl: lbl, pointRadius: 5, pointHoverRadius: 8, backgroundColor: pts.map((q, i) => lbl.has(i) ? 'rgba(255,107,44,.9)' : 'rgba(58,160,255,.55)'), borderColor: 'rgba(0,0,0,.3)' },
    { type: 'line', data: [{ x: mx, y: Math.min(...pts.map(q => q.y)) }, { x: mx, y: Math.max(...pts.map(q => q.y)) }], borderColor: '#3a4660', borderDash: [5, 5], pointRadius: 0 },
    { type: 'line', data: [{ x: Math.min(...pts.map(q => q.x)), y: my }, { x: Math.max(...pts.map(q => q.x)), y: my }], borderColor: '#3a4660', borderDash: [5, 5], pointRadius: 0 }] };
  const opt = { responsive: true, maintainAspectRatio: false, animation: { duration: 300 }, plugins: { legend: { display: false }, tooltip: { filter: c => c.datasetIndex === 0, callbacks: { label: c => `${c.raw.p.n} (${c.raw.p.t}) · ${sx.label} ${fv(x, c.raw.x)} · ${sy.label} ${fv(y, c.raw.y)}` } } },
    scales: { x: { title: { display: true, text: sx.label, color: '#8b97ad' }, grid: { color: '#1b2438' }, ticks: { color: '#8b97ad' }, reverse: false }, y: { title: { display: true, text: sy.label, color: '#8b97ad' }, grid: { color: '#1b2438' }, ticks: { color: '#8b97ad' }, reverse: sy.hb === 0 } },
    onClick: (e, els) => { const el = els.find(e => e.datasetIndex === 0); if (el) go(`#player=${pts[el.index].p.id}${sLink()}`); } };
  if (charts.sc) charts.sc.destroy(); charts.sc = new Chart($('#sc-chart'), { type: 'scatter', data, options: opt, plugins: [labelPlugin] });
}

// ---------- player card ----------
function statCell(p, k) { const s = ST[k], v = p.s[k], r = p.r[k];
  if (s.q === 'espn') { if (v == null) return `<div class="sg"><div class="l"><span>${s.label}</span></div><div class="v np">Not published</div><div class="rk">ESPN lists only its top ${s.groups.includes('OL') ? '10–20 OT/IOL' : '10–20 Edge/DT'} players</div></div>`;
    const w = p.wr[k]; return `<div class="sg"><div class="l"><span>${s.label}</span><span class="tag espn">ESPN</span></div><div class="v">${fv(k, v)}</div><div class="rk">#${w.rank} of ESPN's top ${w.n} ${w.list} · ${w.wins} wins / ${w.plays} plays</div><div class="bar"><i style="width:${v}%;background:var(--accent2)"></i></div></div>`; }
  if (v == null) return '';
  const rk = r ? `<b>#${r[0]}</b> of ${r[2]} ${p.gr} · ${ord(r[1])} pct` : s.hb === null ? 'no rank (direction-neutral stat)' : `not qualified · ${qtext(s.q)}`;
  return `<div class="sg"><div class="l"><span>${s.label}</span>${/proxy/i.test(s.label) ? '<span class="tag proxy">proxy</span>' : ''}</div><div class="v">${fv(k, v)}</div><div class="rk">${rk}</div>${r ? `<div class="bar"><i style="width:${r[1]}%;background:${pctColor(r[1])}"></i></div>` : ''}</div>`; }
function renderPlayer(p) {
  if (!p) { $('#pcard').innerHTML = `<div class="card"><p class="muted">Search for any player above, or pick one from Leaders.</p><div class="quick">${['Josh Allen','Jaxon Smith-Njigba','Bijan Robinson','Will Anderson Jr.','Maxx Crosby','Fred Warner'].map(n => P.find(p => p.n === n)).filter(Boolean).map(p => `<div class="qc" onclick="location.hash='#player=${p.id}${sLink()}'"><img src="${img(p.h)}"><div><div class="l">${p.p} · ${p.t}</div><div class="n">${p.n}</div></div></div>`).join('')}</div></div>`; return; }
  const cats = {}; D.stats.filter(s => s.groups.includes(p.gr)).forEach(s => (cats[s.cat] ??= []).push(s.k));
  const o = otherSeason(), op = o && o.byId[p.id];
  $('#pcard').innerHTML = `<div class="card"><div class="pc-head"><img src="${img(p.h)}" onerror="this.src='${PH}'" alt=""><div style="flex:1;min-width:200px"><h1>${p.n}</h1>
    <div class="pills"><span class="pill"><b>${p.t || 'FA'}</b></span><span class="pill">${p.p} · ${GNAME[p.gr]}</span><span class="pill"><b>${p.g}</b> of ${p.tg || '—'} games</span>${p.ss != null ? `<span class="pill"><b>${p.ss}%</b> of team ${['QB','RB','WR','TE','OL'].includes(p.gr) ? 'off.' : 'def.'} snaps</span>` : ''}${p.st && p.st !== 'ACT' ? `<span class="pill warn">Roster status: ${p.st}</span>` : ''}${p.q.includes('snap') ? '' : '<span class="pill warn">Below 25% snap qualifier</span>'}</div></div>
    <div class="ctrls"><button class="btn" id="pc-cmp">Compare ⇄</button>${p.e ? `<a class="btn ghost" href="https://www.espn.com/nfl/player/_/id/${p.e}" target="_blank" rel="noopener">ESPN ↗</a>` : ''}</div></div>
    ${!p.g ? `<div class="banner">${p.n} has no ${SEASON} regular-season games through Week ${D.meta.through_week}.${op && op.g ? ` <button class="btn" id="pc-other">See his ${o.meta.season} season (${op.g} G) →</button>` : ''}</div>` : ''}</div>
    <div id="pc-tv"></div>
    ${Object.entries(cats).map(([c, ks]) => { const cells = ks.map(k => statCell(p, k)).join(''); return cells ? `<div class="cat-h">${c}</div><div class="statgrid">${cells}</div>` : ''; }).join('')}`;
  loadTV().then(() => { const el = $('#pc-tv'); if (el) el.innerHTML = tvCard(p); });
  $('#pc-cmp').onclick = () => { cmpIds = [p.id]; go(`#compare=${shareSlug(p)}${sLink()}`); };
  const ob = $('#pc-other'); if (ob) ob.onclick = () => go(`#player=${p.id}&season=${o.meta.season}`);
}

// ---------- compare ----------
let cmpIds = [];
function cmpHash() { return '#compare=' + cmpIds.map(id => shareSlug(BY[id])).join(',') + sLink(); }
function renderCompare() {
  cmpIds = cmpIds.filter(id => BY[id]);
  const ps = cmpIds.map(id => BY[id]);
  $('#cmp-pick').innerHTML = [0, 1, 2, 3].map(i => { const p = ps[i];
    if (p) return `<div class="slot filled" style="--c:${COLORS[i]}"><button class="x" data-i="${i}" title="Remove">✕</button><div class="who"><img src="${img(p.h)}" onerror="this.src='${PH}'"><div><div class="nm"><span class="dot"></span>${p.n}</div><div class="sub">${p.p} · ${p.t} · ${p.g} G${p.ss != null ? ` · ${p.ss}% snaps` : ''}</div></div></div></div>`;
    if (i > ps.length) return `<div class="slot" style="opacity:.4"></div>`;
    return `<div class="slot" style="--c:${COLORS[i]}"><div class="search"><input data-slot="${i}" type="search" placeholder="${i < 2 ? 'Add player ' + (i + 1) : 'Add another (optional)'}…" autocomplete="off"><div class="ta"></div></div></div>`; }).join('');
  $$('#cmp-pick .slot input').forEach(inp => typeahead(inp, inp.nextElementSibling, p => { if (!cmpIds.includes(p.id)) cmpIds.push(p.id); history.replaceState(null, '', cmpHash()); renderCompare(); }));
  $$('#cmp-pick .x').forEach(b => b.onclick = () => { cmpIds.splice(+b.dataset.i, 1); history.replaceState(null, '', cmpHash()); renderCompare(); });
  const groups = [...new Set(ps.map(p => p.gr))];
  const curSet = $('#cmp-set').value; $('#cmp-set').innerHTML = groups.map(g => `<option value="${g}">${GNAME[g]} stats</option>`).join('') + (groups.length ? '<option value="all">All stats</option>' : '');
  if ([...$('#cmp-set').options].some(o => o.value === curSet) && groups.includes(curSet)) $('#cmp-set').value = curSet;
  const set = $('#cmp-all').checked ? 'all' : ($('#cmp-set').value || groups[0]);
  // banners
  const o = otherSeason(); const idle = ps.filter(p => !p.g);
  $('#cmp-banner').innerHTML = idle.length ? `<div class="banner">${idle.map(p => `<b>${p.n}</b>`).join(', ')} ${idle.length > 1 ? 'have' : 'has'} not played a ${SEASON} regular-season game through Week ${D.meta.through_week}${idle.some(p => p.st && p.st !== 'ACT') ? ` (roster status: ${idle.map(p => p.st).join(', ')})` : ''}, so ${idle.length > 1 ? 'their' : 'his'} ${SEASON} columns are empty.${o && idle.some(p => o.byId[p.id]?.g) ? ` <button class="btn" id="cmp-other">Compare their ${o.meta.season} seasons →</button>` : ''}</div>` : '';
  const ob = $('#cmp-other'); if (ob) ob.onclick = () => go(cmpHash().replace(/&season=\d+/, '') + (o.meta.season !== 2026 ? `&season=${o.meta.season}` : ''));
  if (ps.length < 2) { $('#cmp-table').innerHTML = `<p class="muted">Pick at least two players. Try <a href="#compare=micah-parsons,montez-sweat&season=2025">Micah Parsons vs Montez Sweat (2025)</a>, <a href="#compare=josh-allen,lamar-jackson">Josh Allen vs Lamar Jackson</a>, or <a href="#compare=jaxon-smith-njigba,puka-nacua,ceedee-lamb">JSN vs Puka vs CeeDee</a>.</p>`; $('#cmp-score').innerHTML = ''; if (charts.radar) { charts.radar.destroy(); charts.radar = null; } return; }
  // rows
  const stats = D.stats.filter(s => set === 'all' ? ps.some(p => p.s[s.k] != null || (s.q === 'espn' && s.groups.includes(p.gr))) : s.groups.includes(set));
  const wins = ps.map(() => 0); let rowsN = 0; let html = `<div class="table-wrap" style="max-height:none;border:0"><table class="cmp-tbl"><thead><tr><th>Stat</th>${ps.map((p, i) => `<th style="color:${COLORS[i]}">${p.n}<span class="rk muted" style="display:block;font-weight:400">${p.p} · ${p.t}</span></th>`).join('')}</tr></thead><tbody>`;
  let cat = null;
  for (const s of stats) {
    if (s.cat !== cat) { cat = s.cat; html += `<tr class="cat"><td colspan="${ps.length + 1}">${cat}</td></tr>`; }
    const vals = ps.map(p => p.s[s.k]); const have = vals.filter(v => v != null);
    let best = null; if (have.length >= 2 && s.hb !== null) { best = s.hb ? Math.max(...have) : Math.min(...have); if (have.every(v => v === best)) best = null; }
    if (best != null) { rowsN++; vals.forEach((v, i) => { if (v === best) wins[i]++; }); }
    html += `<tr><td>${s.label}${/proxy/i.test(s.label) ? ' <span class="tag proxy">proxy</span>' : ''}</td>${ps.map((p, i) => { const v = p.s[s.k], r = p.r[s.k];
      let sub = '';
      if (s.q === 'espn') sub = v == null ? (s.groups.includes(p.gr) ? 'not published' : '') : `ESPN ${p.wr[s.k].list} #${p.wr[s.k].rank} of ${p.wr[s.k].n}`;
      else if (r) sub = `#${r[0]} ${p.gr} · ${ord(r[1])} pct`; else if (v != null && s.hb !== null) sub = 'not qualified';
      return `<td class="${v != null && v === best ? 'win' : ''}"><span class="v">${v == null ? (s.q === 'espn' && s.groups.includes(p.gr) ? '<span class="np">n/p</span>' : '—') : fv(s.k, v)}</span><span class="rk">${sub}</span></td>`; }).join('')}</tr>`;
  }
  html += '</tbody></table></div>';
  $('#cmp-table').innerHTML = `<div class="card-head"><h2>Every stat, side by side</h2><span class="muted small">▲ green = best in row (lower-is-better stats handled) · rank &amp; percentile are within each player's own position group among qualified players</span></div>` + html;
  $('#cmp-score').innerHTML = `<div class="score">${ps.map((p, i) => `<div class="row"><div><b style="color:${COLORS[i]}">${p.n}</b><div class="bar"><i style="width:${rowsN ? 100 * wins[i] / rowsN : 0}%;background:${COLORS[i]}"></i></div></div><div><b style="font-size:1.4rem">${wins[i]}</b><span class="muted small"> / ${rowsN}</span></div></div>`).join('')}</div><p class="note" style="margin-top:12px">Rows won among the ${rowsN} stats where at least two players have a value and there is a clear "better" direction. Volume stats favor players with more games, so check per-game and rate rows too.</p>`;
  // radar
  const rg = set === 'all' ? groups[0] : set; const keys = (RADAR[rg] || []).filter(k => ST[k]);
  if (charts.radar) charts.radar.destroy();
  if (keys.length) {
    $('#cmp-radar-note').textContent = `${GNAME[rg]} percentiles (0 = not qualified / no data)`;
    charts.radar = new Chart($('#cmp-radar'), { type: 'radar', data: { labels: keys.map(k => ST[k].label.replace(/ \(.*\)/, '')), datasets: ps.map((p, i) => ({ label: p.n, data: keys.map(k => p.r[k] && p.gr === rg ? p.r[k][1] : 0), borderColor: COLORS[i], backgroundColor: COLORS[i] + '33', pointBackgroundColor: COLORS[i], borderWidth: 2 })) },
      options: { responsive: true, maintainAspectRatio: false, animation: { duration: 400 }, plugins: { legend: { labels: { color: '#eaf0fa', boxWidth: 12 } }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${ord(c.raw)} pct` } } },
        scales: { r: { min: 0, max: 100, ticks: { display: false, stepSize: 25 }, grid: { color: '#26314a' }, angleLines: { color: '#26314a' }, pointLabels: { color: '#c9d3e6', font: { size: 11, weight: 600 } } } } } });
  } else $('#cmp-radar-note').textContent = 'No percentile radar for this position group (win rates are ESPN top-N only).';
}

// ---------- leaderboard table ----------
let tbSort = null, tbAsc = false, tbLimit = 100;
function initTable() { const cur = $('#tb-pos').value || 'QB'; $('#tb-pos').innerHTML = GROUPS.map(g => `<option value="${g}">${GNAME[g]}</option>`).join(''); $('#tb-pos').value = cur; tbCats(); }
function tbCats() { const g = $('#tb-pos').value; const cats = [...new Set(D.stats.filter(s => s.groups.includes(g)).map(s => s.cat))]; const cur = $('#tb-cat').value;
  $('#tb-cat').innerHTML = cats.map(c => `<option>${c}</option>`).join(''); if (cats.includes(cur)) $('#tb-cat').value = cur; }
function drawTable() {
  const g = $('#tb-pos').value, cat = $('#tb-cat').value, q = norm($('#tb-q').value), qual = $('#tb-qual').checked;
  const cols = D.stats.filter(s => s.groups.includes(g) && s.cat === cat);
  const qk = {Passing:'pass',Rushing:'rush',Receiving:'recv','Win rates':'espn'}[cat] || 'snap';
  let rows = P.filter(p => p.gr === g && cols.some(s => p.s[s.k] != null) && (!q || p._n.includes(q) || (p.t || '').toLowerCase() === q) && (!qual || isQual(p, {q: qk, k: cols[0].k})));
  if (!tbSort || !cols.some(s => s.k === tbSort)) { const pref = ['pass_yds','rush_yds','rec_yds','scrim_yds','tackles','sacks','ints','prwr','pbwr','off_snaps','def_snaps'].find(k => cols.some(s => s.k === k)); tbSort = pref || cols.find(s => s.hb === 1)?.k || cols[0].k; tbAsc = false; }
  const sk = tbSort; rows.sort((a, b) => { const x = a.s[sk], y = b.s[sk]; if (x == null) return 1; if (y == null) return -1; return tbAsc ? x - y : y - x; });
  $('#tb-note').innerHTML = `${rows.length} ${GNAME[g].toLowerCase()}${qual ? ` · qualified: ${qtext(qk)}` : ''}. Click a column to sort, or a row to open the player.`;
  $('#tb thead').innerHTML = `<tr><th class="l">#</th><th class="l">Player</th><th>G</th>${cols.map(s => `<th data-k="${s.k}" class="${s.k === sk ? 'sorted' + (tbAsc ? ' asc' : '') : ''}" title="${s.desc || ''}">${s.label.replace(' (ESPN)', '')}</th>`).join('')}</tr>`;
  $('#tb tbody').innerHTML = rows.slice(0, tbLimit).map((p, i) => `<tr data-id="${p.id}"><td class="l muted">${i + 1}</td><td class="l"><div class="pn"><img loading="lazy" src="${img(p.h)}" onerror="this.src='${PH}'"><span><b>${p.n}</b> <span class="muted small">${p.t || ''}</span></span></div></td><td>${p.g}</td>${cols.map(s => `<td>${s.q === 'espn' && p.s[s.k] == null ? '<span class="muted">n/p</span>' : fv(s.k, p.s[s.k])}</td>`).join('')}</tr>`).join('');
  $('#tb-more').hidden = rows.length <= tbLimit;
  $$('#tb th[data-k]').forEach(th => th.onclick = () => { if (tbSort === th.dataset.k) tbAsc = !tbAsc; else { tbSort = th.dataset.k; tbAsc = ST[tbSort].hb === 0; } drawTable(); });
}

// ---------- trade value ----------
let TV = null, tvSort = 'v', tvAsc = false, tvLimit = 100;
function loadTV() { return TV ? Promise.resolve(TV) : (TV = fetch('data/trade_values_2026.json').then(r => r.json()).then(d => (TV = d)).catch(() => (TV = {meta: null, players: {}}))); }
const money = v => v == null ? '—' : '$' + (v / 1e6).toFixed(v >= 1e7 ? 1 : 2) + 'M';
const pts = v => Math.round(v).toLocaleString();
function drvText(k, t, p) {
  switch (k) {
    case 'quality': return `Quality ${Math.round(t.Q)}/100${t.qs.now != null && t.qs.prev != null ? ` ('26 ${Math.round(t.qs.now)} · '25 ${Math.round(t.qs.prev)})` : ''}`;
    case 'age_dev': return `Age ${Math.floor(t.age)}`;
    case 'cap': return t.rk ? `Rookie deal (valued at ${p.gr} market rate for his quality)` : `$${t.apy.toFixed(1)}M APY (${t.apy_pct.toFixed(1)}% of cap)`;
    case 'control': return `${t.yl} contract yr${t.yl === 1 ? '' : 's'} of control`;
    case 'expiring': return 'Expiring deal';
    case 'pedigree': return 'Draft pedigree';
    case 'position': return `${p.gr} trade market`;
  } return k; }
function drivers(t, p, n = 5) {
  return Object.entries(t.drv).filter(([k, x]) => Math.abs(x) >= 0.03 && !(k === 'expiring' && t.yl > 1) && !(k === 'pedigree' && !t.ped)).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, n)
    .map(([k, x]) => { const pc = Math.round((Math.exp(x) - 1) * 100); return `<span class="drv ${x > 0 ? 'up' : 'dn'}" title="${pc > 0 ? '+' : ''}${pc}% vs. a typical traded player">${drvText(k, t, p)} <b>${x > 0 ? '+' : '−'}</b></span>`; }).join(''); }
function tvCard(p) {
  const t = TV && TV.players[p.id]; const m = TV && TV.meta;
  const head = `<div class="tv-h"><span class="cat-h" style="margin:0">Estimated trade value</span><a class="small" href="#glossary=trade">How this works</a></div>`;
  if (!m) return '';
  if (!t) return `<div class="card tv">${head}<p class="muted">No estimate: no ${m.season} or ${m.season - 1} playing time on file.</p></div>`;
  if (t.status !== 'ok') return `<div class="card tv">${head}<div class="tv-main"><div class="tv-big muted">Insufficient data</div><p class="muted small">${t.why}. Rather than guess, no number is shown.</p></div></div>`;
  const x = v => Math.max(0, Math.min(100, Math.log(v / 60) / Math.log(8000 / 60) * 100));
  const comps = t.comps.map(c => `<div class="tv-comp"><div><b>${c.n}</b> <span class="muted small">${c.g} · age ${c.a} · ${c.ft}→${c.tt}</span></div><div class="small">${new Date(c.d + 'T12:00').toLocaleDateString(undefined, {month: 'short', year: 'numeric'})} · ${c.ret}</div><div class="tv-pts">${pts(c.v)} pts</div></div>`).join('');
  return `<div class="card tv">${head}
   <div class="tv-grid"><div class="tv-main">
     <div class="tv-big">${t.desc}</div>
     <div class="tv-sub"><b>${pts(t.v)}</b> draft-pick points <span class="muted">(range ${pts(t.lo)}–${pts(t.hi)})</span> <span class="conf ${t.conf.toLowerCase()}">${t.conf} confidence</span></div>
     <div class="tv-range"><i style="left:${x(t.lo)}%;width:${x(t.hi) - x(t.lo)}%"></i><b style="left:${x(t.v)}%"></b>${[['7th', 208], ['3rd', 80], ['1st', 16], ['2×1st', 8]].map(([l, n]) => `<span style="left:${x(l === '2×1st' ? 2 * 1540 : {208: 210, 80: 650, 16: 1540}[n])}%">${l}</span>`).join('')}</div>
     <div class="drvs">${drivers(t, p)}</div>
     <div class="tv-facts small muted">Age ${t.age} · quality ${Math.round(t.Q)}/100 · ${t.rk ? 'rookie contract' : 'veteran contract'}: $${t.apy.toFixed(2)}M APY (${t.apy_pct}% of cap)${t.cap != null ? ` · 2026 cap hit ${money(t.cap)}` : ''} · ${t.yl} yr${t.yl === 1 ? '' : 's'} left${t.gtd != null ? ` · ${money(t.gtd)} guaranteed salary remaining` : ''}</div>
     ${t.notes.length ? `<div class="tv-notes small">${t.notes.map(n => `<div>⚠ ${n}</div>`).join('')}</div>` : ''}
   </div>
   <div class="tv-comps"><div class="small muted" style="margin-bottom:6px">Most similar real trades</div>${comps}</div></div></div>`; }
function initTV() { if (!$('#tv-pos').options.length) $('#tv-pos').innerHTML = `<option value="">All positions</option>` + GROUPS.map(g => `<option value="${g}">${GNAME[g]}</option>`).join(''); }
function drawTV() {
  initTV(); const m = TV.meta; if (!m) { $('#tv-note').textContent = 'Trade values unavailable.'; return; }
  const B = cache[m.season] ? null : null; const src = cache[2026];
  Promise.resolve(src).then(d => {
    const g = $('#tv-pos').value, cf = $('#tv-conf').value, ag = +$('#tv-age').value || 99, q = norm($('#tv-q').value);
    const okc = c => !cf || (cf === 'High' ? c === 'High' : c !== 'Low');
    let rows = Object.entries(TV.players).filter(([, t]) => t.status === 'ok').map(([id, t]) => ({p: d.byId[id], t})).filter(r => r.p && (!g || r.p.gr === g) && okc(r.t.conf) && r.t.age < ag && (!q || r.p._n.includes(q) || (r.p.t || '').toLowerCase() === q));
    const key = {v: r => r.t.v, age: r => r.t.age, Q: r => r.t.Q, apy: r => r.t.apy, apy_pct: r => r.t.apy_pct, yl: r => r.t.yl, cap: r => r.t.cap ?? -1, conf: r => ({High: 3, Medium: 2, Low: 1})[r.t.conf], n: r => r.p.n}[tvSort];
    rows.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * (tvAsc ? 1 : -1); });
    const nIns = Object.values(TV.players).filter(t => t.status !== 'ok').length;
    $('#tv-asof').textContent = `· as of ${m.as_of}`;
    $('#tv-note').innerHTML = `${rows.length.toLocaleString()} players with an estimate (${nIns} more marked <i>insufficient data</i>). Values are Over The Cap draft-pick points (pick #1 = 3,000; a mid 1st ≈ 1,540; a 3rd ≈ 650). Model fit on ${m.model.n_trades} real veteran trades (${m.model.date_range[0].slice(0, 4)}–${m.model.date_range[1].slice(0, 7)}), recent trades weighted more. <a href="#glossary=trade">How it works</a>.`;
    const cols = [['n', 'Player', 'l'], ['age', 'Age'], ['Q', 'Quality'], ['apy', 'APY'], ['apy_pct', '% cap'], ['cap', '2026 cap hit'], ['yl', 'Yrs left'], ['v', 'Value (pts)'], [null, 'Range'], [null, '≈ Picks', 'l'], ['conf', 'Confidence']];
    $('#tv thead').innerHTML = `<tr><th class="l">#</th>${cols.map(([k, l, c]) => `<th ${k ? `data-k="${k}"` : ''} class="${c || ''} ${k === tvSort ? 'sorted' + (tvAsc ? ' asc' : '') : ''}">${l}</th>`).join('')}</tr>`;
    $('#tv tbody').innerHTML = rows.slice(0, tvLimit).map(({p, t}, i) => `<tr data-id="${p.id}"><td class="l muted">${i + 1}</td><td class="l"><div class="pn"><img loading="lazy" src="${img(p.h)}" onerror="this.src='${PH}'"><span><b>${p.n}</b> <span class="muted small">${p.p || p.gr} · ${p.t || 'FA'}</span></span></div></td><td>${t.age.toFixed(1)}</td><td>${Math.round(t.Q)}</td><td>${t.rk ? '<span class="muted small">rookie</span> ' : ''}$${t.apy.toFixed(1)}M</td><td>${t.apy_pct.toFixed(1)}%</td><td>${money(t.cap)}</td><td>${t.yl}</td><td><b>${pts(t.v)}</b></td><td class="muted small">${pts(t.lo)}–${pts(t.hi)}</td><td class="l small">${t.desc.replace('≈ ', '')}</td><td><span class="conf ${t.conf.toLowerCase()}">${t.conf}</span></td></tr>`).join('');
    $('#tv-more').hidden = rows.length <= tvLimit;
    $$('#tv th[data-k]').forEach(th => th.onclick = () => { if (tvSort === th.dataset.k) tvAsc = !tvAsc; else { tvSort = th.dataset.k; tvAsc = tvSort === 'n' || tvSort === 'age'; } drawTV(); });
  }); }
function tvHow() {
  const m = TV && TV.meta; if (!m) { $('#tv-how').innerHTML = '<p class="muted">Trade values unavailable.</p>'; return; }
  const M = m.model, c = M.coef, L = M.loo, T = M.time_split, pc = x => Math.round(x * 100) + '%';
  $('#tv-how').innerHTML = `<p><b>What the number means.</b> Each estimate is the draft-pick package a team would most likely give up for the player today, in <b>Over The Cap (Fitzgerald-Spielberger) draft-value points</b> (pick #1 = 3,000, #16 = 1,540, #32 = 1,175, #64 = 810, #96 = 596, #224 = 150). The "≈ late 1st + 3rd" line is the simplest 1–3 pick combination with about the same points. Future picks in the data are valued at the middle of their round and pushed back one round per year out.</p>
  <p><b>Calibration data.</b> ${M.n_dataset} real veteran trades where one player moved for draft picks, ${M.date_range[0]} to ${M.date_range[1]} (including 2026 deadline deals so far): <a href="https://github.com/nflverse/nfldata/blob/master/data/trades.csv" target="_blank" rel="noopener">nflverse trade log</a> plus 2026 deals cited to <a href="https://www.profootballrumors.com/2026/08/2026-nfl-trades" target="_blank" rel="noopener">Pro Football Rumors</a>, <a href="https://www.nfl.com/news/nfl-trade-deadline-track-every-move-since-start-of-2026-regular-season" target="_blank" rel="noopener">NFL.com</a> and ESPN. Player-for-player swaps (e.g. Myles Garrett for Jared Verse + picks, Micah Parsons for Kenny Clark + picks) are excluded because the player coming back can't be priced in picks. Each trade records age, position, contract (Over The Cap) and the player's quality going in. <a href="https://github.com/Coleslaw510/nfl-player-stats-hub/blob/main/trades/trades.csv" target="_blank" rel="noopener">Full dataset (CSV)</a>.</p>
  <p><b>Quality (0–100).</b> For each season: 65% the average of his percentile ranks in the position's key stats (e.g. EDGE: pressures, pressure rate, sacks, QB hits, TFL, ESPN win rates; WR: yards/game, yards per team dropback, EPA/target, target share), plus 35% playing time (snap share). Offensive linemen have no box-score stats, so they get 70% of snap share, raised to 80–100 if they appear on an ESPN block win-rate list. Current players blend 2026 (55%) and 2025 (45%).</p>
  <p><b>The model</b> is a weighted ridge regression of log(points) on quality, age, contract (APY as % of cap; rookie-scale deals use what a veteran of the same quality earns at that position, since a rookie salary says nothing about value), years of control, expiring deal, young-player draft pedigree and position. ${M.n_trades} trades had complete inputs. Trades are weighted by recency with a ${M.half_life_years}-year half-life, so a trade 2½ years old counts half as much. Coefficients: quality ${c.quality > 0 ? '+' : ''}${(c.quality).toFixed(2)} per 25 pts, age ${(c.age_dev * 100).toFixed(1)}% per year, contract +${(c.cap).toFixed(2)} per 10% of cap, control ${(c.control * 100).toFixed(0) > 0 ? '+' : ''}${(c.control * 100).toFixed(0)}% per year. Because regression pulls extremes toward the middle (stars were coming out too cheap), predictions are stretched ×${M.stretch.s.toFixed(2)} around the average.</p>
  <p><b>Why bigger contracts mean more value here:</b> in real trades, well-paid players brought back more picks, because salary signals how the league values a player. A "market minus actual pay" surplus term and guarantee share were tested and did worse in cross-validation, so they're shown on the card but not used in the formula.</p>
  <p><b>Accuracy.</b> Leave-one-out: the median miss is ×${L.median_ratio.toFixed(2)} (actual vs predicted), ${pc(L.within_x2)} of trades within 2×, rank correlation ${L.spearman.toFixed(2)}. Out-of-time backtest (fit on trades before March 2025, test on the ${T.n} since): median miss ×${T.median_ratio.toFixed(2)}, ${pc(T.within_x2)} within 2×. Guessing the average every time misses by ×${Math.exp(M.baseline_median_abs_log).toFixed(2)}. The range shown is ±1 standard error (about ⅔ of real trades land inside it).</p>
  <p><b>Confidence</b> is High with two qualified seasons, 10+ games and Over The Cap cap data on file; it drops for missing seasons, and QBs and OL are capped at Medium (few comparable QB-for-picks trades; no box-score stats for OL). <b>Insufficient data</b>: under 3 games this season and under 4 last season, no birth date, or no contract on file.</p>
  <p><b>Caveats.</b> Trade prices also depend on things no public data covers: injuries, holdouts and extensions signed on arrival, the buyer's urgency, and conditional picks (counted at face value). Elite young players on rookie deals and franchise QBs almost never get traded for picks alone, so their numbers are extrapolations. Treat the estimate as a starting point, not an appraisal.</p>`; }

// ---------- glossary / footer ----------
function glossary() {
  const cats = {}; D.stats.forEach(s => (cats[s.cat] ??= []).push(s));
  $('#gloss').innerHTML = Object.entries(cats).map(([c, ss]) => `<div class="cat-h">${c}</div><div class="gl">${ss.map(s => `<div><b>${s.label}${/proxy/i.test(s.label) ? '<span class="tag proxy">proxy</span>' : ''}${s.q === 'espn' ? '<span class="tag espn">ESPN</span>' : ''}${/PFR/.test(s.label) ? '<span class="tag">PFR</span>' : ''}${/NGS/.test(s.desc) ? '<span class="tag">NGS</span>' : ''}</b><span class="muted">${s.desc || ''} Groups: ${s.groups.join(', ')}. ${s.hb === 0 ? 'Lower is better. ' : s.hb === null ? 'Not ranked (no better/worse direction). ' : ''}Qualifier: ${qtext(s.q)}.</span></div>`).join('')}</div>`).join('');
  const m = D.meta;
  $('#quals').innerHTML = `<p><b>Position groups</b> come from nflverse depth-chart positions: QB · RB (incl. FB) · WR · TE · OL (T/G/C) · EDGE (DE + OLB) · IDL (DT/NT) · LB (ILB/MLB) · CB · S (FS/SS). Ranks and percentiles compare a player only with qualified players in his own group.</p>
  <p><b>Qualifiers.</b> ${Object.entries(m.qualifiers).map(([k, v]) => `<b>${{snap:'Counting stats',pass:'Passing rates',rush:'Rushing rates',recv:'Receiving rates',cov:'Coverage rates',tkl:'Missed tackle %',espn:'Win rates',none:'Usage'}[k]}</b>: ${v}`).join(' · ')}. "Team games" = games his team has played through Week ${m.through_week}.</p>
  <p><b>Rank</b> uses standard competition ranking (ties share a rank). <b>Percentile</b> = share of qualified players in the group he beats (ties count half), from 0 to 100.</p>
  <p><b>YPRR:</b> true yards per route run needs route counts. Those come from PFF (paid) or nflverse participation data, which isn't published for ${m.season}. This site shows <b>receiving yards per team dropback in games he played</b> as a clearly labeled proxy, plus yards per target and per offensive snap.</p>
  <p><b>Win rates</b> come from ESPN Analytics (NFL Next Gen Stats tracking) as published in <a href="${m.espn.meta?.url}" target="_blank" rel="noopener">${m.espn.meta?.headline || 'ESPN'}</a> (${m.espn.meta?.updated || ''}). ESPN publishes the top 20 (pass rush and pass block) or top 10 (run stop and run block) for Edge, DT, OT and IOL. Everyone else is "not published"; nothing is estimated.</p>`;
}
function footer() { const m = D.meta;
  $('#footer').innerHTML = `<p><b>Data through ${m.season} Week ${m.through_week}</b> (last game ${m.last_game}); built ${m.built.replace('T', ' ').slice(0, 16)} UTC. ${m.with_stats.toLocaleString()} players with stats, ${m.players.toLocaleString()} searchable.</p>
  <p><b>Sources:</b> <a href="https://github.com/nflverse/nflverse-data/releases">nflverse-data</a> (play-by-play with EPA/CPOE/success models, weekly player stats, rosters &amp; headshots, snap counts, Next Gen Stats, Pro Football Reference advanced defense through week${m.pfr_def_weeks.length ? ' ' + Math.max(...m.pfr_def_weeks) : 's —'}), schedule from <a href="https://github.com/nflverse/nfldata">nflverse/nfldata</a>, win rates from <a href="${m.espn.meta?.url}">ESPN Analytics</a> (${m.espn.meta?.updated || 'n/a'}). Headshots © NFL. Not affiliated with the NFL, ESPN, PFR or PFF. <a href="https://github.com/Coleslaw510/nfl-player-stats-hub">Source &amp; refresh script</a>.</p>`; }

// ---------- wire ----------
typeahead($('#gsearch'), $('#gsearch-ta'), p => go(`#player=${p.id}${sLink()}`));
typeahead($('#psearch'), $('#psearch-ta'), p => go(`#player=${p.id}${sLink()}`));
$('#ld-stat').onchange = () => { $('#ld-stat').dataset.v = $('#ld-stat').value; ldPos(); drawLeaders(); };
['#ld-pos', '#ld-n', '#ld-q'].forEach(s => $(s).onchange = drawLeaders);
$('#sc-preset').onchange = () => { applyPreset(+$('#sc-preset').value); drawScatter(); };
['#sc-x', '#sc-y', '#sc-pos'].forEach(s => $(s).onchange = () => { $('#sc-preset').value = 'c'; drawScatter(); });
$('#quick').onclick = e => { const c = e.target.closest('.qc'); if (!c) return; $('#ld-stat').value = c.dataset.k; $('#ld-stat').dataset.v = c.dataset.k; ldPos(); $('#ld-pos').value = c.dataset.g; drawLeaders(); $('#ld-title').scrollIntoView({ behavior: 'smooth', block: 'center' }); };
$('#tb-pos').onchange = () => { tbCats(); tbLimit = 100; drawTable(); }; $('#tb-cat').onchange = () => { tbLimit = 100; drawTable(); };
$('#tb-q').oninput = drawTable; $('#tb-qual').onchange = drawTable; $('#tb-more').onclick = () => { tbLimit += 200; drawTable(); };
$('#tv tbody').onclick = e => { const tr = e.target.closest('tr[data-id]'); if (tr) go(`#player=${tr.dataset.id}`); };
['#tv-pos', '#tv-conf', '#tv-age'].forEach(x => $(x).onchange = () => { tvLimit = 100; drawTV(); }); $('#tv-q').oninput = drawTV; $('#tv-more').onclick = () => { tvLimit += 200; drawTV(); };
$('#tb tbody').onclick = e => { const tr = e.target.closest('tr[data-id]'); if (tr) go(`#player=${tr.dataset.id}${sLink()}`); };
$('#cmp-set').onchange = renderCompare; $('#cmp-all').onchange = renderCompare;
$('#cmp-share').onclick = () => { const u = location.origin + location.pathname + cmpHash(); history.replaceState(null, '', cmpHash()); (navigator.clipboard ? navigator.clipboard.writeText(u) : Promise.reject()).then(() => toast('Share link copied'), () => toast(u)); };
$$('#season-seg button').forEach(b => b.onclick = async () => {
  const h = location.hash.replace(/&season=\d+/, ''); const s = +b.dataset.s;
  await setSeason(s, true); OTHER = await load(s === 2026 ? 2025 : 2026); go(h + (s !== 2026 ? `&season=${s}` : '')); route(); });
window.addEventListener('hashchange', route);
Chart.defaults.font.family = 'Inter,-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif'; Chart.defaults.color = '#8b97ad';
(async () => {
  const m = location.hash.match(/season=(\d{4})/); const s = m ? +m[1] : 2026;
  await setSeason(s, true);
  OTHER = await load(s === 2026 ? 2025 : 2026);
  route();
})();
})();
