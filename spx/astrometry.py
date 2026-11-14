"""Where is the star, and where should it be?

measure_position(): fit the star's blur shape in one exposure and return its sky
position. Saturated core pixels are ignored; the fit uses the unsaturated skirt of
light around the core, which is symmetric about the true centre.

predict_position(): textbook prediction from a catalogue entry: straight-line
proper motion plus the yearly parallax wobble caused by Earth's orbit.
"""
from __future__ import annotations

import numpy as np
from astropy import units as u
from astropy.coordinates import get_body_barycentric
from astropy.time import Time
from scipy.optimize import least_squares

from .frames import BAD, FLAG_BITS, Cutout

# Around very bright stars the TRANSIENT / SUR_ERROR flags fire on perfectly good
# pixels, so only true saturation and dead pixels are excluded from the fit.
UNTRUSTED = BAD | FLAG_BITS["OVERFLOW"] | FLAG_BITS["NONLINEAR"]


def _moffat(p, x, y):
    x0, y0, amp, alpha, beta, bkg = p
    r2 = (x - x0) ** 2 + (y - y0) ** 2
    return amp * (1 + r2 / alpha ** 2) ** (-beta) + bkg


def measure_position(c: Cutout, ra_guess: float, dec_guess: float, radius_px: float = 5.0,
                     mask_core_px: float = 0.0):
    """Return (ra, dec, n_pixels_used) for the star nearest the guess, or None."""
    xg, yg = c.wcs.all_world2pix(ra_guess, dec_guess, 0)
    ny, nx = c.image.shape
    yy, xx = np.mgrid[:ny, :nx]
    near = (xx - xg) ** 2 + (yy - yg) ** 2 <= radius_px ** 2
    good = near & np.isfinite(c.image) & ((c.flags & UNTRUSTED) == 0)
    if mask_core_px:  # test mode: pretend the core is saturated
        good &= (xx - xg) ** 2 + (yy - yg) ** 2 > mask_core_px ** 2
    if good.sum() < 12:
        return None
    x, y, z = xx[good].astype(float), yy[good].astype(float), c.image[good]
    sig = np.sqrt(np.clip(c.variance[good], 1e-6, None) + (0.05 * z) ** 2)
    p0 = [float(xg), float(yg), np.nanmax(z) * 3, 1.5, 2.0, 0.0]
    lo = [xg - 2.5, yg - 2.5, 0, 0.3, 1.0, -np.inf]
    hi = [xg + 2.5, yg + 2.5, np.inf, 10, 10, np.inf]
    fit = least_squares(lambda p: (_moffat(p, x, y) - z) / sig, p0, bounds=(lo, hi), loss="soft_l1")
    if not fit.success:
        return None
    ra, dec = c.wcs.all_pix2world(fit.x[0], fit.x[1], 0)
    return float(ra), float(dec), int(good.sum())


def predict_position(star: dict, mjd: float):
    """Apparent (ra, dec) in degrees at the given date, seen from Earth.

    star: ra, dec (deg, at `epoch` in Julian years), pmra, pmdec (mas/yr, pmra
    already includes cos(dec)), parallax (mas).
    """
    t = Time(mjd, format="mjd")
    dt = t.jyear - star["epoch"]
    dec0 = np.radians(star["dec"])
    ra = star["ra"] + dt * star["pmra"] / 3.6e6 / np.cos(dec0)
    dec = star["dec"] + dt * star["pmdec"] / 3.6e6
    # parallax: the star appears displaced opposite to Earth's position
    X, Y, Z = get_body_barycentric("earth", t).xyz.to_value(u.au)
    a, d = np.radians(ra), np.radians(dec)
    plx = star["parallax"] / 3.6e6  # degrees
    ra += plx * (X * np.sin(a) - Y * np.cos(a)) / np.cos(d)
    dec += plx * (X * np.cos(a) * np.sin(d) + Y * np.sin(a) * np.sin(d) - Z * np.cos(d))
    return float(ra), float(dec)
