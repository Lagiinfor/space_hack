"""The whole chain for one sky position, as used by the web app:
find exposures -> download cutouts -> stack per detector per sky pass -> package.

The finished result is saved on disk, so asking for the same spot again is instant.
"""
from __future__ import annotations

import base64
import json
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


def _pack(a: np.ndarray) -> str:
    """Float image -> compact text the browser can unpack (base64 of float32)."""
    return base64.b64encode(np.nan_to_num(a, nan=0.0).astype("<f4").tobytes()).decode()


def build(ra: float, dec: float, field_deg: float = 0.06, progress=lambda stage, frac: None) -> dict:
    ra, dec = round(ra, 4), round(dec, 4)
    out = result_path(ra, dec, field_deg)
    if out.exists():
        return json.loads(out.read_text())
    warnings.filterwarnings("ignore")
    cut_deg = round(max(0.1, field_deg * 1.5), 3)
    pdir = place_dir(ra, dec)

    progress("Asking NASA's archive which images cover this spot", 0.02)
    images = archive.find_images(ra, dec, pdir)
    if not images:
        raise ValueError("SPHEREx has no images of this position yet.")

    progress(f"Downloading {len(images)} image cutouts", 0.05)
    got = archive.fetch_all(images, ra, dec, cut_deg, pdir / f"cutouts_{cut_deg}",
                            progress=lambda d, n: progress(f"Downloading image cutouts ({d} of {n})",
                                                           0.05 + 0.75 * d / n))

    progress("Cleaning up the images", 0.82)
    cuts = []
    for _, p in got:
        try:
            cuts.append(frames.load_cutout(p, ra, dec))
        except Exception as e:  # a damaged file should not sink the whole request
            print(f"  could not read {p.name}: {e}")
    if not cuts:
        raise ValueError("None of the images could be downloaded. Try again in a minute.")
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
        stacks = []
        for d in range(1, 7):
            sel = [c for c in mine if c.detector == d]
            if not sel:
                continue
            img, _ = frames.coadd(sel, grid, shape)
            stacks.append(img)
            frame_list.append(dict(pass_index=k, band=d, n=len(sel),
                                   wl_min=min(c.wavelength for c in sel),
                                   wl_max=max(c.wavelength for c in sel),
                                   data=img))
        if stacks:
            frame_list.append(dict(pass_index=k, band=0, n=len(mine), wl_min=0.75, wl_max=5.0,
                                   data=np.nanmean(stacks, axis=0)))

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
        complete=(pdir / "images.json").exists(),
    )
    # if part of the archive was down, show what we have but don't keep it, so the
    # next visit tries again for the full set
    out_tmp = out if result["complete"] else out.with_name(out.stem + "_partial.json")
    out_tmp.write_text(json.dumps(result))
    progress("Done", 1.0)
    return result
