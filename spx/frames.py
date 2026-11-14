"""Turn raw SPHEREx cutouts into like-for-like stacked frames.

Why stacking is needed: SPHEREx has no ordinary filters. Each detector sits behind
a filter whose colour changes smoothly across it, so every single exposure sees a
given star at a different wavelength. Blinking raw exposures would show fake
brightness changes. Averaging all exposures taken by one detector during one
~6-month sky pass gives frames that cover the same wavelength range every time.
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.wcs import WCS, FITSFixedWarning
from scipy.ndimage import map_coordinates, maximum_filter

logging.getLogger("astropy").setLevel(logging.ERROR)
warnings.simplefilter("ignore", FITSFixedWarning)

# Flag bits (from the FLAGS extension header) that mean "do not trust this pixel".
# Saturation-type flags (OVERFLOW, BLOOM, NONLINEAR) are deliberately NOT here:
# they light up on the cores of bright stars, which we still want to see.
FLAG_BITS = {
    "TRANSIENT": 1 << 0, "OVERFLOW": 1 << 1, "SUR_ERROR": 1 << 2, "NONFUNC": 1 << 6,
    "DICHROIC": 1 << 7, "MISSING_DATA": 1 << 9, "HOT": 1 << 10, "COLD": 1 << 11,
    "FULLSAMPLE": 1 << 12, "PHANMISS": 1 << 14, "NONLINEAR": 1 << 15, "PERSIST": 1 << 17,
    "OUTLIER": 1 << 19, "CROSSTALK": 1 << 20, "SOURCE": 1 << 21, "GHOST": 1 << 22,
    "GHOST_FPA": 1 << 23, "GHOST_EXT": 1 << 24, "STREAK": 1 << 25, "BLOOM": 1 << 26,
    "SNOWBALL": 1 << 27, "HALO": 1 << 28,
}
BAD = sum(FLAG_BITS[k] for k in
          ("NONFUNC", "MISSING_DATA", "HOT", "COLD", "SNOWBALL", "STREAK", "DICHROIC"))
SATURATED = FLAG_BITS["OVERFLOW"] | FLAG_BITS["NONLINEAR"]


@dataclass
class Cutout:
    obs_id: str
    detector: int
    mjd: float
    wavelength: float      # microns, at the requested sky position
    image: np.ndarray      # MJy/sr, zodiacal light and local sky removed, bad pixels = NaN
    variance: np.ndarray
    flags: np.ndarray
    wcs: WCS
    wave_wcs: WCS | None = None   # detector pixel -> wavelength

    def wavelength_at(self, ra: float, dec: float) -> float:
        """Wavelength this exposure saw at a given sky position. The filter's colour
        changes across the detector, so it differs slightly from the centre value."""
        if self.wave_wcs is None:
            return self.wavelength
        x, y = self.wcs.all_world2pix(ra, dec, 0)
        lam, _ = self.wave_wcs.pixel_to_world_values(x, y)
        return float(lam) if np.isfinite(lam) else self.wavelength


def load_cutout(path: Path, ra: float, dec: float) -> Cutout:
    with fits.open(path, memmap=False) as h:  # no memory-mapping: keeps files unlocked on Windows
        hdr = h["IMAGE"].header
        wcs = WCS(hdr)
        img = h["IMAGE"].data.astype(float) - h["ZODI"].data
        var = h["VARIANCE"].data.astype(float)
        flags = h["FLAGS"].data
        x, y = wcs.all_world2pix(ra, dec, 0)
        if "WCS-WAVE" not in h:  # slimmed download: borrow this detector's stored table
            h.append(_wave_table(int(hdr["DETECTOR"])))
        wave_wcs = WCS(hdr, fobj=h, key="W")
        wave_wcs.sip = None
        lam, _ = wave_wcs.pixel_to_world_values(x, y)
        mjd = float(hdr["MJD-AVG"])
        det = int(hdr["DETECTOR"])
        obs = str(hdr["OBSID"])
    bad = (flags & BAD) != 0
    img[bad | ~np.isfinite(img)] = np.nan
    # remove whatever smooth sky glow is left (the field is flat on this scale)
    _, sky, _ = sigma_clipped_stats(img[np.isfinite(img)], sigma=3.0)
    img -= sky
    return Cutout(obs, det, mjd, float(lam), img, var, flags, wcs, wave_wcs)


_WAVE_DIR = Path(__file__).parent / "wave_tables"
_wave_cache: dict[int, fits.BinTableHDU] = {}


def _wave_table(detector: int) -> fits.BinTableHDU:
    """Each detector's wavelength-vs-pixel table is fixed hardware calibration, the
    same in every file, so we keep one copy per detector instead of downloading it."""
    if detector not in _wave_cache:
        with fits.open(_WAVE_DIR / f"D{detector}.fits") as w:
            _wave_cache[detector] = w["WCS-WAVE"].copy()
    return _wave_cache[detector]


def assign_passes(mjds, gap_days: float = 60.0) -> np.ndarray:
    """Number the sky passes: a new pass starts after any gap longer than gap_days."""
    mjds = np.asarray(mjds)
    order = np.argsort(mjds)
    labels = np.zeros(len(mjds), dtype=int)
    k = 0
    for a, b in zip(order[:-1], order[1:]):
        if mjds[b] - mjds[a] > gap_days:
            k += 1
        labels[b] = k
    return labels


def target_grid(ra: float, dec: float, size_deg: float, pix_arcsec: float = 3.075):
    """North-up, east-left grid centred on (ra, dec); default = half a SPHEREx pixel."""
    n = int(round(size_deg * 3600 / pix_arcsec))
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-pix_arcsec / 3600, pix_arcsec / 3600]
    return w, (n, n)


def resample(image, wcs_in: WCS, grid_wcs: WCS, shape) -> np.ndarray:
    """Redraw one exposure on the common grid (bilinear interpolation).
    Pixels that fall off the exposure, or touch a bad pixel, come out as NaN."""
    yy, xx = np.mgrid[: shape[0], : shape[1]]
    ra, dec = grid_wcs.all_pix2world(xx, yy, 0)
    x, y = wcs_in.all_world2pix(ra, dec, 0)
    return map_coordinates(image, [y, x], order=1, mode="constant", cval=np.nan)


def coadd(cutouts: list[Cutout], grid_wcs: WCS, shape, clip: float = 4.0):
    """Reproject every cutout onto the grid and average them.

    Returns (mean image, number of exposures used per pixel). A robust clip throws
    out one-off blemishes (cosmic rays, satellites) that survive the flags.
    """
    cube = np.full((len(cutouts),) + tuple(shape), np.nan)
    for i, c in enumerate(cutouts):
        cube[i] = resample(c.image, c.wcs, grid_wcs, shape)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        med = np.nanmedian(cube, axis=0)
        mad = 1.4826 * np.nanmedian(np.abs(cube - med), axis=0)
        # floor on the scatter so that bright-star pixels are not over-clipped
        tol = clip * np.maximum(mad, 0.05 * np.abs(med) + np.nanmedian(mad))
        cube[np.abs(cube - med) > tol] = np.nan
        mean = np.nanmean(cube, axis=0)
    # saturated star cores disagree so much between exposures that everything gets
    # clipped; fall back to the plain median there rather than leave a hole
    mean = np.where(np.isfinite(mean), mean, med)
    # NOTE: pixels with no measurement stay NaN here. Filling is a separate, explicit step
    # (fill_saturated_cores) so that "no data" is never mistaken for "bright".
    return mean, np.isfinite(cube).sum(axis=0)


def fill_saturated_cores(img: np.ndarray, max_area: int = 80, rounds: int = 6):
    """Fill ONLY small holes that are completely surrounded by measured pixels: in
    practice the burnt-out centre of a very bright star, which the archive stores as
    'no value'. They are painted as bright as their brightest neighbour so the star
    shows as a solid blob, not a doughnut.

    Holes touching the picture's edge, or large empty areas (no coverage), are left
    as NaN = 'no data'. Returns (filled image, mask of the pixels that were filled)."""
    from scipy.ndimage import label

    hole = ~np.isfinite(img)
    lab, n = label(hole)
    fillable = np.zeros_like(hole)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
    for k in range(1, n + 1):
        region = lab == k
        if k in edge or region.sum() > max_area:
            continue
        fillable |= region
    out = img.copy()
    todo = fillable.copy()
    for _ in range(rounds):
        if not todo.any():
            break
        grown = maximum_filter(np.where(np.isfinite(out), out, -np.inf), size=3)
        ok = todo & np.isfinite(grown) & (grown > -np.inf)
        out[ok] = grown[ok]
        todo &= ~ok
    return out, fillable & np.isfinite(out)


def fill_holes(img: np.ndarray, rounds: int = 4) -> np.ndarray:
    """Old behaviour kept for the step-1 demo script only (fills every hole)."""
    out = img.copy()
    for _ in range(rounds):
        hole = ~np.isfinite(out)
        if not hole.any():
            break
        out[hole] = maximum_filter(np.where(hole, -np.inf, out), size=3)[hole]
        out[~np.isfinite(out)] = np.nan
    return out


def reject_glitches(cube: np.ndarray, factor: float = 4.0, nsig: float = 10.0) -> int:
    """In a stack of photos of the same spot from ONE sky pass and ONE detector, blank
    out pixels that are wildly brighter (or darker) than all the other photos agree on:
    cosmic-ray hits, satellite glints, afterimages ("persistence") of an earlier bright
    star. Real objects are in (nearly) every photo, so the per-pixel median ignores the
    glitch. The limits are loose on purpose (4x the typical value AND 10x the scatter),
    because a star's brightness genuinely changes by up to ~2-3x across one detector's
    wavelength range. Works in place; returns how many pixel values were thrown out."""
    if len(cube) < 3:
        return 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        med = np.nanmedian(cube, axis=0)
        mad = 1.4826 * np.nanmedian(np.abs(cube - med), axis=0)
        floor = np.nanmedian(mad)
        dev = np.abs(cube - med)
        bad = (dev > nsig * np.maximum(mad, floor)) & (dev > factor * np.abs(med) + nsig * floor)
    bad &= np.isfinite(cube)
    cube[bad] = np.nan
    return int(bad.sum())


def stack_like_for_like(cuts_by_pass: dict, grid_wcs: WCS, shape, n_sub: int = 6, min_exposures: int = 4):
    """Stack one detector's exposures per sky pass so that every pass covers the SAME
    wavelengths with the SAME weights.

    The detector's wavelength range is split into n_sub narrow slices. In each pass,
    exposures are stacked slice by slice. A pass's frame is then the plain average of
    the slices that ALL the well-covered passes have (min_exposures or more photos).
    So a constant star gives the same brightness in every frame, whatever mix of
    wavelengths each pass happened to sample. A pass that lacks some of those slices,
    or has too few photos, is marked 'limited' rather than silently compared.

    Returns {pass_index: dict(img, n, slices_used, slices_total, wl_min, wl_max, limited)}.
    """
    allc = [c for cs in cuts_by_pass.values() for c in cs]
    if not allc:
        return {}
    wls = np.array([c.wavelength for c in allc])
    edges = np.geomspace(wls.min() * 0.999, wls.max() * 1.001, n_sub + 1)
    slot = lambda c: int(np.clip(np.searchsorted(edges, c.wavelength) - 1, 0, n_sub - 1))  # noqa: E731
    have = {k: {j for c in cs for j in [slot(c)]} for k, cs in cuts_by_pass.items()}
    good = [k for k, cs in cuts_by_pass.items() if len(cs) >= min_exposures]
    common = set(range(n_sub))
    for k in good:
        common &= have[k]
    out = {}
    for k, cs in cuts_by_pass.items():
        use = sorted(common & have[k]) if k in good and common else sorted(have[k])
        # redraw every photo of this pass once, then throw out one-off glitches
        cube = np.stack([resample(c.image, c.wcs, grid_wcs, shape) for c in cs])
        n_glitch = reject_glitches(cube)
        imgs, n = [], 0
        for j in use:
            idx = [i for i, c in enumerate(cs) if slot(c) == j]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                imgs.append(np.nanmean(cube[idx], axis=0))
            n += len(idx)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            img = np.nanmean(imgs, axis=0) if imgs else np.full(shape, np.nan)
        limited = (k not in good) or (not common) or (len(common) < 0.6 * n_sub) or (set(use) != common)
        out[k] = dict(img=img, n=n, slices_used=len(use), slices_total=n_sub, glitch_px=n_glitch,
                      wl_min=float(edges[min(use)]) if use else None,
                      wl_max=float(edges[max(use) + 1]) if use else None, limited=bool(limited))
    return out
