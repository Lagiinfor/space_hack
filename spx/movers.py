# From the shared engine package (spherex-flipbook/spx/movers.py), unchanged.
"""Blind search for things that moved between sky passes, with no catalogue needed.

Steps:
1. In each pass's stacked frame, find every point of light and measure its position.
2. Link each one to its nearest neighbour in the other passes.
3. Most links are ordinary stars that did not move; their scatter tells us how
   precisely positions repeat in THIS field. Anything that shifted by many times
   that scatter, steadily in one direction, is a mover.
4. Ask Gaia whether it predicts that motion. If yes: a known star. If Gaia has no
   moving star there: a candidate worth a human look.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter
from scipy.optimize import least_squares

from . import astrometry


def find_sources(img: np.ndarray, grid_wcs, min_snr: float = 6.0, edge: int = 4) -> list[dict]:
    """Every point of light in a stacked frame: ra, dec, snr, peak."""
    clean = np.nan_to_num(img - np.nanmedian(img))
    smooth = gaussian_filter(clean, 1.0)
    noise = 1.4826 * np.median(np.abs(smooth - np.median(smooth)))
    peaks = (smooth == maximum_filter(smooth, size=5)) & (smooth > min_snr * noise)
    ny, nx = img.shape
    yy, xx = np.mgrid[:ny, :nx]
    out = []
    for py, px in zip(*np.where(peaks)):
        if not (edge <= px < nx - edge and edge <= py < ny - edge):
            continue
        sl = (slice(py - 3, py + 4), slice(px - 3, px + 4))
        X, Y, Z = xx[sl].ravel(), yy[sl].ravel(), clean[sl].ravel()

        def resid(p):
            return p[2] * np.exp(-((X - p[0]) ** 2 + (Y - p[1]) ** 2) / (2 * p[3] ** 2)) + p[4] - Z

        try:
            fit = least_squares(resid, [px, py, clean[py, px], 1.3, 0.0],
                                bounds=([px - 2, py - 2, 0, 0.7, -np.inf], [px + 2, py + 2, np.inf, 3.0, np.inf]))
        except ValueError:
            continue
        ra, dec = grid_wcs.all_pix2world(fit.x[0], fit.x[1], 0)
        out.append(dict(ra=float(ra), dec=float(dec), snr=float(smooth[py, px] / noise),
                        peak=float(clean[py, px]), x=float(fit.x[0]), y=float(fit.x[1])))
    return out


def find_movers(images: list, mjds: list[float], grid_wcs, max_rate_arcsec_yr: float = 12.0,
                min_shift_arcsec: float = 1.5, min_sigma: float = 5.0, min_snr: float = 6.0) -> dict:
    """Compare stacked frames of the same field from different passes.

    images: one stacked frame per pass (None for missing passes). mjds: their dates.
    Returns dict(movers=[...], n_sources, repeatability_arcsec).
    Each mover: ra/dec per pass, shift (arcsec), rate (arcsec/yr east and north),
    sigma (how many times the field's own scatter), snr.
    """
    have = [k for k, im in enumerate(images) if im is not None]
    if len(have) < 2:
        return dict(movers=[], n_sources=0, repeatability_arcsec=None)
    cosd = np.cos(np.radians(grid_wcs.wcs.crval[1]))
    src = {k: find_sources(images[k], grid_wcs, min_snr) for k in have}
    ref = max(have, key=lambda k: len(src[k]))          # pass with most sources anchors the links

    def offsets(a, b):
        """(east, north) offsets in arcsec from source a to every source in list b."""
        e = np.array([(s["ra"] - a["ra"]) * 3600 * cosd for s in b])
        n = np.array([(s["dec"] - a["dec"]) * 3600 for s in b])
        return e, n

    tracks = []
    for s in src[ref]:
        tr = {ref: s}
        for k in have:
            if k == ref or not src[k]:
                continue
            reach = max(3.0, max_rate_arcsec_yr * abs(mjds[k] - mjds[ref]) / 365.25)
            e, n = offsets(s, src[k])
            d = np.hypot(e, n)
            j = int(np.argmin(d))
            if d[j] <= reach:
                # the neighbour must also prefer us (avoids two stars swapping partners)
                e2, n2 = offsets(src[k][j], src[ref])
                if src[ref][int(np.argmin(np.hypot(e2, n2)))] is s:
                    tr[k] = src[k][j]
        if len(tr) >= 2:
            tracks.append(tr)
    need = 3 if len(have) >= 3 else 2     # with 3+ passes, a mover must be seen in at least 3

    # per-pass zero point and scatter from the crowd of ordinary stars
    zero, scatter = {}, {}
    for k in have:
        if k == ref:
            zero[k], scatter[k] = (0.0, 0.0), 0.0
            continue
        de = np.array([(t[k]["ra"] - t[ref]["ra"]) * 3600 * cosd for t in tracks if k in t])
        dn = np.array([(t[k]["dec"] - t[ref]["dec"]) * 3600 for t in tracks if k in t])
        if len(de) >= 5:
            zero[k] = (float(np.median(de)), float(np.median(dn)))
            scatter[k] = float(1.4826 * np.median(np.hypot(de - zero[k][0], dn - zero[k][1])))
        else:
            zero[k], scatter[k] = (0.0, 0.0), 0.5
    floor = max(0.15, float(np.median([scatter[k] for k in have if k != ref])))

    movers = []
    for t in tracks:
        ks = sorted(t)
        tt = np.array([mjds[k] for k in ks]) / 365.25
        e = np.array([(t[k]["ra"] - t[ref]["ra"]) * 3600 * cosd - zero[k][0] for k in ks])
        n = np.array([(t[k]["dec"] - t[ref]["dec"]) * 3600 - zero[k][1] for k in ks])
        err = np.array([np.hypot(floor, 9.0 / 2.35 / t[k]["snr"]) for k in ks])
        shift = float(np.hypot(e[-1] - e[0], n[-1] - n[0]))
        sigma = shift / float(np.hypot(err[0], err[-1]))
        if shift < min_shift_arcsec or sigma < min_sigma or len(ks) < need:
            continue
        rate_e = float(np.polyfit(tt, e, 1)[0])
        rate_n = float(np.polyfit(tt, n, 1)[0])
        if len(ks) >= 3:      # with 3+ passes the motion must be steady, not a one-off jump
            fit_e, fit_n = np.polyval(np.polyfit(tt, e, 1), tt), np.polyval(np.polyfit(tt, n, 1), tt)
            wobble = float(np.max(np.hypot(e - fit_e, n - fit_n)))
            if wobble > max(1.5, 0.35 * shift):
                continue
        movers.append(dict(passes=ks, ra=[t[k]["ra"] for k in ks], dec=[t[k]["dec"] for k in ks],
                           shift_arcsec=shift, sigma=sigma, rate_east=rate_e, rate_north=rate_n,
                           snr=float(np.median([t[k]["snr"] for k in ks]))))
    movers.sort(key=lambda m: -m["sigma"])
    return dict(movers=movers, n_sources=len(tracks), repeatability_arcsec=floor)


def explain_with_gaia(movers: list[dict], gaia: list[dict], mjds: list[float], match_arcsec: float = 4.0) -> None:
    """Label each mover 'known' (a Gaia star predicted to move like this) or
    'candidate' (nothing in Gaia explains it). Adds keys in place."""
    for m in movers:
        m["status"], m["gaia"] = "candidate: no Gaia star predicts this motion", None
        k0, k1 = m["passes"][0], m["passes"][-1]
        years = (mjds[k1] - mjds[k0]) / 365.25
        best = None
        for g in gaia:
            p0 = astrometry.predict_position(g, mjds[k0])
            p1 = astrometry.predict_position(g, mjds[k1])
            cosd = np.cos(np.radians(p0[1]))
            sep = np.hypot((p0[0] - m["ra"][0]) * 3600 * cosd, (p0[1] - m["dec"][0]) * 3600)
            if sep > match_arcsec:
                continue
            pred_e = (p1[0] - p0[0]) * 3600 * cosd
            pred_n = (p1[1] - p0[1]) * 3600
            miss = np.hypot(pred_e - m["rate_east"] * years, pred_n - m["rate_north"] * years)
            if best is None or miss < best[0]:
                best = (float(miss), g, float(np.hypot(pred_e, pred_n)))
        if best:
            miss, g, pred_shift = best
            m["gaia"] = dict(source_id=g["source_id"], gmag=g["gmag"], predicted_shift_arcsec=pred_shift,
                             mismatch_arcsec=miss)
            if miss <= max(1.5, 0.3 * m["shift_arcsec"]):
                m["status"] = "known: Gaia predicts this motion"
            elif pred_shift < 0.5:
                m["status"] = "suspect: Gaia has a star here that should NOT move (likely a measurement glitch)"
