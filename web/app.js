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
const ESTADOS = ['Pendiente','Aviso verbal','Aviso por folleto','Derivado a Comisión','Notificado/Intimado','En proceso de resolución','Resuelto','Verificado sin falta'];
const ESTADOS_GESTION = ['Notificado/Intimado','En proceso de resolución'];   // lo único que puede marcar el usuario de consulta
const CERRADOS = ['Resuelto','Verificado sin falta'];
const ORIGENES = ['Recorrido de inspección','Reclamo de vecino','Reclamo del servicio de recolección'];
const CONTACTOS = ['Hablé con el residente','No había nadie','No había nadie, dejé aviso escrito','Hablé con personal de poda, pasto, obra o limpieza','Pendiente de visita'];
const NIVEL = {consulta: 0, inspector: 1, supervisor: 2, admin: 3};

/* ───────── estado ───────── */
const S = {visitas: {}, hallazgos: {}, hist: [], fotos: [], cat: {}, usuarios: {}, marcas: {}};
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
function cerrarModal() { $('modal').hidden = true; $('modal').innerHTML = ''; limpiarFotos(); }
function modal(titulo, cuerpo, pie) {
  const m = $('modal');
  limpiarFotos();
  m.innerHTML = `<div class="dlg" role="dialog" aria-modal="true" aria-label="${esc(titulo)}"><div class="dlg-h"><h2>${esc(titulo)}</h2><button type="button" class="x" data-close aria-label="Cerrar">×</button></div><div class="dlg-b">${cuerpo}</div>${pie ? `<div class="dlg-f">${pie}</div>` : ''}</div>`;
  m.hidden = false;
  m.querySelectorAll('[data-close]').forEach(b => { b.onclick = cerrarModal; });
  m.onclick = e => { if (e.target === m) cerrarModal(); };
  m.querySelectorAll('img[data-foto]').forEach(ocultarRota);
  iniciarFotos(m);
  return m;
}
document.addEventListener('keydown', e => { if (e.key !== 'Escape') return; if (!$('modal').hidden) cerrarModal(); else if (DIB) salirDibujo(); else if (MAPA_MODO) salirModoMapa(); });
const quien = id => `<span class="who">${esc((S.usuarios[id] || {}).nombre || '—')}</span>`;
const fotoURL = n => '/api/fotos/' + encodeURIComponent(n);
const ocultarRota = img => { img.addEventListener('error', () => { img.style.visibility = 'hidden'; }); };
const catTxt = cod => { const c = S.cat[cod]; return c ? c.falta : '(tipo de falta inexistente)'; };
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
const gLots = el('g', {}), gNum = el('g', {}), gRed = el('g', {}), gRuta = el('g', {}), gMarcas = el('g', {}), gDib = el('g', {}), gGps = el('g', {});
const paths = LOTS.map((l, i) => el('path', {d: l.d, class: 'lot', 'data-i': i}, gLots));
LOTS.forEach(l => { el('text', {x: l.c[0], y: l.c[1], class: 'num'}, gNum).textContent = l.n.join('/'); });

function applyVB() { svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`); svg.classList.toggle('near', vb.w < 700); if (typeof escalarMarcadores === 'function' && gRuta.firstChild) escalarMarcadores(); }
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
  if (DIB) { if (!tip.hidden) ocultarTip(); return; }
  const mk = e.target.dataset && e.target.dataset.m;
  if (mk) { if (tipI !== 'm' + mk) { tipI = 'm' + mk; tip.innerHTML = textoTipMarca(mk); tip.hidden = false; } moverTip(e); return; }
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
  if (ptrs.size === 0 && moved < 8) {
    if (MAPA_MODO) MAPA_MODO(e, downT);
    else if (DIB) agregarPunto(e);
    else if (downT && downT.dataset && downT.dataset.m) fichaMarca(downT.dataset.m);
    else if (downT && downT.dataset && downT.dataset.i != null) seleccionar(+downT.dataset.i);
  }
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
function aGeo(x, y) {   // inversa de aPlano: coordenada del plano → lat/lon
  const E = CAL.a * x + CAL.b * y, N = CAL.b * x - CAL.a * y;
  return {lat: +((N + CAL.ty) / CAL.ky + CAL.lat0).toFixed(6), lon: +((E + CAL.tx) / CAL.kx + CAL.lon0).toFixed(6)};
}
let POS = null, watchId = null, seguir = false, avisoGps = false;
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
function iniciarGps(centrarAlLlegar, sinSeguir) {
  if (!('geolocation' in navigator)) { toast('Este navegador no tiene GPS disponible.', true); return; }
  if (!window.isSecureContext) { toast('El GPS solo funciona si la app se abre por HTTPS.', true); return; }
  if (watchId != null) { if (sinSeguir) return; seguir = true; marcarGps(); if (POS) centrar(POS.x, POS.y, Math.min(vb.w, 600)); return; }
  seguir = !sinSeguir; let primera = true;
  watchId = navigator.geolocation.watchPosition(p => {
    const {latitude: lat, longitude: lon, accuracy} = p.coords, q = aPlano(lat, lon);
    POS = {lat, lon, acc: Math.round(accuracy), x: q.x, y: q.y, ts: Date.now()};
    gGps.style.display = '';
    dot.setAttribute('cx', q.x); dot.setAttribute('cy', q.y);
    acc.setAttribute('cx', q.x); acc.setAttribute('cy', q.y); acc.setAttribute('r', accuracy / M_POR_UNIDAD);
    if (primera && centrarAlLlegar) { const i = loteEn(q.x, q.y); if (i >= 0) seleccionar(i); }
    if (seguir) centrar(q.x, q.y, primera ? 600 : vb.w);
    primera = false; marcarGps();
    if (DIB) gpsDibujo();
  }, e => {
    // Sin permiso: se apaga. Sin señal o demora (pasa bajo árboles o techos): se sigue escuchando y solo se avisa si nunca hubo posición.
    if (e.code === 1) {
      toast('Sin permiso de ubicación. Habilitalo en el navegador para este sitio.', true);
      navigator.geolocation.clearWatch(watchId); watchId = null; seguir = false; marcarGps(); if (DIB) { DIB.grabar = false; pintarDibujo(); }
    } else if (!POS && !avisoGps) { avisoGps = true; toast('Todavía no hay señal GPS. Probá al aire libre.', true); }
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
    const cnt = {venc: 0, hoy: 0, abierta: 0, cerrada: 0, visit: 0};
    paths.forEach((p, i) => {
      const st = estadoLote(i);
      if (st && (!FSEC || sectorDe(LOTS[i].n[0]) === FSEC)) cnt[st]++;
      p.setAttribute('class', 'lot' + (st ? ' st-' + st : '') + (pasaFiltro(i, st) ? '' : ' dim') + (i === SEL ? ' sel' : '') + (ELEG && ELEG.has(i) ? ' it-sel' : ''));
    });
    Object.keys(cnt).forEach(k => { $('lg-' + k).textContent = cnt[k]; });   // lotes en cada estado (del sector filtrado)
    $('lg-mk').textContent = Object.values(S.marcas).filter(m => M_CERR.indexOf(m.estado) < 0 && (!FSEC || m.sector === 'Sector ' + FSEC)).length;
    const n = Object.values(S.hallazgos).filter(h => abierta(h) && h.revision && h.revision <= hoy()).length;
    $('nAgenda').hidden = !n; $('nAgenda').textContent = n;
    if (SEL >= 0) pintarPanel();
    if (typeof tipI === 'number' && tipI >= 0) tip.innerHTML = textoTip(tipI);
    else if (typeof tipI === 'string' && S.marcas[tipI.slice(1)]) tip.innerHTML = textoTipMarca(tipI.slice(1));
    pintarMarcas();   // datos nuevos mientras el mouse está encima
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
    ${puede('inspector') ? '<div class="row"><button type="button" class="pri" id="pNueva">Nueva visita</button></div>' : '<p class="note">Usuario de consulta: solo lectura.</p>'}
    <section class="list"><h3>Faltas abiertas (${ab.length})</h3>${ab.length ? ab.map(item).join('') : '<p class="empty">Sin faltas abiertas.</p>'}</section>
    <section class="list"><h3>Visitas (${vs.length})</h3>${vs.length ? vs.slice(0, 15).map(v => `<div class="item"><span class="top"><span class="cod">${esc(v.n)} · ${fmt(v.fecha)}</span><span class="pill n">${esc(v.origen)}</span></span><span class="meta">${esc(v.contacto || 'Sin contacto registrado')}${v.obs ? ' · ' + esc(v.obs) : ''}</span><span class="meta">${quien(v.autor)}${v.lat != null ? ` · GPS ±${v.prec || '?'} m` : ''}</span>${fotosDe('', v.n)}</div>`).join('') : '<p class="empty">Todavía no hay visitas a esta U.F.</p>'}</section>
    ${ce.length ? `<section class="list"><h3>Faltas cerradas (${ce.length})</h3>${ce.map(item).join('')}</section>` : ''}
  </div>`;
  p.scrollTop = scroll;
  p.querySelectorAll('img[data-foto]').forEach(ocultarRota);
  $('pClose').onclick = () => { SEL = -1; p.hidden = true; render(); };
  if ($('pNueva')) $('pNueva').onclick = () => formVisita(ufs[0]);
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
/* Fotos: en el celular, "Sacar foto" abre la cámara directamente (capture). Cada toma se suma a la lista
   con su miniatura, así se pueden sacar varias seguidas sin pasar por la galería. */
const TACTIL = window.matchMedia('(pointer: coarse)').matches;
const FOTOS = {};
const campoFotos = id => `<div class="f fotos" data-fotos="${id}"><span class="flabel">Fotos</span>
  <div class="prev" id="${id}-prev"></div>
  <div class="row">
    ${TACTIL ? `<button type="button" class="pri cam" data-cam="${id}">📷 Sacar foto</button><button type="button" data-gal="${id}">Galería</button>`
             : `<button type="button" data-gal="${id}">Agregar fotos</button>`}
  </div>
  <input type="file" accept="image/*" capture="environment" id="${id}-cam" hidden>
  <input type="file" accept="image/*" multiple id="${id}-gal" hidden></div>`;
const archivos = id => (FOTOS[id] || []).map(x => x.file);
function pintarFotos(id) {
  const box = $(id + '-prev'); if (!box) return;
  box.innerHTML = (FOTOS[id] || []).map((x, k) => `<figure><img src="${x.url}" alt="Foto ${k + 1}"><button type="button" class="quitar" data-q="${k}" aria-label="Quitar foto ${k + 1}">×</button></figure>`).join('');
  box.querySelectorAll('[data-q]').forEach(b => { b.onclick = () => { const x = FOTOS[id].splice(+b.dataset.q, 1)[0]; URL.revokeObjectURL(x.url); pintarFotos(id); }; });
}
function iniciarFotos(root) {
  root.querySelectorAll('[data-fotos]').forEach(w => {
    const id = w.dataset.fotos;
    if (w.dataset.listo) return; w.dataset.listo = '1';
    FOTOS[id] = FOTOS[id] || [];
    const sumar = inp => { [...inp.files].forEach(f => FOTOS[id].push({file: f, url: URL.createObjectURL(f)})); inp.value = ''; pintarFotos(id); };
    $(id + '-cam').onchange = e => sumar(e.target);
    $(id + '-gal').onchange = e => sumar(e.target);
    w.querySelectorAll('[data-cam]').forEach(b => { b.onclick = () => $(id + '-cam').click(); });
    w.querySelectorAll('[data-gal]').forEach(b => { b.onclick = () => $(id + '-gal').click(); });
    pintarFotos(id);
  });
}
function limpiarFotos() { Object.keys(FOTOS).forEach(id => { FOTOS[id].forEach(x => URL.revokeObjectURL(x.url)); delete FOTOS[id]; }); }
async function agregarFotos(fd, grupo, files) { for (const f of files) fd.append('f_' + grupo, await comprimir(f), 'foto.jpg'); }

/* ───────── nueva visita ───────── */
function opcionesCat(sel) {
  const porRubro = {};
  Object.values(S.cat).filter(c => c.activo && c.visible !== 0).forEach(c => { (porRubro[c.rubro] = porRubro[c.rubro] || []).push(c); });
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
    ${sinCat ? '<p class="note">No hay tipos de faltas cargados: un administrador tiene que cargarlos para registrar faltas.</p>' : '<button type="button" id="addF">Agregar falta</button>'}
  `, '<button type="button" data-close>Cancelar</button><button type="button" class="pri" id="vOk">Guardar visita</button>');
  if ($('addF')) $('addF').onclick = () => {
    $('faltas').insertAdjacentHTML('beforeend', bloqueFalta());
    iniciarFotos($('faltas'));
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
  `, `<a class="btn" id="aPdf" href="/api/faltas/${encodeURIComponent(n)}/pdf" download title="Ficha de la falta en PDF, con las fotos adjuntas">Ficha PDF</a>${puede('supervisor') ? '<button type="button" class="danger" id="aBorrar">Borrar</button>' : ''}${puede('inspector') && abierta(h) ? '<button type="button" id="aRepro">Reprogramar</button>' : ''}${puede('inspector') ? '<button type="button" class="pri" id="aEstado">Cambiar estado</button>' : (YO && YO.rol === 'consulta' && abierta(h) ? '<button type="button" class="pri" id="aEstado">Gestionar</button>' : '')}`);
  if ($('aEstado')) $('aEstado').onclick = () => formEstado(n);
  if ($('aRepro')) $('aRepro').onclick = () => formRepro(n);
  if ($('aBorrar')) $('aBorrar').onclick = () => formBorrar(n);
  return m;
}
function formEstado(n) {
  const h = S.hallazgos[n], gestion = !puede('inspector');
  const lista = gestion ? ESTADOS_GESTION : ESTADOS;
  modal((gestion ? 'Gestionar · ' : 'Cambiar estado · ') + n, `
    <div class="f"><label for="eE">Nuevo estado</label><select id="eE">${opts(lista, lista.indexOf(h.estado) >= 0 ? h.estado : lista[0])}</select></div>
    <div class="f" id="eRw"><label for="eR">Próxima revisión</label><input id="eR" type="date" value="${masDias(7)}" min="${hoy()}"></div>
    <div class="f"><label for="eN">Nota</label><textarea id="eN" rows="2" placeholder="${gestion ? 'Nº de nota o acta, a quién se notificó, plazo dado' : 'Qué se vio o se habló'}"></textarea></div>
    ${gestion ? '<p class="note">Queda en el historial de la falta con tu nombre. No genera una visita.</p>' : campoFotos('eF') + '<p class="note">Se registra una visita “Revisión de caso” de hoy para la U.F. (o se usa la que ya exista).</p>'}
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
  const marcasAb = Object.values(S.marcas).filter(m => M_CERR.indexOf(m.estado) < 0).sort((a, b) => (a.revision || '9').localeCompare(b.revision || '9'));
  const lista = tabAg === 'esp' ? [] : grupos[tabAg].sort((a, b) => (a.revision || '9').localeCompare(b.revision || '9') || a.uf - b.uf);
  const m = modal('Agenda de revisiones', `
    <div class="tabs">${[['venc', 'Vencidas'], ['hoy', 'Hoy'], ['prox', 'Próximas'], ['esp', 'Espacios comunes']].map(([k, l]) => `<button type="button" class="chip" data-tab="${k}" aria-pressed="${k === tabAg}">${l} (${k === 'esp' ? marcasAb.length : grupos[k].length})</button>`).join('')}</div>
    <div class="list">${tabAg === 'esp' ? (marcasAb.length ? marcasAb.map(m => itemMarca(m)).join('') : '<p class="empty">No hay novedades abiertas en espacios comunes.</p>') : lista.length ? lista.map(h => `<button type="button" class="item" data-ag="${esc(h.n)}"><span class="top"><span class="cod">U.F. ${h.uf} · ${esc(h.n)}</span>${pillEstado(h)}</span><span class="t">${esc(catTxt(h.codigo))}</span><span class="meta">Revisión ${fmt(h.revision)} · Sector ${esc(sectorDe(h.uf))}${posVigente() && ufLot[h.uf] != null ? ' · a ' + metrosA(ufLot[h.uf], POS) + ' m' : ''}</span></button>`).join('') : '<p class="empty">Nada en esta lista.</p>'}</div>
  `);
  m.querySelectorAll('[data-tab]').forEach(b => { b.onclick = () => { tabAg = b.dataset.tab; agenda(); }; });
  m.querySelectorAll('[data-mk]').forEach(b => { b.onclick = () => { cerrarModal(); fichaMarca(b.dataset.mk, true); }; });
  m.querySelectorAll('[data-ag]').forEach(b => { b.onclick = () => { const h = S.hallazgos[b.dataset.ag], i = ufLot[h.uf]; cerrarModal(); if (i != null) { seguir = false; marcarGps(); seleccionar(i); irA(i); } fichaFalta(h.n); }; });
}
$('bAgenda').onclick = agenda;

/* ───────── catálogo ───────── */
/* Catálogo: todos lo pueden ver; el admin hace el ABM (alta, baja y modificación) y la importación desde la planilla. */
let catFiltro = '', catBajas = false;
function catalogo() {
  const admin = puede('admin');
  const q = catFiltro.toLowerCase();
  const cs = Object.values(S.cat)
    .filter(c => c.activo || (admin && catBajas))
    .filter(c => !q || [c.codigo, c.rubro, c.falta, c.norma].join(' ').toLowerCase().includes(q))
    .sort((a, b) => (a.rubro || '').localeCompare(b.rubro || '') || a.codigo.localeCompare(b.codigo));
  const nBajas = Object.values(S.cat).filter(c => !c.activo).length;
  const fila = c => `<tr class="${c.activo ? '' : 'baja'}">
      <td class="mono">${esc(c.codigo)}${/^EJ-/.test(c.codigo) ? '<span class="tag-ej">EJEMPLO</span>' : ''}${c.activo ? '' : '<span class="tag-baja">BAJA</span>'}</td>
      <td>${esc(c.rubro)}</td><td>${esc(c.falta)}${c.visible === 0 ? '<br><span class="note">No se ofrece en el recorrido</span>' : ''}</td>
      <td>${esc(c.penalidad || '—')}</td><td class="cnt">${c.usos || 0}</td>
      ${admin ? `<td class="acc"><button type="button" data-ed="${esc(c.codigo)}">Editar</button>${c.activo
        ? `<button type="button" class="danger" data-baja="${esc(c.codigo)}">${c.usos ? 'Dar de baja' : 'Eliminar'}</button>`
        : `<button type="button" data-alta="${esc(c.codigo)}">Reactivar</button>`}</td>` : ''}</tr>`;
  const m = modal('Tipos de faltas', `
    <div class="row cat-bar">
      <input id="cQ" type="search" placeholder="Buscar código, rubro o falta" value="${esc(catFiltro)}" aria-label="Buscar tipos de faltas">
      ${admin ? `<label class="row chk"><input type="checkbox" id="cBajas" ${catBajas ? 'checked' : ''}> Ver dados de baja (${nBajas})</label>
      <button type="button" class="pri" id="cNuevo">+ Nuevo tipo de falta</button>` : ''}
    </div>
    <div class="scroll"><table class="cat"><thead><tr><th>Código</th><th>Rubro</th><th>Falta</th><th>Penalidad</th><th class="cnt" title="Faltas cargadas con este código">Usos</th>${admin ? '<th></th>' : ''}</tr></thead><tbody>
    ${cs.map(fila).join('') || `<tr><td colspan="${admin ? 6 : 5}" class="empty">${q ? 'Ningún código coincide con la búsqueda.' : 'No hay tipos de faltas cargados.'}</td></tr>`}
    </tbody></table></div>
    ${admin ? `<details><summary class="sum">Importar desde la planilla</summary>
      <div class="f"><label for="cImp">Pegá las columnas Código, Rubro, Falta, Norma, Artículo, Penalidad (con el encabezado). Los códigos que ya existen se actualizan.</label><textarea id="cImp" rows="6" class="mono"></textarea></div>
      <div class="row"><label class="row chk"><input type="checkbox" id="cDel"> Quitar los códigos de ejemplo</label><button type="button" class="pri" id="cGo">Importar</button></div></details>
      <details id="cHistD"><summary class="sum">Historial de cambios de los tipos de faltas</summary><div id="cHist" class="note">Cargando…</div></details>` : '<p class="note">Solo un administrador puede modificar los tipos de faltas.</p>'}
  `);
  m.querySelector('.dlg').classList.add('ancho');
  let tq = 0;
  $('cQ').oninput = e => { clearTimeout(tq); tq = setTimeout(() => { catFiltro = e.target.value; const pos = e.target.selectionStart; catalogo(); const i = $('cQ'); i.focus(); try { i.setSelectionRange(pos, pos); } catch (x) {} }, 250); };
  if (!admin) return;
  $('cBajas').onchange = e => { catBajas = e.target.checked; catalogo(); };
  $('cNuevo').onclick = () => formCodigo(null);
  m.querySelectorAll('[data-ed]').forEach(b => { b.onclick = () => formCodigo(S.cat[b.dataset.ed]); });
  m.querySelectorAll('[data-alta]').forEach(b => { b.onclick = async () => {
    const c = S.cat[b.dataset.alta];
    try { busy('Guardando…'); await api('/catalogo/codigos/' + encodeURIComponent(c.codigo), {method: 'PUT', json: Object.assign({}, c, {activo: true})});
      busy(''); toast(c.codigo + ' reactivado'); await cargar(); catalogo(); } catch (e) { busy(''); error(e); }
  }; });
  m.querySelectorAll('[data-baja]').forEach(b => { b.onclick = () => confirmarBaja(S.cat[b.dataset.baja]); });
  $('cHistD').ontoggle = async e => {
    if (!e.target.open) return;
    try {
      const h = await api('/catalogo/historial');
      $('cHist').innerHTML = h.length ? `<div class="timeline">${h.map(x => `<div><span class="d">${esc(x.fecha.replace('T', ' ').slice(0, 16))} · ${esc(x.usuario)}</span><br><b>${esc(x.codigo)}</b> — ${esc(x.accion)}${x.detalle ? ': ' + esc(x.detalle) : ''}</div>`).join('')}</div>` : 'Todavía no hay cambios registrados.';
    } catch (x) { $('cHist').textContent = 'No se pudo cargar el historial.'; }
  };
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
function formCodigo(c) {
  const nuevo = !c; c = c || {visible: 1};
  const rubros = [...new Set(Object.values(S.cat).map(x => x.rubro).filter(Boolean))].sort();
  modal(nuevo ? 'Nuevo tipo de falta' : 'Editar ' + c.codigo, `
    <div class="grid2">
      <div class="f"><label for="kC">Código</label><input id="kC" class="mono" maxlength="10" value="${esc(c.codigo || '')}" ${nuevo ? 'required' : 'disabled'} placeholder="Ej.: RES-04"></div>
      <div class="f"><label for="kR">Rubro</label><input id="kR" list="kRl" maxlength="80" value="${esc(c.rubro || '')}" placeholder="Elegí o escribí uno nuevo"><datalist id="kRl">${rubros.map(r => `<option value="${esc(r)}">`).join('')}</datalist></div>
    </div>
    <div class="f"><label for="kF">Falta</label><input id="kF" maxlength="250" value="${esc(c.falta || '')}" required placeholder="Descripción que ve el inspector al elegirla"></div>
    <div class="f"><label for="kO">Qué observar</label><textarea id="kO" rows="2" maxlength="2000" placeholder="Opcional: criterio para el inspector">${esc(c.que_observar || '')}</textarea></div>
    <div class="grid2">
      <div class="f"><label for="kN">Norma</label><input id="kN" maxlength="150" value="${esc(c.norma || '')}" placeholder="Ej.: Reglamento interno"></div>
      <div class="f"><label for="kA">Artículo</label><input id="kA" maxlength="40" value="${esc(c.articulo || '')}"></div>
    </div>
    <div class="f"><label for="kP">Penalidad</label><input id="kP" maxlength="150" value="${esc(c.penalidad || '')}"></div>
    <label class="row chk"><input type="checkbox" id="kV" ${c.visible === 0 ? '' : 'checked'}> Ofrecerlo al cargar faltas en el recorrido</label>
    ${!nuevo && c.usos ? `<p class="note">Este código tiene ${c.usos} ${c.usos === 1 ? 'falta cargada' : 'faltas cargadas'}. Si cambiás la descripción, se ve la nueva también en esas faltas.</p>` : ''}
  `, '<button type="button" id="kCancel">Cancelar</button><button type="button" class="pri" id="kOk">Guardar</button>');
  $('kCancel').onclick = catalogo;
  $('kOk').onclick = async () => {
    const d = {codigo: $('kC').value.trim().toUpperCase(), rubro: $('kR').value.trim(), falta: $('kF').value.trim(), que_observar: $('kO').value.trim(),
      norma: $('kN').value.trim(), articulo: $('kA').value.trim(), penalidad: $('kP').value.trim(), visible: $('kV').checked};
    if (nuevo && !d.codigo) { toast('Escribí el código.', true); return; }
    if (!d.falta) { toast('Escribí la descripción de la falta.', true); return; }
    try {
      busy('Guardando…');
      if (nuevo) await api('/catalogo/codigos', {method: 'POST', json: d});
      else await api('/catalogo/codigos/' + encodeURIComponent(c.codigo), {method: 'PUT', json: d});
      busy(''); toast(nuevo ? 'Código ' + d.codigo + ' creado' : c.codigo + ' actualizado'); await cargar(); catalogo();
    } catch (e) { busy(''); error(e); }
  };
}
function confirmarBaja(c) {
  const usado = c.usos > 0;
  modal((usado ? 'Dar de baja ' : 'Eliminar ') + c.codigo, `
    <p class="ftxt"><b>${esc(c.codigo)}</b> · ${esc(c.falta)}</p>
    <p class="ftxt">${usado
      ? `Tiene ${c.usos} ${c.usos === 1 ? 'falta cargada' : 'faltas cargadas'}, así que no se borra: deja de ofrecerse al cargar visitas y las faltas existentes conservan su descripción. Se puede reactivar cuando quieras.`
      : 'Nunca se usó, así que se elimina de la lista.'}</p>
  `, `<button type="button" id="bCancel">Cancelar</button><button type="button" class="danger" id="bOk">${usado ? 'Dar de baja' : 'Eliminar'}</button>`);
  $('bCancel').onclick = catalogo;
  $('bOk').onclick = async () => {
    try {
      busy('Guardando…');
      const r = await api('/catalogo/codigos/' + encodeURIComponent(c.codigo), {method: 'DELETE'});
      busy(''); toast(c.codigo + (r.resultado === 'baja' ? ' dado de baja' : ' eliminado')); await cargar(); catalogo();
    } catch (e) { busy(''); error(e); }
  };
}
$('bCat').onclick = catalogo;

/* ───────── novedades en espacios comunes (lápiz) ───────── */
const M_ESTADOS = ['Relevado', 'Informado a mantenimiento', 'En reparación', 'Reparado', 'No corresponde'];
const M_CERR = ['Reparado', 'No corresponde'], M_GESTION = ['Informado a mantenimiento', 'En reparación'];
const M_TIPOS = ['Bache / calzada dañada', 'Cordón o vereda rota', 'Luminaria apagada o dañada', 'Arbolado / ramas / poda', 'Pasto alto / falta de limpieza',
  'Residuos o escombros', 'Pérdida de agua / desagüe', 'Señalización / cartelería', 'Mobiliario, juegos o bancos', 'Cableado bajo o caído', 'Cerco perimetral', 'Otro'];
const M_LUGARES = ['Calle', 'Peatonal', 'Plaza', 'Espacio verde', 'Club / deportes', 'Perímetro', 'Otro'];
const M_FORMA = {P: 'Punto', L: 'Línea', A: 'Área'};
const mkClase = e => ({'Relevado': 'rel', 'Informado a mantenimiento': 'inf', 'En reparación': 'rep'}[e] || 'ok');
const pillMarca = m => `<span class="pill mk-${mkClase(m.estado)}">${esc(m.estado)}</span>`;
const centro = g => [g.reduce((s, p) => s + p[0], 0) / g.length, g.reduce((s, p) => s + p[1], 0) / g.length];
function sectorDePunto(x, y) {
  let best = -1, bd = Infinity;
  LOTS.forEach((l, i) => { const d = Math.hypot(l.c[0] - x, l.c[1] - y); if (d < bd) { bd = d; best = i; } });
  return best >= 0 ? sectorDe(LOTS[best].n[0]) : '';
}
function textoTipMarca(n) {
  const m = S.marcas[n]; if (!m) return '';
  return `<b>${esc(m.n)} · ${esc(m.lugar)}</b><span class="tip-s">${esc(m.tipo)}</span><span class="tip-n">${esc(m.estado)}</span>${m.revision && M_CERR.indexOf(m.estado) < 0 ? `<span class="tip-s">Revisión ${fmt(m.revision)}</span>` : ''}`;
}
function pintarMarcas() {
  gMarcas.innerHTML = '';
  Object.values(S.marcas).forEach(m => {
    const c = 'mk mk-' + mkClase(m.estado) + (FSEC && m.sector && m.sector !== 'Sector ' + FSEC ? ' dim' : '');
    const pts = m.geo.map(p => p.join(',')).join(' ');
    if (m.forma === 'Área') el('polygon', {points: pts, class: c + ' mk-a', 'data-m': m.n}, gMarcas);
    else if (m.forma === 'Línea') { el('polyline', {points: pts, class: c + ' mk-l-halo', 'data-m': m.n}, gMarcas); el('polyline', {points: pts, class: c + ' mk-l', 'data-m': m.n}, gMarcas); }
    else { const [x, y] = m.geo[0]; el('circle', {cx: x, cy: y, r: 20, class: c + ' mk-p', 'data-m': m.n}, gMarcas); }
  });
}
const itemMarca = m => `<button type="button" class="item" data-mk="${esc(m.n)}"><span class="top"><span class="cod">${esc(m.n)} · ${esc(m.lugar)}${m.sector ? ' · ' + esc(m.sector) : ''}</span>${pillMarca(m)}</span><span class="t">${esc(m.tipo)}</span><span class="meta">${esc(m.descripcion)}${m.revision && M_CERR.indexOf(m.estado) < 0 ? ' · revisión ' + fmt(m.revision) : ''}</span></button>`;

/* modo dibujo */
let DIB = null;   // {forma, pts:[[x,y]], editar: n | null}
function entrarDibujo(forma, editar) {
  if (!puede('inspector')) return;
  cerrarModal(); ocultarTip();
  DIB = {forma: forma || 'P', pts: [], editar: editar || null, gps: [], grabar: false};   // gps: precisión de cada vértice tomado con GPS (null = tocado en el plano)
  if ('geolocation' in navigator && window.isSecureContext) iniciarGps(false, true);
  $('dibujo').hidden = false; $('bLapiz').classList.add('on'); svg.classList.add('dibujando');
  pintarDibujo();
}
function salirDibujo() { DIB = null; gDib.innerHTML = ''; $('dibujo').hidden = true; $('bLapiz').classList.remove('on'); svg.classList.remove('dibujando'); }
function agregarPunto(e) {
  const p = aSvg(e.clientX, e.clientY), q = [Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10];
  ponerVertice(q, null);
}
function ponerVertice(q, prec) {
  if (DIB.forma === 'P') { DIB.pts = [q]; DIB.gps = [prec]; } else { DIB.pts.push(q); DIB.gps.push(prec); }
  pintarDibujo();
  if (DIB.forma === 'P') terminarDibujo();
}
const GPS_MAX = 30, PASO_M = 5;   // precisión mínima aceptable (m) y separación entre vértices al grabar recorrido
function gpsDibujo() {
  const d = DIB, p = posVigente(); if (!d) return;
  if (d.grabar && p && p.acc <= GPS_MAX) {
    const u = d.pts[d.pts.length - 1];
    if (!u || Math.hypot(u[0] - p.x, u[1] - p.y) * M_POR_UNIDAD >= PASO_M) { centrar(p.x, p.y, vb.w); ponerVertice([Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10], p.acc); return; }
  }
  pintarDibujo();
}
function pintarDibujo() {
  gDib.innerHTML = '';
  const d = DIB; if (!d) return;
  document.querySelectorAll('[data-forma]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.forma === d.forma)));
  const min = d.forma === 'A' ? 3 : d.forma === 'L' ? 2 : 1;
  $('dibTxt').textContent = d.forma === 'P' ? 'Tocá el plano donde está la novedad.'
    : `Tocá el plano para marcar ${d.forma === 'L' ? 'el recorrido' : 'el contorno'} (${d.pts.length} ${d.pts.length === 1 ? 'punto' : 'puntos'}${d.pts.length < min ? `, mínimo ${min}` : ''}).`;
  $('dibOk').hidden = d.forma === 'P'; $('dibOk').disabled = d.pts.length < min;
  $('dibUndo').hidden = d.forma === 'P'; $('dibUndo').disabled = !d.pts.length;
  const p = posVigente();
  $('dibGps').disabled = !p; $('dibRec').hidden = d.forma === 'P'; $('dibRec').disabled = !p;
  $('dibRec').textContent = d.grabar ? '⏸ Pausar recorrido' : '🚶 Grabar recorrido'; $('dibRec').classList.toggle('on', d.grabar);
  $('dibEst').textContent = watchId == null ? 'GPS apagado: ubicá la novedad tocando el plano.' : !p ? 'Buscando señal GPS…'
    : `GPS ±${p.acc} m${p.acc > GPS_MAX ? ' · precisión baja, conviene ubicar a mano' : ''}${d.grabar ? ' · grabando: caminá el tramo' : ''}`;
  $('dibEst').classList.toggle('lejos', !!p && p.acc > GPS_MAX);
  if (d.pts.length > 1) el(d.forma === 'A' ? 'polygon' : 'polyline', {points: d.pts.map(p => p.join(',')).join(' '), class: 'dib-' + d.forma}, gDib);
  d.pts.forEach(([x, y]) => el('circle', {cx: x, cy: y, r: 7, class: 'dib-v'}, gDib));
}
function terminarDibujo() {
  const d = DIB; if (!d) return;
  const forma = d.forma, geo = d.pts.slice(), editar = d.editar, ub = ubicacionDe(geo, d.gps);
  salirDibujo();
  if (editar) guardarRedibujo(editar, forma, geo, ub); else formMarca(forma, geo, ub);
}
document.querySelectorAll('[data-forma]').forEach(b => { b.onclick = () => { if (DIB) { DIB.forma = b.dataset.forma; DIB.pts = []; pintarDibujo(); } }; });
$('bLapiz').onclick = () => DIB ? salirDibujo() : entrarDibujo('P');
$('dibX').onclick = salirDibujo;
$('dibUndo').onclick = () => { if (DIB) { DIB.pts.pop(); DIB.gps.pop(); pintarDibujo(); } };
$('dibRec').onclick = () => { if (!DIB) return; DIB.grabar = !DIB.grabar; if (DIB.grabar) { const p = posVigente(); if (p) centrar(p.x, p.y, Math.min(vb.w, 500)); } gpsDibujo(); };
$('dibOk').onclick = terminarDibujo;
$('dibGps').onclick = () => { const p = posVigente(); if (!DIB || !p) return;
  if (p.acc > GPS_MAX) toast(`Precisión baja (±${p.acc} m): revisá que el punto quede bien ubicado.`, true);
  centrar(p.x, p.y, Math.min(vb.w, 500)); ponerVertice([Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10], p.acc); };
/* La novedad se georreferencia siempre por el centro del dibujo (calibración del plano, ±15 m).
   Si todos los vértices salieron del GPS se guarda como "GPS" con la peor precisión de esos vértices. */
function ubicacionDe(geo, gps) {
  const [x, y] = centro(geo), g = aGeo(x, y), todosGps = gps.length === geo.length && gps.every(v => v != null);
  return Object.assign(g, todosGps ? {ubicacion: 'GPS', prec: String(Math.max(...gps))} : {ubicacion: 'Plano'});
}
const textoUbic = m => m.lat == null ? 'Sin coordenadas' : `${(+m.lat).toFixed(6)}, ${(+m.lon).toFixed(6)} · ${m.ubic === 'GPS' ? 'GPS' + (m.prec != null ? ' ±' + m.prec + ' m' : '') : 'ubicada en el plano (±15 m)'}`;

function formMarca(forma, geo, ub) {
  const [cx, cy] = centro(geo), sector = sectorDePunto(cx, cy);
  modal('Nueva novedad en espacio común', `
    <p class="note">${M_FORMA[forma]} marcado en el plano${sector ? ' · Sector ' + esc(sector) : ''}.</p>
    <p class="gpsinfo${ub.ubicacion === 'GPS' && +ub.prec > GPS_MAX ? ' lejos' : ''}">📍 ${esc(textoUbic({lat: ub.lat, lon: ub.lon, ubic: ub.ubicacion, prec: ub.prec}))}</p>
    <div class="grid2">
      <div class="f"><label for="mT">Tipo de novedad</label><select id="mT">${opts(M_TIPOS, M_TIPOS[0])}</select></div>
      <div class="f"><label for="mL">Lugar</label><select id="mL">${opts(M_LUGARES, forma === 'A' ? 'Plaza' : 'Calle')}</select></div>
    </div>
    <div class="f"><label for="mD">Descripción</label><textarea id="mD" rows="2" maxlength="500" placeholder="Qué se ve y dónde (ej.: bache de 1 m frente a la U.F. 1203)"></textarea></div>
    <div class="grid2">
      <div class="f"><label for="mE">Estado</label><select id="mE">${opts(M_ESTADOS.slice(0, 3), 'Relevado')}</select></div>
      <div class="f"><label for="mR">Volver a revisar</label><input id="mR" type="date" value="${masDias(7)}" min="${hoy()}"></div>
    </div>
    <div class="f"><label for="mO">Observación</label><textarea id="mO" rows="2" placeholder="Opcional"></textarea></div>
    ${campoFotos('mF')}
  `, '<button type="button" id="mX">Cancelar</button><button type="button" id="mRedib">Volver a dibujar</button><button type="button" class="pri" id="mOk">Guardar</button>');
  $('mX').onclick = cerrarModal;
  $('mRedib').onclick = () => entrarDibujo(forma);
  $('mOk').onclick = async () => {
    const d = Object.assign({forma: Object.keys(M_FORMA).find(k => M_FORMA[k] === M_FORMA[forma]) || forma, geo, sector, tipo: $('mT').value, lugar: $('mL').value,
      descripcion: $('mD').value.trim(), estado: $('mE').value, revision: $('mR').value, obs: $('mO').value.trim()}, ub);
    if (!d.descripcion) { toast('Describí la novedad.', true); return; }
    try {
      busy('Guardando…');
      const fd = new FormData(); fd.append('datos', JSON.stringify(d)); await agregarFotos(fd, 'marca', archivos('mF'));
      const r = await api('/marcas', {method: 'POST', form: fd});
      busy(''); cerrarModal(); toast(r.n + ' guardada'); await cargar(); fichaMarca(r.n);   // queda abierta para compartirla
    } catch (e) { busy(''); error(e); }
  };
}
async function guardarRedibujo(n, forma, geo, ub) {
  const [cx, cy] = centro(geo);
  try { busy('Guardando…'); await api('/marcas/' + encodeURIComponent(n), {method: 'PUT', json: Object.assign({forma, geo, sector: sectorDePunto(cx, cy)}, ub)}); busy(''); toast(n + ': dibujo actualizado'); await cargar(); fichaMarca(n); }
  catch (e) { busy(''); error(e); }
}
function fichaMarca(n, centrar_) {
  const m = S.marcas[n]; if (!m) return;
  if (centrar_) { const [x, y] = centro(m.geo); seguir = false; marcarGps(); centrar(x, y, 500); }
  const abierta_ = M_CERR.indexOf(m.estado) < 0, hs = S.hist.filter(x => x.reg === n);
  const acciones = [
    puede('supervisor') ? '<button type="button" class="danger" id="kBorrar">Borrar</button>' : '',
    '<button type="button" class="wa" id="kWa">Enviar por WhatsApp</button>',
    puede('inspector') ? '<button type="button" id="kEdit">Editar</button>' : '',
    puede('inspector') ? '<button type="button" id="kRedib">Redibujar</button>' : '',
    puede('inspector') ? '<button type="button" class="pri" id="kEst">Cambiar estado</button>' : (YO && YO.rol === 'consulta' && abierta_ ? '<button type="button" class="pri" id="kEst">Gestionar</button>' : ''),
  ].join('');
  modal(n + ' · ' + m.lugar, `
    <div class="row">${pillMarca(m)}<span class="cod">${esc(m.forma)}${m.sector ? ' · ' + esc(m.sector) : ''}</span></div>
    <p class="ftit">${esc(m.tipo)}</p>
    <p class="ftxt">${esc(m.descripcion)}</p>
    <dl class="kv">
      <dt>Relevada</dt><dd>${fmt(m.fecha)} · ${quien(m.autor)}</dd>
      <dt>Ubicación</dt><dd>${esc(textoUbic(m))}${m.lat != null ? ` · <a href="https://www.google.com/maps/search/?api=1&query=${+m.lat},${+m.lon}" target="_blank" rel="noopener">Abrir en el mapa</a>` : ''} · <button type="button" class="link" id="kVer">Ver en el plano</button></dd>
      <dt>${abierta_ ? 'Revisión' : 'Cierre'}</dt><dd>${fmt(abierta_ ? m.revision : m.cierre)}</dd>
      ${m.obs ? `<dt>Observación</dt><dd>${esc(m.obs)}</dd>` : ''}
    </dl>
    ${fotosDe(n)}
    <div class="list"><h3>Historial</h3><div class="timeline">${hs.map(x => `<div><span class="d">${fmt(x.fecha)} · ${quien(x.autor)}</span><br>${esc(x.cambio)}${x.nota ? ' — ' + esc(x.nota) : ''}</div>`).join('') || '<p class="empty">Sin movimientos.</p>'}</div></div>
  `, acciones);
  const prep = prepararFotos(n);   // se bajan antes del toque: compartir exige hacerlo enseguida del clic
  $('kWa').onclick = () => compartirMarca(n, prep);
  $('kVer').onclick = () => { cerrarModal(); const [x, y] = centro(m.geo); seguir = false; marcarGps(); centrar(x, y, 400); };
  if ($('kEst')) $('kEst').onclick = () => formEstadoMarca(n);
  if ($('kEdit')) $('kEdit').onclick = () => editarMarca(n);
  if ($('kRedib')) $('kRedib').onclick = () => entrarDibujo(Object.keys(M_FORMA).find(k => M_FORMA[k] === m.forma), n);
  if ($('kBorrar')) $('kBorrar').onclick = () => borrarMarca(n);
}
/* compartir por WhatsApp: en el celular usa el menú de compartir del sistema (texto + fotos);
   en la PC abre WhatsApp Web solo con el texto y la ubicación. */
const MAX_FOTOS_WA = 4;
function prepararFotos(n) {
  if (!navigator.canShare) return Promise.resolve([]);
  const fs = S.fotos.filter(f => f.reg === n).slice(-MAX_FOTOS_WA);
  return Promise.all(fs.map(async f => {
    try { const r = await fetch(fotoURL(f.n)); if (!r.ok) return null; return new File([await r.blob()], `${n}-${f.n}.jpg`, {type: 'image/jpeg'}); }
    catch (e) { return null; }
  })).then(a => a.filter(Boolean));
}
function textoMarca(m) {
  const g = m.lat != null ? {lat: +m.lat, lon: +m.lon} : aGeo(...centro(m.geo));
  return [`*Novedad ${m.n} · ${m.lugar}${m.sector ? ' · ' + m.sector : ''}*`,
    `Tipo: ${m.tipo}`, m.descripcion, `Estado: ${m.estado}`,
    `Relevada el ${fmt(m.fecha)} por ${(S.usuarios[m.autor] || {}).nombre || "—"}`,
    `Ubicación: https://www.google.com/maps/search/?api=1&query=${g.lat},${g.lon}`].join('\n');
}
async function compartirMarca(n, prep) {
  const m = S.marcas[n]; if (!m) return;
  const text = textoMarca(m);
  const abrirWa = () => window.open('https://wa.me/?text=' + encodeURIComponent(text), '_blank', 'noopener');
  if (!navigator.share) {
    abrirWa();
    if (S.fotos.some(f => f.reg === n)) toast('Desde la PC WhatsApp no deja adjuntar las fotos por enlace: tocá cada foto, guardala y adjuntala en el chat.');
    return;
  }
  const files = await prep;
  try {
    if (files.length && navigator.canShare({files, text})) await navigator.share({files, text, title: 'Novedad ' + n});
    else { await navigator.share({text, title: 'Novedad ' + n}); if (S.fotos.some(f => f.reg === n)) toast('Este celular no permite compartir las fotos junto con el texto.', true); }
  } catch (e) {
    if (e.name === 'AbortError') return;     // el usuario cerró el menú
    abrirWa();                               // p. ej. se venció el permiso del toque mientras bajaban las fotos
  }
}
function formEstadoMarca(n) {
  const m = S.marcas[n], gestion = !puede('inspector'), lista = gestion ? M_GESTION : M_ESTADOS;
  modal((gestion ? 'Gestionar · ' : 'Cambiar estado · ') + n, `
    <div class="f"><label for="qE">Nuevo estado</label><select id="qE">${opts(lista, lista.indexOf(m.estado) >= 0 ? m.estado : lista[0])}</select></div>
    <div class="f" id="qRw"><label for="qR">Volver a revisar</label><input id="qR" type="date" value="${masDias(7)}" min="${hoy()}"></div>
    <div class="f"><label for="qN">Nota</label><textarea id="qN" rows="2" placeholder="${gestion ? 'A quién se informó, Nº de pedido, plazo' : 'Qué se vio o se hizo'}"></textarea></div>
    ${gestion ? '' : campoFotos('qF')}
  `, '<button type="button" id="qX">Cancelar</button><button type="button" class="pri" id="qOk">Guardar</button>');
  const sync = () => { $('qRw').hidden = M_CERR.indexOf($('qE').value) >= 0; }; $('qE').onchange = sync; sync();
  $('qX').onclick = () => fichaMarca(n);
  $('qOk').onclick = async () => {
    const estado = $('qE').value;
    try {
      busy('Guardando…');
      const fd = new FormData(); fd.append('datos', JSON.stringify({estado, nota: $('qN').value.trim(), revision: $('qR').value}));
      if (!gestion) await agregarFotos(fd, 'estado', archivos('qF'));
      await api('/marcas/' + encodeURIComponent(n) + '/estado', {method: 'POST', form: fd});
      busy(''); cerrarModal(); toast(n + ': ' + estado); await cargar();
    } catch (e) { busy(''); error(e); }
  };
}
function editarMarca(n) {
  const m = S.marcas[n];
  modal('Editar ' + n, `
    <div class="grid2">
      <div class="f"><label for="eT">Tipo de novedad</label><select id="eT">${opts(M_TIPOS.indexOf(m.tipo) >= 0 ? M_TIPOS : [m.tipo].concat(M_TIPOS), m.tipo)}</select></div>
      <div class="f"><label for="eL">Lugar</label><select id="eL">${opts(M_LUGARES, m.lugar)}</select></div>
    </div>
    <div class="f"><label for="eD">Descripción</label><textarea id="eD" rows="2" maxlength="500">${esc(m.descripcion)}</textarea></div>
    <div class="f"><label for="eO">Observación</label><textarea id="eO" rows="2">${esc(m.obs || '')}</textarea></div>
  `, '<button type="button" id="eX">Cancelar</button><button type="button" class="pri" id="eOk">Guardar</button>');
  $('eX').onclick = () => fichaMarca(n);
  $('eOk').onclick = async () => {
    const d = {tipo: $('eT').value, lugar: $('eL').value, descripcion: $('eD').value.trim(), observacion: $('eO').value.trim()};
    if (!d.descripcion) { toast('La descripción no puede quedar vacía.', true); return; }
    try { busy('Guardando…'); await api('/marcas/' + encodeURIComponent(n), {method: 'PUT', json: d}); busy(''); toast(n + ' actualizada'); await cargar(); fichaMarca(n); }
    catch (e) { busy(''); error(e); }
  };
}
function borrarMarca(n) {
  modal('Borrar ' + n, `
    <p class="ftxt">Se borra la novedad con su historial. Las fotos pasan a la papelera del servidor y queda una constancia con el motivo.</p>
    <div class="f"><label for="xM">Motivo (obligatorio)</label><textarea id="xM" rows="2"></textarea></div>
  `, '<button type="button" id="xX">Cancelar</button><button type="button" class="danger" id="xOk">Borrar definitivamente</button>');
  $('xX').onclick = () => fichaMarca(n);
  $('xOk').onclick = async () => {
    const motivo = $('xM').value.trim(); if (motivo.length < 5) { toast('Escribí el motivo del borrado.', true); return; }
    try { busy('Borrando…'); await api('/marcas/' + encodeURIComponent(n) + '/borrar', {method: 'POST', json: {motivo}}); busy(''); cerrarModal(); toast(n + ' borrada'); await cargar(); }
    catch (e) { busy(''); error(e); }
  };
}

/* ───────── importar faltas desde la planilla de Reportes (solo admin) ───────── */
const RES_TXT = {nueva: 'Se importa', omitida: 'Se omite', error: 'Error'};
function importar(res, archivo) {
  if (res && res.tipo === 'base') return importarBase(res, archivo);
  const cuenta = k => res ? res.filas.filter(f => f.resultado === k).length : 0;
  const hecho = res && res.confirmado;
  const m = modal('Importar faltas', `
    ${res ? '' : `<p class="ftxt">Se pueden subir dos tipos de archivo. Primero se revisa y no se guarda nada hasta que confirmes.</p>
    <ul class="note imp-reglas">
      <li><b>Planilla completa de Construcciones (.xlsx)</b>, la "Base de datos": trae tipos de faltas, visitas, faltas con su historial y novedades de espacios comunes. Conserva los números originales cuando están libres. Si se vuelve a subir una versión más nueva, actualiza lo ya importado y agrega lo nuevo.</li>
      <li><b>Planilla de Reportes (.csv)</b>, la que descarga <b>Reportes → Descargar Excel</b> en otro entorno de la app. Con este archivo rigen estas reglas:</li>
    </ul>
    <ul class="note imp-reglas">
      <li>Cada falta recibe un número nuevo de esta base. En el historial queda el número original.</li>
      <li>Las faltas del mismo día, U.F. e inspector se agrupan en una visita.</li>
      <li>Lo que ya se importó antes se omite, así que podés volver a subir el mismo archivo.</li>
      <li>Los códigos tienen que existir en Tipos de faltas. Si el inspector no existe en esta base, la falta queda a tu nombre y se anota quién la cargó.</li>
      <li>No se importan fotos ni ubicación GPS: la planilla no las trae.</li>
    </ul>
    <div class="f"><label for="iF">Archivo (.xlsx o .csv)</label><input id="iF" type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"></div>`}
    ${res ? `<p class="ftxt"><b>${esc(res.archivo)}</b> · ${res.filas.length} filas</p>
      <div class="imp-tot"><span class="pill mk-ok">${hecho ? 'Importadas' : 'Para importar'}: ${cuenta('nueva')}</span><span class="pill n">Se omiten: ${cuenta('omitida')}</span>${cuenta('error') ? `<span class="pill venc">Con error: ${cuenta('error')}</span>` : ''}</div>
      <div class="scroll"><table class="cat"><thead><tr><th>Fila</th><th>N° origen</th><th>Fecha</th><th>U.F.</th><th>Código</th><th>Estado</th><th>Cargó</th><th>Resultado</th></tr></thead><tbody>
      ${res.filas.map(f => `<tr class="imp-${f.resultado}"><td class="cnt">${f.fila}</td><td class="mono">${esc(f.n || '—')}</td><td>${esc(f.fecha || '')}</td><td>${esc(f.uf || '')}</td><td class="mono">${esc(f.codigo || '')}</td><td>${esc(f.estado || '')}</td><td>${esc(f.cargo || '')}</td>
        <td>${f.nuevo ? `<b>${esc(f.nuevo)}</b>` : esc(RES_TXT[f.resultado])}${f.motivo ? ` <span class="note">· ${esc(f.motivo)}</span>` : ''}</td></tr>`).join('')}
      </tbody></table></div>` : ''}
    <details id="iHistD"><summary class="sum">Importaciones anteriores</summary><div id="iHist" class="note">Cargando…</div></details>
  `, res ? (hecho ? '<button type="button" class="pri" id="iOtra">Importar otro archivo</button>'
               : `<button type="button" id="iOtra">Elegir otro archivo</button><button type="button" class="pri" id="iOk" ${cuenta('nueva') ? '' : 'disabled'}>Importar ${cuenta('nueva')} ${cuenta('nueva') === 1 ? 'falta' : 'faltas'}</button>`)
         : '<button type="button" id="iX">Cancelar</button><button type="button" class="pri" id="iRev">Revisar archivo</button>');
  m.querySelector('.dlg').classList.add('ancho');
  const enviar = async (file, confirmar) => {
    const fd = new FormData(); fd.append('archivo', file, file.name); fd.append('confirmar', confirmar ? '1' : '0');
    return api('/importar/faltas', {method: 'POST', form: fd});
  };
  if ($('iX')) $('iX').onclick = cerrarModal;
  if ($('iOtra')) $('iOtra').onclick = () => importar();
  if ($('iRev')) $('iRev').onclick = async () => {
    const file = $('iF').files[0]; if (!file) { toast('Elegí el archivo.', true); return; }
    try { busy('Revisando…'); const r = await enviar(file, false); busy(''); importar(r, file); } catch (e) { busy(''); error(e); }
  };
  if ($('iOk')) $('iOk').onclick = async () => {
    try { busy('Importando…'); const r = await enviar(archivo, true); busy(''); toast(`${r.filas.filter(f => f.nuevo).length} faltas importadas`); await cargar(); importar(r, archivo); }
    catch (e) { busy(''); error(e); }
  };
  $('iHistD').ontoggle = async () => {
    if (!$('iHistD').open) return;
    try {
      const h = await api('/importar/historial');
      $('iHist').innerHTML = h.length ? `<table class="cat"><thead><tr><th>Fecha</th><th>Archivo</th><th class="cnt">Filas</th><th class="cnt">Creadas</th><th class="cnt">Omitidas</th><th class="cnt">Errores</th><th>Quién</th></tr></thead><tbody>${h.map(x => `<tr><td>${fechaHora(x.creado)}</td><td>${esc(x.archivo)}</td><td class="cnt">${x.filas}</td><td class="cnt">${x.creadas}</td><td class="cnt">${x.omitidas}</td><td class="cnt">${x.errores}</td><td>${esc(x.usuario)}</td></tr>`).join('')}</tbody></table>` : 'Todavía no se importó nada.';
    } catch (e) { $('iHist').textContent = 'No se pudo cargar.'; }
  };
}

function importarBase(res, archivo) {
  const T = res.totales, hecho = res.confirmado, n = T.nuevas + T.actualizadas;
  const tablaMsg = (l, tit) => l.length ? `<details ${tit === 'Errores' ? 'open' : ''}><summary class="sum">${tit} (${l.length}${l.length >= 300 ? '+' : ''})</summary><div class="scroll"><table class="cat"><thead><tr><th>Hoja</th><th class="cnt">Fila</th><th>N°</th><th>Detalle</th></tr></thead><tbody>
    ${l.map(e => `<tr${tit === 'Errores' ? ' class="imp-error"' : ''}><td>${esc(e.hoja)}</td><td class="cnt">${e.fila || ''}</td><td class="mono">${esc(e.ref || '')}</td><td>${esc(e.motivo)}</td></tr>`).join('')}</tbody></table></div></details>` : '';
  const m = modal('Importar planilla de Construcciones', `
    <p class="ftxt"><b>${esc(res.archivo)}</b></p>
    <div class="imp-tot"><span class="pill mk-ok">${hecho ? 'Importadas' : 'Nuevas'}: ${T.nuevas}</span><span class="pill mk-rep">${hecho ? 'Actualizadas' : 'Se actualizan'}: ${T.actualizadas}</span><span class="pill n">Sin cambios: ${T.sin_cambios}</span>${T.errores ? `<span class="pill venc">Con error: ${T.errores}</span>` : ''}</div>
    <div class="scroll"><table class="cat"><thead><tr><th>Hoja</th><th class="cnt">Filas</th><th class="cnt">Nuevas</th><th class="cnt">Actualizadas</th><th class="cnt">Sin cambios</th><th class="cnt">Errores</th></tr></thead><tbody>
      ${res.hojas.map(h => `<tr><td>${esc(h.hoja)}</td><td class="cnt">${h.total}</td><td class="cnt">${h.nuevas}</td><td class="cnt">${h.actualizadas}</td><td class="cnt">${h.sin_cambios}</td><td class="cnt">${h.errores}</td></tr>`).join('')}
    </tbody></table></div>
    ${tablaMsg(res.errores, 'Errores')}
    ${tablaMsg(res.avisos || [], 'Avisos (fechas estimadas)')}
    ${res.no_importa.length ? `<details><summary class="sum">No se importa (${res.no_importa.reduce((s, x) => s + x.filas, 0)} filas)</summary><ul class="note imp-reglas">${res.no_importa.map(x => `<li><b>${esc(x.hoja)}</b> (${x.filas}): ${esc(x.motivo)}</li>`).join('')}</ul></details>` : ''}
    ${hecho ? '' : '<p class="note">Las filas con error no se importan; el resto sí. Si corregís la planilla y la volvés a subir, entran las que faltaban.</p>'}
  `, hecho ? '<button type="button" class="pri" id="iOtra">Importar otro archivo</button>'
           : `<button type="button" id="iOtra">Elegir otro archivo</button><button type="button" class="pri" id="iOk" ${n ? '' : 'disabled'}>${n ? `Importar (${T.nuevas} nuevas, ${T.actualizadas} actualizadas)` : 'No hay nada para importar'}</button>`);
  m.querySelector('.dlg').classList.add('ancho');
  $('iOtra').onclick = () => importar();
  if ($('iOk')) $('iOk').onclick = async () => {
    try {
      busy('Importando…');
      const fd = new FormData(); fd.append('archivo', archivo, archivo.name); fd.append('confirmar', '1');
      const r = await api('/importar/faltas', {method: 'POST', form: fd});
      busy(''); toast(`Importación lista: ${r.totales.nuevas} nuevas, ${r.totales.actualizadas} actualizadas`); await cargar(); importarBase(r, archivo);
    } catch (e) { busy(''); error(e); }
  };
}

/* ───────── recorrido del día (itinerario) y red de calles ─────────
   El inspector arma la lista de paradas, la API calcula el mejor orden sobre la red de calles del plano
   (Dijkstra + Held-Karp / 2-opt) y el recorrido queda dibujado y se va tachando con las visitas. */
let MAPA_MODO = null;          // función (evento, elemento tocado) mientras se elige en el plano o se edita la red
let ELEG = null;               // Set de índices de lote elegidos desde el plano
let ITIN = null, PREVIA = null, RED = null;
const PLAN = {modo: 'vehiculo', inicio: 'fijo', volver: false, lotes: new Set()};
const VEL = {vehiculo: 20, pie: 4.5};
const kmTxt = km => km < 1 ? Math.round(km * 1000) + ' m' : (Math.round(km * 10) / 10).toString().replace('.', ',') + ' km';
const minTxt = m => m < 60 ? Math.round(m) + ' min' : Math.floor(m / 60) + ' h ' + Math.round(m % 60) + ' min';
const refUF = i => LOTS[i].n.join('/');
const nombreP = p => p.tipo === 'uf' ? 'U.F. ' + p.ref : p.ref + (S.marcas[p.ref] ? ' · ' + S.marcas[p.ref].lugar : '');

/* armado del recorrido: las U.F. se eligen solo tocando los lotes en el plano */
function planificar(limpiar) {
  if (limpiar) PLAN.lotes = new Set();
  cerrarModal(); ocultarTip();
  PREVIA = null; gRuta.innerHTML = '';
  ELEG = PLAN.lotes;
  MAPA_MODO = (e, t) => {
    const i = t && t.dataset && t.dataset.i != null ? +t.dataset.i : -1; if (i < 0) return;
    ELEG.has(i) ? ELEG.delete(i) : ELEG.add(i); render(); barraPlan();
  };
  render(); barraPlan();
}
function marcarElegidos() {
  gRuta.innerHTML = '';
  ELEG.forEach(i => { const [x, y] = LOTS[i].c; marcador(x, y, '+', 'ruta-p elegida'); });
  escalarMarcadores();
}
function barraPlan() {
  marcarElegidos();
  const b = $('itBar'), n = ELEG.size, gps = posVigente();
  b.hidden = false;
  b.innerHTML = `<div class="row"><b>Armar recorrido</b><span class="note">${n ? n + ' U.F. elegida' + (n === 1 ? '' : 's') : 'Tocá en el plano las U.F. a visitar'}</span></div>
    <div class="row">
      <span class="seg"><button type="button" data-modo="vehiculo" aria-pressed="${PLAN.modo === 'vehiculo'}">🚗 Vehículo</button><button type="button" data-modo="pie" aria-pressed="${PLAN.modo === 'pie'}">🚶 A pie</button></span>
      <select id="itIni" aria-label="Salida"><option value="fijo">Salida: ${esc((RED && RED.inicio.nombre) || 'punto fijo')}</option><option value="gps" ${PLAN.inicio === 'gps' ? 'selected' : ''}>Salida: mi ubicación${gps ? '' : ' (GPS)'}</option></select>
      <label class="row chk"><input type="checkbox" id="itVolver" ${PLAN.volver ? 'checked' : ''}> Volver al final</label>
    </div>
    <div class="row"><button type="button" id="itX">Cancelar</button>${n ? '<button type="button" id="itLimpiar">Limpiar</button>' : ''}<button type="button" class="pri" id="itCalc" ${n ? '' : 'disabled'}>Calcular recorrido</button></div>`;
  b.querySelectorAll('[data-modo]').forEach(x => { x.onclick = () => { PLAN.modo = x.dataset.modo; barraPlan(); }; });
  $('itIni').onchange = e => { PLAN.inicio = e.target.value; if (PLAN.inicio === 'gps') iniciarGps(false, true); };
  $('itVolver').onchange = e => { PLAN.volver = e.target.checked; };
  $('itX').onclick = () => { salirModoMapa(); };
  if ($('itLimpiar')) $('itLimpiar').onclick = () => { ELEG.clear(); render(); barraPlan(); };
  $('itCalc').onclick = calcularRecorrido;
}
function pedidoRecorrido() {
  const d = {modo: PLAN.modo, volver: PLAN.volver, paradas: [...PLAN.lotes].map(i => ({tipo: 'uf', ref: refUF(i), x: LOTS[i].c[0], y: LOTS[i].c[1]}))};
  if (PLAN.inicio === 'gps') {
    const g = posVigente(); if (!g) throw new Error('Todavía no hay señal GPS. Esperá unos segundos o elegí la salida fija.');
    d.inicio = {x: g.x, y: g.y, nombre: 'Mi ubicación'};
  }
  return d;
}
async function calcularRecorrido() {
  let d; try { d = pedidoRecorrido(); } catch (e) { toast(e.message, true); return; }
  try {
    busy('Calculando el mejor recorrido…');
    const r = await api('/itinerarios/calcular', {method: 'POST', json: d});
    busy(''); MAPA_MODO = null; ELEG = null; render();
    PREVIA = Object.assign(r, {pedido: d}); pintarRuta(); verRuta(); barraRuta();
  } catch (e) { busy(''); error(e); }
}
function verRuta() {
  const r = PREVIA || ITIN; if (!r) return;
  const xs = [], ys = [];
  (PREVIA ? PREVIA.piernas : ITIN.geometria).forEach(p => p.geo.forEach(([x, y]) => { xs.push(x); ys.push(y); }));
  if (!xs.length) return;
  const w = Math.max(Math.max(...xs) - Math.min(...xs), (Math.max(...ys) - Math.min(...ys)) * FULL.w / FULL.h, 500) * 1.25;
  seguir = false; marcarGps(); centrar((Math.max(...xs) + Math.min(...xs)) / 2, (Math.max(...ys) + Math.min(...ys)) / 2, Math.min(w, FULL.w));
}
function salirModoMapa() { MAPA_MODO = null; ELEG = null; $('itBar').hidden = true; gRed.innerHTML = ''; svg.classList.remove('editando'); render(); if (PREVIA || ITIN) { pintarRuta(); barraRuta(); } }

/* dibujo del recorrido */
function pintarRuta() {
  gRuta.innerHTML = '';
  const r = PREVIA || ITIN; if (!r) return;
  const piernas = PREVIA ? PREVIA.piernas : ITIN.geometria;
  const paradas = PREVIA ? PREVIA.paradas : ITIN.paradas;
  const pend = PREVIA ? null : ITIN.paradas.filter(p => p.estado === 'pendiente');
  piernas.forEach(p => el('polyline', {points: p.geo.map(q => q.join(',')).join(' '), class: 'ruta'}, gRuta));
  const ini = PREVIA ? PREVIA.inicio : ITIN.inicio;
  marcador(ini.x, ini.y, 'S', 'ruta-ini');
  paradas.forEach((p, k) => {
    const st = p.estado || 'pendiente', sig = pend && pend[0] === p;
    marcador(+p.x, +p.y, st === 'hecha' ? '✓' : String(k + 1), 'ruta-p ' + st + (sig ? ' sig' : ''));
  });
  escalarMarcadores();
}
if (window.ResizeObserver) new ResizeObserver(() => { if (gRuta.firstChild) escalarMarcadores(); }).observe(svg);
/* marcadores cuadrados numerados: mismo tamaño en pantalla con cualquier zoom */
function marcador(x, y, txt, clase) {
  const g = el('g', {class: 'ruta-m', 'data-x': x, 'data-y': y}, gRuta);
  const s = txt.length > 2 ? 34 : 28;
  el('rect', {x: -s / 2, y: -14, width: s, height: 28, rx: 5, class: clase}, g);
  el('text', {x: 0, y: 6, class: 'ruta-n'}, g).textContent = txt;
  return g;
}
function escalarMarcadores() {
  const r = svg.getBoundingClientRect(); if (!r.width) return;
  const k = Math.max(vb.w / r.width, vb.h / r.height);       // unidades del plano por píxel de pantalla
  gRuta.querySelectorAll('.ruta-m').forEach(g => g.setAttribute('transform', `translate(${g.dataset.x},${g.dataset.y}) scale(${k})`));
}
function barraRuta() {
  const b = $('itBar');
  if (MAPA_MODO) return;
  if (PREVIA) {
    b.hidden = false;
    b.innerHTML = `<div class="row"><b>Recorrido propuesto</b><span class="note">${PREVIA.paradas.length} paradas · ${kmTxt(PREVIA.km)} · ${minTxt(PREVIA.minutos)} ${PREVIA.modo === 'pie' ? 'a pie' : 'en vehículo'}</span></div>
      ${PREVIA.avisos.length ? `<p class="gpsinfo lejos">${PREVIA.avisos.map(esc).join('<br>')}</p>` : ''}
      <div class="row"><button type="button" id="itLista">Ver orden</button><button type="button" id="itGmaps">Google Maps</button><button type="button" id="itCambiar">Cambiar paradas</button><button type="button" id="itDescartar">Descartar</button><button type="button" class="pri" id="itGuardar">Empezar recorrido</button></div>`;
    $('itLista').onclick = () => listaRecorrido(PREVIA.paradas, PREVIA.piernas, false);
    $('itGmaps').onclick = () => abrirEnMaps(PREVIA.paradas, PREVIA.pedido.inicio ? null : PREVIA.inicio, PREVIA.modo, PREVIA.volver ? PREVIA.inicio : false, 1);
    $('itCambiar').onclick = () => planificar();
    $('itDescartar').onclick = () => { PREVIA = null; PLAN.lotes = new Set(); gRuta.innerHTML = ''; if (ITIN) { pintarRuta(); barraRuta(); } else b.hidden = true; };
    $('itGuardar').onclick = async () => {
      try { busy('Guardando…'); ITIN = await api('/itinerarios', {method: 'POST', json: PREVIA.pedido}); busy(''); PREVIA = null; PLAN.lotes = new Set(); toast('Recorrido guardado. ¡Buen recorrido!'); pintarRuta(); barraRuta(); }
      catch (e) { busy(''); error(e); }
    };
    return;
  }
  if (!ITIN) { b.hidden = true; return; }
  const ps = ITIN.paradas, sig = ps.find(p => p.estado === 'pendiente'), hechas = ps.filter(p => p.estado === 'hecha').length;
  const g = posVigente(), dist = sig && g ? Math.round(Math.hypot(g.x - sig.x, g.y - sig.y) * M_POR_UNIDAD) : null;
  b.hidden = false;
  b.innerHTML = `<div class="row"><b>Recorrido de hoy</b><span class="note">${hechas} de ${ps.length} hechas${ITIN.salteadas ? ' · ' + ITIN.salteadas + ' salteada' + (ITIN.salteadas > 1 ? 's' : '') : ''}</span></div>
    <div class="it-prog"><i style="width:${Math.round(100 * hechas / Math.max(ps.length, 1))}%"></i></div>
    <p class="note">${sig ? `Próxima: <b>${esc(nombreP(sig))}</b>${dist != null ? ' · a unos ' + dist + ' m en línea recta' : ''}` : '¡Listo! No quedan paradas pendientes.'}</p>
    <div class="row"><button type="button" id="itLista">Lista</button>${sig ? '<button type="button" id="itIr">Ir a la próxima</button><button type="button" id="itGmaps">Google Maps</button>' : ''}<button type="button" id="itMin" title="Ocultar">▾</button></div>`;
  $('itLista').onclick = () => listaRecorrido();
  if ($('itIr')) $('itIr').onclick = () => irParada(sig);
  if ($('itGmaps')) $('itGmaps').onclick = () => {
    const pend = ps.filter(p => p.estado === 'pendiente');
    abrirEnMaps(pend, null, ITIN.modo, ITIN.volver ? ITIN.inicio : false, ps.indexOf(pend[0]) + 1);
  };
  $('itMin').onclick = () => { b.hidden = true; $('bItin').classList.add('on'); };
}
/* Abrir el recorrido en Google Maps, con las paradas en el orden calculado.
   Google admite pocas paradas intermedias por enlace (3 en el celular, 9 en la PC): si hay más, se parte en tramos.
   Sin origen, Google arranca desde la ubicación del celular. */
function abrirEnMaps(paradas, origen, modo, volver, primerNro) {
  if (!paradas.length) return;
  const ll = g => g.lat.toFixed(6) + ',' + g.lon.toFixed(6);
  const pts = paradas.map((p, k) => ({g: aGeo(+p.x, +p.y), nro: primerNro + k}));
  if (volver) pts.push({g: aGeo(+volver.x, +volver.y), nro: 'S'});
  const max = TACTIL ? 3 : 9, tramos = [];
  let desde = origen ? aGeo(+origen.x, +origen.y) : null, i = 0;
  while (i < pts.length) {
    const tr = pts.slice(i, i + max + 1), dest = tr[tr.length - 1], way = tr.slice(0, -1);
    const url = 'https://www.google.com/maps/dir/?api=1' + (desde ? '&origin=' + ll(desde) : '') + '&destination=' + ll(dest.g)
      + (way.length ? '&waypoints=' + encodeURIComponent(way.map(w => ll(w.g)).join('|')) : '') + '&travelmode=' + (modo === 'pie' ? 'walking' : 'driving');
    tramos.push({url, a: tr[0].nro, b: dest.nro, desdeMi: !desde});
    desde = dest.g; i += tr.length;
  }
  if (tramos.length === 1) { window.open(tramos[0].url, '_blank', 'noopener'); return; }
  modal('Abrir en Google Maps', `
    <p class="ftxt">Google Maps admite hasta ${max} paradas intermedias por enlace, así que el recorrido se abre en ${tramos.length} partes. Abrí la siguiente cuando termines la anterior.</p>
    <div class="it-gm">${tramos.map((t, k) => `<a class="btn" href="${t.url}" target="_blank" rel="noopener">Parte ${k + 1}: paradas ${t.a} a ${t.b}${t.desdeMi ? ' (desde tu ubicación)' : ''}</a>`).join('')}</div>
    <p class="note">Google arma su propio camino entre paradas, respetando este orden. Puede que no conozca todas las calles internas o las manos del country; ante la duda, seguí el plano de la app. Solo se envían coordenadas, sin números de U.F. ni nombres.</p>
  `, '<button type="button" id="gmX">Cerrar</button>');
  $('gmX').onclick = cerrarModal;
}
function irParada(p) {
  seguir = false; marcarGps(); cerrarModal();
  if (p.tipo === 'uf') { const i = ufLot[+String(p.ref).split('/')[0]]; if (i != null) { seleccionar(i); irA(i); return; } }
  centrar(+p.x, +p.y, 450); if (p.tipo === 'marca' && S.marcas[p.ref]) fichaMarca(p.ref);
}
function listaRecorrido(ps, piernas, activo = true) {
  ps = ps || ITIN.paradas; piernas = piernas || (ITIN && ITIN.geometria) || [];
  const r = activo ? ITIN : PREVIA;
  const icono = p => p.estado === 'hecha' ? '<span class="it-st ok">✓</span>' : p.estado === 'salteada' ? '<span class="it-st sk">⤼</span>' : '';
  const kmDe = (p, k) => activo ? +p.km_desde_anterior : (piernas[k] ? piernas[k].km : 0);
  modal(activo ? 'Recorrido de hoy' : 'Orden propuesto', `
    <p class="note">${r.modo === 'pie' ? '🚶 A pie' : '🚗 En vehículo'} · salida: ${esc(r.inicio.nombre || 'Inicio')} · ${kmTxt(activo ? +ITIN.km_plan : PREVIA.km)} · ${minTxt(activo ? ITIN.minutos_plan : PREVIA.minutos)}${r.volver ? ' · vuelve al punto de salida' : ''}</p>
    <ol class="it-orden">${ps.map((p, k) => `<li class="${p.estado || ''}"><span class="it-num">${k + 1}</span><span class="it-txt"><b>${esc(nombreP(p))}</b>
      <small>${kmDe(p, k) ? kmTxt(kmDe(p, k)) + ' desde la anterior' : ''}${p.fijada ? ' · 📌 fijada' : ''}${p.estado === 'hecha' && p.marcada ? ' · hecha ' + String(p.marcada).slice(11, 16) : ''}</small></span>${icono(p)}
      <span class="acc">${activo && p.estado === 'pendiente' ? `<button type="button" data-ir="${k}">Ir</button><button type="button" data-sk="${k}">Saltear</button>` : ''}${activo && p.estado === 'salteada' ? `<button type="button" data-re="${k}">Retomar</button>` : ''}${activo && p.estado === 'pendiente' ? `<button type="button" data-ok="${k}" title="Marcar como hecha sin cargar visita">✓</button>` : ''}</span></li>`).join('')}</ol>
    ${activo ? '<p class="note">Al cargar una visita en una U.F. del recorrido (o un cambio en una novedad), la parada se tacha sola.</p>' : ''}
  `, activo ? `<button type="button" class="danger" id="itFin">Terminar recorrido</button><button type="button" id="itNuevo">Planificar de nuevo</button><button type="button" class="pri" id="itRec">Recalcular lo que falta</button>`
            : '<button type="button" id="itCerrar">Cerrar</button>');
  if (!activo) { $('itCerrar').onclick = cerrarModal; return; }
  const estado = async (k, est) => {
    try { busy('Guardando…'); ITIN = await api(`/itinerarios/${ITIN.id_itinerario}/paradas/${ps[k].orden}`, {method: 'POST', json: {estado: est}}); busy(''); pintarRuta(); barraRuta(); listaRecorrido(); }
    catch (e) { busy(''); error(e); }
  };
  document.querySelectorAll('[data-ir]').forEach(b => { b.onclick = () => irParada(ps[+b.dataset.ir]); });
  document.querySelectorAll('[data-sk]').forEach(b => { b.onclick = () => estado(+b.dataset.sk, 'salteada'); });
  document.querySelectorAll('[data-re]').forEach(b => { b.onclick = () => estado(+b.dataset.re, 'pendiente'); });
  document.querySelectorAll('[data-ok]').forEach(b => { b.onclick = () => estado(+b.dataset.ok, 'hecha'); });
  $('itRec').onclick = async () => {
    const g = posVigente();
    try {
      busy('Recalculando…'); ITIN = await api(`/itinerarios/${ITIN.id_itinerario}/recalcular`, {method: 'POST', json: g ? {inicio: {x: g.x, y: g.y}} : {}}); busy('');
      toast(`Recalculado ${g ? 'desde tu ubicación' : 'desde la última parada hecha'}: ${kmTxt(ITIN.recalculado.km)} para lo que falta`);
      pintarRuta(); barraRuta(); listaRecorrido();
    } catch (e) { busy(''); error(e); }
  };
  $('itNuevo').onclick = () => planificar(true);
  $('itFin').onclick = async () => {
    try { busy('Cerrando…'); await api(`/itinerarios/${ITIN.id_itinerario}/terminar`, {method: 'POST', json: {}}); busy(''); ITIN = null; gRuta.innerHTML = ''; cerrarModal(); barraRuta(); toast('Recorrido terminado'); }
    catch (e) { busy(''); error(e); }
  };
}
async function cargarRecorrido() {
  if (!puede('inspector')) return;
  try {
    if (!RED) RED = await api('/red');
    ITIN = await api('/itinerarios/actual');
  } catch (e) { return; }
  if (!MAPA_MODO) { pintarRuta(); barraRuta(); }
}
$('bItin').onclick = () => {
  $('bItin').classList.remove('on');
  if (ITIN && $('itBar').hidden) { barraRuta(); return; }
  if (MAPA_MODO) return;
  if (ITIN) listaRecorrido(); else if (PREVIA) barraRuta(); else planificar();
};

/* editor de la red de calles (admin) */
const TIPO_TR = {calle: 'Calle (vehicular)', peatonal: 'Paso peatonal', cerrado: 'No transitable'};
const SENT_TR = {doble: 'Doble mano', a_b: 'Mano única →', b_a: 'Mano única ←'};
function segmentosRed(tipos) {
  const out = [];
  RED.tramos.forEach(t => { if (tipos.indexOf(t.tipo) >= 0) for (let i = 0; i < t.geo.length - 1; i++) out.push([t.geo[i][0], t.geo[i][1], t.geo[i + 1][0], t.geo[i + 1][1]]); });
  return out;
}
function distSeg(px, py, s) {
  const dx = s[2] - s[0], dy = s[3] - s[1], l2 = dx * dx + dy * dy || 1e-9;
  const u = Math.max(0, Math.min(1, ((px - s[0]) * dx + (py - s[1]) * dy) / l2));
  return Math.hypot(px - s[0] - u * dx, py - s[1] - u * dy);
}
function diagnosticoRed() {
  const seg = segmentosRed(['calle', 'borde']);
  const sinAcceso = [];
  LOTS.forEach((l, i) => { let m = Infinity; for (const s of seg) { const d = distSeg(l.c[0], l.c[1], s); if (d < m) { m = d; if (m * M_POR_UNIDAD < 40) break; } } if (m * M_POR_UNIDAD >= 40) sinAcceso.push(i); });
  const ady = {}; RED.tramos.filter(t => t.tipo === 'calle' || t.tipo === 'borde').forEach(t => { (ady[t.a] = ady[t.a] || []).push(t.b); (ady[t.b] = ady[t.b] || []).push(t.a); });
  const vist = new Set(); let partes = 0;
  Object.keys(ady).forEach(n => { if (vist.has(n)) return; partes++; const pila = [n]; vist.add(n); while (pila.length) { const u = pila.pop(); ady[u].forEach(v => { v = String(v); if (!vist.has(v)) { vist.add(v); pila.push(v); } }); } });
  return {sinAcceso, partes};
}
function pintarRed() {
  gRed.innerHTML = '';
  const diag = RED.diag;
  RED.tramos.forEach(t => {
    const pts = t.geo.map(q => q.join(',')).join(' ');
    el('polyline', {points: pts, class: 'tr tr-' + t.tipo + (t.revisado ? '' : ' sinrev')}, gRed);
    if (t.sentido !== 'doble' && t.geo.length > 1) {
      const k = Math.floor((t.geo.length - 1) / 2), [x1, y1] = t.geo[k], [x2, y2] = t.geo[k + 1];
      let ang = Math.atan2(y2 - y1, x2 - x1); if (t.sentido === 'b_a') ang += Math.PI;
      const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2, r = 16, f = a => [cx + r * Math.cos(ang + a), cy + r * Math.sin(ang + a)].join(',');
      el('polygon', {points: [f(0), f(2.5), f(-2.5)].join(' '), class: 'tr-flecha'}, gRed);
    }
    el('polyline', {points: pts, class: 'tr-hit', 'data-tr': t.id}, gRed);
  });
  diag.sinAcceso.forEach(i => el('path', {d: LOTS[i].d, class: 'tr-sinacc'}, gRed));
  const ini = RED.inicio;
  el('rect', {x: ini.x - 14, y: ini.y - 14, width: 28, height: 28, rx: 5, class: 'ruta-ini'}, gRed);
  el('text', {x: ini.x, y: ini.y + 6, class: 'ruta-n'}, gRed).textContent = 'S';
}
async function editarRed() {
  try { busy('Cargando la red…'); RED = await api('/red'); busy(''); } catch (e) { busy(''); error(e); return; }
  RED.diag = diagnosticoRed();
  gRuta.innerHTML = ''; svg.classList.add('editando');
  let ponerInicio = false;
  MAPA_MODO = (e, t) => {
    if (ponerInicio) {
      const p = aSvg(e.clientX, e.clientY); ponerInicio = false;
      api('/red/inicio', {method: 'PUT', json: {x: p.x, y: p.y, nombre: RED.inicio.nombre}}).then(r => { RED.inicio = r.inicio; pintarRed(); barraRed(); toast('Punto de salida actualizado'); }).catch(error);
      return;
    }
    if (t && t.dataset && t.dataset.tr) formTramo(+t.dataset.tr);
  };
  const barraRed = () => {
    const c = k => RED.tramos.filter(t => t.tipo === k), km = l => kmTxt(l.reduce((s, t) => s + +t.largo, 0) / 1000);
    const d = RED.diag;
    const b = $('itBar'); b.hidden = false;
    b.innerHTML = `<div class="row"><b>Red de calles</b><span class="note">tocá un tramo para corregirlo</span></div>
      <div class="tr-ley"><span><i class="tr-calle"></i>Calle ${km(c('calle'))}</span><span><i class="tr-peatonal"></i>Peatonal ${km(c('peatonal'))}</span><span><i class="tr-cerrado"></i>No transitable ${c('cerrado').length}</span></div>
      <p class="note">${d.partes <= 1 ? '✓ La red vehicular está toda conectada.' : `⚠ La red vehicular está partida en ${d.partes} partes.`} ${d.sinAcceso.length ? `⚠ ${d.sinAcceso.length} lote(s) sin calle a menos de 40 m (en rojo).` : '✓ Todos los lotes tienen calle cerca.'}</p>
      <div class="row"><button type="button" id="rdIni">${ponerInicio ? 'Tocá el plano…' : 'Mover punto de salida (S)'}</button><button type="button" class="pri" id="rdX">Salir</button></div>`;
    $('rdIni').onclick = () => { ponerInicio = true; barraRed(); toast('Tocá en el plano el nuevo punto de salida.'); };
    $('rdX').onclick = () => { salirModoMapa(); cargarRecorrido(); };
  };
  RED.barra = barraRed;
  pintarRed(); barraRed();
}
function formTramo(id) {
  const t = RED.tramos.find(x => x.id === id); if (!t) return;
  gRed.querySelectorAll('.tr-sel').forEach(x => x.remove());
  el('polyline', {points: t.geo.map(q => q.join(',')).join(' '), class: 'tr-sel'}, gRed);
  modal('Tramo ' + id, `
    <p class="note">${kmTxt(t.largo / 1000)} · ${t.revisado ? 'revisado' : 'sin revisar (detectado del plano)'}${t.modificado ? ' · modificado ' + fmt(String(t.modificado).slice(0, 10)) : ''}</p>
    <div class="f"><span class="flabel">Tipo</span><div class="tr-opc">${Object.entries(TIPO_TR).map(([k, l]) => `<label class="row chk"><input type="radio" name="trT" value="${k}" ${t.tipo === k ? 'checked' : ''}> <i class="tr-${k}"></i> ${l}</label>`).join('')}</div></div>
    <div class="f"><label for="trS">Sentido de circulación (vehículos)</label><select id="trS">${Object.entries(SENT_TR).map(([k, l]) => `<option value="${k}" ${t.sentido === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <p class="note">La flecha del plano muestra el sentido "→". A pie se puede ir en los dos sentidos.</p></div>
  `, '<button type="button" id="trX">Cancelar</button><button type="button" class="pri" id="trOk">Guardar</button>');
  const quitarSel = () => gRed.querySelectorAll('.tr-sel').forEach(x => x.remove());
  $('trX').onclick = () => { cerrarModal(); quitarSel(); };
  $('trOk').onclick = async () => {
    const tipo = (document.querySelector('[name=trT]:checked') || {}).value, sentido = $('trS').value;
    try {
      busy('Guardando…'); await api('/red/tramos/' + id, {method: 'PUT', json: {tipo, sentido}}); busy('');
      Object.assign(t, {tipo, sentido, revisado: tipo !== 'borde', modificado: new Date().toISOString()});
      RED.diag = diagnosticoRed(); cerrarModal(); pintarRed(); RED.barra(); toast('Tramo ' + id + ': ' + TIPO_TR[tipo]);
    } catch (e) { busy(''); error(e); }
  };
}
$('bRed').onclick = () => { if (MAPA_MODO) salirModoMapa(); editarRed(); };

/* ───────── reportes (consulta, inspector y superiores) ───────── */
const REP = {desde: '', hasta: '', sector: '', estado: '', rubro: ''};
function qsRep() {
  return Object.entries(REP).filter(([, v]) => v).map(([k, v]) => k + '=' + encodeURIComponent(v)).join('&');
}
function barras(lista, opts = {}) {
  if (!lista.length) return '<p class="empty">Sin datos para el período.</p>';
  const max = Math.max(...lista.map(x => x.n)) || 1;
  return `<div class="barras">${lista.map(x => `<div class="barra"${opts.click ? ` data-uf="${esc(x.etiqueta)}"` : ''}>
    <span class="b-et" title="${esc(x.etiqueta)}">${esc(opts.pref || '')}${esc(x.etiqueta)}</span>
    <span class="b-pista"><span class="b-tot" style="width:${(x.n / max * 100).toFixed(1)}%"><span class="b-ab" style="width:${(x.abiertas / x.n * 100 || 0).toFixed(1)}%"></span></span></span>
    <span class="b-n">${x.n}${x.abiertas ? ` <small>(${x.abiertas} ab.)</small>` : ''}</span></div>`).join('')}</div>`;
}
function columnasMes(lista) {
  if (!lista.length) return '<p class="empty">Sin datos para el período.</p>';
  const max = Math.max(...lista.map(x => x.n)) || 1;
  const mes = s => ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'][+s.slice(5, 7) - 1] + ' ' + s.slice(2, 4);
  return `<div class="cols">${lista.map(x => `<div class="col" title="${esc(x.etiqueta)}: ${x.n} faltas, ${x.abiertas} abiertas">
    <span class="c-n">${x.n}</span><span class="c-pista"><span class="c-tot" style="height:${(x.n / max * 100).toFixed(1)}%"><span class="c-ab" style="height:${(x.abiertas / x.n * 100 || 0).toFixed(1)}%"></span></span></span>
    <span class="c-et">${mes(x.etiqueta)}</span></div>`).join('')}</div>`;
}
async function reportes() {
  if (!REP.hasta) { REP.hasta = hoy(); REP.desde = masDias(-30); }
  const rubros = [...new Set(Object.values(S.cat).map(c => c.rubro).filter(Boolean))].sort();
  const m = modal('Reportes', `
    <div class="rep-filtros no-print">
      <div class="f"><label for="rD">Desde</label><input id="rD" type="date" value="${REP.desde}" max="${hoy()}"></div>
      <div class="f"><label for="rH">Hasta</label><input id="rH" type="date" value="${REP.hasta}" max="${hoy()}"></div>
      <div class="f"><label for="rS">Sector</label><select id="rS"><option value="">Todos</option>${['I','II','III','IV','V','Golf'].map(s => `<option ${REP.sector === s ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
      <div class="f"><label for="rE">Estado</label><select id="rE">${[['', 'Todos'], ['abiertas', 'Abiertas'], ['vencidas', 'Abiertas y vencidas'], ['cerradas', 'Cerradas']].concat(ESTADOS.map(e => [e, e])).map(([v, l]) => `<option value="${esc(v)}" ${REP.estado === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></div>
      <div class="f"><label for="rR">Rubro</label><select id="rR"><option value="">Todos</option>${rubros.map(r => `<option ${REP.rubro === r ? 'selected' : ''}>${esc(r)}</option>`).join('')}</select></div>
      <div class="rep-atajos"><button type="button" data-per="7">7 días</button><button type="button" data-per="30">30 días</button><button type="button" data-per="90">3 meses</button><button type="button" data-per="365">12 meses</button></div>
    </div>
    <p class="rep-tit only-print" id="rTit"></p>
    <div id="rCuerpo"><p class="note">Cargando…</p></div>
  `, '<a class="btn no-print" id="rCsv" href="#">Descargar Excel (CSV)</a><button type="button" class="no-print" id="rPrint">Imprimir / PDF</button><button type="button" class="pri no-print" data-close>Cerrar</button>');
  m.querySelector('.dlg').classList.add('ancho');
  const leer = () => { REP.desde = $('rD').value; REP.hasta = $('rH').value; REP.sector = $('rS').value; REP.estado = $('rE').value; REP.rubro = $('rR').value; cargarRep(); };
  ['rD', 'rH', 'rS', 'rE', 'rR'].forEach(id => { $(id).onchange = leer; });
  m.querySelectorAll('[data-per]').forEach(b => { b.onclick = () => { $('rH').value = hoy(); $('rD').value = masDias(-(+b.dataset.per)); leer(); }; });
  $('rPrint').onclick = () => window.print();
  cargarRep();
}
async function cargarRep() {
  const box = $('rCuerpo'); if (!box) return;
  $('rCsv').href = '/api/reportes.csv?' + qsRep();
  $('rTit').textContent = `Período ${fmt(REP.desde)} al ${fmt(REP.hasta)}` + (REP.sector ? ` · Sector ${REP.sector}` : '') + (REP.estado ? ` · ${REP.estado}` : '') + (REP.rubro ? ` · ${REP.rubro}` : '');
  box.style.opacity = .5;
  let d;
  try { d = await api('/reportes?' + qsRep()); } catch (e) { box.style.opacity = 1; box.innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
  box.style.opacity = 1;
  const r = d.resumen, n = x => x == null ? 0 : x;
  const tile = (v, l, cls) => `<div class="tile ${cls || ''}"><b>${v}</b><span>${l}</span></div>`;
  box.innerHTML = `
    <div class="tiles">
      ${tile(n(r.detectadas), 'faltas detectadas')}
      ${tile(n(r.abiertas), 'siguen abiertas', n(r.abiertas) ? 'warn' : '')}
      ${tile(n(r.vencidas), 'con revisión vencida', n(r.vencidas) ? 'bad' : '')}
      ${tile(n(r.cerradas), 'cerradas', 'ok')}
      ${tile(r.dias_cierre == null ? '—' : r.dias_cierre, 'días promedio hasta el cierre')}
      ${tile(n(r.visitas), 'visitas realizadas')}
      ${tile(n(r.ufs), 'U.F. con faltas')}
      ${tile(n(r.reiteradas), 'faltas reiteradas')}
    </div>
    <p class="note leyenda-b"><i class="sw tot"></i>Total <i class="sw ab"></i>Siguen abiertas</p>
    <section class="rep-sec"><h3>Faltas por mes</h3>${columnasMes(d.por_mes)}</section>
    <div class="rep-grid">
      <section class="rep-sec"><h3>Por estado</h3>${barras(d.por_estado)}</section>
      <section class="rep-sec"><h3>Por sector</h3>${barras(d.por_sector)}</section>
      <section class="rep-sec"><h3>Por rubro</h3>${barras(d.por_rubro)}</section>
      <section class="rep-sec"><h3>Por inspector</h3>${barras(d.por_inspector)}</section>
      <section class="rep-sec"><h3>Tipos de faltas más frecuentes</h3>${barras(d.por_tipo)}</section>
      <section class="rep-sec"><h3>U.F. con más faltas</h3>${barras(d.por_uf, {pref: 'U.F. ', click: true})}</section>
    </div>
    <section class="rep-sec"><h3>Detalle (${d.listado.length}${d.listado.length >= 500 ? ' más recientes; el resto en el Excel' : ''})</h3>
      <div class="scroll"><table class="cat rep-tab"><thead><tr><th>Falta</th><th>Fecha</th><th>U.F.</th><th>Tipo</th><th>Estado</th><th>Revisión / cierre</th><th>Cargó</th></tr></thead><tbody>
      ${d.listado.map(x => `<tr data-n="${esc(x.n)}" data-uf="${x.uf}"><td class="mono">${esc(x.n)}</td><td>${fmt(x.fecha)}</td><td class="mono">${x.uf}</td>
        <td><span class="mono">${esc(x.codigo)}</span> ${esc(x.falta)}</td><td>${pillEstado(x)}</td><td>${CERRADOS.indexOf(x.estado) >= 0 ? 'Cerró ' + fmt(x.cierre) : fmt(x.revision)}</td><td>${esc(x.cargo)}</td></tr>`).join('') || '<tr><td colspan="7" class="empty">No hay faltas con estos filtros.</td></tr>'}
      </tbody></table></div></section>`;
  const ir = (uf, n) => { const i = ufLot[uf]; cerrarModal(); if (i != null) { seguir = false; marcarGps(); seleccionar(i); irA(i); } if (n && S.hallazgos[n]) fichaFalta(n); };
  box.querySelectorAll('tr[data-n]').forEach(tr => { tr.onclick = () => ir(+tr.dataset.uf, tr.dataset.n); });
  box.querySelectorAll('.barra[data-uf]').forEach(b => { b.onclick = () => ir(+b.dataset.uf); });
}
$('bRep').onclick = reportes;

/* ───────── usuarios (ABM solo admin) y cambio de la clave propia ───────── */
const ROLES = [['consulta', 'Consulta', 'Ve todo y gestiona faltas (notificada / en proceso)'], ['inspector', 'Inspector', 'Carga visitas, faltas, fotos y GPS'],
  ['supervisor', 'Supervisor', 'Como inspector, y además borra faltas'], ['admin', 'Administrador', 'Todo: tipos de faltas y usuarios']];
const rolTxt = r => (ROLES.find(x => x[0] === r) || [r, r])[1];
const claveAzar = () => { const a = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'; const v = new Uint32Array(14); crypto.getRandomValues(v); return [...v].map(x => a[x % a.length]).join(''); };
const fechaHora = s => s ? fmt(s.slice(0, 10)) + ' ' + s.slice(11, 16) : 'Nunca';
let usrFiltro = '', usrBajas = false;
async function usuarios() {
  let lista;
  try { lista = await api('/usuarios'); } catch (e) { error(e); return; }
  const q = usrFiltro.toLowerCase();
  const vis = lista.filter(u => (u.activo || usrBajas) && (!q || (u.usuario + ' ' + u.nombre + ' ' + rolTxt(u.rol)).toLowerCase().includes(q)));
  const nBajas = lista.filter(u => !u.activo).length;
  const m = modal('Usuarios', `
    <div class="row cat-bar">
      <input id="uQ" type="search" placeholder="Buscar usuario, nombre o perfil" value="${esc(usrFiltro)}" aria-label="Buscar usuarios">
      <label class="row chk"><input type="checkbox" id="uBajas" ${usrBajas ? 'checked' : ''}> Ver dados de baja (${nBajas})</label>
      <button type="button" class="pri" id="uNuevo">+ Nuevo usuario</button>
    </div>
    <div class="scroll"><table class="cat"><thead><tr><th>Usuario</th><th>Nombre</th><th>Perfil</th><th>Último ingreso</th><th></th></tr></thead><tbody>
    ${vis.map(u => `<tr class="${u.activo ? '' : 'baja'}"><td class="mono">${esc(u.usuario)}${u.id === YO.id ? ' <span class="tag-ej">VOS</span>' : ''}${u.activo ? '' : '<span class="tag-baja">BAJA</span>'}</td>
      <td>${esc(u.nombre)}</td><td><span class="pill n">${esc(rolTxt(u.rol))}</span></td><td>${fechaHora(u.ultimo_ingreso)}</td>
      <td class="acc"><button type="button" data-ue="${u.id}">Editar</button><button type="button" data-uc="${u.id}">Clave</button>${u.id === YO.id ? '' : u.activo
        ? `<button type="button" class="danger" data-ub="${u.id}">${u.actividad ? 'Dar de baja' : 'Eliminar'}</button>`
        : `<button type="button" data-ua="${u.id}">Reactivar</button>`}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">Ningún usuario coincide.</td></tr>'}
    </tbody></table></div>
    <details id="uHistD"><summary class="sum">Historial de cambios de usuarios</summary><div id="uHist" class="note">Cargando…</div></details>
  `);
  m.querySelector('.dlg').classList.add('ancho');
  const porId = id => lista.find(u => u.id === +id);
  let tq = 0;
  $('uQ').oninput = e => { clearTimeout(tq); tq = setTimeout(() => { usrFiltro = e.target.value; const pos = e.target.selectionStart; usuarios().then(() => { const i = $('uQ'); if (i) { i.focus(); try { i.setSelectionRange(pos, pos); } catch (x) {} } }); }, 300); };
  $('uBajas').onchange = e => { usrBajas = e.target.checked; usuarios(); };
  $('uNuevo').onclick = () => formUsuario(null);
  m.querySelectorAll('[data-ue]').forEach(b => { b.onclick = () => formUsuario(porId(b.dataset.ue)); });
  m.querySelectorAll('[data-uc]').forEach(b => { b.onclick = () => formClave(porId(b.dataset.uc)); });
  m.querySelectorAll('[data-ua]').forEach(b => { b.onclick = async () => {
    try { busy('Guardando…'); await api('/usuarios/' + b.dataset.ua, {method: 'PUT', json: {activo: true}}); busy(''); toast('Usuario reactivado'); usuarios(); } catch (e) { busy(''); error(e); }
  }; });
  m.querySelectorAll('[data-ub]').forEach(b => { b.onclick = () => bajaUsuario(porId(b.dataset.ub)); });
  $('uHistD').ontoggle = async e => {
    if (!e.target.open) return;
    try {
      const h = await api('/usuarios/historial');
      $('uHist').innerHTML = h.length ? `<div class="timeline">${h.map(x => `<div><span class="d">${esc(fechaHora(x.fecha))} · ${esc(x.actor)}</span><br><b>${esc(x.usuario)}</b> — ${esc(x.accion)}${x.detalle ? ': ' + esc(x.detalle) : ''}</div>`).join('')}</div>` : 'Todavía no hay cambios registrados.';
    } catch (x) { $('uHist').textContent = 'No se pudo cargar el historial.'; }
  };
}
const rolesOpts = sel => ROLES.map(([v, l, d]) => `<option value="${v}" ${v === sel ? 'selected' : ''}>${l} — ${d}</option>`).join('');
function campoClave(id) {
  return `<div class="f"><label for="${id}">Clave (mínimo 10 caracteres)</label><div class="row nowrap"><input id="${id}" class="mono" autocomplete="new-password" minlength="10"><button type="button" data-gen="${id}">Generar</button></div></div>`;
}
function conectarGen(m) { m.querySelectorAll('[data-gen]').forEach(b => { b.onclick = () => { $(b.dataset.gen).value = claveAzar(); }; }); }
function mostrarClave(usuario, clave, titulo) {
  modal(titulo, `
    <p class="ftxt">Pasale estos datos a la persona por un canal privado. <b>La clave no se vuelve a mostrar.</b></p>
    <div class="credencial"><span>Usuario</span><b class="mono">${esc(usuario)}</b><span>Clave</span><b class="mono" id="cTxt">${esc(clave)}</b></div>
    <p class="note">Recomendale que la cambie desde su nombre, arriba a la derecha, la primera vez que entre.</p>
  `, '<button type="button" id="cCopy">Copiar</button><button type="button" class="pri" id="cOk">Listo</button>');
  $('cCopy').onclick = () => { navigator.clipboard.writeText(`Usuario: ${usuario}\nClave: ${clave}`).then(() => toast('Copiado'), () => toast('No se pudo copiar: seleccioná el texto.', true)); };
  $('cOk').onclick = usuarios;
}
function formUsuario(u) {
  const nuevo = !u;
  modal(nuevo ? 'Nuevo usuario' : 'Editar ' + u.usuario, `
    <div class="grid2">
      <div class="f"><label for="nU">Usuario</label><input id="nU" class="mono" maxlength="40" autocomplete="off" value="${esc(u ? u.usuario : '')}" ${nuevo ? '' : 'disabled'} placeholder="ej.: jperez"></div>
      <div class="f"><label for="nN">Nombre y apellido</label><input id="nN" maxlength="80" value="${esc(u ? u.nombre : '')}"></div>
    </div>
    <div class="f"><label for="nR">Perfil</label><select id="nR" ${u && u.id === YO.id ? 'disabled' : ''}>${rolesOpts(u ? u.rol : 'inspector')}</select></div>
    ${nuevo ? campoClave('nC') : ''}
    ${u && u.id === YO.id ? '<p class="note">No podés cambiar tu propio perfil.</p>' : ''}
  `, '<button type="button" id="nX">Cancelar</button><button type="button" class="pri" id="nOk">Guardar</button>');
  conectarGen($('modal'));
  if (nuevo) $('nC').value = claveAzar();
  $('nU') && ($('nU').oninput = e => { e.target.value = e.target.value.toLowerCase().replace(/[^a-z0-9._-]/g, ''); });
  $('nX').onclick = usuarios;
  $('nOk').onclick = async () => {
    const d = {nombre: $('nN').value.trim(), rol: $('nR').value};
    if (!d.nombre) { toast('Escribí el nombre y apellido.', true); return; }
    try {
      busy('Guardando…');
      if (nuevo) {
        d.usuario = $('nU').value.trim(); d.clave = $('nC').value;
        if (d.usuario.length < 3) { busy(''); toast('El usuario tiene que tener al menos 3 caracteres.', true); return; }
        if (d.clave.length < 10) { busy(''); toast('La clave tiene que tener al menos 10 caracteres.', true); return; }
        await api('/usuarios', {method: 'POST', json: d});
        busy(''); await cargar(); mostrarClave(d.usuario, d.clave, 'Usuario creado');
      } else {
        await api('/usuarios/' + u.id, {method: 'PUT', json: d});
        busy(''); toast(u.usuario + ' actualizado'); await cargar(); usuarios();
      }
    } catch (e) { busy(''); error(e); }
  };
}
function formClave(u) {
  modal('Nueva clave · ' + u.usuario, `
    ${campoClave('kC')}
    <p class="note">${u.id === YO.id ? 'Para tu propio usuario conviene usar “Cambiar mi clave” desde tu nombre, arriba.' : 'Al guardarla se cierran las sesiones abiertas de este usuario: tiene que volver a ingresar con la clave nueva.'}</p>
  `, '<button type="button" id="kX">Cancelar</button><button type="button" class="pri" id="kOk">Guardar clave</button>');
  conectarGen($('modal')); $('kC').value = claveAzar();
  $('kX').onclick = usuarios;
  $('kOk').onclick = async () => {
    const clave = $('kC').value;
    if (clave.length < 10) { toast('La clave tiene que tener al menos 10 caracteres.', true); return; }
    try { busy('Guardando…'); await api('/usuarios/' + u.id + '/clave', {method: 'POST', json: {clave}}); busy(''); mostrarClave(u.usuario, clave, 'Clave restablecida'); }
    catch (e) { busy(''); error(e); }
  };
}
function bajaUsuario(u) {
  const elim = !u.actividad;
  modal((elim ? 'Eliminar ' : 'Dar de baja ') + u.usuario, `
    <p class="ftxt"><b>${esc(u.nombre)}</b> · ${esc(rolTxt(u.rol))}</p>
    <p class="ftxt">${elim ? 'No tiene actividad registrada, así que se elimina.' : 'Tiene visitas o cambios cargados, así que no se borra: deja de poder ingresar (se cierran sus sesiones) y todo lo que cargó conserva su nombre. Se puede reactivar.'}</p>
  `, `<button type="button" id="bX">Cancelar</button><button type="button" class="danger" id="bOk">${elim ? 'Eliminar' : 'Dar de baja'}</button>`);
  $('bX').onclick = usuarios;
  $('bOk').onclick = async () => {
    try {
      busy('Guardando…');
      if (elim) await api('/usuarios/' + u.id, {method: 'DELETE'}); else await api('/usuarios/' + u.id, {method: 'PUT', json: {activo: false}});
      busy(''); toast(u.usuario + (elim ? ' eliminado' : ' dado de baja')); await cargar(); usuarios();
    } catch (e) { busy(''); error(e); }
  };
}
function miClave() {
  modal('Cambiar mi clave', `
    <div class="f"><label for="mA">Clave actual</label><input id="mA" type="password" autocomplete="current-password"></div>
    <div class="f"><label for="mN">Clave nueva (mínimo 10 caracteres)</label><input id="mN" type="password" autocomplete="new-password" minlength="10"></div>
    <div class="f"><label for="mR">Repetí la clave nueva</label><input id="mR" type="password" autocomplete="new-password"></div>
  `, '<button type="button" data-close>Cancelar</button><button type="button" class="pri" id="mOk">Cambiar clave</button>');
  $('mOk').onclick = async () => {
    const actual = $('mA').value, nueva = $('mN').value;
    if (nueva.length < 10) { toast('La clave nueva tiene que tener al menos 10 caracteres.', true); return; }
    if (nueva !== $('mR').value) { toast('Las claves nuevas no coinciden.', true); return; }
    try { busy('Guardando…'); await api('/yo/clave', {method: 'POST', json: {actual, nueva}}); busy(''); cerrarModal(); toast('Clave cambiada'); }
    catch (e) { busy(''); error(e); }
  };
}
$('bUsr').onclick = usuarios;
$('bImp').onclick = () => importar();
$('uName').onclick = () => { if (YO) miClave(); };

/* ───────── datos y aviso en vivo ───────── */
async function cargar() {
  const d = await api('/estado');
  HOY = d.hoy || HOY;
  S.visitas = {}; d.visitas.forEach(v => { S.visitas[v.n] = v; });
  S.hallazgos = {}; d.hallazgos.forEach(h => { S.hallazgos[h.n] = h; });
  S.hist = d.historial; S.fotos = d.fotos;
  S.cat = {}; d.catalogo.forEach(c => { c.activo = !!c.activo; S.cat[c.codigo] = c; });
  S.usuarios = {}; d.usuarios.forEach(u => { S.usuarios[u.id] = u; });
  S.marcas = {}; (d.marcas || []).forEach(m => { S.marcas[m.n] = m; });
  GRUPOS = {}; d.grupos.forEach(g => { GRUPOS[g.uf] = String(g.ufs).split(',').map(Number); });
  const b = $('banner');
  if (!Object.values(S.cat).some(c => c.activo)) { b.hidden = false; b.textContent = 'No hay tipos de faltas cargados. Un administrador tiene que cargarlos en Tipos de faltas.'; }
  else b.hidden = true;
  render();
  cargarRecorrido();
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
  $('bUsr').hidden = !puede('admin');
  $('bImp').hidden = !puede('admin');
  $('bLapiz').hidden = !puede('inspector');
  $('bItin').hidden = !puede('inspector');
  $('bRed').hidden = !puede('admin');
  applyVB();
  await cargar().catch(error);
  abrirEventos();
}
applyVB(); render(); iniciar();
})();
