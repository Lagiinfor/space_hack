// Every optional feature starts switched off: a patch opens as the plain flip-book with its
// play controls, and the person switches on what they want. Their choices are remembered on
// this computer, and a shared link that names a feature (?scan=1&ast=1&other=1&cross=1, as
// well as cats=..., gaia=1) switches it on.
//   scan  = the computer's notice and picks panel      ("💡 Computer's picks")
//   ast   = known asteroids: marks, panel and the check itself ("☄ Asteroids")
//   other = older photos from other telescopes          ("Older photos")
//   cross = the centre mark
// Catalogues, catalogue marks, combining colours and the rest were already off by default.
// Loaded after export.js.
"use strict";

const FEAT_KEY = "features.v1";
const F_SAVED = (() => { try { return JSON.parse(localStorage.getItem(FEAT_KEY) || "{}") || {}; } catch (e) { return {}; } })();
const F_LINK = new URLSearchParams(location.search);
const featWant = (k) => (F_LINK.has(k) ? F_LINK.get(k) === "1" : !!F_SAVED[k]);

S.scanOn = featWant("scan");
S.showAst = featWant("ast");
S.otherPref = featWant("other");
S.cross = featWant("cross");
function saveFeat() {
  try { localStorage.setItem(FEAT_KEY, JSON.stringify({ scan: S.scanOn, ast: S.showAst, other: S.otherPref, cross: S.cross })); } catch (e) { /* private window */ }
}
$("astBtn").classList.toggle("on", S.showAst);
$("cross").classList.toggle("on", S.cross);

// ---- the computer's notice and picks: only when asked for
const f0_renderScanBanner = renderScanBanner;
renderScanBanner = function () {
  if (!S.scanOn) { const el = $("scanbanner"); if (el) el.className = "scanbanner hidden"; return; }
  f0_renderScanBanner();
};
const f0_renderPicks = renderPicks;
renderPicks = function () {
  f0_renderPicks();
  if (!S.scanOn) $("moverpanel").classList.add("hidden");
  $("moversBtn").classList.toggle("on", S.scanOn);
};
$("moversBtn").title = "Switch the computer's own scan on or off: a notice above the picture says what it found, and a panel lists it (key: p)";
$("moversBtn").onclick = () => {
  S.scanOn = !S.scanOn;
  if (!S.scanOn && S.showPicks) togglePicks(false);
  saveFeat();
  if (S.R) { renderPicks(); updateURL(); }
};

// ---- known asteroids: marks, panel and the check itself only when switched on
const f0_loadAsteroids = loadAsteroids;
loadAsteroids = function () {
  if (!S.showAst) { $("astpanel").classList.add("hidden"); return; }
  return f0_loadAsteroids();
};
const f0_astSummary = astSummary;
astSummary = function () { return S.showAst ? f0_astSummary() : { pending: false, caught: [], faint: 0 }; };
$("astBtn").onclick = () => {
  S.showAst = !S.showAst;
  $("astBtn").classList.toggle("on", S.showAst);
  saveFeat();
  if (!S.R) return;
  if (S.showAst && !S.R.preview && !S.R.follow && !S.ast) loadAsteroids();
  else $("astpanel").classList.toggle("hidden", !S.showAst);
  draw(); renderPicks(); updateURL();
};

// ---- older photos and the centre mark: remembered
$("otherBtn").addEventListener("click", () => { S.otherPref = !!S.showOther; saveFeat(); if (S.R) updateURL(); });
$("cross").addEventListener("click", () => { saveFeat(); if (S.R) updateURL(); });

const f0_afterFinal = afterFinal;
afterFinal = function () {
  if (S.otherPref) S.wantOther = true;        // the person asked for older photos before
  f0_afterFinal();
  if (!S.showAst) $("astpanel").classList.add("hidden");
};

// ---- showcase targets open plain too (no picks shown, no older photos unless the person chose them)
const f0_startTour = startTour;
startTour = function (t) {
  const p = f0_startTour(t);
  S.showPicks = S.showMovers = false;
  S.wantOther = S.otherPref;
  return p;
};

const f0_refresh = refresh;
refresh = function () { f0_refresh(); $("moversBtn").classList.toggle("on", S.scanOn); };

// ---- share links say which features are on
const f0_updateURL = updateURL;
updateURL = function () {
  f0_updateURL();
  if (!S.R) return;
  const p = new URLSearchParams(location.search);
  for (const [k, on] of [["scan", S.scanOn], ["ast", S.showAst], ["other", !!S.showOther], ["cross", S.cross]]) {
    if (on) p.set(k, "1"); else p.delete(k);
  }
  history.replaceState(null, "", "?" + p.toString());
};
