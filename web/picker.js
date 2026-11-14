// Glue between the 3D sky (sky.js) and the rest of the page (app.js).
import { SkyPicker } from "./sky.js?v=9";

const $ = (id) => document.getElementById(id);
const fmt = (ra, dec) => `RA ${ra.toFixed(3)}°, Dec ${dec >= 0 ? "+" : ""}${dec.toFixed(3)}°`;
let current = null;   // what the pick card is showing
let tour = [];

const sky = new SkyPicker($("globe"), {
  onPick: ({ ra, dec, target, constellation }) => showCard(ra, dec, target, constellation),
  onHover: (p) => {
    $("skyhover").textContent = p ? `${fmt(p.ra, p.dec)}${p.constellation ? " · near " + p.constellation : ""} · click to choose` : "";
  },
});
window.skyPicker = sky;

function showCard(ra, dec, target, constellation) {
  current = { ra, dec, target };
  const isTour = target && target.key;
  $("pckind").textContent = isTour ? target.kind : target && target.search ? "You searched for" : "Your patch";
  $("pctitle").textContent = isTour ? target.name : target && target.name ? target.name
    : constellation ? `A patch in ${constellation}` : "Your patch of sky";
  $("pcsub").textContent = fmt(ra, dec) + (constellation && isTour ? ` · in ${constellation}` : "");
  $("pcstory").textContent = isTour ? target.story : target && target.story ? target.story
    : "SPHEREx has photographed this spot several times since 2025. Let's see if anything there moved or changed.";
  if (isTour) $("field").value = String(target.field);
  $("pcnote").textContent = isTour && target.ready ? "Saved on this computer: opens instantly."
    : "First visit to a new spot: the tool fetches every SPHEREx photo of it from NASA (2 to 4 minutes).";
  $("pickcard").classList.remove("hidden");
  document.body.classList.add("has-card");
  for (const b of $("tour").children) b.classList.toggle("on", isTour && b.dataset.key === target.key);
}

$("pcclose").onclick = () => {
  $("pickcard").classList.add("hidden"); sky.reticle.visible = false; document.body.classList.remove("has-card");
};

$("pcgo").onclick = async () => {
  if (!current) return;
  const { ra, dec, target } = current;
  $("pickcard").classList.add("hidden");
  document.body.classList.remove("has-card");
  await sky.flyTo(ra, dec);
  document.body.classList.add("warp");
  setTimeout(() => document.body.classList.remove("warp"), 900);
  if (target && target.key) startTour(target);
  else { S.tourKey = null; load(ra, dec, parseFloat($("field").value)).catch((e) => fail(e.message)); }
};

window.addEventListener("tour-loaded", (e) => {
  tour = e.detail || [];
  sky.setTargets(tour);
  $("tour").innerHTML = "";
  for (const t of tour) {
    const b = document.createElement("button");
    b.className = "tour-btn";
    b.dataset.key = t.key;
    b.innerHTML = `<b>${t.name}</b><span>${t.kind}</span>`;
    b.onclick = () => { if (t.ra !== undefined) sky.select(t.ra, t.dec, t); };
    $("tour").appendChild(b);
  }
});
// app.js may have loaded the tour before this module ran
if (typeof S !== "undefined" && S.tour && S.tour.length) window.dispatchEvent(new CustomEvent("tour-loaded", { detail: S.tour }));

// a shared link (?ra=..&dec=..) skips the globe and opens the patch directly
const p = new URLSearchParams(location.search);
if (p.has("ra") && p.has("dec")) {
  document.body.classList.remove("on-pick");
  document.body.classList.add("on-explore");
}
