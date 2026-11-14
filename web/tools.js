// Volunteer tools: "what is it?" label, automatic checks and report, single photos,
// computer's picks, practice mode, zoom / inverted colours, links to other sky viewers.
// Loaded after app.js and asteroids.js; uses their globals.
"use strict";

const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ====================================================================== object card
function afterSpectrum(sp, sky) {
  const w = sp.what;
  if (w) {
    $("whatis").classList.remove("hidden");
    $("whatis").innerHTML = `<b>${esc(w.label)}</b>` + (w.confidence !== "none" ? ` <span class="conf">(${esc(w.confidence)})</span>` : "") +
      (w.why && w.why.length ? `<details><summary>Why the tool thinks so</summary><ul>${w.why.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details>` : "");
  } else $("whatis").classList.add("hidden");
  setLinks(sky.ra, sky.dec);
  $("reportbox").classList.add("hidden");
  loadChecks(sky);
}

function setLinks(ra, dec) {
  const r = ra.toFixed(5), d = dec.toFixed(5);
  $("lnWise").href = `http://byw.tools/wiseview#ra=${r}&dec=${d}&size=176&band=3&speed=20&zoom=9`;
  $("lnLegacy").href = `https://www.legacysurvey.org/viewer?ra=${r}&dec=${d}&layer=unwise-neo7&zoom=14&mark=${r},${d}`;
  $("lnSimbad").href = `https://simbad.cfa.harvard.edu/simbad/sim-coo?Coord=${r}+${d >= 0 ? "%2B" : ""}${d}&Radius=30&Radius.unit=arcsec`;
  $("lnAladin").href = `https://aladin.cds.unistra.fr/AladinLite/?target=${r}%20${d >= 0 ? "%2B" : ""}${d}&fov=0.1&survey=P%2FallWISE%2Fcolor`;
}

async function loadChecks(sky) {
  const box = $("objchecks");
  box.innerHTML = `<div class="muted small-note">Running the automatic checks (star catalogues, known asteroids, motion)...</div>`;
  const ticket = (S.checkTicket = (S.checkTicket || 0) + 1);
  try {
    const C = await api(`/api/inspect?${posQuery()}&ra=${sky.ra}&dec=${sky.dec}`);
    if (ticket !== S.checkTicket) return;
    S.checks = C;
    box.innerHTML = renderChecks(C);
  } catch (e) {
    if (ticket === S.checkTicket) box.innerHTML = `<div class="muted small-note">The automatic checks could not run just now: ${esc(e.message)}</div>`;
  }
}

function checkLines(C) {
  const L = [];   // [mark, text]   mark: "known" | "new" | "info" | "warn"
  const g = C.gaia || {};
  if (g.error) L.push(["warn", "Gaia star catalogue could not be reached."]);
  else if (g.found) L.push(["known", `<b>Already in the Gaia star catalogue</b>: a star of brightness G=${g.g}, ${g.sep_arcsec}″ from where you clicked` +
    (g.distance_ly ? `, about ${g.distance_ly.toLocaleString()} light-years away` : "") + `, moving ${g.pm.toFixed(3)}″ per year.`]);
  else if (g.background_star) L.push(["new", `<b>Not in the Gaia catalogue.</b> There is a Gaia star ${g.sep_arcsec}″ away, but it stands still while this object moves, so it is a different, background star.`]);
  else L.push(["new", `<b>Not in the Gaia star catalogue</b>` + (g.nearest_arcsec ? ` (nearest Gaia star is ${g.nearest_arcsec}″ away).` : ".") + ` Gaia sees visible light, so cold or very faint objects are missing from it.`]);

  const sb = C.simbad || {};
  if (sb.objects && sb.objects.length) {
    const o = sb.objects[0];
    L.push(["known", `<b>It has a name:</b> ${esc(o.name)}, listed as a ${esc(o.type)}` + (o.sp_type ? ` (type ${esc(o.sp_type)})` : "") +
      ` in the SIMBAD database` + (o.found !== "here" ? `, found at the place it occupied in the year 2000` : "") + `.` +
      (sb.objects.length > 1 ? ` Also nearby: ${sb.objects.slice(1).map((x) => esc(x.name)).join(", ")}.` : "")]);
  } else if (sb.error) L.push(["warn", "The SIMBAD name database could not be reached."]);
  else L.push(["new", "<b>No named object here</b> in the SIMBAD database."]);

  const a = C.asteroids || {};
  if (a.hits && a.hits.length) L.push(["known", `<b>A known asteroid passed here:</b> ${a.hits.map((h) => `${esc(h.name)} on ${h.date} UTC (${h.sep_arcsec}″ away${h.seen ? ", visible in that photo" : ""})`).join("; ")}. Light seen only on that date is the asteroid.`]);
  else if (a.checked) L.push(["info", "No known asteroid or comet passed over this spot during the photos."]);
  else L.push(["info", "The asteroid check for this patch has not finished yet."]);

  const m = C.motion;
  if (m && (m.source === "mover search" || m.significant)) {
    const dir = (m.north > 0 ? "north" : "south") + "-" + (m.east > 0 ? "east" : "west");
    L.push([m.status && m.status.startsWith("candidate") ? "new" : "info",
      `<b>It moves:</b> about ${m.rate.toFixed(1)}″ per year toward the ${dir}` +
      (m.status ? ` (${m.status.startsWith("known") ? "Gaia predicts this motion" : m.status.startsWith("candidate") ? "no Gaia star explains this motion" : esc(m.status)})` : "") + "."]);
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
}

function renderChecks(C) {
  const icon = { known: "✔", new: "★", info: "•", warn: "!" };
  const L = checkLines(C);
  const isNew = !(C.gaia || {}).found && !((C.simbad || {}).objects || []).length && !((C.asteroids || {}).hits || []).length;
  const verdict = isNew
    ? `<div class="verdict new">★ Not found in the catalogues we checked. That does not prove it is new, but it is worth a report.</div>`
    : `<div class="verdict known">✔ This object is already known. Knowing that is useful too: nothing lost by having looked.</div>`;
  return `<div class="ctl-label">Automatic checks</div>${verdict}<ul class="checks">` +
    L.map(([k, t]) => `<li class="${k}"><span>${icon[k]}</span><div>${t}</div></li>`).join("") + "</ul>";
}

// ---------------------------------------------------------------------- report
function reportText(name, note) {
  const C = S.checks || {}, sp = S.spec || {}, w = sp.what || {};
  const strip = (h) => h.replace(/<[^>]+>/g, "");
  return [
    "SPHEREx Sky Flip-book: object report",
    `Reported by: ${name || "(no name given)"}`,
    `Date of report: ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC`,
    "",
    `Position: RA ${S.click.ra.toFixed(5)} deg, Dec ${S.click.dec.toFixed(5)} deg (ICRS, about epoch ${C.epoch ?? "2026"})`,
    `Patch: centre RA ${S.R.ra} Dec ${S.R.dec}, ${(S.R.field_deg * 60).toFixed(1)} arcmin, ${S.R.n_used} SPHEREx photos in ${S.R.passes.length} sky passes (${S.R.passes.map((p) => p.label).join(", ")})`,
    `Link (works where the tool is running): ${location.origin}/?ra=${S.R.ra}&dec=${S.R.dec}&field=${S.R.field_deg}&band=${S.band}`,
    "",
    `What it looks like from its spectrum: ${w.label || "not classified"}${w.confidence && w.confidence !== "none" ? ` (${w.confidence})` : ""}`,
    "",
    "Automatic checks:",
    ...checkLines(C).map(([k, t]) => " - " + strip(t)),
    "",
    "Reporter's note:",
    note || "(none)",
    "",
    "Checks made with: ESA Gaia DR3, SIMBAD (CDS), IMCCE SkyBoT, NASA/IPAC IRSA SPHEREx archive.",
  ].join("\n");
}

function openReport() {
  if (!S.click) return;
  const saved = localStorage.getItem("spx_name") || "";
  const box = $("reportbox");
  box.classList.remove("hidden");
  box.innerHTML = `<div class="ctl-label">Report this object</div>
    <p class="muted small-note">A report is just a note saying "someone should look at this". Mistakes are fine: most reports
      turn out to be known objects or camera glitches, and every one still helps. Your name goes on the report so you get the credit.</p>
    <div class="row wrap"><input type="text" id="repname" placeholder="Your name (for credit)" value="${esc(saved)}"></div>
    <textarea id="repnote" rows="3" placeholder="What caught your eye? (optional)"></textarea>
    <div class="row wrap"><button class="primary" id="repsave">Save report</button><button id="repcopy">Copy as text</button>
      <button id="repclose">Cancel</button><span class="muted small-note" id="repmsg"></span></div>`;
  $("repclose").onclick = () => box.classList.add("hidden");
  $("repcopy").onclick = async () => {
    try { await navigator.clipboard.writeText(reportText($("repname").value.trim(), $("repnote").value.trim())); $("repmsg").textContent = "Copied. Paste it into an email or message."; }
    catch { $("repmsg").textContent = "Could not copy; use Save report instead."; }
  };
  $("repsave").onclick = async () => {
    const name = $("repname").value.trim(), note = $("repnote").value.trim();
    localStorage.setItem("spx_name", name);
    const text = reportText(name, note);
    try {
      const r = await fetch("/api/report", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, note, ra: S.click.ra, dec: S.click.dec, patch: { ra: S.R.ra, dec: S.R.dec, field: S.R.field_deg },
          what: (S.spec || {}).what, checks: S.checks, text }) });
      const j = await r.json();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
      a.download = `spherex_report_${S.click.ra.toFixed(4)}_${S.click.dec.toFixed(4)}.txt`; a.click();
      $("repmsg").innerHTML = `Saved${name ? ", thank you " + esc(name) : ""}! A copy is in your Downloads folder and in the tool's <code>reports</code> folder (${esc(j.file)}).`;
    } catch (e) { $("repmsg").textContent = "Could not save: " + e.message; }
  };
}

// ---------------------------------------------------------------------- single photos behind a spot
async function playPhotosHere() {
  if (!S.R || !S.click) return;
  play(false);
  const k = (S.mode === "flip" && currentPass() !== null) ? currentPass() : S.R.passes.length - 1;
  let ex = S.R.exposures.filter((e) => e.pass_index === k && (S.band === 0 || e.band === S.band) && e.obs_id).sort((a, b) => a.mjd - b.mjd);
  if (ex.length > 16) ex = Array.from({ length: 16 }, (_, i) => ex[Math.round(i * (ex.length - 1) / 15)]);
  if (!ex.length) { $("hover").textContent = "No single photos available for this frame."; return; }
  $("hover").textContent = `Loading ${ex.length} single photos from ${S.R.passes[k].label}...`;
  const seq = { obj: { name: "the spot you clicked" }, list: ex, idx: 0, frames: [] };
  for (const e of ex) {
    try {
      const P = await api(`/api/photo?${posQuery()}&obs_id=${encodeURIComponent(e.obs_id)}&detector=${e.band}`);
      P.arr = unpack(P.pixels); seq.frames.push(P);
    } catch { /* skip */ }
  }
  if (!seq.frames.length) return;
  S.photoSeq = seq; S.photoView = seq.frames[0];
  $("photoexit").classList.remove("hidden");
  $("hover").textContent = `Single photos from ${S.R.passes[k].label}, one after another. A real object shows up in (nearly) every photo; ` +
    `a flash in just one photo is a camera glitch or a fast asteroid.`;
  const tick = () => {
    if (!S.photoView || S.photoSeq !== seq) return;
    seq.idx = (seq.idx + 1) % seq.frames.length; S.photoView = seq.frames[seq.idx]; draw();
    S.photoTimer = setTimeout(tick, 800);
  };
  draw(); clearTimeout(S.photoTimer); S.photoTimer = setTimeout(tick, 800);
}

// ====================================================================== computer's picks
const PICK_COLORS = { mover: "#ff7b72", changed: "#d2a8ff", red: "#ffa657" };

async function loadPicks() {
  S.picks = null; S.quick = null;
  renderPicks();
  const forPos = posQuery();
  try {
    const P = await api(`/api/picks?${forPos}`);
    if (!S.R || forPos !== posQuery()) return;
    S.picks = P;
  } catch (e) { S.picks = { picks: [], error: e.message }; }
  renderPicks(); draw();
}

function togglePicks(on) {
  S.showPicks = on ?? !S.showPicks;
  S.showMovers = S.showPicks;
  if (!S.showPicks) S.quick = null;
  renderPicks(); refresh();
}

function renderPicks() {
  if (!S.R) return;
  const el = $("moverlist"), q = $("pickquick");
  $("moverpanel").classList.toggle("hidden", !!S.practice);
  q.classList.add("hidden");
  if (S.R.preview) { el.textContent = "The computer's own search runs as soon as all photos are in."; return; }
  if (!S.picks) { el.textContent = "The computer is searching this patch in the background..."; return; }
  if (!S.showPicks) {
    el.innerHTML = `<p style="margin:0 0 8px">Look for yourself first: play the flip-book and see what catches your eye. ` +
      `When you are ready, compare with what the computer found.</p>` +
      `<button class="primary" onclick="togglePicks(true)">💡 Show the computer's picks</button>`;
    return;
  }
  const P = S.picks.picks || [];
  if (S.picks.error) { el.textContent = "The computer's search failed: " + S.picks.error; return; }
  if (!P.length) {
    el.innerHTML = "The computer found nothing unusual here: nothing moving steadily (between about 1.5″ per pass and 12″ per year), " +
      "no clear brightness change, nothing unusually red. Fainter or much faster things could still be hiding, so your eyes still count. " +
      `<div style="margin-top:8px"><button class="small-btn" onclick="togglePicks(false)">Hide</button></div>`;
    return;
  }
  el.innerHTML = `<ol class="picks">` + P.map((p, i) =>
    `<li><span class="pk" style="background:${PICK_COLORS[p.kind]}">${p.n}</span><div><b>${esc(p.title)}</b> ` +
    `<span class="muted">${Math.round(p.east) + 0}″ E, ${Math.round(p.north) + 0}″ N of centre</span><br>${esc(p.why)} ` +
    `<button class="small-btn" onclick="lookAtPick(${i})">Look</button></div></li>`).join("") + `</ol>` +
    `<div class="row wrap"><button class="small-btn" onclick="startQuick()">Go through them one by one</button>` +
    `<button class="small-btn" onclick="togglePicks(false)">Hide the picks</button></div>`;
  if (S.quick) renderQuick();
}

function drawPicks(ctx, s) {
  if (!S.showPicks || !S.picks || S.practice || !S.R || S.photoView) return;
  const W = ctx.canvas.width;
  for (const p of S.picks.picks || []) {
    if (p.kind === "mover") continue;                 // movers are drawn as arrows already
    const [x, y] = skyToCanvas(p.east, p.north).map((v) => v * s);
    const r = s * 4;
    ctx.strokeStyle = PICK_COLORS[p.kind]; ctx.lineWidth = 2; ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = PICK_COLORS[p.kind]; ctx.font = `bold ${Math.round(W / 46)}px system-ui`;
    ctx.fillText(`${p.n} ${p.title}`, x + r + 3, y - r + 2);
  }
  if (S.quick) {
    const p = S.picks.picks[S.quick.i];
    if (p) {
      const [x, y] = skyToCanvas(p.east, p.north).map((v) => v * s);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(x, y, s * 6.5, 0, 2 * Math.PI); ctx.stroke();
    }
  }
}

function pickSky(p) {
  const dec = S.R.dec + p.north / 3600, ra = S.R.ra + p.east / 3600 / Math.cos(S.R.dec * Math.PI / 180);
  return { ra: ((ra % 360) + 360) % 360, dec, east: p.east, north: p.north };
}

async function lookAtPick(i) {
  const p = S.picks.picks[i];
  if (!p) return;
  // for a mover, look where it is in the frame on screen
  let tgt = p;
  if (p.kind === "mover" && p.track) {
    const k = currentPass();
    const t = p.track[Math.min(k ?? p.track.length - 1, p.track.length - 1)];
    tgt = { east: t[0], north: t[1] };
  }
  const sky = pickSky(tgt);
  S.click = sky; setZoomOrigin(); draw();
  $("specpanel").classList.remove("hidden"); setStep(3);
  $("specinfo").textContent = "Measuring this pick in every photo...";
  try {
    const ticket = (S.specTicket = (S.specTicket || 0) + 1);
    const sp = await api(`/api/spectrum?${posQuery()}&ra=${sky.ra}&dec=${sky.dec}`);
    if (ticket !== S.specTicket) return;
    S.spec = sp; plotSpectrum(); draw(); afterSpectrum(sp, sky);
    $("specpanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) { $("specinfo").textContent = "Could not measure here: " + e.message; }
}

function startQuick() { S.quick = { i: 0, yes: [], no: 0 }; renderQuick(); draw(); }
function renderQuick() {
  const q = $("pickquick"), P = S.picks.picks;
  q.classList.remove("hidden");
  if (S.quick.i >= P.length) {
    q.innerHTML = `<div class="quick"><b>Done.</b> You marked ${S.quick.yes.length} of ${P.length} as interesting. ` +
      (S.quick.yes.length ? `Click <b>Look</b> on one above to inspect or report it.` : `Nothing stood out, which is a normal result.`) +
      ` <button class="small-btn" onclick="S.quick=null;renderPicks();draw()">Close</button></div>`;
    return;
  }
  const p = P[S.quick.i];
  q.innerHTML = `<div class="quick"><div class="muted small-note">One by one: ${S.quick.i + 1} of ${P.length} (white circle on the picture)</div>` +
    `<b>${esc(p.title)}</b>: ${esc(p.why)}<div class="row wrap" style="margin-top:8px">` +
    `<button class="primary" onclick="quickAnswer(true)">Interesting (y)</button><button onclick="quickAnswer(false)">Nothing special (n)</button>` +
    `<button class="small-btn" onclick="lookAtPick(${S.quick.i})">Inspect it</button></div></div>`;
}
function quickAnswer(yes) {
  if (!S.quick) return;
  if (yes) S.quick.yes.push(S.quick.i); else S.quick.no++;
  S.quick.i++; renderQuick(); draw();
}

// ====================================================================== practice mode
const PRACTICE_KEYS = ["barnard", "epsindib", "wise0855", "luhman16", "kapteyn", "rwaur", "m82", "barnard68", "rdra"];

function startPractice() {
  const pool = S.tour.filter((t) => PRACTICE_KEYS.includes(t.key) && t.ra !== undefined);
  if (pool.length < 3) { $("error").textContent = "Practice needs the saved tour targets."; return; }
  const rounds = pool.map((t) => [Math.random(), t]).sort((a, b) => a[0] - b[0]).slice(0, 5).map((x) => x[1]);
  S.practice = { rounds, i: 0, score: 0, answered: false };
  document.body.classList.add("practising");
  practiceRound();
}

async function practiceRound() {
  const P = S.practice, t = P.rounds[P.i];
  P.answered = false;
  S.tourKey = null; S.wantOther = false; S.showPicks = S.showMovers = false; S.showGaia = false; S.showAst = false;
  S.band = t.band; S.mode = "flip"; S.view = "normal"; $("view").value = "normal";
  $("practicepanel").classList.remove("hidden");
  $("practitle").textContent = `Round ${P.i + 1} of ${P.rounds.length}`;
  $("practext").innerHTML = "Watch the flip-book. <b>Is anything moving from frame to frame?</b> Click on it. " +
    "If nothing moves, press the button. Tip: try <b>Changes only</b>, where a mover shows as a red/blue pair.";
  $("pracbtns").innerHTML = `<button id="pracnone">Nothing moves here</button><button class="small-btn" id="pracstop">Stop practice</button>`;
  $("pracnone").onclick = () => practiceAnswer(null);
  $("pracstop").onclick = endPractice;
  S.movers = null; S.R = null; S.click = null; S.spec = null;      // forget the previous patch's answers
  try { await load(t.ra, t.dec, 0.06, true); } catch (e) { fail(e.message); }
  $("wherenow").textContent = "Mystery patch";
}

function practiceClick(e) {
  if (!S.practice) return false;
  if (S.practice.answered || !S.R || S.R.preview) return true;
  const r = e.target.getBoundingClientRect(), n = S.R.size;
  const sky = canvasToSky((e.clientX - r.left) / r.width * n, (e.clientY - r.top) / r.height * n);
  practiceAnswer(sky);
  return true;
}

function practiceAnswer(sky) {
  const P = S.practice, t = P.rounds[P.i];
  if (P.answered) return;
  if (!S.movers) { $("practext").textContent = "One moment, the answer for this patch is still being worked out..."; return; }
  P.answered = true;
  const movers = S.movers.movers || [];
  let ok = false, msg = "";
  if (movers.length) {
    const hit = sky && movers.some((m) => m.track.some((p) => Math.hypot(p[0] - sky.east, p[1] - sky.north) < 18));
    ok = !!hit;
    const m = movers[0];
    msg = ok ? `<b>Yes, well spotted!</b> That is ${esc(t.name)}, moving about ${m.rate.toFixed(1)}″ per year.`
      : sky ? `<b>Not that one.</b> The mover is marked with the arrow now: ${esc(t.name)}, about ${m.rate.toFixed(1)}″ per year. It is a subtle shift, about one SPHEREx pixel a year, so this is hard at first.`
        : `<b>There was one.</b> See the arrow: ${esc(t.name)} moves about ${m.rate.toFixed(1)}″ per year. Small shifts are easy to miss; "Changes only" helps.`;
  } else {
    ok = !sky;
    msg = ok ? `<b>Correct, nothing moves here.</b> This is ${esc(t.name)} (${esc(t.kind.toLowerCase())}): it changes in other ways, not by moving.`
      : `<b>Nothing actually moves here.</b> This is ${esc(t.name)} (${esc(t.kind.toLowerCase())}). Looking closely was still the right instinct; small wobbles between frames are measuring noise.`;
  }
  if (ok) P.score++;
  S.showPicks = S.showMovers = true; draw();
  $("practext").innerHTML = msg + `<br><span class="muted">${esc(t.story)}</span>`;
  const last = P.i + 1 >= P.rounds.length;
  $("pracbtns").innerHTML = `<button class="primary" id="pracnext">${last ? "See my score" : "Next round →"}</button><button class="small-btn" id="pracstop">Stop practice</button>`;
  $("pracstop").onclick = endPractice;
  $("pracnext").onclick = () => {
    if (!last) { P.i++; practiceRound(); return; }
    $("practitle").textContent = `You got ${P.score} of ${P.rounds.length}`;
    $("practext").innerHTML = (P.score >= 4 ? "Excellent: you are ready to explore real, unexplored patches." :
      P.score >= 2 ? "Good start. These shifts are tiny, and everyone misses some at first." :
        "This is genuinely hard: the movers shift by about one pixel. Try again with 'Changes only' switched on.") +
      " Mistakes are part of it; a second pair of eyes is exactly what the sky needs.";
    $("pracbtns").innerHTML = `<button class="primary" id="pracagain">Practice again</button><button id="pracstop">Back to the sky</button>`;
    $("pracagain").onclick = startPractice;
    $("pracstop").onclick = endPractice;
  };
}

function endPractice() {
  S.practice = null;
  document.body.classList.remove("practising");
  $("practicepanel").classList.add("hidden");
  S.showAst = true;
  backToSky();
}

// ====================================================================== follow a moving object
function followSetup() {
  const F = S.R.follow;
  const O = { frames: (F.other || []).map((f) => ({ ...f, arr: unpack(f.pixels), other: true })), neossat: F.neossat };
  S.other = O;
  S.showOther = O.frames.length > 0;
  $("otherBtn").disabled = !O.frames.length;
  for (const id of ["moverpanel", "astpanel", "specpanel"]) $(id).classList.add("hidden");
  $("summary").textContent = F.note + ` ${S.R.n_used} SPHEREx photos contain it in this window. ` +
    "The centre mark is where the object should be; a real detection is a dot exactly there, in more than one frame.";
  $("otherinfo").innerHTML = O.frames.length
    ? `🇨🇦 <b>Canada's NEOSSat followed ${esc(F.name)} too</b>: ${O.frames.map((f) => `${f.date_text} (${f.n} photos, centre ${f.snr}× the noise)`).join(", ")}. Dashed buttons in the timeline.`
    : (F.neossat && F.neossat.n_images ? "Canada's NEOSSat also photographed it, but those photos could not be lined up." : "");
  $("hover").textContent = `Following ${F.name}: the dot at the centre mark is the object; stars have slid away.`;
  refresh();
}

// ====================================================================== view controls
S.zoom = 1;
function setZoomOrigin() {
  const cv = $("sky");
  if (S.zoom === 1) { cv.style.transform = ""; return; }
  let ox = 50, oy = 50;
  if (S.click && S.R) {
    const [x, y] = skyToCanvas(S.click.east, S.click.north);
    ox = Math.max(0, Math.min(100, x / S.R.size * 100)); oy = Math.max(0, Math.min(100, y / S.R.size * 100));
  }
  cv.style.transformOrigin = `${ox}% ${oy}%`;
  cv.style.transform = `scale(${S.zoom})`;
}
function setZoom(z) {
  S.zoom = Math.max(1, Math.min(4, z));
  $("zoomtxt").textContent = `Zoom ×${S.zoom}`;
  setZoomOrigin();
}

// ====================================================================== wiring
$("objphotos").onclick = playPhotosHere;
$("objreport").onclick = openReport;
$("zoomin").onclick = () => setZoom(S.zoom + 1);
$("zoomout").onclick = () => setZoom(S.zoom - 1);
$("invertBtn").onclick = () => { S.invert = !S.invert; $("invertBtn").classList.toggle("on", S.invert); draw(); };
$("tameBtn").onclick = () => { S.tame = !S.tame; $("tameBtn").classList.toggle("on", S.tame); draw(); };
$("practiceBtn").onclick = startPractice;
$("sky").addEventListener("click", () => setTimeout(setZoomOrigin, 0));

document.addEventListener("keydown", (e) => {
  if (!S.R || !document.body.classList.contains("on-explore")) return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
  if (e.key === "i") $("invertBtn").click();
  if (e.key === "+" || e.key === "=") setZoom(S.zoom + 1);
  if (e.key === "-") setZoom(S.zoom - 1);
  if (e.key === "p" && !S.practice) togglePicks();
  if (e.key === "s" && S.click) playPhotosHere();
  if (e.key === "r" && S.click) openReport();
  if (e.key === "Escape") { if (S.photoView) exitPhotoView(); else setZoom(1); }
  if (S.quick && e.key === "y") quickAnswer(true);
  if (S.quick && e.key === "n") quickAnswer(false);
});
