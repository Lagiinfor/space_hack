"""Extra frames from other telescopes, added to the flip-book as extra dates.

These are NOT like-for-like with SPHEREx (different telescope, wavelengths, pixel size and
depth), so they are never used in the fair brightness comparison. They are there to see
POSITION change over a much longer time: WISE in 2010, Canada's NEOSSat where it looked.

Sources
- WISE (NASA): the AllWISE Atlas images, made from the 2010 survey, at 3.4 um (W1) and
  4.6 um (W2), through the same NASA/IPAC IRSA cutout service as SPHEREx. All-sky, so every
  patch gets a 2010 frame.
- NEOSSat (Canadian Space Agency), via the Canadian Astronomy Data Centre (CADC). A small
  space telescope that mostly hunts asteroids and satellites, so it covers only a few
  percent of the sky. Its archive images are raw: they carry the pointing but no precise
  sky coordinates, so we work those out by matching the stars in each image to the Gaia
  catalogue (plate solving), then stack the aligned images.
"""
from __future__ import annotations

import csv
import io
import json
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS, FITSFixedWarning
from scipy.ndimage import gaussian_filter, maximum_filter

from . import frames

warnings.simplefilter("ignore", FITSFixedWarning)
IRSA_SIA = "https://irsa.ipac.caltech.edu/SIA"
CADC_TAP = "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/argus/sync"
CADC_DATA = "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/data/pub/NEOSSAT/"
_s = requests.Session()


def _get(url, params=None, tries=4, timeout=120):
    last = None
    for i in range(tries):
        try:
            r = _s.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code}")
        except requests.RequestException as e:
            last = e
        time.sleep(1.5 * (i + 1))
    raise last


def _robust_noise(img):
    v = img[np.isfinite(img)]
    med = np.median(v)
    return med, 1.4826 * np.median(np.abs(v - med))


# ---------------------------------------------------------------- WISE 2010
def wise_frames(ra: float, dec: float, field_deg: float) -> list[dict]:
    """AllWISE (2010) W1 and W2 images of the patch, redrawn on the flip-book grid."""
    grid, shape = frames.target_grid(ra, dec, field_deg)
    rows = list(csv.DictReader(io.StringIO(_get(IRSA_SIA, {"COLLECTION": "wise_allwise",
                                                           "POS": f"circle {ra} {dec} 0.001",
                                                           "RESPONSEFORMAT": "csv"}).text)))
    out = []
    for band, wl in (("W1", 3.4), ("W2", 4.6)):
        sci = [r for r in rows if r["energy_bandpassname"] == band and r["dataproduct_subtype"] == "science"]
        if not sci:
            continue
        r = sci[0]
        raw = _get(r["access_url"], {"center": f"{ra},{dec}d", "size": f"{field_deg * 1.5}"}).content
        if raw[:2] == bytes([0x1F, 0x8B]):            # the archive sends this one gzip-compressed
            import gzip
            raw = gzip.decompress(raw)
        if not raw.startswith(b"SIMPLE"):
            continue
        with fits.open(io.BytesIO(raw)) as h:
            img = h[0].data.astype(float)
            w = WCS(h[0].header)
        img = frames.resample(img, w, grid, shape)
        med, sd = _robust_noise(img)
        img = img - med
        out.append(dict(source="WISE", band=band, wl=wl, mjd=0.5 * (float(r["t_min"]) + float(r["t_max"])),
                        date_text="2010", start=float(r["t_min"]), end=float(r["t_max"]),
                        note="NASA's WISE telescope (AllWISE Atlas image, made from the 2010 survey)",
                        img=img, noise=float(max(sd, 1e-9))))
    return out


# ---------------------------------------------------------------- NEOSSat
def neossat_list(ra: float, dec: float) -> list[dict]:
    """NEOSSat science images (from CADC) whose footprint contains the position.
    One entry per observation, preferring the cleaned + dark-subtracted file."""
    q = ("SELECT o.observationID, o.target_name, p.productID, p.time_bounds_lower, a.uri FROM caom2.Observation o "
         "JOIN caom2.Plane p ON o.obsID=p.obsID JOIN caom2.Artifact a ON a.planeID=p.planeID "
         f"WHERE o.collection='NEOSSAT' AND INTERSECTS(POINT('ICRS',{ra},{dec}), p.position_bounds)=1")
    txt = _get(CADC_TAP, {"LANG": "ADQL", "FORMAT": "csv", "QUERY": q}).text
    rank = {"cord": 0, "cor": 1, "raw": 2}
    best: dict = {}
    for r in csv.DictReader(io.StringIO(txt)):
        if not r["uri"].endswith(".fits") or (r.get("target_name") or "").upper() == "DARK":
            continue
        k = rank.get(r["productID"], 3)
        if r["observationID"] not in best or k < best[r["observationID"]]["rank"]:
            best[r["observationID"]] = dict(obs=r["observationID"], mjd=float(r["time_bounds_lower"]),
                                            file=r["uri"].split("/")[-1], kind=r["productID"], rank=k)
    return sorted(best.values(), key=lambda x: x["mjd"])


def _gaia_stars(ra, dec, radius_deg, epoch_jyear, gmax=13.5):
    q = (f"SELECT TOP 400 ra, dec, pmra, pmdec, phot_g_mean_mag FROM gaiadr3.gaia_source WHERE "
         f"1=CONTAINS(POINT(ra,dec),CIRCLE({ra},{dec},{radius_deg})) AND phot_g_mean_mag < {gmax} "
         f"ORDER BY phot_g_mean_mag")
    txt = _get("https://gea.esac.esa.int/tap-server/tap/sync",
               {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": q}).text
    out = []
    for r in csv.DictReader(io.StringIO(txt)):
        pmra = float(r["pmra"] or 0); pmde = float(r["pmdec"] or 0); d = float(r["dec"])
        dt = epoch_jyear - 2016.0
        out.append((float(r["ra"]) + dt * pmra / 3.6e6 / np.cos(np.radians(d)), d + dt * pmde / 3.6e6,
                    float(r["phot_g_mean_mag"])))
    return out


def _detect(img, n=40):
    sm = gaussian_filter(img, 1.2)
    med, sd = _robust_noise(sm)
    pk = (sm == maximum_filter(sm, 7)) & (sm > med + 8 * sd)
    ys, xs = np.where(pk)
    vals = sm[ys, xs]
    keep = np.argsort(vals)[::-1][:n]
    # sub-pixel centroids
    pts = []
    for y, x in zip(ys[keep], xs[keep]):
        y0, y1, x0, x1 = max(0, y - 2), min(img.shape[0], y + 3), max(0, x - 2), min(img.shape[1], x + 3)
        cut = np.clip(sm[y0:y1, x0:x1] - med, 0, None)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        if cut.sum() > 0:
            pts.append(((xx * cut).sum() / cut.sum(), (yy * cut).sum() / cut.sum()))
    return np.array(pts)


def _solve(img, ra_hint, dec_hint, stars, scale_arcsec=3.0, hint=None):
    """Find the rotation and shift that map detected stars onto Gaia stars (fixed pixel
    scale, allowing a mirror flip). Returns a WCS or None."""
    pts = _detect(img)
    if len(pts) < 5:
        return None
    cosd = np.cos(np.radians(dec_hint))
    gx = np.array([((s[0] - ra_hint + 180) % 360 - 180) * 3600 * cosd for s in stars])   # east, arcsec
    gy = np.array([(s[1] - dec_hint) * 3600 for s in stars])                              # north
    cx, cy = img.shape[1] / 2, img.shape[0] / 2
    best = None
    # hint = (flip, angle) from an earlier photo of the same visit: only search near it
    trials = ([(hint[0], a) for a in hint[1] + np.radians(np.arange(-3, 3.01, 0.5))] if hint else
              [(f, a) for f in (1, -1) for a in np.radians(np.arange(0, 360, 1.0))])
    for flip, ang in trials:
        if True:
            c, s_ = np.cos(ang), np.sin(ang)
            px = (pts[:, 0] - cx) * scale_arcsec * flip
            py = (pts[:, 1] - cy) * scale_arcsec
            ex = c * px - s_ * py
            ny = s_ * px + c * py
            # vote for the shift between every detected star and every Gaia star
            dx = (gx[None, :] - ex[:, None]).ravel()
            dy = (gy[None, :] - ny[:, None]).ravel()
            H, xe, ye = np.histogram2d(dx, dy, bins=[np.arange(-1500, 1500, 6), np.arange(-1500, 1500, 6)])
            k = np.unravel_index(np.argmax(H), H.shape)
            if best is None or H[k] > best[0]:
                best = (H[k], flip, ang, xe[k[0]] + 3, ye[k[1]] + 3)
    votes, flip, ang, sx, sy = best
    if votes < 5:
        return None
    # refine with matched pairs (least squares, similarity transform)
    c, s_ = np.cos(ang), np.sin(ang)
    px = (pts[:, 0] - cx) * scale_arcsec * flip
    py = (pts[:, 1] - cy) * scale_arcsec
    ex = c * px - s_ * py + sx
    ny = s_ * px + c * py + sy
    pairs = []
    for i in range(len(pts)):
        d = np.hypot(gx - ex[i], gy - ny[i])
        j = int(np.argmin(d))
        if d[j] < 8:
            pairs.append((i, j))
    if len(pairs) < 5:
        return None
    # model: east = a*fX - b*Y + tx ; north = b*fX + a*Y + ty   (arcsec; f = mirror flip)
    A, rhs = [], []
    for i, j in pairs:
        fX, Y = flip * (pts[i, 0] - cx), pts[i, 1] - cy
        A += [[fX, -Y, 1, 0], [Y, fX, 0, 1]]
        rhs += [gx[j], gy[j]]
    A = np.array(A, float); rhs = np.array(rhs, float)
    sol, *_ = np.linalg.lstsq(A, rhs, rcond=None)
    resid = np.hypot(*(A @ sol - rhs).reshape(-1, 2).T)
    if np.median(resid) > 4:
        return None
    a_, b_, tx, ty = sol
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crpix = [cx + 1, cy + 1]
    w.wcs.crval = [ra_hint + tx / 3600 / cosd, dec_hint + ty / 3600]
    # intermediate coordinates: xi points east, eta points north (degrees)
    w.wcs.cd = np.array([[a_ * flip / 3600, -b_ / 3600],
                         [b_ * flip / 3600, a_ / 3600]])
    w._hint = (flip, float(np.arctan2(b_, a_)))
    w._n_matched = len(pairs)
    w._resid = float(np.median(resid))
    return w


def neossat_frames(ra: float, dec: float, field_deg: float, cache_dir: Path, max_per_visit: int = 15,
                   progress=lambda s: None) -> tuple[list[dict], dict]:
    """Stack NEOSSat images of the patch, one frame per observing period. Returns
    (frames, summary). Summary always says how many NEOSSat images exist here."""
    lst = neossat_list(ra, dec)
    summary = dict(n_images=len(lst))
    if not lst:
        return [], summary
    mj = np.array([x["mjd"] for x in lst])
    summary["first"] = Time(mj.min(), format="mjd").strftime("%Y-%m-%d")
    summary["last"] = Time(mj.max(), format="mjd").strftime("%Y-%m-%d")
    # group into observing periods (gap > 30 days), take up to max_per_visit spread out in each
    groups, cur = [], [lst[0]]
    for x in lst[1:]:
        if x["mjd"] - cur[-1]["mjd"] > 30:
            groups.append(cur); cur = []
        cur.append(x)
    groups.append(cur)
    grid, shape = frames.target_grid(ra, dec, field_deg)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for g in groups:
        pick = [g[int(i)] for i in np.linspace(0, len(g) - 1, min(max_per_visit, len(g)))]
        epoch = Time(np.mean([x["mjd"] for x in pick]), format="mjd").jyear
        stars = _gaia_stars(ra, dec, 0.6 if pick[0]["kind"] != "raw" else 0.35, epoch)
        if len(stars) < 5:
            continue

        def fetch(x):
            p = cache_dir / x["file"]
            if not p.exists():
                r = _get(CADC_DATA + x["file"])
                p.write_bytes(r.content)
            return p
        progress(f"Downloading {len(pick)} NEOSSat photos from the Canadian archive")
        with ThreadPoolExecutor(8) as pool:
            paths = list(pool.map(fetch, pick))
        stack, used, hint = [], [], None
        for x, p in zip(pick, paths):
            try:
                with fits.open(p) as h:
                    img = h[0].data.astype(float)
                    H = h[0].header
                hint_ra = _hms(H.get("OBJCTRA") or H.get("RA"))
                hint_de = _dms(H.get("OBJCTDEC") or H.get("DEC"))
                img = img - np.nanmedian(img, axis=0, keepdims=True)    # remove column-wise bias
                img = np.nan_to_num(img)
                w = _solve(img, hint_ra, hint_de, stars, hint=hint) or (hint and _solve(img, hint_ra, hint_de, stars))
                if not w:
                    continue
                hint = w._hint
                stack.append(frames.resample(img, w, grid, shape))
                used.append(x)
            except Exception:
                continue
        if not stack:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            img = np.nanmedian(stack, axis=0)
        med, sd = _robust_noise(img)
        t0, t1 = min(x["mjd"] for x in used), max(x["mjd"] for x in used)
        out.append(dict(source="NEOSSat", band="visible", wl=0.6, mjd=float(np.mean([x["mjd"] for x in used])),
                        date_text=Time((t0 + t1) / 2, format="mjd").strftime("%b %Y"), start=t0, end=t1,
                        note=f"Canada's NEOSSat (Canadian Space Agency), {len(used)} short photos aligned to Gaia stars "
                             "and stacked; images from the Canadian Astronomy Data Centre",
                        img=img - med, noise=float(max(sd, 1e-9)), n=len(used), n_available=len(g)))
    return out, summary


def _hms(v):
    a = [float(x) for x in str(v).replace(":", " ").split()]
    return 15 * (a[0] + a[1] / 60 + a[2] / 3600)


def _dms(v):
    s = str(v).strip()
    sign = -1 if s.startswith("-") else 1
    a = [abs(float(x)) for x in s.replace(":", " ").replace("+", "").replace("-", "").split()]
    return sign * (a[0] + a[1] / 60 + a[2] / 3600)
