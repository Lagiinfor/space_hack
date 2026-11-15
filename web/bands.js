// Combine any chosen infrared colours (detectors), for example only 1.6-2.4 µm with 4.4-5.0 µm.
//
// Fairness rule (the same as everywhere else in the tool): every sky pass is built from the
// SAME mix. A combined frame is the plain average of the chosen detectors' fair frames of that
// pass; a pass that lacks any chosen detector is left out; a pixel missing in any of them stays
// "no data". A combination is stored as a band number made of its digits (36 = detectors 3 and 6),
// so the rest of the page, and share links (?band=36), treat it like any other band.
// Loaded after app.js and the other page scripts.
"use strict";

S.comboMode = false;
const comboDigits = (code) => [...new Set(String(code).split("").map(Number))].filter((b) => b >= 1 && b <= 6).sort();

function buildCombo(list) {
  const R = S.R;
  if (!R || R.follow || list.length < 2) return null;
  const code = Number(list.join(""));
  R.frames = R.frames.filter((f) => f.band !== code);
  const passes = [...new Set(R.frames.filter((f) => f.band === list[0]).map((f) => f.pass_index))].sort((a, b) => a - b);
  let made = 0;
  for (const k of passes) {
    const parts = list.map((b) => R.frames.find((f) => f.band === b && f.pass_index === k));
    if (parts.some((p) => !p || !p.arr)) continue;          // this pass lacks one of the chosen colours
    const len = parts[0].arr.length, m = parts.length, arr = new Float32Array(len);
    for (let i = 0; i < len; i++) {
      let s = 0, ok = true;
      for (const p of parts) { const v = p.arr[i]; if (Number.isFinite(v)) s += v; else { ok = false; break; } }
      arr[i] = ok ? s / m : NaN;
    }
    R.frames.push({
      pass_index: k, band: code, combo: list.slice(), arr,
      n: parts.reduce((s, p) => s + p.n, 0),
      limited: parts.some((p) => p.limited),
      // a pass counts as well covered only if every chosen colour has enough photos in it
      thin: parts.some((p) => p.n < MIN_EXPOSURES),
      wl_min: Math.min(...parts.map((p) => p.wl_min)), wl_max: Math.max(...parts.map((p) => p.wl_max)),
      noise: Math.sqrt(parts.reduce((s, p) => s + p.noise * p.noise, 0)) / m,
      peak: parts.reduce((s, p) => s + p.peak, 0) / m,
      ranges: parts.map((p) => `${p.wl_min.toFixed(2)}–${p.wl_max.toFixed(2)}`),
    });
    made++;
  }
  return made ? code : null;
}

function comboSelection() {
  if (S.band > 6) return comboDigits(S.band);
  return S.band >= 1 ? [S.band] : [];
}

function setCombo(list) {
  list = [...new Set(list)].sort();
  if (list.length === 0) S.band = 0;
  else if (list.length === 1) S.band = list[0];
  else {
    const code = buildCombo(list);
    if (!code) { $("combonote").textContent = "These colours have no sky pass in common here, so they cannot be combined fairly."; return; }
    S.band = code;
  }
  S.flags = null; S.frameIdx = 0;
  refresh(); loadFlags();
}

function renderComboUI() {
  const box = $("bands");
  if (!box || !S.R) return;
  let chip = $("combochip");
  if (!chip || chip.parentElement !== box) {
    chip = document.createElement("button");
    chip.id = "combochip"; chip.className = "chip";
    chip.title = "Choose two or more colours and see them averaged together. Every sky pass uses the same mix.";
    chip.onclick = () => { S.comboMode = !S.comboMode; if (!S.comboMode && S.band > 6) setCombo([]); else renderComboUI(); };
    box.appendChild(chip);
  }
  if (!$("combonote")) {
    const n = document.createElement("div");
    n.id = "combonote"; n.className = "muted small-note"; n.style.marginTop = "6px";
    box.insertAdjacentElement("afterend", n);
  }
  chip.style.display = S.R.follow ? "none" : "";
  if (S.band > 6) S.comboMode = true;
  chip.textContent = S.comboMode ? "✓ Combining colours" : "➕ Combine colours";
  chip.classList.toggle("on", S.comboMode);
  const sel = comboSelection();
  if (S.comboMode) for (const b of box.children) {
    const v = parseInt(b.dataset.band);
    if (v >= 1 && v <= 6) b.classList.toggle("on", sel.includes(v));
    if (v === 0) b.classList.toggle("on", false);
  }
  $("combonote").textContent = !S.comboMode ? ""
    : sel.length >= 2 ? `Showing the average of ${sel.length} colours. Every sky pass uses the same mix; a pass that lacks one of them is left out.`
    : "Click two or more colours to combine them. Click a chosen colour again to remove it.";
}

// in combine mode a click on a colour adds or removes it instead of switching to it
$("bands").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-band]");
  if (!btn || !S.comboMode) return;
  const v = parseInt(btn.dataset.band);
  e.stopPropagation(); e.preventDefault();
  if (v === 0) { S.comboMode = false; setCombo([]); return; }
  const sel = comboSelection();
  setCombo(sel.includes(v) ? sel.filter((x) => x !== v) : [...sel, v]);
}, true);

// keep a chosen combination when the pictures are replaced (a sharper preview, another patch)
// and when a shared link asks for one (?band=36)
const band0_showResult = showResult;
showResult = function (R, keepBand, swapping) {
  let want = S.band > 6 ? S.band : null;
  if (!want && !S.R) {
    const b = parseInt(new URLSearchParams(location.search).get("band"));
    if (b > 6) want = b;
  }
  band0_showResult(R, keepBand, swapping);
  if (want && S.R && !S.R.follow && S.band <= 6 && !S.tourKey) {
    const code = buildCombo(comboDigits(want));
    if (code) { S.band = code; S.comboMode = true; refresh(); }
  } else if (S.band <= 6 && S.comboMode && S.tourKey) S.comboMode = false;
  renderComboUI();
};

const band0_refresh = refresh;
refresh = function () { band0_refresh(); renderComboUI(); };

// a pass where one of the chosen colours has too few photos is not compared
const band0_blinkFrames = blinkFrames;
blinkFrames = function () {
  if (!(S.band > 6)) return band0_blinkFrames();
  const all = framesForBand(), ok = all.filter((f) => !f.thin && !f.limited);
  const fs = ok.length >= 2 ? ok : all;
  return S.blinkset === "ends" && fs.length > 2 ? [fs[0], fs[fs.length - 1]] : fs;
};
