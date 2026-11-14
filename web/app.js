// SPHEREx Sky Flip-book: the page's behaviour.
// The server (server/app.py) does the heavy lifting; this file draws and handles clicks.
"use strict";

const $ = (id) => document.getElementById(id);
const GAIA_GMAX = 16.5;
const MIN_EXPOSURES = 6;
const TAB_ID = Math.random().toString(36).slice(2, 10);   // lets the server tell browser tabs apart
// a colour per detector for the band buttons: short (bluish) to long (red) infrared
const BAND_COLORS = { 1: "#7aa2ff", 2: "#62c7ff", 3: "#5fe0c0", 4: "#c6e66a", 5: "#ffb35c", 6: "#ff6f61" };
const LENS_ICONS = { color: "🌈", methane: "🟣", ice: "🧊", co2: "💨" };
const LENS_SHORT = {
  color: "Normal stars white; cool or dusty things orange-red.",
  methane: "Brown dwarfs with methane in their air glow red.",
  ice: "Stars seen through icy dust clouds turn magenta.",
  co2: "Carbon dioxide and carbon monoxide show up as colour.",
};
const PASS_COLORS =["#58a6ff", "#f0883e", "#3fb950", "#bc8cff", "#ff7b72", "#d29922"];

const S = {
  R: null,            // flip-book result from the server
  mode: "flip",       // "flip" or "lens"
  band: 0, frameIdx: 0, playing: true, timer: null,
  view: "normal", blinkset: "all",
  cross: true, gaia: null, showGaia: false, movers: null, showMovers: true,
  flags: null, flagLayer: "",
  lenses: [], lensKey: "methane", lensPass: "all", lensData: null,
  click: null, spec: null, logy: false,
  tour: [], tourKey: null,
};

// ------------------------------------------------------------------ helpers
const OFFLINE_MSG = "Can't reach the tool's engine. Is the black start.bat window still open? " +
  "If you closed it, double-click start.bat again, then refresh this page.";
const api = async (url, opts) => {
  let r;
  try { r = await fetch(url, opts); }
  catch { throw new Error(OFFLINE_MSG); }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
};
const posQuery = () => `ra0=${S.R.ra}&dec0=${S.R.dec}&field=${S.R.field_deg}`;

function unpack(b64) {
  const bin = atob(b64), buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return new Float32Array(buf.buffer);
}
function showScreen(name) {
  document.body.classList.toggle("on-pick", name === "pick");
  document.body.classList.toggle("on-explore", name === "explore");
  if (name === "explore") window.dispatchEvent(new Event("resize"));
}
function setStep(n) {
  for (let i = 1; i <= 3; i++) {
    $("step" + i).classList.toggle("active", i === n);
    $("step" + i).classList.toggle("done", i < n);
  }
}
function showProgress(stage, frac) {
  $("progress").style.display = "flex";
  $("stage").textContent = stage;
  $("barfill").style.width = Math.round(frac * 100) + "%";
}
function hideProgress() { $("progress").style.display = "none"; }
function fail(msg) {
  hideProgress();
  msg = msg || "Something went wrong.";
  $("error").textContent = msg;
  if (document.body.classList.contains("on-explore")) {
    $("viewerror").innerHTML = `<b>That didn't work.</b><br>${msg}<br><br>` +
      `<button class="primary" onclick="location.reload()">Try again</button> ` +
      `<button onclick="backToSky()">Pick another patch</button>`;
    $("viewerror").classList.remove("hidden");
  }
}
function backToSky() {
  play(false);
  showScreen("pick");
  window.skyPicker && window.skyPicker.reset();
  history.replaceState(null, "", location.pathname);
}

// sky geometry. Grid: north up, east left, centre between the two middle pixels.
function canvasToSky(cx, cy) {         // cx, cy in data-pixel units (0..n)
  const n = S.R.size, pix = S.R.pix_arcsec;
  const east = -(cx - n / 2) * pix, north = (n / 2 - cy) * pix;     // arcsec
  const dec = S.R.dec + north / 3600;
  const ra = S.R.ra + east / 3600 / Math.cos(S.R.dec * Math.PI / 180);
  return { ra: ((ra % 360) + 360) % 360, dec, east, north };
}
function skyToCanvas(east, north) {    // arcsec offsets -> data-pixel units
  const n = S.R.size, pix = S.R.pix_arcsec;
  return [n / 2 - east / pix, n / 2 - north / pix];
}

// ------------------------------------------------------------------ loading a position
async function go(q) {
  q = (q ?? $("where").value).trim();
  if (!q) return;
  $("where").value = q;
  $("error").textContent = "";
  $("resolved").textContent = "";
  showProgress("Working out the position...", 0.01);
  try {
    const pos = await api("/api/resolve?q=" + encodeURIComponent(q));
    hideProgress();
    $("resolved").textContent = `Found: ${pos.how}`;
    S.tourKey = null;
    if (window.skyPicker && document.body.classList.contains("on-pick")) {
      window.skyPicker.select(pos.ra, pos.dec, { name: pos.name || q, kind: "You searched for", story: pos.how, search: true });
    } else {
      await load(pos.ra, pos.dec, parseFloat($("field").value));
    }
  } catch (e) { fail(e.message); }
}

async function load(ra, dec, field, keepBand) {
  showScreen("explore");
  setStep(2);
  $("viewerror").classList.add("hidden");
  $("player").classList.add("hidden");
  $("specpanel").classList.add("hidden");
  $("wherenow").textContent = `RA ${(+ra).toFixed(4)}°, Dec ${(+dec).toFixed(4)}°`;
  showProgress("Starting...", 0.01);
  $("error").textContent = "";
  const token = (S.loadToken = (S.loadToken || 0) + 1);   // a newer click makes this one step aside
  const { job } = await api(`/api/flipbook?ra=${ra}&dec=${dec}&field=${field}&client=${TAB_ID}`, { method: "POST" });
  let shownPreview = 0;
  S.R = null;
  while (true) {
    if (token !== S.loadToken) return;
    const st = await api(`/api/job/${job}`);
    if (token !== S.loadToken || st.state === "cancelled") return;
    if (st.state === "error") return fail(st.stage);
    if (st.state === "done") break;
    if (st.preview_n && st.preview_n !== shownPreview) {
      // a fair first look from the photos that have arrived; it sharpens as more come in
      try {
        const P = await api(`/api/job/${job}/preview`);
        if (token !== S.loadToken) return;
        shownPreview = st.preview_n;
        showResult(P, keepBand, !!S.R);
      } catch { /* the next poll will try again */ }
    }
    if (S.R) showSharpening(st.stage, st.frac);
    else showProgress(st.stage, st.frac);
    await new Promise((res) => setTimeout(res, 700));
  }
  if (!S.R) showProgress("Unpacking pictures...", 1);
  const R = await api(`/api/job/${job}/result`);
  if (token !== S.loadToken) return;
  showResult(R, keepBand, !!S.R);
}

// show a (preview or final) result; if one is already on screen, swap the pictures in
// place and keep the person's choices (band, view, frame)
function showResult(R, keepBand, swapping) {
  for (const f of R.frames) f.arr = unpack(f.pixels);
  hideProgress();
  $("sharpen").classList.toggle("hidden", !R.preview);
  if (swapping && S.R && S.R.ra === R.ra && S.R.dec === R.dec) {
    const keepIdx = S.frameIdx;
    S.R = R;
    S.flags = null; S.lensData = null;
    if (!R.frames.some((f) => f.band === S.band)) S.band = 0;
    S.frameIdx = Math.min(keepIdx, Math.max(0, blinkFrames().length - 1));
    fillPatchInfo();
    if (!R.preview) afterFinal();
    refresh();
    return;
  }
  S.R = R;
  S.gaia = null; S.flags = null; S.lensData = null; S.click = null; S.spec = null; S.movers = null;
  S.ast = null; S.photoView = null; S.photoSeq = null; clearTimeout(S.photoTimer);
  $("photoexit").classList.add("hidden"); $("astpanel").classList.add("hidden");
  setup(keepBand);
}

function showSharpening(stage, frac) {
  const el = $("sharpen");
  el.classList.remove("hidden");
  el.innerHTML = `<b>First look</b> from ${S.R.n_used} of ${S.R.n_images} photos · still downloading, the pictures will sharpen` +
    `<div class="mini-bar"><div style="width:${Math.round(frac * 100)}%"></div></div>`;
}

// things that need every photo: run them once the final result is in
function afterFinal() {
  if (S.showGaia) loadGaia();
  loadMovers();
  if (typeof loadAsteroids === "function") loadAsteroids();
}

// ------------------------------------------------------------------ building the player
function setup(keepBand) {
  const R = S.R;
  $("player").classList.remove("hidden");
  $("info").classList.remove("hidden");
  $("specpanel").classList.add("hidden");
  const params = new URLSearchParams(location.search);
  if (!keepBand && params.has("band")) S.band = parseInt(params.get("band"));
  if (!R.frames.some((f) => f.band === S.band)) S.band = 0;
  S.frameIdx = 0;

  $("bands").innerHTML = "";
  for (const b of R.bands) {
    if (!R.frames.some((f) => f.band === b.band)) continue;
    const btn = document.createElement("button");
    btn.textContent = b.band === 0 ? "All colours" : `${b.wl_min.toFixed(1)}–${b.wl_max.toFixed(1)} µm`;
    btn.className = "chip band-chip";
    if (b.band) btn.style.setProperty("--band", BAND_COLORS[b.band]);
    btn.title = b.band === 0 ? "All six detectors averaged: deepest picture" : `Detector ${b.band}`;
    btn.dataset.band = b.band;
    btn.onclick = () => { S.band = b.band; S.flags = null; refresh(); loadFlags(); };
    $("bands").appendChild(btn);
  }
  $("lenspass").innerHTML = `<option value="all">All passes added (deepest)</option>` +
    R.passes.map((p) => `<option value="${p.index}">${p.label} only</option>`).join("");
  fillPatchInfo();
  if (params.get("mode") === "lens" && !keepBand && !R.preview) S.mode = "lens";
  if (params.get("gaia") === "1" && !keepBand) S.showGaia = true;
  if (R.preview) {
    S.mode = "flip";
    $("moverpanel").classList.remove("hidden");
    $("moverlist").textContent = "The automatic search for moving objects runs as soon as all photos are in.";
  } else afterFinal();
  if (S.mode === "lens") setMode("lens"); else setMode("flip");
  play(true);
}

function fillPatchInfo() {
  const R = S.R;
  $("scale").textContent = `${(R.field_deg * 60).toFixed(1)}′ across`;
  const cname = window.skyPicker ? window.skyPicker.constellationOf(R.ra, R.dec) : "";
  $("wherenow").textContent = `RA ${R.ra.toFixed(4)}°, Dec ${R.dec >= 0 ? "+" : ""}${R.dec.toFixed(4)}°` + (cname ? ` · in ${cname}` : "");
  const tt = S.tourKey && S.tour.find((t) => t.key === S.tourKey);
  $("tourpanel").classList.toggle("hidden", !tt);
  if (tt) { $("tourkind").textContent = tt.kind; $("tourname").textContent = tt.name; $("tourstory").textContent = tt.story; }
  $("summary").textContent = (R.complete === false && !R.preview ? `NASA's archive did not deliver ${R.n_images - R.n_used} of the ${R.n_images} photos; they are left out (and tried again on a later visit). ` : "") +
    `RA ${R.ra.toFixed(4)}°, Dec ${R.dec.toFixed(4)}°. ${R.n_used} of ${R.n_images} SPHEREx exposures used, ` +
    `in ${R.passes.length} sky passes. Pixel size on screen: ${R.pix_arcsec}″ (SPHEREx pixels are 6.15″).`;
  let t = "<tr><th>Pass</th><th>Dates</th><th>Exposures</th></tr>";
  for (const p of R.passes) t += `<tr><td><span style="color:${PASS_COLORS[p.index % 6]}">●</span> ${p.label}</td>` +
    `<td>${p.start} to ${p.end}</td><td>${p.n}</td></tr>`;
  $("ptable").innerHTML = t;
  if (R.preview) $("summary").textContent = `First look: ${R.n_used} of ${R.n_images} photos downloaded so far. ` +
    "The picture sharpens as the rest arrive; spectra, chemistry filters and the mover search open when all are in.";
  $("gaiainfo").textContent = "";
}

function framesForBand() {
  return S.R.frames.filter((f) => f.band === S.band).sort((a, b) => a.pass_index - b.pass_index);
}
function blinkFrames() {
  // a pass with only a handful of exposures in this band is too noisy to compare fairly
  const all = framesForBand(), ok = all.filter((f) => f.n >= MIN_EXPOSURES && !f.limited);
  const fs = ok.length >= 2 ? ok : all;
  return S.blinkset === "ends" && fs.length > 2 ? [fs[0], fs[fs.length - 1]] : fs;
}
function currentFrame() {
  const fs = blinkFrames();
  return fs[S.frameIdx % fs.length];
}

function updateURL() {
  if (!S.R) return;
  const p = new URLSearchParams({ ra: S.R.ra, dec: S.R.dec, field: S.R.field_deg, band: S.band });
  if (S.mode === "lens") { p.set("mode", "lens"); p.set("lens", S.lensKey); }
  if (S.view !== "normal") p.set("view", S.view);
  if (S.showGaia) p.set("gaia", "1");
  history.replaceState(null, "", "?" + p.toString());
}

function refresh() {
  for (const b of $("bands").children) b.classList.toggle("on", parseInt(b.dataset.band) === S.band);
  const fs = blinkFrames();
  $("passes").innerHTML = "";
  fs.forEach((f, i) => {
    const p = S.R.passes[f.pass_index];
    const btn = document.createElement("button");
    btn.className = "pass-chip";
    btn.innerHTML = `<span class="dot" style="background:${PASS_COLORS[p.index % 6]}"></span>${p.label}<small>${f.n} photos</small>`;
    btn.classList.toggle("on", i === S.frameIdx % fs.length);
    btn.onclick = () => { play(false); S.frameIdx = i; draw(); };
    $("passes").appendChild(btn);
  });
  $("cross").classList.toggle("on", S.cross);
  $("gaiaBtn").classList.toggle("on", S.showGaia);
  $("moversBtn").classList.toggle("on", S.showMovers);
  $("play").textContent = S.playing ? "❚❚" : "▶";
  for (const b of $("viewseg").children) b.classList.toggle("on", b.dataset.view === S.view || (S.view === "first" && b.dataset.view === "diff"));
  setStep(S.mode === "lens" || !$("specpanel").classList.contains("hidden") ? 3 : 2);
  $("tab-flip").classList.toggle("on", S.mode === "flip");
  $("tab-lens").classList.toggle("on", S.mode === "lens");
  $("flip-controls").classList.toggle("hidden", S.mode !== "flip");
  $("lens-controls").classList.toggle("hidden", S.mode !== "lens");
  for (const b of $("lenslist").children) b.classList.toggle("on", b.dataset.key === S.lensKey);
  updateURL();
  draw();
}

// ------------------------------------------------------------------ drawing
const off = document.createElement("canvas");

function stretchParams(frames) {
  const peak = Math.max(...frames.map((g) => g.peak));
  const noise = frames[0].noise;
  const vmax = peak * Math.pow(10, -3 * $("bright").value / 100);
  const soft = noise * Math.pow(10, 2 - 3 * $("soft").value / 100);
  return { vmax, soft };
}

function boxSmooth(a, n) {
  const out = new Float32Array(n * n);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    let s = 0, c = 0;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const yy = y + dy, xx = x + dx;
      if (yy >= 0 && xx >= 0 && yy < n && xx < n) { s += a[yy * n + xx]; c++; }
    }
    out[y * n + x] = s / c;
  }
  return out;
}
function nanMean(arrs, len) {
  const out = new Float32Array(len), cnt = new Uint16Array(len);
  for (const a of arrs) for (let i = 0; i < len; i++) if (Number.isFinite(a[i])) { out[i] += a[i]; cnt[i]++; }
  for (let i = 0; i < len; i++) out[i] = cnt[i] ? out[i] / cnt[i] : NaN;
  return out;
}
function robustSigma(a) {
  const v = Array.from(a).filter(Number.isFinite).sort((p, q) => p - q);
  const med = v[v.length >> 1];
  const dev = v.map((x) => Math.abs(x - med)).sort((p, q) => p - q);
  return Math.max(1.4826 * dev[dev.length >> 1], 1e-9);
}

function draw() {
  if (!S.R) return;
  const n = S.R.size;
  off.width = n; off.height = n;
  const octx = off.getContext("2d");
  const img = octx.createImageData(n, n);
  const px = img.data;
  let label = "", sub = "";

  if (S.photoView) {
    [label, sub] = drawPhotoView(px, n);
  } else if (S.mode === "lens") {
    if (!S.lensData) { loadLens(); return; }
    const L = S.lensData;
    const peak = L.peak, noise = L.noise;
    const vmax = peak * Math.pow(10, -3 * $("bright").value / 100);
    const soft = noise * Math.pow(10, 2 - 3 * $("soft").value / 100);
    const norm = Math.asinh(vmax / soft);
    // colour is only trusted where there is real signal: faint/noisy pixels fade to grey
    const nL = (L.noises[0] + L.noises[1] + L.noises[2]) / 3 / Math.sqrt(3);
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const src = (n - 1 - y) * n + x, o = (y * n + x) * 4;
      const ch = [L.arr[0][src], L.arr[1][src], L.arr[2][src]];
      const lum = (ch[0] + ch[1] + ch[2]) / 3;
      const w = Math.max(0, Math.min(1, (lum / nL - 4) / 8));
      for (let c = 0; c < 3; c++) {
        const val = lum + (ch[c] - lum) * w;
        const v = Math.asinh(Math.max(0, val) / soft) / norm;
        px[o + c] = 255 * Math.max(0, Math.min(1, v));
      }
      px[o + 3] = 255;
    }
    const passTxt = S.lensPass === "all" ? "all passes added" : S.R.passes[+S.lensPass].label;
    label = L.name;
    sub = L.windows.map((w, i) => `${["R", "G", "B"][i]} ${w[0]}–${w[1]} µm (${L.counts[i]})`).join(" · ") + ` · ${passTxt}`;
  } else {
    const fs = blinkFrames();
    if (!fs.length) return;
    const f = currentFrame();
    const all = framesForBand();
    const { vmax, soft } = stretchParams(all);
    let ref = null, data = f.arr;
    if (S.view === "diff") {
      ref = nanMean(fs.map((g) => g.arr), n * n);
    } else if (S.view === "first") {
      ref = fs[0].arr;
    } else if (S.view === "stack") {
      data = nanMean(fs.map((g) => g.arr), n * n);
    }
    const norm = Math.asinh(vmax / soft);
    // differences: smooth over one SPHEREx pixel (the grid is half-pixel) and measure the
    // noise of the difference itself, so only changes well above the noise get colour
    let D = null, dsoft = 1, dnorm = 1;
    if (ref) {
      D = boxSmooth(data.map((v, i) => v - ref[i]), n);
      const dn = robustSigma(D);
      dsoft = 2 * dn;
      dnorm = Math.asinh(Math.max(vmax * 0.3, 15 * dn) / dsoft);
      S.diffNoise = dn;
    }
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const src = (n - 1 - y) * n + x, o = (y * n + x) * 4;
      if (!Number.isFinite(data[src]) || (ref && !Number.isFinite(ref[src]))) {
        // no measurement here: shown as no data, never as sky or as a change
        const hatch = ((x + y) % 6 < 3) ? 34 : 26;
        px[o] = hatch; px[o + 1] = hatch + 2; px[o + 2] = hatch + 10;
      } else if (ref) {
        const d = D[src];
        const v = Math.abs(d) < dsoft * 1.5 ? 0 : Math.max(-1, Math.min(1, Math.asinh(d / dsoft) / dnorm));
        const a = Math.sqrt(Math.abs(v));
        if (v >= 0) { px[o] = 30 + 225 * a; px[o + 1] = 30 + 60 * a; px[o + 2] = 30 + 40 * a; }
        else { px[o] = 30 + 30 * a; px[o + 1] = 30 + 110 * a; px[o + 2] = 30 + 225 * a; }
      } else {
        const c = 255 * Math.max(0, Math.min(1, Math.asinh(data[src] / soft) / norm));
        px[o] = c; px[o + 1] = c; px[o + 2] = c;
      }
      px[o + 3] = 255;
    }
    // problem-flag tint
    const flagsOk = S.flags && S.flags.key === `${f.pass_index}-${S.band}` && S.flags.pos === posQuery();
    if (S.flagLayer && !flagsOk) loadFlags();
    if (S.flagLayer && flagsOk) {
      const layer = S.flags.layers.find((l) => l.name === S.flagLayer);
      if (layer) for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
        const v = layer.arr[(n - 1 - y) * n + x];
        if (v > 0.02) {
          const o = (y * n + x) * 4, a = Math.min(0.75, 0.25 + v * 0.6);
          px[o] = px[o] * (1 - a) + 255 * a; px[o + 1] = px[o + 1] * (1 - a) + 190 * a; px[o + 2] = px[o + 2] * (1 - a);
        }
      }
    }
    const p = S.R.passes[f.pass_index];
    const viewTxt = { normal: "", diff: " (difference)", first: ` (minus ${S.R.passes[fs[0].pass_index].label})`, stack: "" }[S.view];
    label = S.view === "stack" ? "All passes added" : p.label + viewTxt;
    const bandName = S.band === 0 ? `${f.n_detectors ?? 6} of 6 detectors averaged`
      : (f.wl_min ? `${f.wl_min.toFixed(2)}–${f.wl_max.toFixed(2)} µm, same wavelength mix in every pass` : "");
    const nimg = S.view === "stack" ? fs.reduce((s, g) => s + g.n, 0) : f.n;
    const skipped = all.filter((g) => !fs.includes(g)).map((g) => S.R.passes[g.pass_index].label);
    sub = `${nimg} exposures used · ${bandName}` +
      (skipped.length ? ` · ${skipped.join(", ")} left out (too few photos or missing wavelengths)` : "") +
      (f.limited && fs.includes(f) ? " · LIMITED COMPARISON: this pass lacks some wavelengths" : "");
    for (const [i, b] of [...$("passes").children].entries()) b.classList.toggle("on", i === S.frameIdx % fs.length && S.view !== "stack");
  }
  octx.putImageData(img, 0, 0);
  if ($("expdetails").open) listExposures();

  const cv = $("sky"), ctx = cv.getContext("2d");
  const s = cv.width / n;
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(off, 0, 0, cv.width, cv.height);
  drawOverlays(ctx, s);
  $("olabel").textContent = label;
  $("osub").textContent = sub;
  drawLegend();
}

function drawOverlays(ctx, s) {
  const W = ctx.canvas.width;
  if (typeof drawAsteroidMarkers === "function") drawAsteroidMarkers(ctx, s);
  if (S.cross) {
    const c = W / 2, g = W * 0.03, L = W * 0.05;
    ctx.strokeStyle = "#58a6ffbb"; ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(c - g - L, c); ctx.lineTo(c - g, c); ctx.moveTo(c + g, c); ctx.lineTo(c + g + L, c);
    ctx.moveTo(c, c - g - L); ctx.lineTo(c, c - g); ctx.moveTo(c, c + g); ctx.lineTo(c, c + g + L);
    ctx.stroke();
  }
  if (S.showGaia && S.gaia) {
    const passIdx = S.mode === "flip" && S.view !== "stack" ? currentFrame().pass_index : null;
    for (const st of S.gaia.stars) {
      const fast = st.pm > 200;
      if (!fast && st.g > GAIA_GMAX) continue;   // fainter Gaia stars are mostly invisible to SPHEREx
      // track through all passes for fast movers
      if (fast) {
        ctx.strokeStyle = "#ffd33d99"; ctx.lineWidth = 1.5; ctx.setLineDash([4, 4]);
        ctx.beginPath();
        st.track.forEach((t, i) => { const [x, y] = skyToCanvas(t[0], t[1]); i ? ctx.lineTo(x * s, y * s) : ctx.moveTo(x * s, y * s); });
        ctx.stroke(); ctx.setLineDash([]);
      }
      const t = st.track[passIdx ?? Math.floor(st.track.length / 2)];
      const [x, y] = skyToCanvas(t[0], t[1]);
      const r = Math.max(6, 16 - st.g * 0.6) * s / 6;
      ctx.strokeStyle = fast ? "#ffd33d" : "#3fb950cc";
      ctx.lineWidth = fast ? 2.2 : 1.4;
      ctx.beginPath(); ctx.arc(x * s, y * s, r, 0, 2 * Math.PI); ctx.stroke();
      if (fast) {
        ctx.fillStyle = "#ffd33d"; ctx.font = `${Math.round(W / 50)}px system-ui`;
        ctx.fillText(`${(st.pm / 1000).toFixed(2)}″/yr`, x * s + r + 3, y * s - r);
      }
    }
  }
  if (S.showMovers && S.movers) {
    for (const m of S.movers.movers) {
      const cand = m.status.startsWith("candidate");
      const col = cand ? "#ff7b72" : "#56d4dd";
      const pts = m.track.map((t) => skyToCanvas(t[0], t[1]).map((v) => v * s));
      const [x0, y0] = pts[0], [x1, y1] = pts[pts.length - 1];
      // stretch the arrow so a few-arcsecond motion is visible: 4x, from the first position
      const k = 4, xe = x0 + (x1 - x0) * k, ye = y0 + (y1 - y0) * k;
      ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 2.5;
      ctx.beginPath(); ctx.arc(x0, y0, s * 3.2, 0, 2 * Math.PI); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(xe, ye); ctx.stroke();
      const ang = Math.atan2(ye - y0, xe - x0), h = s * 1.6;
      ctx.beginPath(); ctx.moveTo(xe, ye);
      ctx.lineTo(xe - h * Math.cos(ang - 0.45), ye - h * Math.sin(ang - 0.45));
      ctx.lineTo(xe - h * Math.cos(ang + 0.45), ye - h * Math.sin(ang + 0.45)); ctx.closePath(); ctx.fill();
      ctx.font = `bold ${Math.round(W / 42)}px system-ui`;
      ctx.fillText(`${cand ? "CANDIDATE " : ""}${m.rate.toFixed(1)}″/yr`, x0 + s * 3.6, y0 + s * 5);
    }
  }
  if (S.click && S.spec && S.spec.followed) {
    // where the spectrum measured the object in each pass (it follows movers)
    for (const [k, f] of Object.entries(S.spec.followed)) {
      const [x, y] = skyToCanvas(S.click.east + f.east, S.click.north + f.north);
      ctx.fillStyle = PASS_COLORS[k % 6];
      ctx.beginPath(); ctx.arc(x * s, y * s, Math.max(3, s * 0.6), 0, 2 * Math.PI); ctx.fill();
    }
  }
  if (S.click) {
    const [x, y] = skyToCanvas(S.click.east, S.click.north);
    const r = 2 / S.R.pix_arcsec * 6.15 * s;  // 2 SPHEREx pixels = the measuring circle (12.3″)
    ctx.strokeStyle = "#ff7b72"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x * s, y * s, r, 0, 2 * Math.PI); ctx.stroke();
  }
}

function listExposures() {
  if (!S.R || S.mode !== "flip") { $("explist").textContent = ""; return; }
  const f = currentFrame();
  const ex = S.R.exposures.filter((e) => (S.view === "stack" || e.pass_index === f.pass_index) &&
    (S.band === 0 || e.band === S.band)).sort((a, b) => a.mjd - b.mjd);
  const date = (mjd) => new Date((mjd - 40587) * 86400000).toISOString().slice(0, 16).replace("T", " ");
  $("explist").innerHTML = `<table><tr><th>Date (UTC)</th><th>Detector</th><th>Wavelength here</th>${ex[0] && ex[0].obs_id ? "<th>Observation</th>" : ""}</tr>` +
    ex.map((e) => `<tr><td>${date(e.mjd)}</td><td>${e.band}</td><td>${e.wl.toFixed(3)} µm</td>${e.obs_id ? `<td>${e.obs_id}</td>` : ""}</tr>`).join("") + "</table>";
}

function drawLegend() {
  const el = $("legend");
  if (S.mode === "flip" && S.flags && S.flagLayer && S.flags.key === `${currentFrame().pass_index}-${S.band}`) {
    const layer = S.flags.layers.find((l) => l.name === S.flagLayer);
    el.innerHTML = `<span style="color:#ffbe00">■</span> ${S.flagLayer}: flagged in up to ${Math.round(layer.max * 100)}% of the ${S.flags.n} exposures in this pass`;
    el.classList.remove("hidden");
  } else if (S.mode === "flip" && (S.view === "diff" || S.view === "first")) {
    el.innerHTML = `<span style="color:#ff6b5b">■</span> brighter than ${S.view === "diff" ? "average" : "first pass"} &nbsp; <span style="color:#5b8cff">■</span> fainter`;
    el.classList.remove("hidden");
  } else if (S.showGaia && S.gaia) {
    el.innerHTML = `<span style="color:#3fb950">○</span> Gaia star (predicted position) &nbsp; <span style="color:#ffd33d">○</span> fast mover, dashed = path`;
    el.classList.remove("hidden");
  } else el.classList.add("hidden");
}

function speedMs() { return 800 / (parseFloat($("speed").value) || 1); }   // ×0.25 … ×2
function step(k) { const n = blinkFrames().length; S.frameIdx = (S.frameIdx + k + n) % n; draw(); }
function play(on) {
  S.playing = on;
  clearTimeout(S.timer);
  const tick = () => {
    if (!S.playing) return;
    if (S.mode === "flip" && S.view !== "stack") step(1);
    S.timer = setTimeout(tick, speedMs());
  };
  draw();
  if (on) S.timer = setTimeout(tick, speedMs());
  $("play").textContent = S.playing ? "❚❚" : "▶";
}

// ------------------------------------------------------------------ modes, lenses, overlays
function setMode(m) {
  if (m === "lens" && S.R && S.R.preview) {
    $("hover").textContent = "Chemistry filters open as soon as all photos are downloaded.";
    m = "flip";
  }
  S.mode = m;
  if (m === "lens") { S.lensData = null; }
  refresh();
}

async function loadLenses() {
  S.lenses = await api("/api/lenses");
  $("lenslist").innerHTML = "";
  for (const L of S.lenses) {
    const b = document.createElement("button");
    b.className = "lens-card";
    b.innerHTML = `<span class="lens-icon">${LENS_ICONS[L.key] || "🔬"}</span><b>${L.name}</b><small>${LENS_SHORT[L.key] || ""}</small>`;
    b.dataset.key = L.key;
    b.onclick = () => { S.lensKey = L.key; S.lensData = null; refresh(); };
    $("lenslist").appendChild(b);
  }
  const p = new URLSearchParams(location.search);
  if (p.get("lens")) S.lensKey = p.get("lens");
}

// lens pictures already built for this patch, so switching back is instant
const lensCache = new Map();
let lensWanted = "";
async function loadLens() {
  const pp = S.lensPass === "all" ? "" : `&pass_index=${S.lensPass}`;
  const key = `${S.R.ra},${S.R.dec},${S.R.field_deg},${S.lensKey}${pp}`;
  if (lensCache.has(key)) { S.lensData = lensCache.get(key); $("lensexplain").textContent = S.lensData.explain; draw(); return; }
  if (lensWanted === key) return;          // already on its way
  lensWanted = key;
  $("lensexplain").textContent = "Building this filter: sorting every photo by the colour it saw (a few seconds)...";
  showLensBusy(true);
  try {
    const L = await api(`/api/lens?${posQuery()}&key=${S.lensKey}${pp}`);
    L.arr = L.channels.map(unpack);
    lensCache.set(key, L);
    if (lensWanted !== key) return;        // the person picked another filter meanwhile
    S.lensData = L;
    $("lensexplain").textContent = L.explain;
  } catch (e) {
    if (lensWanted === key) $("lensexplain").textContent = "Could not build this filter: " + e.message;
  } finally {
    if (lensWanted === key) { lensWanted = ""; showLensBusy(false); }
  }
  if (S.lensData && S.mode === "lens") draw();
}
function showLensBusy(on) {
  if (on) {
    $("olabel").textContent = "Building filter...";
    $("osub").textContent = "";
    const ctx = $("sky").getContext("2d");
    ctx.fillStyle = "rgba(5,8,15,0.6)";
    ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  }
}

async function loadGaia() {
  $("gaiainfo").textContent = "Asking the Gaia archive for stars here...";
  try {
    const forPos = posQuery();
    const g = await api(`/api/gaia?${forPos}`);
    if (!S.R || forPos !== posQuery()) return;   // the person moved to another patch meanwhile
    S.gaia = g;
    const fast = S.gaia.stars.filter((s) => s.pm > 200);
    $("gaiainfo").textContent = `Gaia DR3: ${S.gaia.n} stars brighter than G=19 in view` +
      (fast.length ? `, ${fast.length} fast mover${fast.length > 1 ? "s" : ""} (over 0.2″/yr): ` +
        fast.map((s) => `${(s.pm / 1000).toFixed(2)}″/yr at G=${s.g}`).join(", ") : "") + ".";
  } catch (e) { $("gaiainfo").textContent = e.message; S.showGaia = false; }
  refresh();
}

let flagsPending = "";
async function loadFlags() {
  if (!S.flagLayer || S.mode !== "flip" || !S.R) { draw(); return; }
  const f = currentFrame();
  const key = `${f.pass_index}-${S.band}`, full = `${posQuery()}|${key}`;
  if (S.flags && S.flags.key === key && S.flags.pos === posQuery()) return;
  if (flagsPending === full) return;               // already being fetched
  flagsPending = full;
  try {
    const F = await api(`/api/flags?${posQuery()}&pass_index=${f.pass_index}&band=${S.band}`);
    for (const l of F.layers) l.arr = unpack(l.data);
    F.key = key; F.pos = full.split("|")[0];
    if (flagsPending === full) S.flags = F;        // only if it is still the frame we want
  } catch (e) { /* keep showing the picture without flags */ }
  if (flagsPending === full) flagsPending = "";
  draw();
}

async function loadMovers() {
  $("moverpanel").classList.remove("hidden");
  $("moverlist").textContent = "Searching all passes for anything that moved...";
  const key = `${S.R.ra},${S.R.dec}`;
  try {
    const M = await api(`/api/movers?${posQuery()}`);
    if (!S.R || `${S.R.ra},${S.R.dec}` !== key) return;
    S.movers = M;
    const dir = (m) => (m.rate_north > 0 ? "north" : "south") + "-" + (m.rate_east > 0 ? "east" : "west");
    const bandTxt = (b) => b === 0 ? "all bands" : b === 6 ? "4.4–5.0 µm" : "3.8–4.4 µm";
    $("moverlist").innerHTML = M.movers.length
      ? "<ul>" + M.movers.map((m) => `<li><b style="color:${m.status.startsWith("candidate") ? "#ff7b72" : "#56d4dd"}">` +
          `${m.status.split(":")[0].toUpperCase()}</b>: ${m.rate.toFixed(1)}″/yr to the ${dir(m)}, ` +
          `${m.track[0][0].toFixed(0)}″ E ${m.track[0][1].toFixed(0)}″ N of centre (seen in ${bandTxt(m.band)}, ` +
          `${m.sigma.toFixed(0)}× the field's position noise). ${m.status.split(":")[1] || ""}</li>`).join("") + "</ul>"
      : "No moving objects found by this search (objects bright enough to detect in the stacked pictures, " +
        "moving steadily by more than about 1.5″ between passes and up to 12″ per year). Fainter or much faster " +
        "objects, such as asteroids, would not be caught.";
    draw();
  } catch (e) { $("moverlist").textContent = "Mover search failed: " + e.message; }
}

// ------------------------------------------------------------------ spectrum
function snapToStar(cx, cy) {
  // move the click to the brightness-weighted centre of the nearest blob (within 2 data pixels)
  const f = S.mode === "flip" ? currentFrame() : null;
  if (!f) return [cx, cy];
  const n = S.R.size, arr = f.arr;
  const val = (x, y) => (x < 0 || y < 0 || x >= n || y >= n) ? -Infinity : arr[(n - 1 - y) * n + x];
  let bx = Math.floor(cx), by = Math.floor(cy), best = val(bx, by);
  for (let dy = -3; dy <= 3; dy++) for (let dx = -3; dx <= 3; dx++) {
    const v = val(Math.floor(cx) + dx, Math.floor(cy) + dy);
    if (v > best) { best = v; bx = Math.floor(cx) + dx; by = Math.floor(cy) + dy; }
  }
  if (!(best > 5 * f.noise)) return [cx, cy];   // nothing bright here: keep the exact click
  let sw = 0, sx = 0, sy = 0;
  for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
    const v = Math.max(0, val(bx + dx, by + dy));
    sw += v; sx += v * (bx + dx + 0.5); sy += v * (by + dy + 0.5);
  }
  return sw > 0 ? [sx / sw, sy / sw] : [bx + 0.5, by + 0.5];
}

async function clickSpectrum(e) {
  if (!S.R) return;
  if (S.R.preview) { $("hover").textContent = "Spectra open as soon as all photos are downloaded (see the bar at the top of the picture)."; return; }
  const r = e.target.getBoundingClientRect();
  const n = S.R.size;
  let cx = (e.clientX - r.left) / r.width * n, cy = (e.clientY - r.top) / r.height * n;
  [cx, cy] = snapToStar(cx, cy);
  const sky = canvasToSky(cx, cy);
  S.click = sky;
  draw();
  $("specpanel").classList.remove("hidden");
  setStep(3);
  $("specinfo").textContent = `Measuring at RA ${sky.ra.toFixed(5)}°, Dec ${sky.dec.toFixed(5)}° in every exposure...`;
  $("specwarn").classList.add("hidden");
  try {
    const ticket = (S.specTicket = (S.specTicket || 0) + 1);
    const sp = await api(`/api/spectrum?${posQuery()}&ra=${sky.ra}&dec=${sky.dec}`);
    if (ticket !== S.specTicket) return;      // a newer click is already on its way
    S.spec = sp;
    plotSpectrum();
    draw();
  } catch (e2) { $("specinfo").textContent = "Could not measure here: " + e2.message; }
}

function plotSpectrum() {
  const sp = S.spec;
  if (!sp) return;
  const nearest = nearestGaia(S.click.east, S.click.north);
  $("specinfo").innerHTML = `RA ${sp.ra.toFixed(5)}°, Dec ${sp.dec.toFixed(5)}° · ${sp.n} exposures` +
    (nearest ? ` · nearest Gaia star ${nearest.d.toFixed(1)}″ away (G=${nearest.s.g})` : "") +
    (sp.wing ? "<br>Too bright (burnt-out centre) to measure its motion precisely." :
      (moveText(sp.followed) ? `<br>${moveText(sp.followed)}` : ""));
  const traces = [];
  for (const c of sp.curves) {
    const p = sp.passes[c.pass_index], col = PASS_COLORS[c.pass_index % 6];
    const pts = sp.points.filter((q) => q.pass_index === c.pass_index);
    traces.push({
      x: pts.map((q) => q.wl), y: pts.map((q) => q.flux), mode: "markers", type: "scatter",
      name: p.label + " exposures", legendgroup: p.label, showlegend: false,
      marker: { size: 4, color: col, opacity: pts.map((q) => q.outlier ? 0.2 : 0.45),
        symbol: pts.map((q) => q.outlier ? "circle-open" : q.sat ? "x" : "circle") },
      error_y: { type: "data", array: pts.map((q) => q.err), visible: true, color: col, thickness: 0.6, width: 0 },
      text: pts.map((q) => q.outlier ? "<br>(one-off bad photo: left out of the line)" : ""),
      hovertemplate: "%{x:.3f} µm<br>%{y:.3g} mJy%{text}<extra>" + p.label + "</extra>",
    });
    traces.push({
      x: c.wl, y: c.flux, mode: "lines", type: "scatter", name: p.label, legendgroup: p.label,
      line: { color: col, width: 2.5, shape: "spline", smoothing: 0.3 },
      hovertemplate: "%{x:.2f} µm<br>%{y:.3g} mJy<extra>" + p.label + "</extra>",
    });
  }
  const css = getComputedStyle(document.documentElement);
  const layout = {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: css.getPropertyValue("--text"), size: 12 },
    margin: { l: 56, r: 10, t: 46, b: 44 },
    xaxis: { title: "Wavelength (µm)", gridcolor: "#30363d", range: [0.7, 5.05], zeroline: false },
    yaxis: { title: sp.wing ? "Outer-glow brightness (mJy)" : "Brightness (mJy)", gridcolor: "#30363d", type: S.logy ? "log" : "linear", zeroline: false,
      // ignore a few wild single-photo points when choosing the scale (they stay on the plot; zoom out to see them)
      ...(S.logy ? {} : { range: robustRange(sp.points.filter((q) => !q.outlier).map((q) => q.flux)) }) },
    legend: { orientation: "h", y: 0.99, yanchor: "top", x: 0, yref: "container" },
    shapes: [
      // molecule bands, as faint shading
      ...[[3.2, 3.45, "CH₄"], [2.9, 3.15, "H₂O ice"], [4.2, 4.35, "CO₂"], [4.55, 4.75, "CO"]].map(([a, b]) => ({
        type: "rect", xref: "x", yref: "paper", x0: a, x1: b, y0: 0, y1: 1, fillcolor: "#ffffff", opacity: 0.05, line: { width: 0 } })),
    ],
    annotations: [[3.32, "CH₄"], [3.0, "ice"], [4.27, "CO₂"], [4.68, "CO"]].map(([x, t]) => ({
      x, y: 0.99, xref: "x", yref: "paper", text: t, showarrow: false, font: { size: 10, color: "#8b949e" }, yanchor: "top" })),
  };
  Plotly.react("specplot", traces, layout, { displaylogo: false, responsive: true,
    modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d"] });
  $("specwarn").classList.add("hidden");
  if (sp.wing) {
    $("specwarn").textContent = `This object is so bright that its centre is burnt out (saturated) in ${sp.n_saturated} exposures. ` +
      "So the tool measures its outer glow instead (a ring 18–37″ from the centre), the same way in every exposure. " +
      "The numbers are not its total brightness, but passes can be compared. Changes of about 10–20% between passes can still " +
      "come from the telescope's slightly different star shape in different seasons; bigger changes are real.";
    $("specwarn").classList.remove("hidden");
  } else if (sp.n === 0) {
    $("specwarn").textContent = "No clean measurements here (too close to the edge or to flagged pixels).";
    $("specwarn").classList.remove("hidden");
  }
}

function robustRange(v) {
  const a = v.filter(Number.isFinite).sort((x, y) => x - y);
  if (!a.length) return undefined;
  const lo = a[Math.floor(a.length * 0.01)], hi = a[Math.floor(a.length * 0.985)];
  const pad = (hi - lo) * 0.15 || 1;
  return [Math.min(0, lo - pad), hi + pad];
}

function moveText(fol) {
  const ks = Object.keys(fol || {}).map(Number).sort((a, b) => a - b);
  if (ks.length < 2) return "";
  const a = fol[ks[0]], b = fol[ks[ks.length - 1]];
  const d = Math.hypot(b.east - a.east, b.north - a.north);
  const yrs = (S.R.passes[ks[ks.length - 1]].mjd - S.R.passes[ks[0]].mjd) / 365.25;
  if (d < 2.5) return "No motion detected between passes (within about 2.5″, the measuring precision here).";
  const dir = (b.north - a.north > 0 ? "north" : "south") + "-" + (b.east - a.east > 0 ? "east" : "west");
  return `Moved ${d.toFixed(1)}″ ${dir} in ${yrs.toFixed(1)} years (≈${(d / yrs).toFixed(1)}″/yr). Coloured dots mark where it was found in each pass.`;
}

function nearestGaia(east, north) {
  if (!S.gaia) return null;
  const passIdx = S.mode === "flip" && S.view !== "stack" ? currentFrame().pass_index : 0;
  let best = null;
  for (const s of S.gaia.stars) {
    const t = s.track[Math.min(passIdx, s.track.length - 1)];
    const d = Math.hypot(t[0] - east, t[1] - north);
    if (!best || d < best.d) best = { d, s };
  }
  return best && best.d < 15 ? best : null;
}

// ------------------------------------------------------------------ GIF export
function frameWithLabels() {
  // copy the sky picture and burn in the labels shown on top of it
  const src = $("sky"), c = document.createElement("canvas");
  c.width = 540; c.height = 540;
  const ctx = c.getContext("2d");
  ctx.drawImage(src, 0, 0, c.width, c.height);
  ctx.fillStyle = "#fff"; ctx.shadowColor = "#000"; ctx.shadowBlur = 4;
  ctx.font = "bold 22px system-ui"; ctx.fillText($("olabel").textContent, 12, 30);
  ctx.font = "13px system-ui"; ctx.fillText($("osub").textContent, 12, 50);
  ctx.textAlign = "right"; ctx.fillText(`N↑ E← · ${$("scale").textContent}`, c.width - 10, 22);
  ctx.textAlign = "left"; ctx.font = "12px system-ui";
  ctx.fillText(`SPHEREx · RA ${S.R.ra.toFixed(4)} Dec ${S.R.dec.toFixed(4)}`, 12, c.height - 12);
  return c.toDataURL("image/png");
}
async function saveGif() {
  if (!S.R || S.mode !== "flip") { $("sharemsg").textContent = "Switch to the flip-book to save an animation."; return; }
  const wasPlaying = S.playing; play(false);
  const keep = S.frameIdx, frames = [];
  const n = blinkFrames().length;
  for (let i = 0; i < n; i++) { S.frameIdx = i; draw(); frames.push(frameWithLabels()); }
  S.frameIdx = keep; draw();
  $("sharemsg").textContent = "Making the GIF...";
  try {
    const r = await fetch("/api/gif", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frames, ms: speedMs() }) });
    if (!r.ok) throw new Error(r.statusText);
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement("a");
    a.href = url; a.download = `spherex_${S.R.ra}_${S.R.dec}_band${S.band}_${S.view}.gif`; a.click();
    $("sharemsg").textContent = "GIF saved to your Downloads folder.";
  } catch (e) { $("sharemsg").textContent = "Could not make the GIF: " + e.message; }
  if (wasPlaying) play(true);
}

// ------------------------------------------------------------------ tour
async function loadTour() {
  try { S.tour = await api("/api/tour"); } catch { S.tour = []; }
  window.dispatchEvent(new CustomEvent("tour-loaded", { detail: S.tour }));
}
async function startTour(t) {
  S.tourKey = t.key;
  S.band = t.band; S.mode = "flip"; S.view = "normal"; $("view").value = "normal";
  const field = parseFloat($("field").value) || t.field;   // keep the size the person picked on the card
  history.replaceState(null, "", "?");
  try {
    if (t.ra !== undefined) {
      $("where").value = `${t.ra} ${t.dec}`;
      $("resolved").textContent = t.how ? `→ ${t.how}` : "";
      await load(t.ra, t.dec, field, true);
    } else await go(t.query);
  } catch (e) { fail(e.message); }
}

// ------------------------------------------------------------------ wiring
function wire() {
  $("go").onclick = () => { S.tourKey = null; go(); };
  $("backtosky").onclick = backToSky;
  $("globebtn").onclick = backToSky;
  $("step1").onclick = backToSky;
  $("step2").onclick = () => { if (S.R) setMode("flip"); };
  $("step3").onclick = () => {
    if (!S.R) return;
    setMode("lens");
    $("hover").textContent = "Tip: click any star or dot to see its spectrum (what it is made of).";
  };
  for (const b of $("viewseg").children) b.onclick = () => { $("view").value = b.dataset.view; $("view").onchange(); };
  $("where").addEventListener("keydown", (e) => { if (e.key === "Enter") $("go").click(); });
  $("play").onclick = () => play(!S.playing);
  $("prev").onclick = () => { play(false); step(-1); loadFlags(); };
  $("next").onclick = () => { play(false); step(1); loadFlags(); };
  $("view").onchange = () => { S.view = $("view").value; refresh(); };
  $("blinkset").onchange = () => { S.blinkset = $("blinkset").value; S.frameIdx = 0; refresh(); };
  $("cross").onclick = () => { S.cross = !S.cross; refresh(); };
  $("moversBtn").onclick = () => { S.showMovers = !S.showMovers; refresh(); };
  $("gaiaBtn").onclick = () => { S.showGaia = !S.showGaia; if (S.showGaia && !S.gaia) loadGaia(); else refresh(); };
  $("tab-flip").onclick = () => setMode("flip");
  $("tab-lens").onclick = () => setMode("lens");
  $("lenspass").onchange = () => { S.lensPass = $("lenspass").value; S.lensData = null; draw(); };
  $("flagsel").onchange = () => { S.flagLayer = $("flagsel").value; if (S.flagLayer) play(false); loadFlags(); };
  for (const id of ["bright", "soft"]) $(id).addEventListener("input", draw);
  $("sky").addEventListener("click", clickSpectrum);
  $("specclose").onclick = () => { $("specpanel").classList.add("hidden"); S.click = null; refresh(); };
  $("logy").onclick = () => { S.logy = !S.logy; $("logy").classList.toggle("on", S.logy); plotSpectrum(); };
  $("share").onclick = async () => {
    try { await navigator.clipboard.writeText(location.href); $("sharemsg").textContent = "Link copied."; }
    catch { $("sharemsg").textContent = location.href; }
  };
  $("savepng").onclick = () => {
    const a = document.createElement("a");
    const tag = S.mode === "lens" ? S.lensKey : (S.view === "stack" ? "stack" : S.R.passes[currentFrame().pass_index].label.replace(" ", ""));
    a.download = `spherex_${S.R.ra}_${S.R.dec}_band${S.band}_${tag}.png`;
    a.href = $("sky").toDataURL("image/png");
    a.click();
  };
  $("savegif").onclick = saveGif;
  $("expdetails").addEventListener("toggle", listExposures);
  $("sky").addEventListener("mousemove", (e) => {
    if (!S.R) return;
    const r = e.target.getBoundingClientRect(), n = S.R.size;
    const cx = (e.clientX - r.left) / r.width * n, cy = (e.clientY - r.top) / r.height * n;
    const sky = canvasToSky(cx, cy);
    let val = "";
    if (S.mode === "flip") {
      const f = currentFrame(), x = Math.floor(cx), y = Math.floor(cy);
      if (x >= 0 && y >= 0 && x < n && y < n) val = ` · ${f.arr[(n - 1 - y) * n + x].toFixed(3)} MJy/sr`;
    }
    const g = nearestGaia(sky.east, sky.north);
    $("hover").textContent = `RA ${sky.ra.toFixed(5)}°  Dec ${sky.dec.toFixed(5)}° · ${sky.east.toFixed(1)}″ E, ${sky.north.toFixed(1)}″ N of centre${val}` +
      (g && g.d < 6 ? ` · Gaia star G=${g.s.g}, moves ${(g.s.pm / 1000).toFixed(3)}″/yr` : "");
  });
  document.addEventListener("keydown", (e) => {
    if (!S.R || !document.body.classList.contains("on-explore")) return;
    if (e.target.tagName === "INPUT" && e.target.type === "text") return;
    if (e.target.tagName === "SELECT") return;
    if (e.key === " ") { e.preventDefault(); play(!S.playing); }
    if (e.key === "ArrowRight") { play(false); step(1); loadFlags(); }
    if (e.key === "ArrowLeft") { play(false); step(-1); loadFlags(); }
    if (e.key === "d") { $("view").value = S.view === "diff" ? "normal" : "diff"; $("view").onchange(); }
    if (e.key === "g") $("gaiaBtn").click();
  });
}

async function init() {
  wire();
  const groups = ["Saturated / bloom", "Cosmic ray / transient", "Ghost / stray light", "Satellite streak",
    "Bad / hot / dead pixel", "Persistence (afterimage)"];
  $("flagsel").innerHTML += groups.map((g) => `<option value="${g}">Flags: ${g}</option>`).join("");
  try { await Promise.all([loadLenses(), loadTour()]); }
  catch (e) { $("error").textContent = OFFLINE_MSG; }
  // open straight onto a shared link: ?ra=..&dec=..&field=..&band=..&mode=..&lens=..&gaia=1&view=..
  const p = new URLSearchParams(location.search);
  if (p.get("view")) { S.view = p.get("view"); $("view").value = S.view; }
  if (p.has("ra") && p.has("dec")) {
    const field = p.get("field") || "0.06";
    if ([...$("field").options].some((o) => o.value === field)) $("field").value = field;
    $("where").value = `${p.get("ra")} ${p.get("dec")}`;
    load(parseFloat(p.get("ra")), parseFloat(p.get("dec")), parseFloat(field)).catch((e) => fail(e.message));
  }
}
init();
