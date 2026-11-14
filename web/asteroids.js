// Known asteroids and comets: panel, markers on the picture, and single-photo view.
// Loaded after app.js; uses its globals (S, $, api, posQuery, unpack, skyToCanvas, draw ...).
"use strict";

const JD_LINK = (des) => `https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr=${encodeURIComponent(des)}`;
const mjdToText = (mjd) => new Date((mjd - 40587) * 86400000).toISOString().slice(0, 16).replace("T", " ") + " UTC";

S.showAst = true;
S.ast = null;
S.photoView = null;    // a single photo being shown instead of the stacked frame

async function loadAsteroids() {
  if (!S.R || S.R.preview) return;
  $("astpanel").classList.remove("hidden");
  $("astlist").textContent = "Asking which known asteroids and comets were in this patch when each photo was taken " +
    "(the first time for a patch this takes up to a minute)...";
  const forPos = posKey();
  try {
    const A = await api(`/api/asteroids?${forPos}`);
    if (!S.R || forPos !== posKey()) return;
    S.ast = A;
    renderAsteroids();
    draw();
  } catch (e) {
    $("astlist").textContent = "Could not check for asteroids right now: " + e.message;
  }
}

function riskLines(o) {
  const r = o.risk || {};
  const out = [];
  if (r.error || r.sbdb_error) return ["NASA's small-body database could not be reached just now."];
  const cls = r.orbit_class ? `Orbit type: ${r.orbit_class}.` : "";
  if (r.neo) {
    out.push(`<b>Near-Earth object</b>${r.pha ? " and listed by NASA as <b>potentially hazardous</b> (a size and orbit worth watching; this is not a prediction of impact)" : ""}. ${cls}`);
  } else {
    out.push(`Not a near-Earth object: it stays far from Earth's orbit. ${cls}`);
  }
  const st = r.sentry || {};
  if (st.listed) {
    const p = Number(st.impact_probability);
    const odds = p > 0 ? `about 1 in ${Math.round(1 / p).toLocaleString()}` : "very small";
    out.push(`On NASA's impact-monitoring list (Sentry): published chance of impact ${odds} (Torino scale ${st.torino ?? "0"}` +
      `${st.years ? `, possible dates ${st.years}` : ""}). Such chances usually drop to zero as more observations come in.`);
  } else if (r.neo) {
    out.push("<b>Not on NASA's impact-monitoring list</b> (Sentry): NASA's monitoring has found no possible impact in the next 100 years.");
  }
  if (r.next_close_approach) {
    const c = r.next_close_approach;
    out.push(`Next close pass by Earth: ${c.date.slice(0, 11)}, at ${c.distance_lunar} times the Moon's distance (${c.distance_au.toFixed(3)} AU).`);
  } else if (r.neo) {
    out.push("No close pass by Earth (within 0.2 AU) in the next 100 years.");
  }
  return out;
}

function renderAsteroids() {
  const A = S.ast;
  if (!A) return;
  const objs = A.objects || [];
  if (!objs.length) {
    $("astlist").innerHTML = "No known asteroid or comet crossed this patch while SPHEREx was photographing it.";
    return;
  }
  const caught = objs.filter((o) => o.n_caught > 0);
  const others = objs.filter((o) => o.n_caught === 0);
  const show = [...caught, ...others.slice(0, Math.max(0, 4 - caught.length))];
  const rest = objs.length - show.length;
  let html = "";
  for (const o of show) {
    const des = o.number ? `${o.number} ${o.name}` : o.name;
    const first = o.photos.find((p) => p.seen) || o.photos[0];
    html += `<div class="ast"><b>${des}</b>` +
      (o.risk && o.risk.neo ? `<span class="tag neo">near-Earth</span>` : "") +
      (o.n_caught ? `<span class="tag caught">caught in ${o.n_caught} of ${o.n_photos} photos</span>` :
        `<span class="tag">in ${o.n_photos} photo${o.n_photos > 1 ? "s" : ""}, too faint to see; its place is marked on the picture</span>`) +
      `<div class="muted small-note">${o.kind || ""} · brightness ${o.vmag ?? "?"} (a smaller number is brighter) · ` +
      `${mjdToText(first.mjd)}, moving ${first.rate.toFixed(0)}″ per hour</div>` +
      `<ul>${riskLines(o).map((l) => `<li>${l}</li>`).join("")}</ul>` +
      `<div class="row wrap">` +
      (o.n_caught ? `<button class="small-btn" onclick="showAsteroidPhotos('${encodeURIComponent(o.name)}')">▶ See it in SPHEREx's photos</button>` : "") +
      `<a class="small-note" href="${JD_LINK(o.number || o.name)}" target="_blank" rel="noopener">NASA/JPL page</a></div></div>`;
  }
  if (rest > 0) html += `<p class="muted small-note">…and ${rest} fainter known asteroid${rest > 1 ? "s" : ""} passed through, too faint for SPHEREx to see.</p>`;
  $("astlist").innerHTML = html;
}

// ---------------------------------------------------------------- markers on the picture
// Every known asteroid or comet that crossed the patch is marked where it was, whether
// SPHEREx could see it or not: a diamond at its place in each photo, a dashed line along the
// way it was travelling, and a label with its name and date. Gold = SPHEREx caught it;
// pale = too faint to see. In frames of another pass the mark is dimmer (it was not there then).
function drawAsteroidMarkers(ctx, s) {
  if (!S.showAst || !S.ast || !S.R) return;
  const W = ctx.canvas.width;
  const half = S.R.field_deg * 1800;
  if (S.photoView) {
    for (const o of S.ast.objects) for (const p of o.photos)
      if (p.obs_id === S.photoView.obs_id && p.detector === S.photoView.detector) astMark(ctx, s, W, o, [p], 1, true);
    return;
  }
  const f = S.mode === "flip" && S.view !== "stack" ? currentFrame() : null;
  const k = f && !f.other ? f.pass_index : null;
  for (const o of S.ast.objects) {
    // one mark per visit: photos taken within a few hours of each other
    const visits = [];
    for (const p of [...o.photos].sort((x, y) => x.mjd - y.mjd)) {
      const v = visits[visits.length - 1];
      if (v && p.mjd - v[v.length - 1].mjd < 0.25) v.push(p); else visits.push([p]);
    }
    for (const v of visits) astMark(ctx, s, W, o, v, k === null || v[0].pass_index === k ? 1 : 0.45, false, half);
  }
}

function astMark(ctx, s, W, o, photos, alpha, single, half) {
  const seen = photos.some((p) => p.seen);
  const col = seen ? "#ffc857" : "#e6edf7";
  const r = W / 60;
  ctx.save();
  ctx.globalAlpha = alpha;
  const p0 = photos[0];
  // the way it was travelling: a dashed line across the patch, with an arrowhead
  if (!single && p0.rate_e !== undefined && p0.rate > 0) {
    const ue = p0.rate_e / p0.rate, un = p0.rate_n / p0.rate;
    const span = Math.min(half * 0.9, Math.max(25, p0.rate * 1.5));        // about 1.5 hours of travel each way
    // keep both ends inside the picture, so the arrowhead is always visible
    const reach = (dir) => {
      let t = span;
      for (const [c, u] of [[p0.east, ue * dir], [p0.north, un * dir]])
        if (u !== 0) t = Math.min(t, ((u > 0 ? half * 0.94 : -half * 0.94) - c) / u);
      return Math.max(0, t);
    };
    const tA = reach(-1), tB = reach(1);
    const A = skyToCanvas(p0.east - ue * tA, p0.north - un * tA).map((v) => v * s);
    const B = skyToCanvas(p0.east + ue * tB, p0.north + un * tB).map((v) => v * s);
    for (const [c, w] of [["rgba(0,0,0,0.7)", 4], [col, 1.8]]) {
      ctx.strokeStyle = c; ctx.lineWidth = w; ctx.setLineDash([7, 6]);
      ctx.beginPath(); ctx.moveTo(A[0], A[1]); ctx.lineTo(B[0], B[1]); ctx.stroke();
    }
    ctx.setLineDash([]);
    const ang = Math.atan2(B[1] - A[1], B[0] - A[0]), h = W / 55;
    ctx.fillStyle = col;
    ctx.beginPath(); ctx.moveTo(B[0], B[1]);
    ctx.lineTo(B[0] - h * Math.cos(ang - 0.45), B[1] - h * Math.sin(ang - 0.45));
    ctx.lineTo(B[0] - h * Math.cos(ang + 0.45), B[1] - h * Math.sin(ang + 0.45));
    ctx.closePath(); ctx.fill();
  }
  const spots = new Map();
  for (const p of photos) spots.set(`${p.east.toFixed(1)},${p.north.toFixed(1)}`, p);
  for (const p of spots.values()) {
    const [x, y] = skyToCanvas(p.east, p.north).map((v) => v * s);
    const path = () => { ctx.beginPath(); ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath(); };
    ctx.strokeStyle = "rgba(0,0,0,0.75)"; ctx.lineWidth = 4.5; path(); ctx.stroke();
    ctx.strokeStyle = col; ctx.lineWidth = 2.2; path(); ctx.stroke();
  }
  const [x, y] = skyToCanvas(p0.east, p0.north).map((v) => v * s);
  const day = new Date((p0.mjd - 40587) * 86400000).toISOString().slice(0, 10);
  const label = `☄ ${o.name}` + (single ? "" : `, ${day}`) + (seen ? "" : " (too faint to see)");
  ctx.font = `bold ${Math.max(12, Math.round(W / 50))}px system-ui`;
  const tw = ctx.measureText(label).width;
  let lx = x + r + 5; if (lx + tw > W - 4) lx = x - r - 5 - tw;
  const ly = Math.min(W - 6, Math.max(16, y - r - 2));
  ctx.lineWidth = 4; ctx.strokeStyle = "rgba(0,0,0,0.85)"; ctx.strokeText(label, lx, ly);
  ctx.fillStyle = col; ctx.fillText(label, lx, ly);
  ctx.restore();
}

// ---------------------------------------------------------------- single photos
async function showAsteroidPhotos(nameEnc) {
  const o = S.ast.objects.find((x) => x.name === decodeURIComponent(nameEnc));
  if (!o) return;
  play(false);
  const seen = o.photos.filter((p) => p.seen);
  S.photoSeq = { obj: o, list: seen, idx: 0, frames: [] };
  $("hover").textContent = `Loading ${seen.length} single photos of ${o.name}...`;
  for (const p of seen) {
    try {
      const P = await api(`/api/photo?${posQuery()}&obs_id=${encodeURIComponent(p.obs_id)}&detector=${p.detector}`);
      P.arr = unpack(P.pixels);
      S.photoSeq.frames.push(P);
    } catch { /* skip a missing photo */ }
  }
  if (!S.photoSeq.frames.length) return;
  $("photoexit").classList.remove("hidden");
  S.photoView = S.photoSeq.frames[0];
  $("hover").textContent = `These are single photos, not stacks: ${o.name} is only in these, so the stacked flip-book ` +
    `leaves it out as a one-off. Watch it shift between photos taken minutes apart.`;
  const tick = () => {
    if (!S.photoView || !S.photoSeq) return;
    S.photoSeq.idx = (S.photoSeq.idx + 1) % S.photoSeq.frames.length;
    S.photoView = S.photoSeq.frames[S.photoSeq.idx];
    draw();
    S.photoTimer = setTimeout(tick, 900);
  };
  draw();
  clearTimeout(S.photoTimer);
  S.photoTimer = setTimeout(tick, 900);
}

function exitPhotoView() {
  clearTimeout(S.photoTimer);
  S.photoView = null; S.photoSeq = null;
  $("photoexit").classList.add("hidden");
  draw();
}

function drawPhotoView(px, n) {
  const P = S.photoView;
  const vmax = P.peak * Math.pow(10, -3 * $("bright").value / 100);
  const soft = P.noise * Math.pow(10, 2 - 3 * $("soft").value / 100);
  const norm = Math.asinh(vmax / soft);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const src = (n - 1 - y) * n + x, o = (y * n + x) * 4;
    const v = P.arr[src];
    if (!Number.isFinite(v)) { const h = ((x + y) % 6 < 3) ? 34 : 26; px[o] = h; px[o + 1] = h + 2; px[o + 2] = h + 10; }
    else { const c = tone(Math.asinh(v / soft) / norm); px[o] = c; px[o + 1] = c; px[o + 2] = c; }
    px[o + 3] = 255;
  }
  return [`Single photo · ${mjdToText(P.mjd)}`,
    `detector ${P.detector}, ${P.wl.toFixed(2)} µm · ${S.photoSeq ? `photo ${S.photoSeq.idx + 1} of ${S.photoSeq.frames.length} showing ${S.photoSeq.obj.name}` : ""}`];
}

$("photoexit").onclick = exitPhotoView;
$("astBtn").onclick = () => { S.showAst = !S.showAst; $("astBtn").classList.toggle("on", S.showAst); draw(); };
