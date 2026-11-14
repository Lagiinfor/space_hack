// Zoom and pan directly on the picture: mouse wheel or pinch zooms toward the pointer,
// drag moves the picture when zoomed in. The picture is only scaled with CSS, so clicks,
// overlays and coordinates stay lined up at any zoom (they are all worked out from the
// picture's on-screen rectangle). Loaded last; replaces the simpler zoom from tools.js.
"use strict";

S.zoom = 1; S.panX = 0; S.panY = 0;
const ZMAX = 8;

function applyZoom() {
  const cv = $("sky"), box = cv.parentElement.getBoundingClientRect();
  const W = box.width, H = box.width;                 // the picture is square
  S.zoom = Math.max(1, Math.min(ZMAX, S.zoom));
  S.panX = Math.min(0, Math.max(W * (1 - S.zoom), S.panX));
  S.panY = Math.min(0, Math.max(H * (1 - S.zoom), S.panY));
  cv.style.transformOrigin = "0 0";
  cv.style.transform = S.zoom === 1 ? "" : `translate(${S.panX}px, ${S.panY}px) scale(${S.zoom})`;
  cv.style.touchAction = S.zoom === 1 ? "pan-y" : "none";
  cv.style.cursor = S.zoom > 1 ? "grab" : "crosshair";
  $("zoomtxt").textContent = `Zoom ×${S.zoom.toFixed(S.zoom % 1 ? 1 : 0)}`;
}

// zoom to z, keeping the picture point under (px, py) (pixels inside the viewer box) fixed
function zoomAt(z, px, py) {
  z = Math.max(1, Math.min(ZMAX, z));
  const ux = (px - S.panX) / S.zoom, uy = (py - S.panY) / S.zoom;
  S.zoom = z; S.panX = px - ux * z; S.panY = py - uy * z;
  applyZoom();
}

// buttons and keys: zoom toward the last clicked spot, or the middle
function setZoom(z) {
  const cv = $("sky"), box = cv.parentElement.getBoundingClientRect();
  let px = box.width / 2, py = box.width / 2;
  if (S.click && S.R && z > S.zoom) {
    const [x, y] = skyToCanvas(S.click.east, S.click.north);
    px = S.panX + x / S.R.size * box.width * S.zoom; py = S.panY + y / S.R.size * box.width * S.zoom;
  }
  $("sky").style.transition = "transform .2s ease";
  zoomAt(z, px, py);
}
function setZoomOrigin() { /* no longer needed: the view stays where the person put it */ }

(function wireZoom() {
  const cv = $("sky"), viewer = cv.parentElement;
  const local = (e) => { const b = viewer.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top]; };

  // mouse wheel: zoom toward the pointer. At ×1, scrolling down is left alone so the page
  // can still scroll past the picture.
  viewer.addEventListener("wheel", (e) => {
    if (!S.R || document.body.classList.contains("on-pick")) return;
    const zoomIn = e.deltaY < 0;
    if (!zoomIn && S.zoom <= 1) return;
    e.preventDefault();
    cv.style.transition = "none";
    const [px, py] = local(e);
    zoomAt(S.zoom * (zoomIn ? 1.25 : 0.8), px, py);
  }, { passive: false });

  // drag to pan (when zoomed), pinch to zoom
  const pts = new Map();
  let drag = null, pinch = null, moved = false;
  cv.addEventListener("pointerdown", (e) => {
    pts.set(e.pointerId, local(e));
    moved = false;
    if (pts.size === 1) drag = { x: e.clientX, y: e.clientY, panX: S.panX, panY: S.panY };
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), z: S.zoom }; drag = null; moved = true;
    }
  });
  cv.addEventListener("pointermove", (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, local(e));
    cv.style.transition = "none";
    if (pinch && pts.size === 2) {
      const [a, b] = [...pts.values()];
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      zoomAt(pinch.z * d / Math.max(pinch.d, 1), (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
    } else if (drag && S.zoom > 1) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.hypot(dx, dy) > 5) { moved = true; cv.setPointerCapture(e.pointerId); cv.style.cursor = "grabbing"; }
      if (moved) { S.panX = drag.panX + dx; S.panY = drag.panY + dy; applyZoom(); }
    }
  });
  const up = (e) => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; if (!pts.size) { drag = null; applyZoom(); } };
  cv.addEventListener("pointerup", up);
  cv.addEventListener("pointercancel", up);
  // a drag or pinch must not count as a click on an object
  cv.addEventListener("click", (e) => { if (moved) { e.stopImmediatePropagation(); e.preventDefault(); moved = false; } }, true);
  cv.addEventListener("dblclick", (e) => { const [px, py] = local(e); cv.style.transition = "transform .2s ease"; zoomAt(S.zoom > 1 ? 1 : 3, px, py); });
  window.addEventListener("resize", applyZoom);
  applyZoom();
})();
