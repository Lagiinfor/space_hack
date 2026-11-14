// Catalogues of known objects that the person switches on (one colour each), and the
// banner that says plainly what the computer's background scan found.
//
// "Known" and "unexplained" always mean: compared with the catalogues that are switched on.
// A catalogue is downloaded for a patch the first time it is switched on there, then kept.
// Loaded after game.js; wraps a few functions from app.js / tools.js / game.js.
"use strict";

const CAT_LIST = [
  // kept in step with spx/catalogs.py (the server's list fills in the rest)
  { key: "gaia", short: "Gaia", colour: "#4fd765" },
  { key: "catwise", short: "CatWISE", colour: "#ff9f43" },
  { key: "twomass", short: "2MASS", colour: "#ff6bd6" },
  { key: "panstarrs", short: "Pan-STARRS", colour: "#4cc9f0" },
  { key: "skymapper", short: "SkyMapper", colour: "#b8f04c" },
  { key: "simbad", short: "SIMBAD", colour: "#c9a0ff" },
];
const CAT = Object.fromEntries(CAT_LIST.map((c) => [c.key, c]));
// each catalogue marks a source with its own quarter of a ring, so one object known in
// several catalogues gets a ring of several colours
const CAT_ARC = { catwise: [-90, 0], twomass: [0, 90], panstarrs: [90, 180], skymapper: [180, 270] };
const CAT_FAINTEST = { panstarrs: 20, catwise: 16.8, skymapper: 19 };    // fainter sources are not drawn (SPHEREx cannot see them)

S.cats = new Set(["gaia"]);
try {
  const saved = JSON.parse(localStorage.getItem("cats") || "null");
  if (Array.isArray(saved)) S.cats = new Set(saved.filter((k) => CAT[k]));
} catch (e) { /* no saved choice */ }
S.catData = {}; S.catState = {};

const cat0_posQuery = posQuery;
const catKeys = () => CAT_LIST.map((c) => c.key).filter((k) => S.cats.has(k));
const catNames = (keys) => (keys || catKeys()).map((k) => (CAT[k] || { short: k }).short).join(", ") || "no catalogue";
// every request for this patch carries the catalogue choice, so all answers agree with it
posQuery = function () { return `${cat0_posQuery()}&cats=${catKeys().join(",")}`; };

fetch("/api/catalogs").then((r) => r.json()).then((L) => { for (const c of L) Object.assign(CAT[c.key] || {}, c); renderCatChips(); }).catch(() => {});

function renderCatChips() {
  const box = $("catchips");
  if (!box) return;
  box.innerHTML = CAT_LIST.map((c) => {
    const st = S.catState[c.key], d = S.catData[c.key];
    const n = c.key === "gaia" ? (S.gaia ? S.gaia.n : null) : d && d.pos === cat0_posQuery() ? d.n : null;
    const extra = st === "loading" ? " …" : n !== null && S.cats.has(c.key) ? ` ${n}` : "";
    return `<button class="chip cat ${S.cats.has(c.key) ? "on" : ""}" style="--cat:${c.colour}" onclick="toggleCat('${c.key}')" ` +
      `title="${esc((c.what || "") + (c.coverage ? " Coverage: " + c.coverage + "." : ""))}"><span class="catdot"></span>${c.short}${extra}</button>`;
  }).join("");
  const info = $("catinfo");
  const notes = [];
  for (const k of catKeys()) {
    const d = S.catData[k];
    if (S.catState[k] === "loading") notes.push(`Downloading ${CAT[k].short} for this patch (only the first time)...`);
    else if (typeof S.catState[k] === "string" && S.catState[k].startsWith("error")) notes.push(`${CAT[k].short}: ${S.catState[k].slice(6)}`);
    else if (d && d.pos === cat0_posQuery() && d.note) notes.push(d.note);
  }
  const old = catKeys().filter((k) => ["twomass", "panstarrs", "skymapper"].includes(k));
  if (old.length && S.showGaia) notes.push(`${catNames(old)}: marks show where each source was when that survey photographed it (no motions given).`);
  info.innerHTML = (catKeys().length ? `Known or unexplained is judged against: <b>${catNames()}</b>.` : `<b>No catalogue is switched on</b>, so nothing can be recognised as known.`) +
    (notes.length ? "<br>" + notes.map(esc).join("<br>") : "");
}

async function ensureCat(key) {
  if (key === "gaia" || !S.R || S.R.preview) return;
  const pos = cat0_posQuery();
  if (S.catData[key] && S.catData[key].pos === pos) return;
  S.catState[key] = "loading"; renderCatChips();
  try {
    const d = await api(`/api/catalog?${pos}&cat=${key}`);
    if (!S.R || pos !== cat0_posQuery()) return;
    d.pos = pos; S.catData[key] = d; S.catState[key] = "ok";
  } catch (e) {
    S.catState[key] = "error " + e.message;
  }
  renderCatChips(); draw();
}

function rescanWithCats() {
  if (!S.R || S.R.preview || S.practice) return;
  S.known = null;
  loadMovers(); loadPicks();
  if (S.click && !$("specpanel").classList.contains("hidden")) loadChecks(S.click);
  refresh();
}

async function toggleCat(key) {
  if (S.cats.has(key)) S.cats.delete(key);
  else { S.cats.add(key); S.showGaia = true; }
  try { localStorage.setItem("cats", JSON.stringify([...S.cats])); } catch (e) { /* private window */ }
  delete S.catState[key];
  renderCatChips();
  if (S.cats.has(key)) {
    if (key === "gaia") { if (S.R && !S.gaia) loadGaia(); }
    else await ensureCat(key);
  }
  rescanWithCats();
}

// ---------------------------------------------------------------------- drawing
function catFrameYear() {
  const f = S.mode === "flip" && S.view !== "stack" ? currentFrame() : null;
  return f && f.mjd ? 2000 + (f.mjd - 51544.5) / 365.25 : null;
}

function drawCatalogMarks(ctx, s) {
  const W = ctx.canvas.width, yr = catFrameYear();
  const labels = [];
  for (const key of catKeys()) {
    const d = S.catData[key];
    if (key === "gaia" || !d || d.pos !== cat0_posQuery()) continue;
    const col = CAT[key].colour;
    for (const o of d.sources) {
      if (CAT_FAINTEST[key] && o.mag > CAT_FAINTEST[key]) continue;
      const dt = o.moves && yr ? yr - d.mid_year : 0;
      const e = o.east + (o.ve || 0) * dt, n = o.north + (o.vn || 0) * dt;
      const [x, y] = skyToCanvas(e, n).map((v) => v * s);
      if (x < 0 || y < 0 || x > W || y > W) continue;
      const near = S.click && Math.hypot(e - S.click.east, n - S.click.north) < 7;
      if (key === "simbad") {
        const r = Math.max(4, s * 0.55);
        const path = () => { ctx.beginPath(); ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath(); };
        ctx.strokeStyle = "rgba(0,0,0,0.75)"; ctx.lineWidth = 4; path(); ctx.stroke();
        ctx.strokeStyle = col; ctx.lineWidth = 2; path(); ctx.stroke();
        if (!o.plain || near) {
          ctx.font = `600 ${Math.max(11, Math.round(W / 58))}px system-ui`;
          const t = o.name.replace(/^NAME /, "");
          ctx.lineWidth = 3; ctx.strokeStyle = "rgba(0,0,0,0.85)"; ctx.strokeText(t, x + r + 4, y + r + 10);
          ctx.fillStyle = col; ctx.fillText(t, x + r + 4, y + r + 10);
        }
      } else {
        const [a0, a1] = CAT_ARC[key].map((a) => a * Math.PI / 180);
        const r = s * 1.45, lw = o.moves ? 3 : 2;
        ctx.strokeStyle = "rgba(0,0,0,0.75)"; ctx.lineWidth = lw + 2;
        ctx.beginPath(); ctx.arc(x, y, r, a0, a1); ctx.stroke();
        ctx.strokeStyle = col; ctx.lineWidth = lw;
        ctx.beginPath(); ctx.arc(x, y, r, a0 + 0.06, a1 - 0.06); ctx.stroke();
      }
      if (near) labels.push([col, `${CAT[key].short}` + (o.type ? `: ${o.type}` : "") + (o.mag !== undefined ? ` ${o.band} ${o.mag}` : "") +
        (o.moves ? `, ${o.pm}″/yr` : o.old ? `, seen ${o.year}` : "")]);
    }
  }
  if (S.click && labels.length) {
    const [cx, cy] = skyToCanvas(S.click.east, S.click.north).map((v) => v * s);
    const r = 2 / S.R.pix_arcsec * 6.15 * s + Math.max(5, s * 0.5), fs = Math.max(12, Math.round(W / 48));
    ctx.font = `600 ${fs}px system-ui`;
    const tw = Math.max(...labels.map((l) => ctx.measureText(l[1]).width));
    let lx = cx + r + 6; if (lx + tw > W - 4) lx = cx - r - 6 - tw;
    labels.slice(0, 5).forEach(([col, t], i) => {
      const ly = Math.min(W - 6, Math.max(16, cy - r * 0.6 + (i + 1) * (fs + 4)));
      ctx.lineWidth = 4; ctx.strokeStyle = "rgba(0,0,0,0.85)"; ctx.strokeText(t, lx, ly);
      ctx.fillStyle = col; ctx.fillText(t, lx, ly);
    });
  }
}

const cat0_drawOverlays = drawOverlays;
drawOverlays = function (ctx, s) {
  const g = S.gaia;
  if (!S.cats.has("gaia")) S.gaia = null;         // Gaia switched off: no Gaia rings
  try { cat0_drawOverlays(ctx, s); } finally { S.gaia = g; }
  if (S.showGaia && S.R && !S.practice && !S.photoView) drawCatalogMarks(ctx, s);
};

const cat0_drawLegend = drawLegend;
drawLegend = function () {
  const g0 = S.gaia;
  if (!S.cats.has("gaia")) S.gaia = null;
  try { cat0_drawLegend(); } finally { S.gaia = g0; }
  const el = $("legend");
  const extra = catKeys().filter((k) => k !== "gaia" && S.catData[k] && S.catData[k].pos === cat0_posQuery());
  if (!S.showGaia || !extra.length || S.practice) return;
  const bits = extra.map((k) => `<span style="color:${CAT[k].colour}">${k === "simbad" ? "◇" : "◜"}</span> ${CAT[k].short}`).join(" &nbsp; ");
  if (el.classList.contains("hidden")) { el.classList.remove("hidden"); el.innerHTML = bits; }
  else el.innerHTML += " &nbsp; " + bits;
};

// ---------------------------------------------------------------------- the banner
function renderScanBanner() {
  const el = $("scanbanner");
  if (!el) return;
  if (!S.R || S.practice || S.R.follow || document.body.classList.contains("on-pick")) { el.className = "scanbanner hidden"; return; }
  if (S.R.preview) {
    el.className = "scanbanner busy";
    el.innerHTML = `<span class="mini-spin"></span><div>The computer's own scan of this patch starts as soon as all photos are in.</div>`;
    return;
  }
  if (!S.picks) {
    el.className = "scanbanner busy";
    el.innerHTML = `<span class="mini-spin"></span><div><b>The computer is still scanning this patch...</b> You can already look for yourself.</div>`;
    return;
  }
  if (S.picks.error) {
    el.className = "scanbanner busy";
    el.innerHTML = `<div>The computer's scan of this patch failed (${esc(S.picks.error)}). <button class="small-btn" onclick="loadPicks()">Try again</button></div>`;
    return;
  }
  const P = S.picks.picks || [];
  const mv = P.filter((p) => p.kind === "mover");
  const U = mv.filter((p) => p.status.startsWith("candidate")).length;
  const K = mv.filter((p) => p.status.startsWith("known"));
  const D = mv.length - U - K.length;
  const C = P.filter((p) => p.kind === "changed").length, R = P.filter((p) => p.kind === "red").length;
  const pl = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const checked = (S.picks.checked && S.picks.checked.length ? S.picks.checked.join(", ") : "no catalogue");
  const notes = (S.picks.notes || []).length ? `<div class="muted small-note">${S.picks.notes.map(esc).join(" ")}</div>` : "";
  const btn = `<button class="${S.showPicks ? "small-btn" : "primary"}" onclick="bannerShow()">${S.showPicks ? "Hide them" : "Show me where"}</button>`;
  if (!P.length) {
    el.className = "scanbanner none";
    el.innerHTML = `<div><b>The computer found no candidates in this patch under these conditions.</b> ` +
      `<span class="muted">It looked for steady movers (about 1.5″ per pass up to 12″ per year), clear brightness changes and unusually red objects. ` +
      `Fainter or faster things can still be here, so your eyes still count.</span>${notes}</div>`;
    return;
  }
  const found = [];
  if (U) found.push(`<b>${pl(U, "unexplained moving object", "unexplained moving objects")}</b>`);
  if (C) found.push(`<b>${pl(C, "brightness change", "brightness changes")}</b>`);
  if (R) found.push(`<b>${pl(R, "unusually red object", "unusually red objects")}</b>`);
  const knownIn = [...new Set(K.flatMap((p) => p.known_in || []))].join(" and ") || "a catalogue";
  const also = [];
  if (K.length) also.push(`${pl(K.length, "moving object", "moving objects")} that ${K.length === 1 ? "is" : "are"} already known in ${knownIn}`);
  if (D) also.push(`${pl(D, "doubtful mover", "doubtful movers")}`);
  if (found.length) {
    el.className = "scanbanner found";
    el.innerHTML = `<div>💡 The computer found ${found.join(", ").replace(/, ([^,]*)$/, " and $1")} in this patch` +
      (also.length ? `, plus ${also.join(" and ")}` : "") + `. ` +
      (U ? `<span class="muted">Unexplained means: not recognised in the catalogues checked (${esc(checked)}).</span>` : "") + `${notes}</div>${btn}`;
  } else {
    el.className = "scanbanner known";
    el.innerHTML = `<div>✔ The computer found ${also.join(" and ")} in this patch, and nothing unexplained. ` +
      `<span class="muted">Catalogues checked: ${esc(checked)}.</span>${notes}</div>${btn}`;
  }
}

function bannerShow() {
  togglePicks(!S.showPicks);
  if (S.showPicks) $("sky").scrollIntoView({ block: "center", behavior: "smooth" });
}

const cat0_renderPicks = renderPicks;
renderPicks = function () { cat0_renderPicks(); renderScanBanner(); renderCatChips(); };

const _afterFinalCats = afterFinal;
afterFinal = function () {
  S.catData = {}; S.catState = {};
  _afterFinalCats();
  renderCatChips();
  for (const k of catKeys()) ensureCat(k);
};

// ---------------------------------------------------------------------- wording of the checks
// An object is described by what it is known in. "Unexplained" is always relative to the
// catalogues that were checked, and says which.
checkLines = function (C) {
  const L = [];
  const g = C.gaia || {};
  const noMatch = [], notes = [];
  if (g.error) L.push(["warn", "The Gaia star catalogue could not be reached."]);
  else if (g.found) L.push(["known", `<b>Known in the Gaia star catalogue</b> (visible light): a star of brightness G=${g.g}, ${g.sep_arcsec}″ from where you clicked` +
    (g.distance_ly ? `, about ${g.distance_ly.toLocaleString()} light-years away` : "") + `, moving ${g.pm.toFixed(3)}″ per year.`]);
  else if (g.background_star) { noMatch.push("Gaia"); notes.push(`A Gaia star lies ${g.sep_arcsec}″ away, but it stands still while this object moves, so it is a different, background star.`); }
  else if (!g.off) noMatch.push("Gaia");

  for (const c of C.catalogs || []) {
    if (c.error) L.push(["warn", `The ${esc(c.name)} catalogue could not be reached.`]);
    else if (c.not_covered) notes.push(`${c.name} does not cover this part of the sky (it covers ${c.not_covered}).`);
    else if (c.found) L.push(["known", `<b>Known in the ${esc(c.name)} catalogue</b> (${esc(c.light)}): ${esc(c.source)}` +
      (c.mag !== undefined ? `, brightness ${c.band} = ${c.mag}` : "") +
      (c.how ? `, ${esc(c.how)}` : c.sep_arcsec !== null ? `, ${c.sep_arcsec}″ from where you clicked` : "") +
      (c.pm ? `; the catalogue says it moves ${c.pm}″ per year` : `; position from ${c.year}`) + `.`]);
    else { noMatch.push(c.name); if (c.too_old) notes.push(`${c.name} is too old to trace this fast object back to where it was then, so it cannot say either way.`); }
  }

  const sb = C.simbad || {};
  if (sb.objects && sb.objects.length) {
    const o = sb.objects[0];
    L.push(["known", `<b>It has a name:</b> ${esc(o.name)}, listed as a ${esc(o.type)}` + (o.sp_type ? ` (type ${esc(o.sp_type)})` : "") +
      ` in the SIMBAD database` + (o.found !== "here" ? `, found at the place it occupied in the year 2000` : "") + `.` +
      (sb.objects.length > 1 ? ` Also nearby: ${sb.objects.slice(1).map((x) => esc(x.name)).join(", ")}.` : "")]);
  } else if (sb.error) L.push(["warn", "The SIMBAD name database could not be reached."]);
  else noMatch.push("SIMBAD names");

  if (noMatch.length) L.push([L.some((l) => l[0] === "known") ? "info" : "new", `<b>Checked without a match:</b> ${noMatch.map(esc).join(", ")}.` +
    (noMatch.includes("Gaia") && !g.background_star ? ` (Gaia sees visible light, so cold or very faint objects are outside its reach.)` : "")]);
  for (const t of notes) L.push(["info", esc(t)]);

  const a = C.asteroids || {};
  if (a.hits && a.hits.length) L.push(["known", `<b>A known asteroid passed here:</b> ${a.hits.map((h) => `${esc(h.name)} on ${h.date} UTC (${h.sep_arcsec}″ away${h.seen ? ", visible in that photo" : ""})`).join("; ")}. Light seen only on that date is the asteroid.`]);
  else if (a.checked) L.push(["info", "No known asteroid or comet passed over this spot during the photos."]);
  else L.push(["info", "The asteroid check for this patch has not finished yet."]);

  const m = C.motion;
  if (m && (m.source === "mover search" || m.significant)) {
    const dir = (m.north > 0 ? "north" : "south") + "-" + (m.east > 0 ? "east" : "west");
    const st = m.status || "";
    L.push([st.startsWith("candidate") ? "new" : "info",
      `<b>It moves:</b> about ${m.rate.toFixed(1)}″ per year toward the ${dir}` +
      (st ? ` (${esc(st.replace(/^(known|candidate|suspect|unchecked): /, ""))})` : "") + "."]);
  } else L.push(["info", "No motion detected between the sky passes (within about 2.5″)."]);

  const p = C.partner || {};
  if (p.checked && p.partners && p.partners.length) {
    const x = p.partners[0];
    L.push(["info", `<b>It may have a partner:</b> a Gaia star (G=${x.g}) ${x.sep_arcsec}″ away moves the same way (${x.pm}″ per year, ` +
      `differing by only ${x.diff}″)` + (x.distance_ly ? `, ${x.distance_ly} light-years away` : "") + `. Two objects travelling together are usually a real pair.`]);
  } else if (p.checked) L.push(["info", `No partner found: no Gaia star within half a degree moves the same way.`]);

  if (C.reports_here && C.reports_here.length)
    L.push(["info", `Already reported on this computer by ${C.reports_here.map((r) => `${esc(r.by)} (${r.when})`).join(", ")}.`]);
  return L;
};

renderChecks = function (C) {
  const icon = { known: "✔", new: "★", info: "•", warn: "!" };
  const L = checkLines(C);
  const knownIn = [];
  if ((C.gaia || {}).found) knownIn.push("Gaia");
  for (const c of C.catalogs || []) if (c.found) knownIn.push(c.name);
  if (((C.simbad || {}).objects || []).length) knownIn.push("SIMBAD");
  if (((C.asteroids || {}).hits || []).length) knownIn.push("the list of known asteroids");
  const checked = [...(C.checked || []).filter((n) => n !== "SIMBAD"), "SIMBAD names", "known asteroids"].join(", ");
  const verdict = !knownIn.length
    ? `<div class="verdict new">★ Unexplained by what was checked (${esc(checked)}). That does not prove it is new: switch on more catalogues to check further. It is worth a report.</div>`
    : `<div class="verdict known">✔ Already known: listed in ${esc(knownIn.join(", ").replace(/, ([^,]*)$/, " and $1"))}. Knowing that is useful too: nothing lost by having looked.</div>`;
  return `<div class="ctl-label">Automatic checks</div>${verdict}<ul class="checks">` +
    L.map(([k, t]) => `<li class="${k}"><span>${icon[k]}</span><div>${t}</div></li>`).join("") + "</ul>";
};

// the "already known in this patch" list: add what the other switched-on catalogues hold
const cat0_knownHtml = knownHtml;
knownHtml = function (K) {
  let h = cat0_knownHtml(K);
  const L = [];
  for (const c of K.catalogs || []) {
    const col = (CAT[c.key] || {}).colour || "#fff";
    if (c.note) { L.push(`<li class="muted">${esc(c.note)}</li>`); continue; }
    L.push(`<li><span style="color:${col}">●</span> <b>${esc(c.name)}</b>: ${c.n} catalogued sources in this patch` +
      (c.movers.length ? `; it lists ${c.movers.length === 1 ? "one" : c.movers.length} as clearly moving: ` +
        c.movers.map((m) => `${esc(m.name)} (${m.pm}″ per year, ${m.east}″ E ${m.north}″ N of centre)`).join("; ") : "") + `.</li>`);
  }
  if (L.length) h += `<ul class="known">${L.join("")}</ul>`;
  return h;
};

renderCatChips();
