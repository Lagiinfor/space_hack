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
    return Cutout(obs, det, mjd, float(lam), img, var, flags, wcs)


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
    return fill_holes(mean), np.isfinite(cube).sum(axis=0)


def fill_holes(img: np.ndarray, rounds: int = 4) -> np.ndarray:
    """Pixels with no data at all are almost always the burnt-out centre of a very
    bright star (the archive stores those as 'no value'). Paint them as bright as
    their brightest neighbour so the star shows as a solid blob, not a doughnut."""
    out = img.copy()
    for _ in range(rounds):
        hole = ~np.isfinite(out)
        if not hole.any():
            break
        out[hole] = maximum_filter(np.where(hole, -np.inf, out), size=3)[hole]
        out[~np.isfinite(out)] = np.nan
    return out


