'use strict';
/* Tide – stress diary.
 * Readings (RMSSD in ms) arrive from the Pico over USB (Web Serial), are averaged into
 * 15-minute moments per day, and are drawn relative to the wearer's own baseline.
 * Everything is stored in this browser only (localStorage). See ../README.md for the
 * line protocol the band should print. */

const SLOT_MIN = 15;
const TAGS = ['Lecture', 'Group work', 'Deadline', 'Studying', 'Break', 'Lunch', 'Commute', 'Social'];
const C = [[111, 179, 184], [183, 166, 214], [240, 164, 122]];
const mix = t => { const s = t * 2, i = Math.min(1, Math.floor(s)), f = s - i, a = C[i], b = C[i + 1]; return `rgb(${a.map((x, k) => Math.round(x + (b[k] - x) * f))})`; };
// ratio = RMSSD / baseline. Lower HRV than usual means more tension.
const tension = r => Math.max(0, Math.min(1, (1.05 - r) / .5));
const $ = id => document.getElementById(id);
const pad = n => String(n).padStart(2, '0');
const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const time = s => { const m = s * SLOT_MIN; return pad(Math.floor(m / 60)) + ':' + pad(m % 60); };
const dname = s => new Date(s + 'T12:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
const median = a => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

/* ---------- storage ---------- */
const KEY = 'tide-v1', DEMO_NOTES = 'tide-demo-notes';
const DEFAULTS = () => ({ buckets: {}, notes: {}, baseline: { mode: 'auto', manual: 50, device: null }, cueRatio: .65, days: 14, sawCue: false, source: 'demo' });
function load() {
  try { const s = JSON.parse(localStorage.getItem(KEY)); if (s && s.buckets) return { ...DEFAULTS(), ...s }; } catch (e) { }
  return DEFAULTS();
}
let store = load(), saveTimer;
const flush = () => { clearTimeout(saveTimer); try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) { } };
function save() { clearTimeout(saveTimer); saveTimer = setTimeout(flush, 300); }
addEventListener('pagehide', flush);

/* ---------- demo profile (simulated, like the mockup) ---------- */
const DEMO_BASE = 52;
function makeDemo() {
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const plan = [['Lecture', 8, .9], ['Break', 2, 1.15], ['Group work', 6, .84], ['Lunch', 4, 1.17], ['Studying', 8, .88], ['Deadline', 4, .62]];
  const buckets = {}, acts = {}, d = new Date(); d.setHours(12);
  const dates = [];
  while (dates.length < 14) { if (d.getDay() % 6) dates.unshift(ymd(d)); d.setDate(d.getDate() - 1); }
  dates.forEach(date => {
    const day = (rnd() - .5) * .22; let s = 36; buckets[date] = {};
    plan.forEach(([tag, n, r]) => { for (let k = 0; k < n; k++, s++) { acts[date + '|' + s] = tag; if (rnd() < .05) continue; buckets[date][s] = [DEMO_BASE * (r + day + (rnd() - .5) * .12), 1, 0]; } });
  });
  let notes = null; try { notes = JSON.parse(localStorage.getItem(DEMO_NOTES)); } catch (e) { }
  if (!notes) {
    notes = {};
    dates.slice(0, 4).forEach(date => Object.entries(buckets[date]).forEach(([s, [v]]) => { if (tension(v / DEMO_BASE) > .5 && s % 2 == 0) notes[date + '|' + s] = { tag: acts[date + '|' + s], text: '', sim: 1 }; }));
  }
  return { buckets, notes };
}
const demo = makeDemo();

/* ---------- the dataset currently shown ---------- */
function autoBaseline() {
  const vals = []; Object.keys(store.buckets).sort().slice(-30).forEach(d => Object.values(store.buckets[d]).forEach(([s, n]) => { if (n) vals.push(s / n); }));
  return median(vals);
}
function baseline() {
  if (store.source === 'demo') return DEMO_BASE;
  const b = store.baseline;
  if (b.mode === 'manual' && b.manual > 0) return b.manual;
  return b.device || autoBaseline();
}
const ds = () => store.source === 'demo'
  ? { buckets: demo.buckets, notes: demo.notes, base: DEMO_BASE, flags: false, saveNotes: () => { try { localStorage.setItem(DEMO_NOTES, JSON.stringify(demo.notes)); } catch (e) { } } }
  : { buckets: store.buckets, notes: store.notes, base: baseline(), flags: store.sawCue, saveNotes: save };
// Whether a moment gets the "breathing moment" ring: real CUE events once the band has sent any, otherwise the threshold.
const isCue = (D, c, r) => D.flags ? !!c[2] : r < (store.source === 'demo' ? .65 : store.cueRatio);

/* ---------- landscape ---------- */
const X0 = 96, DX = 21, DY = 38;
let cur = null, tag = null;
function render() {
  const D = ds(), svg = $('map');
  const dates = Object.keys(D.buckets).filter(d => Object.values(D.buckets[d]).some(c => c[1])).sort().slice(-store.days);
  $('empty').hidden = !!(dates.length && D.base);
  svg.style.display = $('empty').hidden ? '' : 'none';
  if (!$('empty').hidden) { svg.innerHTML = ''; patterns(); return; }
  let lo = 96, hi = -1;
  dates.forEach(d => Object.entries(D.buckets[d]).forEach(([s, c]) => { if (c[1]) { lo = Math.min(lo, +s); hi = Math.max(hi, +s); } }));
  lo = Math.floor(lo / 4) * 4; hi = Math.max(Math.ceil((hi + 1) / 4) * 4 - 1, lo + 15);
  if (hi > 95) { lo = Math.max(0, lo - (hi - 95)); hi = 95; }
  const n = hi - lo + 1, W = X0 + (n - 1) * DX + 30, H = 30 + dates.length * DY;
  let g = '<defs><filter id="b" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="3.2"/></filter></defs><g filter="url(#b)">', h = '';
  dates.forEach((d, i) => {
    const y = 30 + i * DY; h += `<text x="4" y="${y + 4}">${dname(d)}</text>`;
    for (let s = lo; s <= hi; s++) {
      const x = X0 + (s - lo) * DX, c = D.buckets[d][s], k = d + '|' + s;
      if (!c || !c[1]) { h += `<circle cx="${x}" cy="${y}" r="2" fill="none" stroke="var(--line)"/>`; continue; }
      const r = c[0] / c[1] / D.base, t = tension(r);
      g += `<circle cx="${x}" cy="${y}" r="${5 + t * 10}" fill="${mix(t)}" opacity=".85"/>`;
      if (isCue(D, c, r)) h += `<circle cx="${x}" cy="${y}" r="${9 + t * 8}" fill="none" stroke="var(--acc)" stroke-width="1.2" pointer-events="none"/>`;
      h += `<circle class="hit${k === cur ? ' sel' : ''}" data-k="${k}" cx="${x}" cy="${y}" r="10" tabindex="0" role="button" aria-label="${dname(d)} ${time(s)}"/>`;
    }
  });
  const every = n > 40 ? 8 : 4;
  for (let s = lo; s <= hi; s += every) h += `<text x="${X0 + (s - lo) * DX}" y="14" text-anchor="middle">${time(s)}</text>`;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.style.minWidth = Math.min(W, 1400) * .87 + 'px';
  svg.innerHTML = g + '</g>' + h;
  patterns();
}
let renderTimer;
const scheduleRender = () => { clearTimeout(renderTimer); renderTimer = setTimeout(render, 800); };

/* ---------- pick a moment & notes ---------- */
const chips = $('chips');
chips.innerHTML = TAGS.map(t => `<button class="chip" aria-pressed="false">${t}</button>`).join('');
const setChips = () => [...chips.children].forEach(c => c.setAttribute('aria-pressed', c.textContent === tag));
chips.onclick = e => { const b = e.target.closest('.chip'); if (!b) return; tag = b.textContent === tag ? null : b.textContent; setChips(); };
function pick(el) {
  document.querySelectorAll('.hit.sel').forEach(x => x.classList.remove('sel')); el.classList.add('sel'); cur = el.dataset.k;
  const D = ds(), [d, s] = cur.split('|'), c = D.buckets[d][s], r = c[0] / c[1] / D.base, t = tension(r);
  $('ptitle').textContent = dname(d) + ', ' + time(+s);
  $('pmood').textContent = (t > .55 ? 'Tenser than your usual.' : t > .2 ? 'A little above your usual.' : 'Calm, close to your usual.') + (isCue(D, c, r) ? ' Your band offered a breathing moment.' : '');
  $('form').hidden = false; const note = D.notes[cur] || {}; tag = note.tag || null; setChips();
  $('txt').value = note.text || ''; $('saved').textContent = note.sim ? 'A simulated note is filled in here. Edit it freely.' : '';
}
function clearPick() { cur = null; $('ptitle').textContent = 'Pick a moment'; $('pmood').textContent = 'Tap any shape above to look closer.'; $('form').hidden = true; }
$('map').addEventListener('click', e => { if (e.target.dataset.k) pick(e.target); });
$('map').addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.dataset.k) { e.preventDefault(); pick(e.target); } });
$('save').onclick = () => {
  const D = ds(), text = $('txt').value.trim();
  if (tag || text) D.notes[cur] = { tag, text }; else delete D.notes[cur];
  D.saveNotes(); $('saved').textContent = 'Saved.'; patterns();
};
function patterns() {
  const D = ds(), c = {}; let n = 0;
  Object.entries(D.notes).forEach(([k, v]) => {
    const [d, s] = k.split('|'), b = D.buckets[d] && D.buckets[d][s];
    if (v.tag && b && b[1] && tension(b[0] / b[1] / D.base) > .4) { c[v.tag] = (c[v.tag] || 0) + 1; n++; }
  });
  const rows = Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 4), mx = rows.length ? rows[0][1] : 1;
  let html = rows.length
    ? `<p class="note">Most often named on your tenser moments (${n} notes):</p>` + rows.map(([t, v]) => `<div class="pat"><span style="width:92px">${t}</span><i style="width:${v / mx * 140}px"></i><span class="note">${v}</span></div>`).join('')
    : '<p class="note">Add a note to a tense moment and hints will appear here.</p>';
  // Time-of-day hint once there are a few days to go on.
  const days = Object.keys(D.buckets), hours = {};
  if (D.base && days.length >= 3) {
    days.forEach(d => Object.entries(D.buckets[d]).forEach(([s, [sum, k]]) => { if (!k) return; const hr = Math.floor(s * SLOT_MIN / 60); (hours[hr] ??= []).push(tension(sum / k / D.base)); }));
    const best = Object.entries(hours).filter(([, a]) => a.length >= 3).map(([hr, a]) => [hr, a.reduce((x, y) => x + y) / a.length]).sort((a, b) => b[1] - a[1])[0];
    if (best && best[1] > .3) html += `<p class="note">Your tenser moments tend to gather around ${pad(best[0])}:00–${pad(+best[0] + 1)}:00.</p>`;
  }
  $('pat').innerHTML = html;
}

/* ---------- source toggle ---------- */
function setSource(src) {
  store.source = src; save(); clearPick();
  $('srcMine').setAttribute('aria-pressed', src === 'mine'); $('srcDemo').setAttribute('aria-pressed', src === 'demo');
  $('demoBadge').hidden = src !== 'demo';
  render(); updateStats();
}
$('srcMine').onclick = () => setSource('mine');
$('srcDemo').onclick = () => setSource('demo');

/* ---------- ingesting readings ---------- */
const live = { last: null, n: 0, cues: 0, ibis: [], sinceCalc: 0 };
function slotOf(ts) { const d = new Date(ts); return [ymd(d), Math.floor((d.getHours() * 60 + d.getMinutes()) / SLOT_MIN)]; }
function cell(ts) { const [d, s] = slotOf(ts); return ((store.buckets[d] ??= {})[s] ??= [0, 0, 0]); }
function addReading(rmssd, ts = Date.now(), fromFile = false) {
  if (!(rmssd > 0 && rmssd < 400) || !isFinite(ts)) return false;
  const c = cell(ts); c[0] += rmssd; c[1]++;
  if (!fromFile) { live.last = rmssd; live.n++; updateLive(); }
  if (store.source !== 'mine') setSource('mine');
  save(); scheduleRender(); return true;
}
function markCue(ts = Date.now(), fromFile = false) {
  cell(ts)[2] = 1; store.sawCue = true; if (!fromFile) { live.cues++; updateStats(); }
  if (store.source !== 'mine') setSource('mine');
  save(); scheduleRender();
}
// Raw inter-beat intervals: compute RMSSD over the last 30 beats, every 10 beats.
function addIbi(ms, ts = Date.now()) {
  if (!(ms > 300 && ms < 2000)) return;
  const prev = live.ibis[live.ibis.length - 1];
  if (prev && Math.abs(ms - prev.ms) / prev.ms > .3) return; // likely a missed/extra beat
  live.ibis.push({ ms, ts }); if (live.ibis.length > 30) live.ibis.shift();
  if (++live.sinceCalc < 10 || live.ibis.length < 20) return;
  live.sinceCalc = 0; let sq = 0;
  for (let i = 1; i < live.ibis.length; i++) sq += (live.ibis[i].ms - live.ibis[i - 1].ms) ** 2;
  addReading(Math.sqrt(sq / (live.ibis.length - 1)), ts);
}
function setDeviceBaseline(v) { if (v > 0 && v < 400) { store.baseline.device = v; save(); updateStats(); scheduleRender(); } }
const toMs = v => { if (v == null || v === '') return undefined; const x = +v; if (isFinite(x)) return x < 1e12 ? x * 1000 : x; const p = Date.parse(v); return isNaN(p) ? NaN : p; };

function ingestLine(raw) {
  const line = raw.trim(); if (!line) return;
  log(line);
  if (line[0] === '{') {
    let o; try { o = JSON.parse(line); } catch (e) { return; }
    const ts = toMs(o.ts ?? o.time);
    if (o.rmssd != null) addReading(+o.rmssd, ts);
    if (o.ibi != null) addIbi(+o.ibi, ts);
    if (o.baseline != null) setDeviceBaseline(+o.baseline);
    if (o.cue) markCue(ts);
    return;
  }
  const [k, ...rest] = line.split(/[\s,:=;]+/), v = parseFloat(rest[0]);
  switch (k.toUpperCase()) {
    case 'RMSSD': case 'HRV': addReading(v); break;
    case 'IBI': case 'RR': addIbi(v); break;
    case 'BASELINE': setDeviceBaseline(v); break;
    case 'CUE': case 'BREATHE': markCue(); break;
  }
}

/* ---------- live panel ---------- */
function updateLive() {
  $('live').hidden = false;
  const b = baseline(), t = b && live.last ? tension(live.last / b) : 0;
  $('orb').setAttribute('fill', mix(t)); $('orb').setAttribute('r', 24 + t * 16);
  $('liveText').textContent = !b ? 'Getting to know your usual rhythm.' : t > .55 ? 'Your body seems busy right now. Your band has you.' : t > .2 ? 'A little more going on than usual.' : 'Calm, close to your usual.';
  updateStats();
}
function updateStats() {
  const b = store.source === 'demo' ? baseline() : (store.baseline.mode === 'manual' ? store.baseline.manual : store.baseline.device || autoBaseline());
  const src = store.source === 'demo' ? 'demo' : store.baseline.mode === 'manual' ? 'fixed' : store.baseline.device ? 'from band' : 'automatic';
  $('dLast').textContent = live.last ? live.last.toFixed(1) + ' ms' : '–';
  $('dBase').textContent = b ? `${b.toFixed(1)} ms (${src})` : 'not enough data yet';
  $('dCount').textContent = live.n; $('dCues').textContent = live.cues;
}
const logLines = [];
function log(s) { logLines.push(new Date().toLocaleTimeString('en-GB') + '  ' + s); if (logLines.length > 60) logLines.shift(); const p = $('log'); p.textContent = logLines.join('\n'); p.scrollTop = p.scrollHeight; }

/* ---------- Web Serial connection to the Pico ---------- */
let port = null, reader = null, piped = null;
const status = s => $('bandStatus').textContent = s;
async function connect() {
  if (!('serial' in navigator)) { status('This browser cannot talk to the band over USB. Please use Chrome or Edge on a laptop or desktop.'); return; }
  try { port = await navigator.serial.requestPort(); } catch (e) { return; } // user closed the picker
  try {
    await port.open({ baudRate: 115200 });
    try { await port.setSignals({ dataTerminalReady: true }); } catch (e) { }
  } catch (e) { status('Could not open the band. Is another program (e.g. Thonny) still connected to it? Close it and try again.'); port = null; return; }
  status('Connected. Your band is sending moments to this diary.'); $('connect').textContent = 'Disconnect'; $('live').hidden = false;
  const dec = new TextDecoderStream(); piped = port.readable.pipeTo(dec.writable).catch(() => { });
  reader = dec.readable.getReader(); let buf = '';
  try {
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += value; let i;
      while ((i = buf.indexOf('\n')) >= 0) { ingestLine(buf.slice(0, i)); buf = buf.slice(i + 1); }
      if (buf.length > 4096) buf = '';
    }
  } catch (e) { }
  await cleanup();
}
async function cleanup() {
  try { reader && await reader.cancel(); } catch (e) { }
  try { piped && await piped; } catch (e) { }
  try { port && await port.close(); } catch (e) { }
  reader = piped = port = null;
  $('connect').textContent = 'Connect band'; status('Disconnected. Your moments so far are saved in this browser.');
}
$('connect').onclick = () => port ? reader && reader.cancel() : connect();
if ('serial' in navigator) navigator.serial.addEventListener('disconnect', e => { if (e.target === port) reader && reader.cancel(); });
else status('To connect the band, open this page in Chrome or Edge on a laptop or desktop. You can still browse the demo and import files.');

/* ---------- settings ---------- */
document.querySelectorAll('input[name=bmode]').forEach(r => { r.checked = r.value === store.baseline.mode; r.onchange = () => { store.baseline.mode = r.value; save(); updateStats(); render(); }; });
$('bManual').value = store.baseline.manual; $('bManual').onchange = e => { store.baseline.manual = +e.target.value; save(); updateStats(); render(); };
$('cueRatio').value = store.cueRatio; $('cueRatio').onchange = e => { store.cueRatio = +e.target.value; save(); render(); };
$('days').value = store.days; $('days').onchange = e => { store.days = +e.target.value; save(); render(); };

/* ---------- export / import ---------- */
function download(name, text, type) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }
$('expJson').onclick = () => download(`tide-backup-${ymd(new Date())}.json`, JSON.stringify(store, null, 1), 'application/json');
$('expCsv').onclick = () => {
  const b = baseline(), rows = [['date', 'time', 'avg_rmssd_ms', 'readings', 'ratio_to_baseline', 'breathing_cue', 'tag', 'note']];
  Object.keys(store.buckets).sort().forEach(d => Object.keys(store.buckets[d]).map(Number).sort((x, y) => x - y).forEach(s => {
    const [sum, n, cue] = store.buckets[d][s], note = store.notes[d + '|' + s] || {};
    rows.push([d, time(s), n ? (sum / n).toFixed(1) : '', n, n && b ? (sum / n / b).toFixed(3) : '', cue, note.tag || '', note.text || '']);
  }));
  download(`tide-data-${ymd(new Date())}.csv`, rows.map(r => r.map(v => /[",\n]/.test(v) ? `"${String(v).replace(/"/g, '""')}"` : v).join(',')).join('\n'), 'text/csv');
};
$('imp').onchange = async e => {
  const f = e.target.files[0]; e.target.value = ''; if (!f) return;
  const text = await f.text();
  if (/\.json$/i.test(f.name)) {
    try { const s = JSON.parse(text); if (!s.buckets) throw 0; if (!confirm('Replace the data in this browser with this backup?')) return; store = { ...DEFAULTS(), ...s, source: 'mine' }; save(); setSource('mine'); alert('Backup restored.'); }
    catch (err) { alert('That file is not a Tide backup.'); }
    return;
  }
  // CSV / text log: columns timestamp,rmssd[,cue] (header optional). Timestamps: ISO text or unix seconds/ms.
  const lines = text.split(/\r?\n/).filter(l => l.trim()); let ti = 0, ri = 1, ci = 2, ok = 0, bad = 0;
  const head = lines[0].toLowerCase().split(/[,;\t]/).map(h => h.trim());
  if (head.some(h => /rmssd|hrv/.test(h))) { ti = head.findIndex(h => /time|ts|date/.test(h)); ri = head.findIndex(h => /rmssd|hrv/.test(h)); ci = head.findIndex(h => /cue/.test(h)); lines.shift(); }
  lines.forEach(l => {
    const c = l.split(/[,;\t]/), ts = toMs(c[ti]);
    if (addReading(parseFloat(c[ri]), ts, true)) { ok++; if (ci >= 0 && +c[ci]) markCue(ts, true); } else bad++;
  });
  alert(`Imported ${ok} readings${bad ? `, skipped ${bad} lines that could not be read` : ''}.`);
  if (ok) setSource('mine');
};
$('wipe').onclick = () => {
  if (!confirm('Delete all readings and notes stored in this browser? Download a backup first if you want to keep them.')) return;
  store = { ...DEFAULTS(), source: 'mine' }; save(); clearPick(); render(); updateStats();
};

/* ---------- start ---------- */
window.tide = { ingestLine, addReading }; // handy for testing from the browser console
setSource(store.source);
