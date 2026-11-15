// Export of real data in its natural format. Loaded after extras.js.
//   pictures  -> FITS (with sky coordinates in the header; default) or PNG
//   tables    -> CSV (default) or JSON
"use strict";

// ---------------------------------------------------------------- the picture on screen, as numbers
function screenImage() {
  // the same numbers the picture on screen is drawn from (MJy/sr), row 0 = south, column 0 = east
  const R = S.R, n = R.size;
  if (S.mode !== "flip") return null;
  const f = currentFrame();
  if (!f || f.other) return null;
  const fs = blinkFrames();
  let data = f.arr, what = "photo", extra = "";
  if (S.view === "diff") { const ref = nanMean(fs.map((g) => g.arr), n * n); data = f.arr.map((v, i) => v - ref[i]); what = "difference"; extra = "this pass minus the average of the compared passes"; }
  else if (S.view === "first") { const ref = fs[0].arr; data = f.arr.map((v, i) => v - ref[i]); what = "difference"; extra = `this pass minus ${R.passes[fs[0].pass_index].label}`; }
  else if (S.view === "stack") { data = nanMean(fs.map((g) => g.arr), n * n); what = "stack"; extra = "average of the compared passes"; }
  return { data, n, f, what, extra, pass: S.view === "stack" ? "all passes" : R.passes[f.pass_index].label };
}

function fitsBytes(img) {
  const R = S.R, n = img.n, f = img.f;
  const card = (k, v, c) => {
    let val = typeof v === "string" ? `'${v.replace(/'/g, "''").padEnd(8)}'`.padEnd(20) : (typeof v === "boolean" ? (v ? "T" : "F") : String(v)).padStart(20);
    return (k.padEnd(8) + "= " + val + (c ? " / " + c : "")).padEnd(80).slice(0, 80);
  };
  const text = (k, t) => (k.padEnd(8) + t).padEnd(80).slice(0, 80);
  const band = f.combo ? `detectors ${f.combo.join("+")} averaged` : S.band === 0 ? "all detectors averaged" : `detector ${S.band}`;
  const cards = [
    card("SIMPLE", true, "standard FITS"), card("BITPIX", -32, "32-bit floating point"), card("NAXIS", 2), card("NAXIS1", n), card("NAXIS2", n),
    card("CTYPE1", "RA---TAN"), card("CTYPE2", "DEC--TAN"), card("CRVAL1", R.ra, "deg, ICRS"), card("CRVAL2", R.dec, "deg, ICRS"),
    card("CRPIX1", (n + 1) / 2), card("CRPIX2", (n + 1) / 2), card("CDELT1", -R.pix_arcsec / 3600, "deg/pixel (east is left)"), card("CDELT2", R.pix_arcsec / 3600, "deg/pixel (north is up)"),
    card("CUNIT1", "deg"), card("CUNIT2", "deg"), card("RADESYS", "ICRS"), card("BUNIT", "MJy/sr", "surface brightness"),
    card("TELESCOP", "SPHEREx"), card("ORIGIN", "SPHEREx Sky Flip-book"), card("IMGTYPE", img.what, "photo, difference or stack"),
    card("PASS", img.pass, "sky pass"), card("BAND", band.slice(0, 60)),
    card("WAVEMIN", Number((f.wl_min ?? 0.75).toFixed(4)), "micron"), card("WAVEMAX", Number((f.wl_max ?? 5.0).toFixed(4)), "micron"),
    card("NEXP", f.n ?? 0, "exposures stacked in this pass"),
    text("COMMENT", " Stack of NASA SPHEREx level-2 spectral images (NASA/IPAC IRSA), re-drawn on a"),
    text("COMMENT", " north-up grid at half a SPHEREx pixel. Zodiacal light and local sky removed."),
    text("COMMENT", " Every pass uses the same wavelength mix. Missing data are NaN."),
  ];
  if (img.extra) cards.push(text("COMMENT", " " + img.extra.slice(0, 70)));
  cards.push("END".padEnd(80));
  while (cards.length % 36) cards.push(" ".repeat(80));
  const head = new TextEncoder().encode(cards.join(""));
  const body = new ArrayBuffer(Math.ceil(n * n * 4 / 2880) * 2880), dv = new DataView(body);
  for (let i = 0; i < n * n; i++) dv.setFloat32(i * 4, img.data[i], false);     // FITS is big-endian
  const out = new Uint8Array(head.length + body.byteLength);
  out.set(head, 0); out.set(new Uint8Array(body), head.length);
  return out;
}

// ---------------------------------------------------------------- tables
const toCsv = (rows, note) => {
  if (!rows.length) return (note ? `# ${note}\n` : "") + "\n";
  const keys = Object.keys(rows[0]);
  const cell = (v) => (v === null || v === undefined ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  return (note ? `# ${note}\n` : "") + keys.join(",") + "\n" + rows.map((r) => keys.map((k) => cell(r[k])).join(",")).join("\n") + "\n";
};
const skyOf = (east, north) => {
  const dec = S.R.dec + north / 3600, ra = S.R.ra + east / 3600 / Math.cos(S.R.dec * Math.PI / 180);
  return [Number((((ra % 360) + 360) % 360).toFixed(6)), Number(dec.toFixed(6))];
};
function tableRows(kind) {
  if (kind === "spectrum") return [xAllPoints().map((q) => ({ wavelength_um: q.wl, flux_mJy: q.flux, flux_err_mJy: q.err, snr: q.snr, detector: q.band,
    pass: S.R.passes[q.pass_index]?.label, mjd: q.mjd, date_utc: xDate(q.mjd), observation_id: q.obs, saturated: q.sat ? 1 : 0, one_off_outlier: q.outlier ? 1 : 0,
    nasa_flags: (q.flags || []).join("; ") })), `SPHEREx aperture photometry at RA ${S.spec.ra.toFixed(6)} Dec ${S.spec.dec.toFixed(6)}; mJy in a 12.3 arcsec circle, local sky removed`];
  if (kind === "lightcurve") return [lightCurve().map((r) => ({ detector: r.band, wl_min_um: Number(r.wl_min.toFixed(3)), wl_max_um: Number(r.wl_max.toFixed(3)), pass: r.label,
    mjd: Number(r.mjd.toFixed(3)), date_utc: xDate(r.mjd), median_flux_mJy: r.flux, err_mJy: r.err, n_exposures: r.n })),
    `Brightness over time at RA ${S.spec.ra.toFixed(6)} Dec ${S.spec.dec.toFixed(6)}; median per detector and sky pass`];
  if (kind === "catalogues") {
    const rows = [];
    for (const k of catKeys()) {
      if (k === "gaia" && S.gaia) for (const st of S.gaia.stars) { const t = st.track[Math.floor(st.track.length / 2)], [ra, dec] = skyOf(t[0], t[1]);
        rows.push({ catalogue: "Gaia DR3", name: st.id ?? "", ra_deg: ra, dec_deg: dec, position_for: "date of the SPHEREx pictures", brightness: `G ${st.g}`, motion_arcsec_per_yr: Number((st.pm / 1000).toFixed(4)), type: "" }); }
      else if (S.catData[k] && S.catData[k].pos === posKey()) for (const o of S.catData[k].sources) { const [ra, dec] = skyOf(o.east, o.north);
        rows.push({ catalogue: CAT[k].name || CAT[k].short, name: o.name, ra_deg: ra, dec_deg: dec, position_for: o.old ? `year ${o.year} (no motion given)` : "date of the SPHEREx pictures",
          brightness: o.mag !== undefined ? `${o.band} ${o.mag}` : "", motion_arcsec_per_yr: o.moves ? o.pm : "", type: o.type || "" }); }
    }
    return [rows, `Catalogued objects inside the patch at RA ${S.R.ra} Dec ${S.R.dec}, field ${S.R.field_deg} deg`];
  }
  if (kind === "picks") return [((S.picks || {}).picks || []).map((p) => { const [ra, dec] = skyOf(p.east, p.north);
    return { kind: p.kind, title: p.title, ra_deg: ra, dec_deg: dec, rate_arcsec_per_yr: p.rate ?? "", status: p.status ?? "", why: p.why }; }),
    `Candidates found by the tool's own scan (hints, not confirmed discoveries); patch RA ${S.R.ra} Dec ${S.R.dec}`];
  if (kind === "detections") return [((S.picks || {}).detections || []).map((d) => { const [ra, dec] = skyOf(d.east, d.north); return { ra_deg: ra, dec_deg: dec, signal_over_noise: d.snr }; }),
    `Points of light the tool detected in the deepest SPHEREx picture (signal over 8x the noise); patch RA ${S.R.ra} Dec ${S.R.dec}`];
  if (kind === "photos") return [(S.R.exposures || []).filter((e) => e.obs_id).map((e) => ({ observation_id: e.obs_id, detector: e.band, pass: S.R.passes[e.pass_index]?.label, mjd: e.mjd, date_utc: xDate(e.mjd),
    wavelength_um: e.wl ?? e.wavelength ?? "", archive_file: (S.imgUrls || {})[`${e.obs_id}_${e.band}`] || "" })), `Every SPHEREx photo used for the patch at RA ${S.R.ra} Dec ${S.R.dec}`];
  return [[], ""];
}

const EXPORTS = [
  { key: "image", name: "Picture on screen", formats: ["fits", "png"], need: () => S.mode === "flip" && screenImage() },
  { key: "spectrum", name: "Spectrum of clicked object", formats: ["csv", "json"], need: () => S.spec },
  { key: "catalogues", name: "Catalogue objects", formats: ["csv", "json"], need: () => typeof catKeys === "function" && catKeys().length },
  { key: "picks", name: "Computer's candidates", formats: ["csv", "json"], need: () => S.picks && (S.picks.picks || []).length },
  { key: "photos", name: "List of photos used", formats: ["csv", "json"], need: () => S.R && (S.R.exposures || []).length },
];
const FORMAT_NAME = { fits: "FITS", png: "PNG", csv: "CSV", json: "JSON" };

function doExport() {
  const kind = $("exwhat").value, x = EXPORTS.find((e) => e.key === kind);
  const fmt = $("exfmt").value || x.formats[0];
  const tag = `${S.R.ra}_${S.R.dec}`;
  if (!x.need()) { $("exmsg").textContent = kind === "image" ? "Switch to the Motion tab on a SPHEREx pass first." : "Nothing to export yet: " + (kind === "spectrum" ? "click an object first." : kind === "catalogues" ? "switch on a catalogue first." : "wait for the scan to finish."); return; }
  if (kind === "image") {
    const img = screenImage();
    if (fmt === "png") { $("savepng").click(); $("exmsg").textContent = "Saved as PNG."; return; }
    xDownload(`spherex_${tag}_band${S.band}_${img.what}_${img.pass.replace(/\s+/g, "")}.fits`, fitsBytes(img), "application/fits");
    $("exmsg").textContent = "Saved as FITS: it opens in DS9, Aladin or astropy with the sky coordinates in place.";
    return;
  }
  const [rows, note] = tableRows(kind);
  if (fmt === "json") xDownload(`spherex_${kind}_${tag}.json`, JSON.stringify({ description: note, source: "NASA SPHEREx via NASA/IPAC IRSA; catalogues as named", rows }, null, 1), "application/json");
  else xDownload(`spherex_${kind}_${tag}.csv`, toCsv(rows, note));
  $("exmsg").textContent = `Saved ${rows.length} rows as ${fmt.toUpperCase()}.`;
}

(function wireExport() {
  const box = document.createElement("div");
  box.id = "exportbox";
  box.innerHTML = `<div class="ctl-label">Export data</div>` +
    `<div class="exrow"><select id="exwhat" title="What to export">` +
    EXPORTS.map((e) => `<option value="${e.key}">${e.name}</option>`).join("") + `</select>` +
    `<select id="exfmt" title="The first choice is the natural format for this kind of data"></select>` +
    `<button id="exgo" class="primary">⬇ Export</button></div><div class="muted small-note" id="exmsg"></div>`;
  $("share").parentElement.insertAdjacentElement("afterend", box);
  const fill = () => { const x = EXPORTS.find((e) => e.key === $("exwhat").value);
    $("exfmt").innerHTML = x.formats.map((f, i) => `<option value="${f}">${FORMAT_NAME[f]}${i === 0 ? " (default)" : ""}</option>`).join(""); $("exmsg").textContent = ""; };
  $("exwhat").onchange = fill; $("exgo").onclick = doExport; fill();
})();
