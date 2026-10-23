/* Inspección CCBP — cliente web. Habla solo con /api del mismo servidor. */
(() => {
'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const fmt = s => s ? s.slice(8, 10) + '/' + s.slice(5, 7) + '/' + s.slice(0, 4) : '—';
let HOY = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Argentina/Buenos_Aires'}).format(new Date());
const hoy = () => HOY;
const masDias = n => { const d = new Date(hoy() + 'T12:00:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };

const SECTORES = [[1,591,'I'],[592,1185,'II'],[1186,1721,'III'],[1722,2289,'IV'],[2290,2851,'V'],[2852,2955,'Golf']];
const sectorDe = uf => { const s = SECTORES.find(x => uf >= x[0] && uf <= x[1]); return s ? s[2] : '—'; };
const ESTADOS = ['Pendiente','Aviso verbal','Aviso por folleto','Derivado a Comisión','Notificado/Intimado','Resuelto','Verificado sin falta'];
const CERRADOS = ['Resuelto','Verificado sin falta'];
const ORIGENES = ['Recorrido de inspección','Reclamo de vecino','Reclamo del servicio de recolección'];
const CONTACTOS = ['Hablé con el residente','No había nadie','No había nadie, dejé aviso escrito','Hablé con personal de poda, pasto, obra o limpieza','Pendiente de visita'];
const NIVEL = {inspector: 1, supervisor: 2, admin: 3};

/* ───────── estado ───────── */
const S = {visitas: {}, hallazgos: {}, hist: [], fotos: [], cat: {}, usuarios: {}};
let YO = null, SEL = -1, FSEC = '', FVIS = '';
const ufLot = {};
LOTS.forEach((l, i) => l.n.forEach(u => { ufLot[u] = i; }));
let GRUPOS = {};
const grupoUF = uf => GRUPOS[uf] || (ufLot[uf] != null ? LOTS[ufLot[uf]].n : [uf]);
const abierta = h => CERRADOS.indexOf(h.estado) < 0;
const puede = rol => YO && NIVEL[YO.rol] >= NIVEL[rol];

/* ───────── API ───────── */
class ErrorApi extends Error { constructor(m, s) { super(m); this.status = s; } }
async function api(ruta, {method = 'GET', json, form} = {}) {
  const h = {'X-CCBP': '1'};
  let body;
  if (json) { h['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
  if (form) body = form;
  let r;
  try { r = await fetch('/api' + ruta, {method, headers: h, body, credentials: 'same-origin'}); }
  catch (e) { throw new ErrorApi('No hay conexión con el servidor. Revisá la señal y reintentá.', 0); }
  if (r.status === 401 && ruta !== '/login') { pedirLogin(); throw new ErrorApi('La sesión venció. Volvé a ingresar.', 401); }
  let d = null;
  try { d = await r.json(); } catch (e) { /* sin cuerpo */ }
  if (!r.ok) throw new ErrorApi((d && d.detail) || 'El servidor no pudo completar la operación.', r.status);
  return d;
}

/* ───────── utilidades de UI ───────── */
let tT = 0;
function toast(m, err) { const t = $('toast'); t.textContent = m; t.className = 'toast' + (err ? ' err' : ''); t.hidden = false; clearTimeout(tT); tT = setTimeout(() => { t.hidden = true; }, err ? 6000 : 2600); }
function busy(m) { $('busyT').textContent = m || 'Guardando…'; $('busy').hidden = !m; }
function cerrarModal() { $('modal').hidden = true; $('modal').innerHTML = ''; }
function modal(titulo, cuerpo, pie) {
  const m = $('modal');
  m.innerHTML = `<div class="dlg" role="dialog" aria-modal="true" aria-label="${esc(titulo)}"><div class="dlg-h"><h2>${esc(titulo)}</h2><button type="button" class="x" data-close aria-label="Cerrar">×</button></div><div class="dlg-b">${cuerpo}</div>${pie ? `<div class="dlg-f">${pie}</div>` : ''}</div>`;
  m.hidden = false;
  m.querySelectorAll('[data-close]').forEach(b => { b.onclick = cerrarModal; });
  m.onclick = e => { if (e.target === m) cerrarModal(); };
  m.querySelectorAll('img[data-foto]').forEach(ocultarRota);
  return m;
}
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('modal').hidden) cerrarModal(); });
const quien = id => `<span class="who">${esc((S.usuarios[id] || {}).nombre || '—')}</span>`;
const fotoURL = n => '/api/fotos/' + encodeURIComponent(n);
const ocultarRota = img => { img.addEventListener('error', () => { img.style.visibility = 'hidden'; }); };
const catTxt = cod => { const c = S.cat[cod]; return c ? c.falta : '(código fuera del catálogo)'; };
function pillEstado(h) {
  if (!abierta(h)) return `<span class="pill ok">${esc(h.estado)}</span>`;
  const k = h.revision && h.revision < hoy() ? 'venc' : h.revision === hoy() ? 'hoy' : 'n';
  return `<span class="pill ${k}">${esc(h.estado)}</span>`;
}
function error(e) {
  if (e && e.status === 401) return;
  toast((e && e.message) || 'No se pudo completar la operación.', true);
}

/* ───────── login ───────── */
function pedirLogin() { YO = null; $('login').hidden = false; cerrarEventos(); setTimeout(() => $('lu').focus(), 50); }
$('flogin').onsubmit = async e => {
  e.preventDefault(); $('lerr').textContent = '';
  try {
    await api('/login', {method: 'POST', json: {usuario: $('lu').value, clave: $('lc').value}});
    $('lc').value = ''; $('login').hidden = true; await iniciar();
  } catch (x) { $('lerr').textContent = x.message; }
};
$('bSalir').onclick = async () => { try { await api('/logout', {method: 'POST'}); } catch (e) { /* igual se sale */ } location.reload(); };

/* ───────── plano ───────── */
const svg = $('map'), NS = 'http://www.w3.org/2000/svg';
const FULL = {x: 80, y: 0, w: 3860, h: 3330};
let vb = {...FULL};
function el(t, a, p) { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); (p || svg).appendChild(e); return e; }
const gBg = el('g', {});
PLAZAS.forEach(d => el('path', {d, class: 'plaza'}, gBg));
el('path', {d: BG.club, class: 'club'}, gBg);
el('path', {d: BG.water, class: 'water'}, gBg);
SECT_LABELS.forEach(([t, x, y]) => { el('text', {x, y: y + 50, class: 'sec-label', 'text-anchor': 'middle'}, gBg).textContent = t; });
const gLots = el('g', {}), gNum = el('g', {}), gGps = el('g', {});
const paths = LOTS.map((l, i) => el('path', {d: l.d, class: 'lot', 'data-i': i}, gLots));
LOTS.forEach(l => { el('text', {x: l.c[0], y: l.c[1], class: 'num'}, gNum).textContent = l.n.join('/'); });

function applyVB() { svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`); svg.classList.toggle('near', vb.w < 700); }
function aSvg(cx, cy) {
  const r = svg.getBoundingClientRect();
  const s = Math.max(vb.w / r.width, vb.h / r.height);
  return {x: vb.x - (r.width * s - vb.w) / 2 + (cx - r.left) * s, y: vb.y - (r.height * s - vb.h) / 2 + (cy - r.top) * s, s};
}
function zoomAt(cx, cy, f) {
  const p = aSvg(cx, cy), nw = Math.min(FULL.w * 1.6, Math.max(120, vb.w * f)), k = nw / vb.w;
  vb = {x: p.x - (p.x - vb.x) * k, y: p.y - (p.y - vb.y) * k, w: nw, h: vb.h * k}; applyVB();
}
function zoomCentro(f) { const r = svg.getBoundingClientRect(); zoomAt(r.left + r.width / 2, r.top + r.height / 2, f); }
function centrar(x, y, w) {
  w = w || 420; const h = w * FULL.h / FULL.w;
  const r = svg.getBoundingClientRect(), visH = r.height * Math.max(w / r.width, h / r.height);
  const off = window.innerWidth <= 760 && !$('panel').hidden ? visH * 0.3 : 0;   // en el celular la ficha tapa la parte de abajo
  vb = {x: x - w / 2, y: y - h / 2 + off, w, h}; applyVB();
}
const irA = i => centrar(LOTS[i].c[0], LOTS[i].c[1]);
const ptrs = new Map(); let moved = 0, downT = null, pinch0 = 0;
svg.addEventListener('pointerdown', e => {
  ocultarTip();
  svg.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, {x: e.clientX, y: e.clientY});
  if (ptrs.size === 1) { moved = 0; downT = e.target; }
  if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; pinch0 = Math.hypot(a.x - b.x, a.y - b.y); moved = 99; }
});
/* cartel al pasar el mouse: número de lote y faltas */
const tip = $('tip'), wrap = svg.parentElement;
let tipI = -1;
function textoTip(i) {
  const ufs = LOTS[i].n, t = hoy();
  const hs = Object.values(S.hallazgos).filter(h => ufs.indexOf(h.uf) >= 0);
  const ab = hs.filter(abierta), venc = ab.filter(h => h.revision && h.revision <= t).length;
  let linea = '';
  if (ab.length) {
    linea = `<span class="tip-n">${ab.length} ${ab.length === 1 ? 'falta abierta' : 'faltas abiertas'}</span>` +
      (venc ? `<span class="tip-v">${venc} para revisar hoy o vencida${venc === 1 ? '' : 's'}</span>` : '');
  } else if (hs.length) {
    linea = `<span class="tip-s">${hs.length} ${hs.length === 1 ? 'falta cerrada' : 'faltas cerradas'}</span>`;
  } else {
    linea = '<span class="tip-s">Sin faltas</span>';
  }
  return `<b>U.F. ${esc(ufs.join(' / '))}</b><span class="tip-s">Sector ${esc(sectorDe(ufs[0]))}</span>${linea}`;
}
function moverTip(e) {
  const r = wrap.getBoundingClientRect();
  let x = e.clientX - r.left + 14, y = e.clientY - r.top + 16;
  if (x + tip.offsetWidth > r.width - 8) x = e.clientX - r.left - tip.offsetWidth - 14;
  if (y + tip.offsetHeight > r.height - 8) y = e.clientY - r.top - tip.offsetHeight - 12;
  tip.style.transform = `translate(${Math.max(4, x)}px, ${Math.max(4, y)}px)`;
}
function ocultarTip() { tip.hidden = true; tipI = -1; }
svg.addEventListener('pointerleave', ocultarTip);
svg.addEventListener('pointermove', e => {
  if (e.pointerType !== 'mouse' || ptrs.size) { if (!tip.hidden) ocultarTip(); return; }
  const i = e.target.dataset && e.target.dataset.i != null ? +e.target.dataset.i : -1;
  if (i < 0) { if (!tip.hidden) ocultarTip(); return; }
  if (i !== tipI) { tipI = i; tip.innerHTML = textoTip(i); tip.hidden = false; }
  moverTip(e);
});

svg.addEventListener('pointermove', e => {
  if (!ptrs.has(e.pointerId)) return;
  const prev = ptrs.get(e.pointerId), cur = {x: e.clientX, y: e.clientY};
  ptrs.set(e.pointerId, cur);
  if (ptrs.size === 1) {
    const dx = cur.x - prev.x, dy = cur.y - prev.y; moved += Math.abs(dx) + Math.abs(dy);
    if (moved > 6) { seguir = false; marcarGps(); }
    const s = aSvg(0, 0).s; vb.x -= dx * s; vb.y -= dy * s; applyVB();
  } else if (ptrs.size === 2) {
    const [a, b] = [...ptrs.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
    if (pinch0) zoomAt((a.x + b.x) / 2, (a.y + b.y) / 2, pinch0 / d);
    pinch0 = d;
  }
});
function finPtr(e) {
  if (!ptrs.has(e.pointerId)) return;
  ptrs.delete(e.pointerId);
  if (ptrs.size === 0 && moved < 8 && downT && downT.dataset && downT.dataset.i != null) seleccionar(+downT.dataset.i);
  if (ptrs.size < 2) pinch0 = 0;
}
svg.addEventListener('pointerup', finPtr);
svg.addEventListener('pointercancel', finPtr);
svg.addEventListener('wheel', e => { e.preventDefault(); zoomAt(e.clientX, e.clientY, e.deltaY > 0 ? 1.18 : 1 / 1.18); }, {passive: false});
$('zIn').onclick = () => zoomCentro(1 / 1.5);
$('zOut').onclick = () => zoomCentro(1.5);
$('zAll').onclick = () => { vb = {...FULL}; applyVB(); };

/* ───────── GPS ─────────
   Calibración del plano de Construcciones (3 puntos sobre línea municipal, 30/09/2026:
   U.F. 1198/1199 · 655/656 · 2450/2451). Error medio ≈ 15 m, del orden del GPS del celular. */
const CAL = {lat0: -34.6, lon0: -58.86, kx: 91631.5405, ky: 110574, a: 0.25210266, b: -0.31173198, tx: 472.03627, ty: 926.57710};
const M_POR_UNIDAD = Math.sqrt(CAL.a * CAL.a + CAL.b * CAL.b);
function aPlano(lat, lon) {
  const E = (lon - CAL.lon0) * CAL.kx - CAL.tx, N = (lat - CAL.lat0) * CAL.ky - CAL.ty, d = CAL.a * CAL.a + CAL.b * CAL.b;
  return {x: (CAL.a * E + CAL.b * N) / d, y: (CAL.b * E - CAL.a * N) / d};
}
let POS = null, watchId = null, seguir = false;
const acc = el('circle', {class: 'gps-acc', r: 0}, gGps), dot = el('circle', {class: 'gps-dot', r: 9}, gGps);
gGps.style.display = 'none';
function marcarGps() { $('bGps').classList.toggle('on', watchId != null && seguir); }
function loteEn(x, y) {
  const pt = svg.createSVGPoint(); pt.x = x; pt.y = y;
  for (let i = 0; i < paths.length; i++) { try { if (paths[i].isPointInFill(pt)) return i; } catch (e) { break; } }
  let best = -1, bd = Infinity;
  LOTS.forEach((l, i) => { const d = Math.hypot(l.c[0] - x, l.c[1] - y); if (d < bd) { bd = d; best = i; } });
  return bd * M_POR_UNIDAD < 60 ? best : -1;
}
const posVigente = () => POS && Date.now() - POS.ts < 120000 ? POS : null;
const metrosA = (i, p) => Math.round(Math.hypot(LOTS[i].c[0] - p.x, LOTS[i].c[1] - p.y) * M_POR_UNIDAD);
function iniciarGps(centrarAlLlegar) {
  if (!('geolocation' in navigator)) { toast('Este navegador no tiene GPS disponible.', true); return; }
  if (!window.isSecureContext) { toast('El GPS solo funciona si la app se abre por HTTPS.', true); return; }
  if (watchId != null) { seguir = true; marcarGps(); if (POS) centrar(POS.x, POS.y, Math.min(vb.w, 600)); return; }
  seguir = true; let primera = true;
  watchId = navigator.geolocation.watchPosition(p => {
    const {latitude: lat, longitude: lon, accuracy} = p.coords, q = aPlano(lat, lon);
    POS = {lat, lon, acc: Math.round(accuracy), x: q.x, y: q.y, ts: Date.now()};
    gGps.style.display = '';
    dot.setAttribute('cx', q.x); dot.setAttribute('cy', q.y);
    acc.setAttribute('cx', q.x); acc.setAttribute('cy', q.y); acc.setAttribute('r', accuracy / M_POR_UNIDAD);
    if (primera && centrarAlLlegar) { const i = loteEn(q.x, q.y); if (i >= 0) seleccionar(i); }
    if (seguir) centrar(q.x, q.y, primera ? 600 : vb.w);
    primera = false; marcarGps();
  }, e => {
    const m = e.code === 1 ? 'Sin permiso de ubicación. Habilitalo en el navegador para este sitio.' : 'No se pudo obtener la ubicación. Probá al aire libre.';
    toast(m, true); navigator.geolocation.clearWatch(watchId); watchId = null; seguir = false; marcarGps();
  }, {enableHighAccuracy: true, maximumAge: 5000, timeout: 20000});
  marcarGps();
}
$('bGps').onclick = () => iniciarGps(true);
function gpsHtml(uf) {
  const p = posVigente(), i = ufLot[uf];
  if (!p) return '<p class="gpsinfo">Sin ubicación: la visita se guarda sin coordenadas. Tocá ◎ en el plano para activar el GPS.</p>';
  const d = i != null ? metrosA(i, p) : null, lejos = d != null && d > 80;
  return `<p class="gpsinfo${lejos ? ' lejos' : ''}">${lejos ? `Estás a unos ${d} m de esta U.F. ¿Es el lote correcto?` : `Ubicación registrada (±${p.acc} m)${d != null ? ` · a ${d} m del lote` : ''}.`}</p>`;
}
const gpsDatos = () => { const p = posVigente(); return p ? {lat: +p.lat.toFixed(6), lon: +p.lon.toFixed(6), prec: String(Math.min(p.acc, 65000))} : {}; };

/* ───────── pintar ───────── */
function estadoLote(i) {
  const ufs = LOTS[i].n, t = hoy();
  const hs = Object.values(S.hallazgos).filter(h => ufs.indexOf(h.uf) >= 0);
  const ab = hs.filter(abierta);
  if (ab.some(h => h.revision && h.revision < t)) return 'venc';
  if (ab.some(h => h.revision === t)) return 'hoy';
  if (ab.length) return 'abierta';
  if (hs.length) return 'cerrada';
  if (Object.values(S.visitas).some(v => ufs.indexOf(v.uf) >= 0)) return 'visit';
  return '';
}
function pasaFiltro(i, st) {
  const l = LOTS[i];
  if (FSEC && sectorDe(l.n[0]) !== FSEC) return false;
  if (!FVIS) return true;
  const t = hoy();
  if (FVIS === 'venc') return st === 'venc' || st === 'hoy';
  if (FVIS === 'abiertas') return st === 'venc' || st === 'hoy' || st === 'abierta';
  if (FVIS === 'visto') return Object.values(S.visitas).some(v => l.n.indexOf(v.uf) >= 0 && v.fecha === t);
  if (FVIS === 'repro') return S.hist.some(x => x.fecha === t && /^Revisión reprogramada/.test(x.cambio || '') && l.n.indexOf(x.uf) >= 0);
  return true;
}
let rq = 0;
function render() {
  if (rq) return;
  rq = requestAnimationFrame(() => {
    rq = 0;
    paths.forEach((p, i) => {
      const st = estadoLote(i);
      p.setAttribute('class', 'lot' + (st ? ' st-' + st : '') + (pasaFiltro(i, st) ? '' : ' dim') + (i === SEL ? ' sel' : ''));
    });
    const n = Object.values(S.hallazgos).filter(h => abierta(h) && h.revision && h.revision <= hoy()).length;
    $('nAgenda').hidden = !n; $('nAgenda').textContent = n;
    if (SEL >= 0) pintarPanel();
    if (tipI >= 0) tip.innerHTML = textoTip(tipI);   // datos nuevos mientras el mouse está encima
  });
}

/* ───────── filtros y búsqueda ───────── */
document.querySelectorAll('[data-sec]').forEach(b => { b.onclick = () => {
  FSEC = b.dataset.sec; document.querySelectorAll('[data-sec]').forEach(x => x.setAttribute('aria-pressed', String(x === b))); render();
}; });
document.querySelectorAll('[data-vis]').forEach(b => { b.onclick = () => {
  FVIS = FVIS === b.dataset.vis ? '' : b.dataset.vis;
  document.querySelectorAll('[data-vis]').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.vis === FVIS))); render();
}; });
$('fsearch').onsubmit = e => {
  e.preventDefault();
  const uf = parseInt($('ufq').value, 10), i = ufLot[uf];
  if (i == null) { toast('No encontré la U.F. ' + ($('ufq').value || '') + ' en el plano.', true); return; }
  seguir = false; marcarGps(); seleccionar(i); irA(i);
};

/* ───────── panel de la U.F. ───────── */
function seleccionar(i) { SEL = i; $('panel').hidden = false; render(); pintarPanel(); }
function fotosDe(reg, visita) {
  const fs = S.fotos.filter(f => reg ? f.reg === reg : (!f.reg && f.visita === visita));
  if (!fs.length) return '';
  return `<div class="thumbs">${fs.map(f => `<figure><a href="${fotoURL(f.n)}" target="_blank" rel="noopener"><img data-foto src="${fotoURL(f.n)}" alt="Foto ${esc(f.n)}" loading="lazy"></a><figcaption>${esc(f.momento)} ${fmt(f.fecha)}</figcaption></figure>`).join('')}</div>`;
}
function pintarPanel() {
  const ufs = LOTS[SEL].n, p = $('panel');
  const hs = Object.values(S.hallazgos).filter(h => ufs.indexOf(h.uf) >= 0).sort((a, b) => (a.revision || '9').localeCompare(b.revision || '9'));
  const ab = hs.filter(abierta), ce = hs.filter(h => !abierta(h)).sort((a, b) => (b.cierre || '').localeCompare(a.cierre || ''));
  const vs = Object.values(S.visitas).filter(v => ufs.indexOf(v.uf) >= 0).sort((a, b) => b.fecha.localeCompare(a.fecha) || b.n.localeCompare(a.n));
  const item = h => `<button type="button" class="item" data-falta="${esc(h.n)}"><span class="top"><span class="cod">${esc(h.n)} · ${esc(h.codigo)}</span>${pillEstado(h)}</span><span class="t">${esc(catTxt(h.codigo))}</span><span class="meta">${abierta(h) ? 'Revisión ' + fmt(h.revision) : 'Cerrada ' + fmt(h.cierre)}${h.reit ? ' · Reiterancia ' + h.reit : ''}</span></button>`;
  const scroll = p.scrollTop;
  p.innerHTML = `<div class="panel-h"><div><h2>U.F. ${esc(ufs.join(' / '))}</h2><div class="sub">Sector ${esc(sectorDe(ufs[0]))}${ufs.length > 1 ? ' · lote unificado' : ''}${posVigente() ? ' · a ' + metrosA(SEL, POS) + ' m de vos' : ''}</div></div><button type="button" class="x" id="pClose" aria-label="Cerrar ficha">×</button></div>
  <div class="panel-b">
    <div class="row"><button type="button" class="pri" id="pNueva">Nueva visita</button></div>
    <section class="list"><h3>Faltas abiertas (${ab.length})</h3>${ab.length ? ab.map(item).join('') : '<p class="empty">Sin faltas abiertas.</p>'}</section>
    <section class="list"><h3>Visitas (${vs.length})</h3>${vs.length ? vs.slice(0, 15).map(v => `<div class="item"><span class="top"><span class="cod">${esc(v.n)} · ${fmt(v.fecha)}</span><span class="pill n">${esc(v.origen)}</span></span><span class="meta">${esc(v.contacto || 'Sin contacto registrado')}${v.obs ? ' · ' + esc(v.obs) : ''}</span><span class="meta">${quien(v.autor)}${v.lat != null ? ` · GPS ±${v.prec || '?'} m` : ''}</span>${fotosDe('', v.n)}</div>`).join('') : '<p class="empty">Todavía no hay visitas a esta U.F.</p>'}</section>
    ${ce.length ? `<section class="list"><h3>Faltas cerradas (${ce.length})</h3>${ce.map(item).join('')}</section>` : ''}
  </div>`;
  p.scrollTop = scroll;
  p.querySelectorAll('img[data-foto]').forEach(ocultarRota);
  $('pClose').onclick = () => { SEL = -1; p.hidden = true; render(); };
  $('pNueva').onclick = () => formVisita(ufs[0]);
  p.querySelectorAll('[data-falta]').forEach(b => { b.onclick = () => fichaFalta(b.dataset.falta); });
}

/* ───────── fotos: se achican en el celular antes de subir ───────── */
async function comprimir(file) {
  try {
    const bmp = await createImageBitmap(file);
    const sc = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
    const c = document.createElement('canvas'); c.width = Math.round(bmp.width * sc); c.height = Math.round(bmp.height * sc);
    c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
    const b = await new Promise(r => c.toBlob(r, 'image/jpeg', 0.82));
    if (b) return b;
  } catch (e) { /* se manda el original; el servidor lo procesa igual */ }
  return file;
}
const campoFotos = id => `<div class="f"><label for="${id}">Fotos</label><input id="${id}" type="file" accept="image/*" capture="environment" multiple></div>`;
const archivos = id => { const i = $(id); return i && i.files ? [...i.files] : []; };
async function agregarFotos(fd, grupo, files) { for (const f of files) fd.append('f_' + grupo, await comprimir(f), 'foto.jpg'); }

/* ───────── nueva visita ───────── */
function opcionesCat(sel) {
  const porRubro = {};
  Object.values(S.cat).filter(c => c.activo).forEach(c => { (porRubro[c.rubro] = porRubro[c.rubro] || []).push(c); });
  return '<option value="">Elegí el tipo de falta…</option>' + Object.keys(porRubro).sort().map(r => `<optgroup label="${esc(r)}">${porRubro[r].sort((a, b) => a.codigo.localeCompare(b.codigo)).map(c => `<option value="${esc(c.codigo)}" ${c.codigo === sel ? 'selected' : ''}>${esc(c.codigo)} · ${esc(c.falta)}${/^EJ-/.test(c.codigo) ? ' (ejemplo)' : ''}</option>`).join('')}</optgroup>`).join('');
}
const opts = (arr, sel) => arr.map(x => `<option ${x === sel ? 'selected' : ''}>${esc(x)}</option>`).join('');
let nFaltaForm = 0;
function bloqueFalta() {
  const k = ++nFaltaForm;
  return `<div class="box" data-fb="${k}"><div class="box-h"><b>Falta</b><button type="button" data-quitar="${k}">Quitar</button></div>
    <div class="f"><label for="fc${k}">Tipo de falta</label><select id="fc${k}">${opcionesCat('')}</select></div>
    <div class="grid2"><div class="f"><label for="fe${k}">Estado</label><select id="fe${k}">${opts(ESTADOS, 'Pendiente')}</select></div>
    <div class="f"><label for="fr${k}">Fecha de revisión</label><input id="fr${k}" type="date" value="${masDias(7)}"></div></div>
    <div class="f"><label for="fo${k}">Observación</label><textarea id="fo${k}" rows="2"></textarea></div>
    ${campoFotos('ff' + k)}</div>`;
}
function formVisita(uf) {
  const sinCat = !Object.values(S.cat).some(c => c.activo);
  const m = modal('Nueva visita · U.F. ' + uf, `
    ${gpsHtml(uf)}
    <div class="grid2">
      <div class="f"><label for="vf">Fecha</label><input id="vf" type="date" value="${hoy()}" max="${hoy()}"></div>
      <div class="f"><label for="vo">Origen</label><select id="vo">${opts(ORIGENES, ORIGENES[0])}</select></div>
    </div>
    <div class="f"><label for="vc">Contacto</label><select id="vc">${opts(CONTACTOS, CONTACTOS[0])}</select></div>
    <div class="f"><label for="vobs">Observación de la visita</label><textarea id="vobs" rows="2" placeholder="Opcional"></textarea></div>
    ${campoFotos('vfo')}
    <div id="faltas" class="list"></div>
    ${sinCat ? '<p class="note">El catálogo está vacío: un administrador tiene que cargarlo para registrar faltas.</p>' : '<button type="button" id="addF">Agregar falta</button>'}
  `, '<button type="button" data-close>Cancelar</button><button type="button" class="pri" id="vOk">Guardar visita</button>');
  if ($('addF')) $('addF').onclick = () => {
    $('faltas').insertAdjacentHTML('beforeend', bloqueFalta());
    $('faltas').querySelectorAll('[data-quitar]').forEach(b => { b.onclick = () => b.closest('[data-fb]').remove(); });
  };
  $('vOk').onclick = async () => {
    const bloques = [...m.querySelectorAll('[data-fb]')].map(b => b.dataset.fb);
    const faltas = bloques.map(k => ({codigo: $('fc' + k).value, estado: $('fe' + k).value, revision: $('fr' + k).value, obs: $('fo' + k).value.trim()}));
    if (faltas.some(f => !f.codigo)) { toast('Elegí el tipo de cada falta o quitala.', true); return; }
    const nFotos = archivos('vfo').length + bloques.reduce((s, k) => s + archivos('ff' + k).length, 0);
    if (nFotos > 12) { toast('Máximo 12 fotos por visita.', true); return; }
    try {
      busy(nFotos ? `Subiendo ${nFotos} ${nFotos === 1 ? 'foto' : 'fotos'}…` : 'Guardando visita…');
      const fd = new FormData();
      fd.append('datos', JSON.stringify(Object.assign({uf, fecha: $('vf').value || hoy(), origen: $('vo').value, contacto: $('vc').value, obs: $('vobs').value.trim(), faltas}, gpsDatos())));
      await agregarFotos(fd, 'visita', archivos('vfo'));
      for (let j = 0; j < bloques.length; j++) await agregarFotos(fd, String(j), archivos('ff' + bloques[j]));
      const r = await api('/visitas', {method: 'POST', form: fd});
      busy(''); cerrarModal();
      toast(r.faltas.length ? `${r.visita} guardada con ${r.faltas.length} ${r.faltas.length === 1 ? 'falta' : 'faltas'}` : r.visita + ' guardada sin faltas');
      await cargar();
    } catch (e) { busy(''); error(e); }
  };
}

/* ───────── ficha de una falta ───────── */
function fichaFalta(n) {
  const h = S.hallazgos[n]; if (!h) return;
  const c = S.cat[h.codigo] || {};
  const hs = S.hist.filter(x => x.reg === n);
  const m = modal(n + ' · U.F. ' + h.uf, `
    <div class="row">${pillEstado(h)}<span class="cod">${esc(h.codigo)}</span></div>
    <p class="ftit">${esc(catTxt(h.codigo))}</p>
    <dl class="kv">
      <dt>Detectada</dt><dd>${fmt(h.fecha)} · visita ${esc(h.visita)}</dd>
      <dt>${abierta(h) ? 'Revisión' : 'Cierre'}</dt><dd>${fmt(abierta(h) ? h.revision : h.cierre)}</dd>
      <dt>Reiterancia</dt><dd>${h.reit || 0} ${h.reit === 1 ? 'falta previa' : 'faltas previas'} en el lote</dd>
      ${c.norma ? `<dt>Norma</dt><dd>${esc(c.norma)}${c.articulo ? ' · art. ' + esc(c.articulo) : ''}</dd>` : ''}
      ${c.penalidad ? `<dt>Penalidad</dt><dd>${esc(c.penalidad)}</dd>` : ''}
      <dt>Cargó</dt><dd>${quien(h.autor)}</dd>
      ${h.obs ? `<dt>Observación</dt><dd>${esc(h.obs)}</dd>` : ''}
    </dl>
    ${fotosDe(n)}
    <div class="list"><h3>Historial</h3><div class="timeline">${hs.map(x => `<div><span class="d">${fmt(x.fecha)} · ${quien(x.autor)}</span><br>${esc(x.cambio)}${x.nota ? ' — ' + esc(x.nota) : ''}</div>`).join('') || '<p class="empty">Sin movimientos.</p>'}</div></div>
  `, `${puede('supervisor') ? '<button type="button" class="danger" id="aBorrar">Borrar</button>' : ''}${abierta(h) ? '<button type="button" id="aRepro">Reprogramar</button>' : ''}<button type="button" class="pri" id="aEstado">Cambiar estado</button>`);
  $('aEstado').onclick = () => formEstado(n);
  if ($('aRepro')) $('aRepro').onclick = () => formRepro(n);
  if ($('aBorrar')) $('aBorrar').onclick = () => formBorrar(n);
  return m;
}
function formEstado(n) {
  const h = S.hallazgos[n];
  modal('Cambiar estado · ' + n, `
    <div class="f"><label for="eE">Nuevo estado</label><select id="eE">${opts(ESTADOS, h.estado)}</select></div>
    <div class="f" id="eRw"><label for="eR">Próxima revisión</label><input id="eR" type="date" value="${masDias(7)}" min="${hoy()}"></div>
    <div class="f"><label for="eN">Nota</label><textarea id="eN" rows="2" placeholder="Qué se vio o se habló"></textarea></div>
    ${campoFotos('eF')}
    <p class="note">Se registra una visita “Revisión de caso” de hoy para la U.F. (o se usa la que ya exista).</p>
  `, '<button type="button" data-close>Cancelar</button><button type="button" class="pri" id="eOk">Guardar</button>');
  const sync = () => { $('eRw').hidden = CERRADOS.indexOf($('eE').value) >= 0; };
  $('eE').onchange = sync; sync();
  $('eOk').onclick = async () => {
    const estado = $('eE').value;
    try {
      busy('Guardando…');
      const fd = new FormData();
      fd.append('datos', JSON.stringify(Object.assign({estado, nota: $('eN').value.trim(), revision: $('eR').value}, gpsDatos())));
      await agregarFotos(fd, 'estado', archivos('eF'));
      await api('/faltas/' + encodeURIComponent(n) + '/estado', {method: 'POST', form: fd});
      busy(''); cerrarModal(); toast(n + ': ' + estado); await cargar();
    } catch (e) { busy(''); error(e); }
  };
}
function formRepro(n) {
  modal('Reprogramar · ' + n, `
    <div class="f"><label for="rF">Nueva fecha de revisión</label><input id="rF" type="date" value="${masDias(7)}" min="${hoy()}"></div>
    <div class="f"><label for="rN">Motivo</label><textarea id="rN" rows="2" placeholder="Por qué se posterga"></textarea></div>
  `, '<button type="button" data-close>Cancelar</button><button type="button" class="pri" id="rOk">Reprogramar</button>');
  $('rOk').onclick = async () => {
    const f = $('rF').value; if (!f) { toast('Elegí la nueva fecha.', true); return; }
    try {
      busy('Guardando…');
      await api('/faltas/' + encodeURIComponent(n) + '/reprogramar', {method: 'POST', json: {fecha: f, nota: $('rN').value.trim()}});
      busy(''); cerrarModal(); toast(n + ' reprogramada al ' + fmt(f)); await cargar();
    } catch (e) { busy(''); error(e); }
  };
}
function formBorrar(n) {
  modal('Borrar ' + n, `
    <p class="ftxt">Se borra la falta con su historial. Las fotos pasan a la papelera del servidor. Queda una constancia con el motivo y quién la borró.</p>
    <div class="f"><label for="bM">Motivo (obligatorio)</label><textarea id="bM" rows="2"></textarea></div>
  `, '<button type="button" data-close>Cancelar</button><button type="button" class="danger" id="bOk">Borrar definitivamente</button>');
  $('bOk').onclick = async () => {
    const motivo = $('bM').value.trim(); if (motivo.length < 5) { toast('Escribí el motivo del borrado.', true); return; }
    try {
      busy('Borrando…');
      await api('/faltas/' + encodeURIComponent(n) + '/borrar', {method: 'POST', json: {motivo}});
      busy(''); cerrarModal(); toast(n + ' borrada'); await cargar();
    } catch (e) { busy(''); error(e); }
  };
}

/* ───────── agenda ───────── */
let tabAg = 'venc';
function agenda() {
  const t = hoy(), todas = Object.values(S.hallazgos).filter(abierta);
  const grupos = {venc: todas.filter(h => h.revision && h.revision < t), hoy: todas.filter(h => h.revision === t), prox: todas.filter(h => !h.revision || h.revision > t)};
  const lista = grupos[tabAg].sort((a, b) => (a.revision || '9').localeCompare(b.revision || '9') || a.uf - b.uf);
  const m = modal('Agenda de revisiones', `
    <div class="tabs">${[['venc', 'Vencidas'], ['hoy', 'Hoy'], ['prox', 'Próximas']].map(([k, l]) => `<button type="button" class="chip" data-tab="${k}" aria-pressed="${k === tabAg}">${l} (${grupos[k].length})</button>`).join('')}</div>
    <div class="list">${lista.length ? lista.map(h => `<button type="button" class="item" data-ag="${esc(h.n)}"><span class="top"><span class="cod">U.F. ${h.uf} · ${esc(h.n)}</span>${pillEstado(h)}</span><span class="t">${esc(catTxt(h.codigo))}</span><span class="meta">Revisión ${fmt(h.revision)} · Sector ${esc(sectorDe(h.uf))}${posVigente() && ufLot[h.uf] != null ? ' · a ' + metrosA(ufLot[h.uf], POS) + ' m' : ''}</span></button>`).join('') : '<p class="empty">Nada en esta lista.</p>'}</div>
  `);
  m.querySelectorAll('[data-tab]').forEach(b => { b.onclick = () => { tabAg = b.dataset.tab; agenda(); }; });
  m.querySelectorAll('[data-ag]').forEach(b => { b.onclick = () => { const h = S.hallazgos[b.dataset.ag], i = ufLot[h.uf]; cerrarModal(); if (i != null) { seguir = false; marcarGps(); seleccionar(i); irA(i); } fichaFalta(h.n); }; });
}
$('bAgenda').onclick = agenda;

/* ───────── catálogo ───────── */
function catalogo() {
  const cs = Object.values(S.cat).filter(c => c.activo).sort((a, b) => (a.rubro || '').localeCompare(b.rubro || '') || a.codigo.localeCompare(b.codigo));
  const admin = puede('admin');
  modal('Catálogo de faltas', `
    <p class="note">${admin ? 'Podés pegar el catálogo copiado de la planilla. Los códigos que ya existen se actualizan.' : 'Solo un administrador puede cambiar el catálogo.'}</p>
    <div class="scroll"><table class="cat"><thead><tr><th>Código</th><th>Rubro</th><th>Falta</th><th>Penalidad</th></tr></thead><tbody>
    ${cs.map(c => `<tr><td class="mono">${esc(c.codigo)}${/^EJ-/.test(c.codigo) ? '<span class="tag-ej">EJEMPLO</span>' : ''}</td><td>${esc(c.rubro)}</td><td>${esc(c.falta)}</td><td>${esc(c.penalidad || '—')}</td></tr>`).join('') || '<tr><td colspan="4" class="empty">El catálogo está vacío.</td></tr>'}
    </tbody></table></div>
    ${admin ? `<div class="f"><label for="cImp">Pegá las columnas Código, Rubro, Falta, Norma, Artículo, Penalidad (con el encabezado)</label><textarea id="cImp" rows="6" class="mono"></textarea></div>
      <div class="row"><label class="row"><input type="checkbox" id="cDel"> Quitar los códigos de ejemplo</label><button type="button" class="pri" id="cGo">Importar</button></div>` : ''}
  `);
  if (!admin) return;
  $('cGo').onclick = async () => {
    const lineas = $('cImp').value.split(/\r?\n/).filter(x => x.trim());
    if (lineas.length < 2) { toast('Pegá el encabezado y al menos una fila.', true); return; }
    const sep = lineas[0].indexOf('\t') >= 0 ? '\t' : (lineas[0].indexOf(';') >= 0 ? ';' : ',');
    const norm = s => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').trim();
    const enc = lineas[0].split(sep).map(norm), ix = k => enc.indexOf(k);
    if (ix('codigo') < 0 || ix('falta') < 0) { toast('No encontré las columnas Código y Falta en el encabezado.', true); return; }
    const v = (r, k) => ix(k) < 0 ? '' : (r[ix(k)] || '').trim();
    const filas = lineas.slice(1).map(l => l.split(sep)).map(r => ({codigo: v(r, 'codigo'), rubro: v(r, 'rubro'), falta: v(r, 'falta'), norma: v(r, 'norma'),
      articulo: v(r, 'articulo'), penalidad: v(r, 'penalidad'), activo: norm(v(r, 'activo')) !== 'no'})).filter(c => c.codigo && c.falta);
    try {
      busy(`Importando ${filas.length} códigos…`);
      const r = await api('/catalogo', {method: 'POST', json: {filas, quitar_ejemplos: $('cDel').checked}});
      busy(''); toast(r.guardados + ' códigos importados'); await cargar(); catalogo();
    } catch (e) { busy(''); error(e); }
  };
}
$('bCat').onclick = catalogo;

/* ───────── datos y aviso en vivo ───────── */
async function cargar() {
  const d = await api('/estado');
  HOY = d.hoy || HOY;
  S.visitas = {}; d.visitas.forEach(v => { S.visitas[v.n] = v; });
  S.hallazgos = {}; d.hallazgos.forEach(h => { S.hallazgos[h.n] = h; });
  S.hist = d.historial; S.fotos = d.fotos;
  S.cat = {}; d.catalogo.forEach(c => { c.activo = !!c.activo; S.cat[c.codigo] = c; });
  S.usuarios = {}; d.usuarios.forEach(u => { S.usuarios[u.id] = u; });
  GRUPOS = {}; d.grupos.forEach(g => { GRUPOS[g.uf] = String(g.ufs).split(',').map(Number); });
  const b = $('banner');
  if (!Object.values(S.cat).some(c => c.activo)) { b.hidden = false; b.textContent = 'El catálogo está vacío. Un administrador tiene que cargarlo.'; }
  else b.hidden = true;
  render();
}
let es = null, tRec = 0;
function vivo(on) { $('live').classList.toggle('on', on); $('liveT').textContent = on ? 'En línea' : 'Reconectando…'; }
function cerrarEventos() { if (es) { es.close(); es = null; } vivo(false); }
function abrirEventos() {
  cerrarEventos();
  es = new EventSource('/api/eventos');
  let primero = true;
  es.onopen = () => vivo(true);
  es.onmessage = () => { vivo(true); if (primero) { primero = false; return; } clearTimeout(tRec); tRec = setTimeout(() => cargar().catch(error), 250); };
  es.onerror = () => { vivo(false); };
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && YO) cargar().catch(error); });

async function iniciar() {
  try { YO = await api('/yo'); } catch (e) { return; }
  $('uName').innerHTML = `<b>${esc(YO.nombre)}</b> · ${esc(YO.rol)}`;
  applyVB();
  await cargar().catch(error);
  abrirEventos();
}
applyVB(); render(); iniciar();
})();
