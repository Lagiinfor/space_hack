// "Spot the mover": a scored game on patches with known answers, a local leaderboard,
// an explorer count for real scanning, the confirmed-discoveries board, and the list of
// already-known objects under the computer's picks.
// Loaded last; replaces the simpler practice mode from tools.js.
"use strict";

const GAME_POOL = ["barnard", "epsindib", "wise0855", "luhman16", "kapteyn", "rwaur", "rdra", "m82", "barnard68"];
const today = () => new Date().toISOString().slice(0, 10);
const playerName = () => (localStorage.getItem("spx_name") || "").trim();

// small repeatable random-number maker, so the daily challenge is the same for everyone that day
function seeded(seedText) {
  let h = 2166136261;
  for (const c of seedText) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); }
  return () => { h += 0x6D2B79F5; let t = h; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

function startPractice(mode = "free") {
  const pool = S.tour.filter((t) => GAME_POOL.includes(t.key) && t.ra !== undefined);
  if (pool.length < 5) { $("error").textContent = "The game needs the saved tour targets."; return; }
  const rnd = mode === "daily" ? seeded("spot-the-mover-" + today()) : Math.random;
  const rounds = pool.map((t) => [rnd(), t]).sort((a, b) => a[0] - b[0]).slice(0, 5).map((x) => x[1]);
  S.practice = { mode, rounds, i: 0, score: 0, results: [], answered: false, t0: null };
  document.body.classList.add("practising");
  practiceRound();
}

async function practiceRound() {
  const P = S.practice, t = P.rounds[P.i];
  P.answered = false; P.t0 = null; S.gameReveal = null;
  S.tourKey = null; S.wantOther = false; S.showPicks = S.showMovers = false; S.showGaia = false; S.showAst = false;
  S.band = t.band; S.mode = "flip"; S.view = "normal"; $("view").value = "normal";
  $("practicepanel").classList.remove("hidden");
  $("practitle").textContent = `${P.mode === "daily" ? "Daily challenge" : "Spot the mover"} · round ${P.i + 1} of 5 · ${P.score.toLocaleString()} points`;
  $("practext").innerHTML = "Getting the patch ready...";
  $("pracbtns").innerHTML = `<button class="small-btn" id="pracstop">Quit game</button>`;
  $("pracstop").onclick = endPractice;
  S.movers = null; S.picks = null; S.R = null; S.click = null; S.spec = null;
  try { await load(t.ra, t.dec, 0.06, true); } catch (e) { fail(e.message); return; }
  // wait for the answer key (the computer's own search of this patch), then start the clock
  for (let k = 0; k < 120 && S.practice === P && !(S.R && !S.R.preview && S.picks && S.movers); k++) await new Promise((r) => setTimeout(r, 500));
  if (S.practice !== P) return;
  P.t0 = performance.now();
  $("practext").innerHTML = "<b>Did something here move or change brightness?</b> Click on it: the closer and the faster, the more points " +
    "(up to 1,000). If nothing real changed, say so. Tip: the <b>Changes only</b> view shows a mover as a red/blue pair.";
  $("pracbtns").innerHTML = `<button id="pracnone">Nothing real changed here</button><button class="small-btn" id="pracstop">Quit game</button>`;
  $("pracnone").onclick = () => practiceAnswer(null);
  $("pracstop").onclick = endPractice;
}

function practiceClick(e) {
  if (!S.practice) return false;
  if (S.practice.answered || !S.practice.t0) return true;
  const r = e.target.getBoundingClientRect(), n = S.R.size;
  practiceAnswer(canvasToSky((e.clientX - r.left) / r.width * n, (e.clientY - r.top) / r.height * n));
  return true;
}

function answerKey() {
  // where the real things are: every position of each mover, and each changed object
  const key = [];
  for (const p of (S.picks.picks || [])) {
    if (p.kind === "mover") for (const t of p.track) key.push({ east: t[0], north: t[1], pick: p });
    if (p.kind === "changed") key.push({ east: p.east, north: p.north, pick: p });
  }
  return key;
}

function practiceAnswer(sky) {
  const P = S.practice, t = P.rounds[P.i];
  if (!P || P.answered || !P.t0) return;
  P.answered = true;
  const secs = (performance.now() - P.t0) / 1000;
  const speed = Math.round(300 * Math.max(0, Math.min(1, 1 - (secs - 5) / 55)));
  const key = answerKey();
  let pts = 0, msg = "", truth = null, dist = null;
  if (key.length) {
    const what = key[0].pick.kind === "mover" ? `moves about ${key[0].pick.rate.toFixed(1)}″ per year` : "changed brightness between passes";
    if (sky) {
      let best = null;
      for (const k of key) { const d = Math.hypot(k.east - sky.east, k.north - sky.north); if (!best || d < best.d) best = { d, k }; }
      dist = best.d; truth = best.k;
      const acc = Math.round(700 * Math.max(0, 1 - Math.max(0, dist - 6) / 45));
      pts = acc + (acc > 300 ? speed : 0);
      msg = (acc >= 650 ? "<b>Spot on!</b>" : acc > 300 ? "<b>Close!</b>" : acc > 0 ? "<b>In the neighbourhood.</b>" : "<b>Not this time.</b>") +
        ` You were ${dist.toFixed(0)}″ from it. It is ${esc(t.name)}, which ${what}.`;
    } else {
      truth = key[0];
      msg = `<b>There was something.</b> ${esc(t.name)} ${what}. The marker shows where.`;
    }
  } else {
    if (!sky) { pts = 700 + speed; msg = `<b>Right: nothing real changed here.</b> This is ${esc(t.name)} (${esc(t.kind.toLowerCase())}).`; }
    else msg = `<b>A trick round: nothing real changed here.</b> This is ${esc(t.name)} (${esc(t.kind.toLowerCase())}). Small wobbles between frames are measuring noise.`;
  }
  P.score += pts;
  P.results.push({ key: t.key, pts, dist: dist === null ? null : Math.round(dist), secs: Math.round(secs) });
  S.gameReveal = { click: sky, truth };
  S.showPicks = S.showMovers = true; draw();
  const last = P.i + 1 >= P.rounds.length;
  $("practitle").textContent = `Round ${P.i + 1} of 5: +${pts.toLocaleString()} points · total ${P.score.toLocaleString()}`;
  $("practext").innerHTML = msg + ` <span class="muted">(${secs.toFixed(0)} s)</span><br><span class="muted">${esc(t.story.split(". ")[0])}.</span>`;
  $("pracbtns").innerHTML = `<button class="primary" id="pracnext">${last ? "See my score" : "Next round →"}</button><button class="small-btn" id="pracstop">Quit game</button>`;
  $("pracstop").onclick = endPractice;
  $("pracnext").onclick = () => { if (last) gameOver(); else { P.i++; practiceRound(); } };
}

function shareText(P) {
  const sq = P.results.map((r) => r.pts >= 800 ? "🟩" : r.pts >= 400 ? "🟨" : r.pts > 0 ? "🟧" : "⬛").join("");
  return `SPHEREx Spot the mover${P.mode === "daily" ? " · daily " + today() : ""}\n${sq}  ${P.score.toLocaleString()} / 5,000`;
}

async function gameOver() {
  const P = S.practice;
  S.gameReveal = null;
  $("practitle").textContent = `${P.score.toLocaleString()} of 5,000 points`;
  $("practext").innerHTML = `<div class="share">${esc(shareText(P)).replace(/\n/g, "<br>")}</div>` +
    (P.score >= 4000 ? "Outstanding. You are ready for real, unexplored sky." : P.score >= 2000 ? "Good hunting. These shifts are about one pixel, so every point is earned."
      : "This is genuinely hard: movers shift by about one pixel. The Changes-only view helps a lot.") +
    `<div class="row wrap" style="margin-top:8px"><input type="text" id="gamename" placeholder="Your name for the board" value="${esc(playerName())}"></div><div class="muted small-note" id="gamemsg"></div>`;
  $("pracbtns").innerHTML = `<button class="primary" id="gamesave">Save my score</button><button id="gameshare">Copy result</button>` +
    `<button id="gameagain">Play again</button><button id="gameboard">🏆 Board</button><button class="small-btn" id="pracstop">Back to the sky</button>`;
  $("pracstop").onclick = endPractice;
  $("gameagain").onclick = () => startPractice("free");
  $("gameboard").onclick = () => showBoard();
  $("gameshare").onclick = async () => { try { await navigator.clipboard.writeText(shareText(P)); $("gamemsg").textContent = "Result copied."; } catch { $("gamemsg").textContent = shareText(P); } };
  $("gamesave").onclick = async () => {
    const name = $("gamename").value.trim();
    if (!name) { $("gamemsg").textContent = "Type a name first."; return; }
    localStorage.setItem("spx_name", name);
    try {
      const r = await api("/api/score", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, score: P.score, mode: P.mode, day: today(), rounds: P.results }) });
      $("gamemsg").textContent = r.saved ? "Saved to the board on this computer." : r.why;
      $("gamesave").disabled = true;
    } catch (e) { $("gamemsg").textContent = "Could not save: " + e.message; }
  };
}

function endPractice() {
  S.practice = null; S.gameReveal = null;
  document.body.classList.remove("practising");
  $("practicepanel").classList.add("hidden");
  S.showAst = true;
  backToSky();
}

// reveal marker: where you clicked, where it really was
const _drawPicks = drawPicks;
drawPicks = function (ctx, s) {
  _drawPicks(ctx, s);
  const g = S.gameReveal;
  if (!g || !S.R) return;
  const pt = (p) => skyToCanvas(p.east, p.north).map((v) => v * s);
  if (g.truth) {
    const [x, y] = pt(g.truth);
    ctx.strokeStyle = "#4fd18b"; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(x, y, s * 5, 0, 2 * Math.PI); ctx.stroke();
    ctx.fillStyle = "#4fd18b"; ctx.font = `bold ${Math.round(ctx.canvas.width / 44)}px system-ui`;
    ctx.fillText("it was here", x + s * 5.5, y + s * 5);
  }
  if (g.click) {
    const [x, y] = pt(g.click);
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(x - 8, y - 8); ctx.lineTo(x + 8, y + 8); ctx.moveTo(x + 8, y - 8); ctx.lineTo(x - 8, y + 8); ctx.stroke();
    if (g.truth) { const [tx, ty] = pt(g.truth); ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(tx, ty); ctx.stroke(); ctx.setLineDash([]); }
  }
};

// ====================================================================== boards
async function showBoard() {
  const el = $("boardbox");
  el.classList.remove("hidden");
  el.innerHTML = `<div class="board"><p>Loading...</p></div>`;
  let B;
  try { B = await api("/api/board?day=" + today()); } catch (e) { el.innerHTML = `<div class="board"><p>${esc(e.message)}</p><button onclick="$('boardbox').classList.add('hidden')">Close</button></div>`; return; }
  const table = (rows, heads) => rows.length ? `<table><tr>${heads.map((h) => `<th>${h}</th>`).join("")}</tr>${rows.join("")}</table>` : `<p class="muted">Nobody yet. Be the first.</p>`;
  el.innerHTML = `<div class="board">
    <div class="row spread"><h2>🏆 Boards</h2><button onclick="$('boardbox').classList.add('hidden')">✕ Close</button></div>
    <p class="muted small-note">Kept on this computer for now. When the site goes online these become shared boards.</p>
    <h3>Spot the mover: all games</h3>
    ${table(B.players.map((p, i) => `<tr><td>${i + 1}</td><td>${esc(p.name)}</td><td>${esc(p.rank)}</td><td>${p.total.toLocaleString()}</td><td>${p.games}</td><td>${p.best.toLocaleString()}</td></tr>`), ["", "Player", "Rank", "Total points", "Games", "Best game"])}
    <p class="muted small-note">Ranks: ${B.ranks.map((r) => `${esc(r.name)} from ${r.points.toLocaleString()}`).join(" · ")}. Points only come from game rounds with a known answer.</p>
    <h3>Today's daily challenge (${today()})</h3>
    ${table(B.daily.map((p, i) => `<tr><td>${i + 1}</td><td>${esc(p.name)}</td><td>${p.score.toLocaleString()}</td></tr>`), ["", "Player", "Score"])}
    <h3>Explorers: real patches of sky looked at</h3>
    ${table(B.explorers.map((p, i) => `<tr><td>${i + 1}</td><td>${esc(p.name)}</td><td>${p.patches}</td></tr>`), ["", "Explorer", "Patches explored"])}
    <p class="muted small-note">Real searching is never scored as right or wrong: nobody knows the answer yet. Effort is what counts here.</p>
    <h3>Confirmed discoveries</h3>
    ${B.discoverers.length ? table(B.discoverers.map((p, i) => `<tr><td>${i + 1}</td><td>${esc(p.name)}</td><td>${p.points.toLocaleString()}</td><td>${p.finds}</td></tr>`), ["", "Discoverer", "Points", "Confirmed finds"])
      : `<p class="muted">No confirmed discoveries yet. Points are given only when astronomers confirm a report, and that has not happened yet.</p>`}
    <details><summary>Points for a confirmed discovery (rarer = more)</summary>
      <table>${B.points_table.map((r) => `<tr><td>${esc(r.label)}</td><td>${r.points.toLocaleString()}</td></tr>`).join("")}</table></details>
    <details><summary>Reports made on this computer (${B.reports.length})</summary>
      ${table(B.reports.map((r) => `<tr><td>${esc(r.when)}</td><td>${esc(r.name)}</td><td>RA ${(+r.ra).toFixed(4)}, Dec ${(+r.dec).toFixed(4)}</td><td>${esc(r.status)}</td><td>${r.points || "–"}</td></tr>`), ["Date", "By", "Where", "Status", "Points"])}
      <p class="muted small-note">Every report starts as "reported". It scores only once its status becomes "confirmed".</p></details>
  </div>`;
}

// ====================================================================== count real exploring
const _afterFinal = afterFinal;
afterFinal = function () {
  _afterFinal();
  if (!S.practice && !S.tourKey && S.R && !S.R.follow && playerName()) {
    fetch("/api/explored", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: playerName(), ra: S.R.ra, dec: S.R.dec }) }).catch(() => {});
  }
};

// ====================================================================== known objects under the picks
const _renderPicks = renderPicks;
renderPicks = function () {
  _renderPicks();
  const box = $("knownbox");
  if (!S.R || !S.showPicks || S.practice || S.R.preview || S.R.follow) { box.innerHTML = ""; return; }
  const key = posQuery();
  if (S.known && S.known.key === key) { box.innerHTML = knownHtml(S.known); return; }
  box.innerHTML = `<div class="ctl-label">Already known in this patch</div><div class="muted small-note">Looking up catalogues...</div>`;
  if (S.knownLoading === key) return;
  S.knownLoading = key;
  api(`/api/known?${key}`).then((K) => { K.key = key; S.known = K; if (posQuery() === key && S.showPicks) box.innerHTML = knownHtml(K); })
    .catch(() => { box.innerHTML = `<div class="muted small-note">The catalogues of known objects could not be reached just now.</div>`; })
    .finally(() => { S.knownLoading = null; });
};

function knownHtml(K) {
  const L = [];
  for (const s of K.fast_stars) L.push(`<li>⭐ <b>Known fast-moving star</b> (Gaia, brightness G=${s.g}): ${s.pm}″ per year, ${Math.round(s.east) + 0}″ E ${Math.round(s.north) + 0}″ N of centre.</li>`);
  for (const o of K.named) L.push(`<li>🏷 <b>${esc(o.name)}</b>: ${esc(o.type)}, ${o.east}″ E ${o.north}″ N of centre.</li>`);
  if (K.n_named > K.named.length) L.push(`<li class="muted">…and ${K.n_named - K.named.length} more named objects (mostly ordinary catalogued stars).</li>`);
  const caught = K.asteroids.filter((a) => a.caught), faint = K.asteroids.length - caught.length;
  for (const a of caught) L.push(`<li>☄ <b>Known asteroid ${esc(a.name)}</b>${a.neo ? " (near-Earth)" : ""}: SPHEREx caught it in ${a.caught} of ${a.photos} photos. See the Asteroids panel.</li>`);
  if (faint) L.push(`<li>☄ ${faint} known asteroid${faint > 1 ? "s" : ""} crossed this patch, too faint for SPHEREx to see. Its place and direction are marked on the picture (pale diamond, "☄ Asteroids" switched on).</li>`);
  if (K.n_gaia !== undefined) L.push(`<li class="muted">${K.n_gaia} ordinary stars here are in the Gaia catalogue (turn on "Catalogue marks" to see them).</li>`);
  for (const n of K.notes) L.push(`<li class="muted">${esc(n)}</li>`);
  return `<div class="ctl-label">Already known in this patch</div><ul class="known">${L.join("") || "<li class='muted'>Nothing notable is catalogued here.</li>"}</ul>` +
    `<div class="muted small-note">These are not discoveries: they are listed so you can tell known things from unexplained ones.</div>`;
}

$("practiceBtn").onclick = () => startPractice("free");
$("dailyBtn").onclick = () => startPractice("daily");
$("boardBtn").onclick = showBoard;
