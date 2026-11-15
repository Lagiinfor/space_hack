// Extras added for the full challenge specification. Everything here works on real measurements
// already fetched by the page; nothing is invented.
//   1. share links: fov, selected object, pass on screen, catalogues, chosen pair (see also app.js init)
//   2. spectrum export (CSV), brightness over time (plot + CSV), hover details
//   3. quality panel for the clicked object (NASA's flags, signal-to-noise) and a quality filter
//   4. blink / subtract any two passes; backward play
//   5. catalogue details of the clicked object; link to each photo's original file at NASA
//   6. false colour from three wavelength ranges of the person's choice
//   7. summary table of what the switched-on catalogues hold in the patch
// Loaded after bands.js.
"use strict";

const xDownload = (name, text, type = "text/csv") => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
};
const xDate = (mjd) => new Date((mjd - 40587) * 86400000).toISOString().slice(0, 16).replace("T", " ");
const xMedian = (v) => { const s = [...v].sort((a, b) => a - b), n = s.length; return n ? (n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2) : NaN; };
const FLAG_HELP = {
  "Saturated / bloom": "The pixel received too much light to measure (a very bright star), or light spilled from one.",
  "Cosmic ray / transient": "A one-off hit, usually a cosmic ray: light in one photo that is not on the sky.",
  "Ghost / stray light": "A reflection inside the telescope from a bright star elsewhere.",
  "Satellite streak": "A satellite or aircraft crossed the photo.",
  "Bad / hot / dead pixel": "A detector pixel known to misbehave.",
  "Persistence (afterimage)": "A faint afterimage of a bright star seen in an earlier photo.",
};

// ---------------------------------------------------------------- hover details (used by app.js)
function pointHover(q) {
  return `<br>${xDate(q.mjd)} UTC` + (q.snr !== null && q.snr !== undefined ? `<br>signal ${q.snr}× the noise` : "") +
    (q.sat ? "<br>saturated" : "") + (q.flags && q.flags.length ? `<br>NASA flags: ${q.flags.join(", ")}` : "");
}

// ---------------------------------------------------------------- spectrum extras
S.hideFlagged = false;
const x0_plotSpectrum = plotSpectrum;
plotSpectrum = function () {
  const sp = S.spec;
  if (sp && S.hideFlagged && !sp._all) {
    sp._all = sp.points;
    sp.points = sp.points.filter((q) => !(q.flags && q.flags.length) && !q.sat);
  } else if (sp && !S.hideFlagged && sp._all) { sp.points = sp._all; delete sp._all; }
  x0_plotSpectrum();
};

function xAllPoints() { return S.spec ? (S.spec._all || S.spec.points) : []; }

function spectrumCsv() {
  const sp = S.spec, P = xAllPoints();
  const head = `# SPHEREx aperture photometry at RA ${sp.ra.toFixed(6)} Dec ${sp.dec.toFixed(6)} (ICRS). ` +
    `Flux in mJy inside a 12.3 arcsec circle (2 SPHEREx pixels) with the local sky removed; not an aperture-corrected total.\n` +
    `# Source: NASA SPHEREx level-2 spectral images via NASA/IPAC IRSA. One row per exposure.\n` +
    (sp.wing ? "# The centre is saturated: these values are the outer-glow brightness, comparable between passes only.\n" : "");
  const rows = P.map((q) => [q.wl, q.flux, q.err, q.snr ?? "", q.band, q.pass_index, S.R.passes[q.pass_index]?.label ?? "", q.mjd, xDate(q.mjd),
    q.obs ?? "", q.sat ? 1 : 0, q.outlier ? 1 : 0, `"${(q.flags || []).join("; ")}"`].join(","));
  return head + "wavelength_um,flux_mJy,flux_err_mJy,snr,detector,pass_index,pass,mjd,date_utc,observation_id,saturated,one_off_outlier,nasa_flags\n" + rows.join("\n") + "\n";
}

// brightness over time: per detector and sky pass, the median of the good measurements
function lightCurve() {
  const out = [];
  const P = xAllPoints().filter((q) => !q.outlier && Number.isFinite(q.flux));
  for (let b = 1; b <= 6; b++) for (const p of S.R.passes) {
    const k = p.index ?? S.R.passes.indexOf(p);
    const v = P.filter((q) => q.band === b && q.pass_index === k);
    if (v.length < 3) continue;
    const fl = v.map((q) => q.flux), med = xMedian(fl);
    const mad = 1.4826 * xMedian(fl.map((x) => Math.abs(x - med)));
    out.push({ band: b, pass_index: k, label: p.label, mjd: xMedian(v.map((q) => q.mjd)), flux: med,
      err: Math.max(mad, xMedian(v.map((q) => q.err))) / Math.sqrt(v.length), n: v.length,
      wl_min: Math.min(...v.map((q) => q.wl)), wl_max: Math.max(...v.map((q) => q.wl)) });
  }
  return out;
}
function lightCurveCsv() {
  const sp = S.spec;
  return `# Brightness over time at RA ${sp.ra.toFixed(6)} Dec ${sp.dec.toFixed(6)}: per detector and sky pass, the median of the ` +
    `exposures (one-off outliers left out). Error = scatter / sqrt(n). mJy in a 12.3 arcsec circle.\n` +
    "detector,wl_min_um,wl_max_um,pass,mjd,date_utc,median_flux_mJy,err_mJy,n_exposures\n" +
    lightCurve().map((r) => [r.band, r.wl_min.toFixed(3), r.wl_max.toFixed(3), r.label, r.mjd.toFixed(3), xDate(r.mjd), r.flux, r.err, r.n].join(",")).join("\n") + "\n";
}

function qualityHtml() {
  const P = xAllPoints();
  if (!P.length) return "";
  if (!P.some((q) => q.flags !== undefined)) return `<p class="muted small-note">Quality flags are not available for this measurement.</p>`;
  const groups = Object.keys(FLAG_HELP).filter((g) => P.some((q) => (q.flags || []).includes(g)));
  let rows = "";
  for (const p of S.R.passes) {
    const k = p.index ?? S.R.passes.indexOf(p), v = P.filter((q) => q.pass_index === k);
    if (!v.length) continue;
    const snr = xMedian(v.filter((q) => q.snr !== null && q.snr !== undefined).map((q) => q.snr));
    const clean = v.filter((q) => !(q.flags || []).length && !q.sat && !q.outlier).length;
    rows += `<tr><td>${esc(p.label)}</td><td>${v.length}</td><td>${Number.isFinite(snr) ? snr.toFixed(1) : "–"}</td><td>${clean}</td>` +
      `<td>${v.filter((q) => q.sat).length || ""}</td><td>${v.filter((q) => q.outlier).length || ""}</td>` +
      groups.map((g) => `<td>${v.filter((q) => q.flags.includes(g)).length || ""}</td>`).join("") + `</tr>`;
  }
  const low = P.filter((q) => q.snr !== null && q.snr !== undefined && q.snr < 3).length;
  return `<div class="ctl-label">Measurement quality <span class="muted">(photos of this object, per sky pass)</span></div>` +
    `<table class="xtable"><tr><th>Pass</th><th title="Photos measured">Photos</th>` +
    `<th title="Typical signal-to-noise of one photo: the measured light divided by its uncertainty. Under 3 means the object is barely detected.">Signal ÷ noise</th>` +
    `<th title="Photos with no flag, not saturated and not a one-off outlier">Clean</th>` +
    `<th title="The centre of the object is burnt out in these photos">Saturated</th>` +
    `<th title="A single measurement far from all others taken at that time: left out of the lines">One-off</th>` +
    groups.map((g) => `<th title="${esc(FLAG_HELP[g])}">${esc(g.split(" / ")[0])}</th>`).join("") + `</tr>${rows}</table>` +
    `<p class="muted small-note">Flags are NASA's own, read for the pixels inside the measuring circle; a column appears only if that problem occurs. ` +
    `An empty cell means none was flagged, which is not a guarantee of a perfect photo. ` +
    (low ? `${low} of ${P.length} photos have signal under 3× the noise. ` : "") + `Hover a heading for its meaning.</p>` +
    `<label class="small-note"><input type="checkbox" id="xhide" ${S.hideFlagged ? "checked" : ""}> Hide flagged and saturated measurements in the graph</label>`;
}

function renderExtras() {
  const sp = S.spec;
  if (!sp || !S.R) return;
  let box = $("objextras");
  if (!box) {
    box = document.createElement("div"); box.id = "objextras";
    $("specwarn").insertAdjacentElement("afterend", box);
  }
  const lc = lightCurve();
  box.innerHTML = `<div class="row wrap" style="margin:8px 0">` +
    `<button class="small-btn" id="xcsv" title="Every measurement behind the graph, with uncertainty, date and NASA's flags">⬇ Spectrum (CSV)</button>` +
    (lc.length ? `<button class="small-btn" id="xlccsv">⬇ Brightness over time (CSV)</button>` : "") + `</div>` +
    (lc.length ? `<div class="ctl-label">Brightness over time <span class="muted">(one line per infrared colour)</span></div><div id="xlc"></div>` +
      `<p class="muted small-note">Each point is the median of one detector's photos in one sky pass (one-off outliers left out); the bar is its uncertainty. ` +
      `A line that rises or falls well beyond its bars is a real brightness change. With only ${S.R.passes.length} passes this is a coarse light curve.</p>` : "") +
    qualityHtml();
  $("xcsv").onclick = () => xDownload(`spherex_spectrum_${sp.ra.toFixed(4)}_${sp.dec.toFixed(4)}.csv`, spectrumCsv());
  if ($("xlccsv")) $("xlccsv").onclick = () => xDownload(`spherex_lightcurve_${sp.ra.toFixed(4)}_${sp.dec.toFixed(4)}.csv`, lightCurveCsv());
  if ($("xhide")) $("xhide").onchange = (e) => { S.hideFlagged = e.target.checked; plotSpectrum(); };
  if (lc.length && window.Plotly) {
    const traces = [];
    for (let b = 1; b <= 6; b++) {
      const v = lc.filter((r) => r.band === b);
      if (!v.length) continue;
      traces.push({ x: v.map((r) => xDate(r.mjd)), y: v.map((r) => r.flux), mode: "lines+markers", type: "scatter",
        name: `${v[0].wl_min.toFixed(1)}–${v[0].wl_max.toFixed(1)} µm`, line: { color: BAND_COLORS[b], width: 1.5 }, marker: { size: 7, color: BAND_COLORS[b] },
        error_y: { type: "data", array: v.map((r) => r.err), visible: true, color: BAND_COLORS[b], thickness: 1 },
        text: v.map((r) => `${r.label}, ${r.n} photos`), hovertemplate: "%{x}<br>%{y:.3g} mJy<br>%{text}<extra>%{fullData.name}</extra>" });
    }
    Plotly.newPlot("xlc", traces, { height: 230, margin: { l: 50, r: 10, t: 6, b: 34 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#c6d1ea", size: 11 }, xaxis: { gridcolor: "#30363d" }, yaxis: { title: sp.wing ? "Outer glow (mJy)" : "Brightness (mJy)", gridcolor: "#30363d", rangemode: "tozero" },
      legend: { orientation: "h", y: -0.25, font: { size: 10 } } }, { displayModeBar: false, responsive: true });
  }
}
const x0_afterSpectrum = afterSpectrum;
afterSpectrum = function (sp, sky) { x0_afterSpectrum(sp, sky); renderExtras(); updateURL(); };

// ---------------------------------------------------------------- catalogue details of the clicked object
const x0_renderChecks = renderChecks;
renderChecks = function (C) {
  const rows = [];
  const g = C.gaia || {};
  if (g.found || g.background_star) rows.push([`Gaia DR3 ${g.id}` + (g.background_star ? " (background star)" : ""), g.ra, g.dec, g.epoch, `G ${g.g}`,
    `${g.pm.toFixed(3)}″/yr (${(g.pmra / 1000).toFixed(3)} E, ${(g.pmdec / 1000).toFixed(3)} N)`,
    g.parallax !== null && g.parallax !== undefined ? `${g.parallax} mas` + (g.distance_ly ? ` (${g.distance_ly.toLocaleString()} ly)` : "") : "–",
    `${g.sep_arcsec}″`]);
  for (const c of C.catalogs || []) if (c.found) rows.push([c.source, c.ra, c.dec, c.epoch ?? c.year, c.mag !== undefined ? `${c.band} ${c.mag}` : "–",
    c.pm ? `${c.pm}″/yr` : "not given", "not given", c.sep_arcsec !== null && c.sep_arcsec !== undefined ? `${c.sep_arcsec}″` : (c.how || "–")]);
  let h = x0_renderChecks(C);
  if (rows.length) h += `<div class="ctl-label">Catalogue entries for this object</div><div style="overflow-x:auto"><table class="xtable">` +
    `<tr><th>Identifier</th><th>RA (°)</th><th>Dec (°)</th><th title="The date the catalogue position refers to">Position date</th><th>Brightness</th>` +
    `<th title="Motion across the sky, arcseconds per year">Motion</th><th title="Yearly wobble caused by Earth's orbit: gives the distance">Parallax</th>` +
    `<th title="How far the catalogue position, moved to the date of the pictures, is from where you clicked">Offset</th></tr>` +
    rows.map((r) => `<tr>${r.map((x) => `<td>${esc(String(x ?? "–"))}</td>`).join("")}</tr>`).join("") + `</table></div>` +
    `<p class="muted small-note">A match within about 2″ with a consistent motion is secure; a larger offset, or a catalogue too old to trace a fast object, is uncertain and is said so above.</p>`;
  return h;
};

// ---------------------------------------------------------------- link to each photo's original file
S.imgUrls = null;
const x0_listExposures = listExposures;
listExposures = function () {
  x0_listExposures();
  if (!S.R || S.R.preview || S.R.follow) return;
  const key = posKey();
  if (!S.imgUrls || S.imgUrls.key !== key) {
    if (S.imgUrls && S.imgUrls.loading === key) return;
    S.imgUrls = { loading: key };
    api(`/api/images?${key}`).then((L) => {
      const m = { key }; for (const i of L) m[`${i.obs_id}_${i.detector}`] = i.url;
      S.imgUrls = m; if (S.R && posKey() === key) listExposures();
    }).catch(() => { S.imgUrls = { key }; });
    return;
  }
  for (const tr of $("explist").querySelectorAll("tr")) {
    const td = tr.querySelectorAll("td");
    if (td.length < 4) continue;
    const obs = td[td.length - 1].textContent.trim(), det = parseInt(td[1].textContent.replace(/\D/g, ""));
    const url = S.imgUrls[`${obs}_${det}`];
    if (url && !td[td.length - 1].querySelector("a"))
      td[td.length - 1].innerHTML = `<a href="${url}" target="_blank" rel="noopener" title="The original calibrated file (level 2) in NASA's IRSA archive, about 60 MB">${esc(obs)} ↗</a>`;
  }
};

// ---------------------------------------------------------------- blink or subtract any two passes; backward play
S.pair = null; S.reverse = false;
(function wirePair() {
  const sel = $("blinkset");
  sel.insertAdjacentHTML("beforeend", `<option value="pair">Blink two passes I choose</option>`);
  sel.insertAdjacentHTML("afterend", `<span id="pairbox" class="hidden"> <select id="pairA" title="First pass"></select> ↔ <select id="pairB" title="Second pass"></select></span>`);
  const set = () => { S.pair = [parseInt($("pairA").value), parseInt($("pairB").value)]; S.frameIdx = 0; refresh(); };
  $("pairA").onchange = set; $("pairB").onchange = set;
  const rev = document.createElement("button");
  rev.id = "revbtn"; rev.className = "icon-btn"; rev.textContent = "⇄"; rev.title = "Play backward / forward";
  rev.onclick = () => { S.reverse = !S.reverse; rev.classList.toggle("on", S.reverse); rev.title = S.reverse ? "Playing backward (click for forward)" : "Play backward / forward"; };
  $("next").insertAdjacentElement("afterend", rev);
})();
function pairUI() {
  const on = S.blinkset === "pair" && S.R && S.mode === "flip";
  $("pairbox").classList.toggle("hidden", !on);
  if (!on) return;
  const fs = framesForBand();
  const opts = fs.map((f) => `<option value="${f.pass_index}">${esc(S.R.passes[f.pass_index].label)}</option>`).join("");
  if ($("pairA").dataset.for !== opts) {
    $("pairA").innerHTML = opts; $("pairB").innerHTML = opts; $("pairA").dataset.for = opts;
    if (!S.pair || !fs.some((f) => f.pass_index === S.pair[0]) || !fs.some((f) => f.pass_index === S.pair[1]))
      S.pair = fs.length ? [fs[0].pass_index, fs[fs.length - 1].pass_index] : null;
  }
  if (S.pair) { $("pairA").value = S.pair[0]; $("pairB").value = S.pair[1]; }
}
const x0_blinkFrames = blinkFrames;
blinkFrames = function () {
  if (S.blinkset === "pair" && S.pair) {
    const fs = framesForBand(), a = fs.find((f) => f.pass_index === S.pair[0]), b = fs.find((f) => f.pass_index === S.pair[1]);
    if (a && b && a !== b) return [a, b];
  }
  return x0_blinkFrames();
};
const x0_step = step;
step = function (k) { x0_step(S.reverse && S.playing && k === 1 ? -1 : k); };

// ---------------------------------------------------------------- false colour from the person's own three ranges
S.lensWin = "4.4-5.0,3.0-3.6,1.5-2.0";
(function wireCustomLens() {
  const box = document.createElement("div");
  box.id = "customlens"; box.className = "small-note"; box.style.margin = "8px 0";
  const def = S.lensWin.split(",").map((w) => w.split("-"));
  const inp = (i, j) => `<input type="number" step="0.05" min="0.75" max="5" id="cl${i}${j}" value="${def[i][j]}" style="width:64px">`;
  box.innerHTML = `<b>Your own colours</b> (wavelength ranges in µm, between 0.75 and 5.0): ` +
    `<span style="color:#ff6b5b">red</span> ${inp(0, 0)}–${inp(0, 1)} ` +
    `<span style="color:#56d364">green</span> ${inp(1, 0)}–${inp(1, 1)} ` +
    `<span style="color:#6cb6ff">blue</span> ${inp(2, 0)}–${inp(2, 1)} ` +
    `<button class="small-btn" id="clgo">Show</button> <span id="clmsg" class="muted"></span>`;
  $("lenslist").insertAdjacentElement("afterend", box);
  $("clgo").onclick = () => {
    const w = [0, 1, 2].map((i) => [parseFloat($(`cl${i}0`).value), parseFloat($(`cl${i}1`).value)]);
    if (w.some(([a, b]) => !(a >= 0.75 && b <= 5.0 && a < b))) { $("clmsg").textContent = "Each range must go from a smaller to a larger number, between 0.75 and 5.0."; return; }
    $("clmsg").textContent = "";
    S.lensWin = w.map(([a, b]) => `${a}-${b}`).join(","); S.lensKey = "custom"; S.lensData = null; refresh();
  };
})();

// ---------------------------------------------------------------- share links
// (reading ra/dec/fov and validating them happens in app.js; here: the extra settings)
const x0_updateURL = updateURL;
updateURL = function () {
  x0_updateURL();
  if (!S.R) return;
  const p = new URLSearchParams(location.search);
  p.set("fov", S.R.field_deg);
  if (S.cats && S.cats.size) p.set("cats", [...S.cats].join(","));
  if (S.blinkset === "ends") p.set("blink", "ends");
  if (S.blinkset === "pair" && S.pair) p.set("blink", S.pair.join("-"));
  if (S.mode === "lens" && S.lensKey === "custom") p.set("win", S.lensWin);
  const cp = S.mode === "flip" && !S.playing && typeof currentPass === "function" ? currentPass() : null;
  if (cp !== null && cp !== undefined) p.set("pass", cp);
  if (S.click && !$("specpanel").classList.contains("hidden")) p.set("sel", `${S.click.ra.toFixed(5)},${S.click.dec.toFixed(5)}`);
  history.replaceState(null, "", "?" + p.toString());
};
$("share").onclick = async () => {
  updateURL();
  try { await navigator.clipboard.writeText(location.href); $("sharemsg").textContent = "Link copied: it reopens this patch, band, view, pass and selected object."; }
  catch { $("sharemsg").textContent = location.href; }
};

const X_START = new URLSearchParams(location.search);     // what the link asked for when the page opened
if (X_START.get("cats") !== null && typeof S.cats !== "undefined")
  S.cats = new Set(X_START.get("cats").split(",").filter((k) => typeof CAT !== "undefined" && CAT[k]));
if (X_START.get("win") && /^[\d.]+-[\d.]+,[\d.]+-[\d.]+,[\d.]+-[\d.]+$/.test(X_START.get("win"))) S.lensWin = X_START.get("win");
let xStartDone = false;
const x0_afterFinalX = afterFinal;
afterFinal = function () {
  x0_afterFinalX();
  if (xStartDone || !S.R) return;
  xStartDone = true;
  // a moment later: the page first finishes putting the pictures on screen (and starts playing)
  setTimeout(() => { try {
    const bl = X_START.get("blink") || (X_START.get("mode") === "blink" ? "ends" : "");
    if (bl === "ends") { S.blinkset = "ends"; $("blinkset").value = "ends"; }
    else if (/^\d+-\d+$/.test(bl)) { S.blinkset = "pair"; $("blinkset").value = "pair"; S.pair = bl.split("-").map(Number); }
    if (X_START.get("pass") !== null && /^\d+$/.test(X_START.get("pass"))) {
      const k = parseInt(X_START.get("pass")), i = timelineFrames().findIndex((f) => !f.other && f.pass_index === k);
      if (i >= 0) { play(false); S.frameIdx = i; }
    }
    refresh();
    const sel = (X_START.get("sel") || "").split(",").map(Number);
    if (sel.length === 2 && sel.every(Number.isFinite)) setTimeout(() => {
      const cosd = Math.cos(S.R.dec * Math.PI / 180);
      const east = (((sel[0] - S.R.ra + 540) % 360) - 180) * 3600 * cosd, north = (sel[1] - S.R.dec) * 3600;
      const half = S.R.field_deg * 1800;
      if (Math.abs(east) > half || Math.abs(north) > half) return;        // the object is outside this picture
      const cv = $("sky"), b = cv.getBoundingClientRect(), k = b.width / (S.R.size * S.R.pix_arcsec);
      cv.dispatchEvent(new MouseEvent("click", { clientX: b.left + b.width / 2 - east * k, clientY: b.top + b.height / 2 - north * k, bubbles: true }));
    }, 600);
  } catch (e) { /* a bad link setting must never stop the page */ } }, 400);
};

// ---------------------------------------------------------------- summary table of the switched-on catalogues
S.tableOnly = false;
function catObjects() {
  // every catalogued object inside the picture, per switched-on catalogue: {e, n, moving, kind}
  const per = {};
  if (!S.R || typeof catKeys !== "function") return per;
  for (const k of catKeys()) {
    if (k === "gaia") {
      if (!S.gaia) continue;
      per.gaia = S.gaia.stars.map((st) => { const t = st.track[Math.floor(st.track.length / 2)]; return { e: t[0], n: t[1], moving: st.pm > 200, kind: null }; });
    } else {
      const d = S.catData[k];
      if (!d || d.pos !== posKey()) continue;
      per[k] = d.sources.map((o) => ({ e: o.east, n: o.north, moving: !!o.moves && o.pm >= 0.2, kind: k === "simbad" ? (o.plain ? "star" : o.type) : null }));
    }
  }
  return per;
}
function renderCatTable() {
  let box = $("cattable");
  if (!box) {
    if (!$("catinfo")) return;
    box = document.createElement("div"); box.id = "cattable";
    $("catinfo").insertAdjacentElement("afterend", box);
    const bar = document.createElement("div");
    bar.className = "row wrap"; bar.style.margin = "6px 0";
    bar.innerHTML = `<button class="small-btn" id="catall">Switch all on</button><button class="small-btn" id="catnone">All off</button>` +
      `<button class="small-btn" id="cattab" title="Keep the summary table but draw no catalogue marks on the picture">📋 Table only</button>`;
    $("catchips").insertAdjacentElement("afterend", bar);
    $("catall").onclick = async () => { for (const c of CAT_LIST) if (!S.cats.has(c.key)) await toggleCat(c.key); };
    $("catnone").onclick = async () => { for (const c of CAT_LIST) if (S.cats.has(c.key)) await toggleCat(c.key); };
    $("cattab").onclick = () => { S.tableOnly = !S.tableOnly; S.showGaia = !S.tableOnly && S.cats.size > 0; refresh(); renderCatTable(); };
  }
  $("cattab").classList.toggle("on", S.tableOnly);
  $("cattab").textContent = S.tableOnly ? "📋 Table only: on (no marks)" : "📋 Table only";
  if (!S.R || S.R.preview || !S.cats.size || S.practice) { box.innerHTML = ""; return; }
  if (S.cats.has("gaia") && !S.gaia && !S.gaiaAsked) { S.gaiaAsked = posKey(); loadGaia().then(() => renderCatTable()); }
  const per = catObjects();
  const keys = catKeys();
  // one list without double counting: an object within 2.5″ of one already listed is the same object
  const all = [];
  for (const k of keys) for (const o of per[k] || []) {
    const hit = all.find((a) => Math.abs(a.e - o.e) < 2.5 && Math.abs(a.n - o.n) < 2.5 && Math.hypot(a.e - o.e, a.n - o.n) < 2.5);
    if (hit) { hit.moving = hit.moving || o.moving; if (o.kind && (!hit.kind || hit.kind === "star")) hit.kind = o.kind; hit.in.add(k); }
    else all.push({ ...o, in: new Set([k]) });
  }
  const kinds = [...new Set(all.map((a) => a.kind).filter((x) => x && x !== "star"))].sort();
  const cols = [];
  cols.push(["Catalogued objects", (L) => L.length]);
  if (all.some((a) => a.moving)) cols.push(["Clearly moving (over 0.2″ a year)", (L) => L.filter((a) => a.moving).length]);
  if (all.some((a) => a.kind === "star")) cols.push(["Named ordinary stars", (L) => L.filter((a) => a.kind === "star").length]);
  for (const t of kinds) cols.push([t.charAt(0).toUpperCase() + t.slice(1), (L) => L.filter((a) => a.kind === t).length]);
  const multi = all.filter((a) => a.in.size > 1).length;
  const row = (name, L, strong, col) => `<tr${strong ? ' style="font-weight:700"' : ""}><td>${col ? `<span style="color:${col}">●</span> ` : ""}${name}</td>` +
    cols.map(([, f]) => { const v = f(L); return `<td>${v || ""}</td>`; }).join("") + `</tr>`;
  const waiting = keys.filter((k) => !per[k]);
  box.innerHTML = `<div class="ctl-label">What the catalogues hold in this patch</div><div style="overflow-x:auto"><table class="xtable"><tr><th>Catalogue</th>` +
    cols.map(([n]) => `<th>${esc(n)}</th>`).join("") + `</tr>` +
    keys.filter((k) => per[k]).map((k) => row(CAT[k].short, per[k], false, CAT[k].colour)).join("") +
    (keys.filter((k) => per[k]).length > 1 ? row("All together (each object once)", all, true) : "") + `</table></div>` +
    `<p class="muted small-note">Only kinds that occur here get a column. Object types (brown dwarf, galaxy...) come from SIMBAD, so switch it on to see them. ` +
    (keys.length > 1 ? `Objects listed by more than one catalogue (${multi} here, matched within 2.5″) are counted once in the total. ` +
      `A fast object in an old catalogue without motions can sit far from its present place and be counted twice. ` : "") +
    (waiting.length ? `Still loading: ${waiting.map((k) => CAT[k].short).join(", ")}.` : "") + `</p>`;
}
const x0_renderCatChips = typeof renderCatChips === "function" ? renderCatChips : null;
if (x0_renderCatChips) renderCatChips = function () { x0_renderCatChips(); if (S.gaiaAsked && S.R && S.gaiaAsked !== posKey()) S.gaiaAsked = null; renderCatTable(); };

const x0_refreshX = refresh;
refresh = function () { x0_refreshX(); pairUI(); };
