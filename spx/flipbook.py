"""The whole chain for one sky position, as used by the web app:
find exposures -> download cutouts -> stack per detector per sky pass -> package.

The finished result is saved on disk, so asking for the same spot again is instant.
"""
from __future__ import annotations

import base64
import json
import threading
import warnings
from pathlib import Path

import numpy as np
from astropy.stats import sigma_clipped_stats
from astropy.time import Time

from . import archive, frames

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# Wavelength range of each detector, microns (SPHEREx instrument paper).
BANDS = {1: (0.75, 1.09), 2: (1.10, 1.62), 3: (1.63, 2.41),
         4: (2.42, 3.82), 5: (3.83, 4.41), 6: (4.42, 5.00)}


def place_dir(ra: float, dec: float) -> Path:
    return DATA / f"ra{ra:.4f}_dec{dec:+.4f}"


def result_path(ra: float, dec: float, field_deg: float) -> Path:
    return place_dir(ra, dec) / f"flipbook_{field_deg:.3f}.json"


def saved_path(ra: float, dec: float, field_deg: float) -> Path:
    """The saved result for a position: the complete one if there is one, else the
    partial one (some photos missing)."""
    p = result_path(ra, dec, field_deg)
    return p if p.exists() else p.with_name(p.stem + "_partial.json")


def is_current(ra: float, dec: float, field_deg: float, nearly: float = 0.97) -> bool:
    """A saved result exists, was made by the current stacking code, and is complete,
    or nearly so: if NASA keeps failing on a handful of photos (here: 3% or fewer) we
    show what we have straight away (labelled as missing those photos) instead of
    making the person wait for retries every time."""
    p = saved_path(ra, dec, field_deg)
    try:
        r = json.loads(p.read_text()) if p.exists() else None
    except Exception:
        return False
    if not r or r.get("version") != RESULT_VERSION or r.get("preview"):
        return False
    return bool(r.get("complete")) or r["n_used"] >= nearly * r["n_images"]


def _pack(a: np.ndarray) -> str:
    """Float image -> compact text the browser can unpack (base64 of float32).
    'No data' pixels stay NaN, so the page can show them as no data, not as black sky."""
    return base64.b64encode(np.asarray(a, dtype="<f4").tobytes()).decode()

RESULT_VERSION = 7   # bump when the way frames are made changes; older saved results are rebuilt


class Cancelled(Exception):
    """The person asked for another patch before this one finished."""


def build(ra: float, dec: float, field_deg: float = 0.06, progress=lambda stage, frac: None, stop=None,
          on_preview=None) -> dict:
    ra, dec = round(ra, 4), round(dec, 4)
    out = result_path(ra, dec, field_deg)
    if out.exists():
        saved = json.loads(out.read_text())
        if saved.get("version") == RESULT_VERSION:
            return saved
    warnings.filterwarnings("ignore")
    cut_deg = round(max(0.1, field_deg * 1.5), 3)
    pdir = place_dir(ra, dec)

    progress("Asking NASA's archive which images cover this spot", 0.02)
    images = archive.find_images(ra, dec, pdir)
    if not images:
        raise ValueError("SPHEREx has no images of this position yet.")

    # Download in a balanced order (every sky pass and detector early on, spread out in
    # time), so that after the first few dozen photos a fair preview can already be made.
    images = priority_order(images)
    n_img = len(images)
    done_paths, lock = [], threading.Lock()

    def on_done(im, path):
        with lock:
            done_paths.append(path)

    fetch_result = {}

    def fetch():
        fetch_result["got"] = archive.fetch_all(
            images, ra, dec, cut_deg, pdir / f"cutouts_{cut_deg}", stop=stop, on_done=on_done,
            progress=lambda d, n: progress(f"Downloading photos from NASA ({d} of {n})", 0.05 + 0.75 * d / n))

    worker = threading.Thread(target=fetch, daemon=True)
    worker.start()
    loaded: dict = {}

    def load_new(paths):
        for p in paths:
            if p not in loaded:
                try:
                    loaded[p] = frames.load_cutout(p, ra, dec)
                except Exception as e:  # a damaged file should not sink the whole request
                    print(f"  could not read {p.name}: {e}")
                    loaded[p] = None

    # previews after about 15%, 40% and 70% of the photos (at least 40 photos)
    checkpoints = [max(40, int(f * n_img)) for f in (0.15, 0.4, 0.7)]
    while worker.is_alive():
        worker.join(timeout=0.5)
        if stop and stop():
            break
        with lock:
            have = list(done_paths)
        if on_preview and checkpoints and len(have) >= checkpoints[0] and len(have) < n_img:
            while checkpoints and len(have) >= checkpoints[0]:
                checkpoints.pop(0)
            load_new(have)
            cuts = [loaded[p] for p in have if loaded[p] is not None]
            try:
                pre = make_result(cuts, images, ra, dec, field_deg, pdir, preview=True)
                on_preview(pre)
            except Exception as e:  # a preview is a bonus; never let it break the real build
                print("  preview skipped:", e)
    if stop and stop():
        raise Cancelled()
    got = fetch_result.get("got", [])

    progress("Cleaning up the images", 0.82)
    load_new([p for _, p in got])
    cuts = [loaded[p] for _, p in got if loaded.get(p) is not None]
    if not cuts:
        raise ValueError("None of the images could be downloaded. Try again in a minute.")
    result = make_result(cuts, images, ra, dec, field_deg, pdir, progress=progress)
    out_tmp = out if result["complete"] else out.with_name(out.stem + "_partial.json")
    out_tmp.write_text(json.dumps(result))
    progress("Done", 1.0)
    return result


def priority_order(images: list[dict]) -> list[dict]:
    """Interleave photos so any early part of the list samples every sky pass and every
    detector, spread over the dates within each pass."""
    if not images:
        return images
    guess = frames.assign_passes([im["mjd"] for im in images])
    groups: dict = {}
    for im, k in zip(images, guess):
        groups.setdefault((int(k), im["detector"]), []).append(im)

    def spread(lst):
        lst = sorted(lst, key=lambda im: im["mjd"])
        n = len(lst)
        def vdc(i):  # van der Corput: 0, 1/2, 1/4, 3/4, ... spreads picks evenly
            x, f = 0.0, 0.5
            while i:
                x += f * (i & 1); i >>= 1; f /= 2
            return x
        return [lst[min(n - 1, int(vdc(i) * n))] for i in range(n)] if n else []

    queues = []
    for key in sorted(groups):
        seen, q = set(), []
        for im in spread(groups[key]) + sorted(groups[key], key=lambda im: im["mjd"]):
            ident = (im["obs_id"], im["detector"])
            if ident not in seen:
                seen.add(ident); q.append(im)
        queues.append(q)
    out = []
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


def make_result(cuts, images, ra, dec, field_deg, pdir, preview=False, progress=lambda s, f: None) -> dict:
    """Turn the photos we have into the flip-book package (fair stacking etc.)."""
    passes = frames.assign_passes([c.mjd for c in cuts])
    n_pass = int(passes.max()) + 1

    progress("Stacking images per sky pass", 0.88)
    grid, shape = frames.target_grid(ra, dec, field_deg)
    pass_info, frame_list = [], []
    for k in range(n_pass):
        mine = [c for c, p in zip(cuts, passes) if p == k]
        mjds = [c.mjd for c in mine]
        t0, t1 = Time(min(mjds), format="mjd"), Time(max(mjds), format="mjd")
        tm = Time(float(np.mean(mjds)), format="mjd")
        pass_info.append(dict(index=k, label=tm.strftime("%b %Y"), mjd=float(np.mean(mjds)),
                              start=t0.strftime("%Y-%m-%d"), end=t1.strftime("%Y-%m-%d"),
                              n=len(mine)))
    # per detector: like-for-like wavelength coverage across passes (see frames.stack_like_for_like)
    per_det = {}
    for d in range(1, 7):
        by_pass = {k: [c for c, p in zip(cuts, passes) if p == k and c.detector == d] for k in range(n_pass)}
        by_pass = {k: v for k, v in by_pass.items() if v}
        if by_pass:
            per_det[d] = frames.stack_like_for_like(by_pass, grid, shape)
    for d, res in per_det.items():
        for k, r in res.items():
            frame_list.append(dict(pass_index=k, band=d, n=r["n"], wl_min=r["wl_min"], wl_max=r["wl_max"],
                                   slices_used=r["slices_used"], slices_total=r["slices_total"],
                                   limited=r["limited"], glitch_px=r.get("glitch_px", 0), data=r["img"]))
    # all detectors together: only detectors that are fairly comparable in every pass they appear in
    passes_present = sorted({k for res in per_det.values() for k in res})
    # a detector is "fair" if it has at least two well-covered passes (4+ photos) and
    # none of those is limited; sparse passes don't disqualify it, they are labelled
    def fair_det(res):
        good = [k for k, r in res.items() if r["n"] >= 4]
        return len(good) >= 2 and all(not res[k]["limited"] for k in good)
    fair = [d for d, res in per_det.items() if fair_det(res)]
    # detectors used for "all colours": the fair ones that are fully comparable in every
    # well-covered pass (24+ photos); if that leaves fewer than two, use all fair ones
    core = [k for k in passes_present if pass_info[k]["n"] >= 24]
    common = [d for d in fair if all(k in per_det[d] and not per_det[d][k]["limited"] for k in core)]
    use = common if len(common) >= 2 else (fair or list(per_det))
    for k in passes_present:
        dets = [d for d in use if k in per_det[d]]
        if not dets:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            img = np.nanmean([per_det[d][k]["img"] for d in dets], axis=0)
        frame_list.append(dict(pass_index=k, band=0, n=sum(per_det[d][k]["n"] for d in dets),
                               wl_min=0.75, wl_max=5.0, detectors=dets, n_detectors=len(dets),
                               limited=bool(set(dets) != set(use) or any(per_det[d][k]["limited"] for d in dets)),
                               data=img))
    # fill only burnt-out star centres (enclosed holes); count them so the page can say so
    for f in frame_list:
        f["data"], filled = frames.fill_saturated_cores(f["data"])
        f["filled_px"] = int(filled.sum())
        f["nodata_px"] = int((~np.isfinite(f["data"])).sum())

    # noise level per band, shared by all passes so the blink is fair
    noise = {}
    for b in range(7):
        imgs = [f["data"] for f in frame_list if f["band"] == b]
        if imgs:
            _, _, s = sigma_clipped_stats(np.concatenate([i[np.isfinite(i)] for i in imgs]), sigma=3)
            noise[b] = float(max(s, 1e-6))
    for f in frame_list:
        d = f.pop("data")
        f["noise"] = noise[f["band"]]
        f["peak"] = float(np.nanmax(d)) if np.isfinite(d).any() else 1.0
        f["pixels"] = _pack(d)

    result = dict(
        ra=ra, dec=dec, field_deg=field_deg, size=shape[0], pix_arcsec=3.075,
        passes=pass_info,
        bands=[dict(band=0, name="All bands", wl_min=0.75, wl_max=5.0)] +
              [dict(band=d, name=f"Band {d}", wl_min=a, wl_max=b) for d, (a, b) in BANDS.items()],
        frames=frame_list,
        exposures=[dict(mjd=c.mjd, band=c.detector, wl=c.wavelength, pass_index=int(p), obs_id=c.obs_id)
                   for c, p in zip(cuts, passes)],
        n_images=len(images), n_used=len(cuts),
        # complete only if the archive listing was complete AND every listed photo was
        # downloaded and read; otherwise the result is shown but not kept, and the next
        # visit tries the missing photos again
        complete=(pdir / "images.json").exists() and len(cuts) == len(images),
        version=RESULT_VERSION,
        built=Time.now().strftime("%Y-%m-%d"),
        collections=archive.COLLECTIONS,
        preview=preview,
    )
    if preview:
        result["complete"] = False
    return result
