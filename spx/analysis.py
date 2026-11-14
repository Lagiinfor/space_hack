"""Things computed on demand from the downloaded cutouts of one position:

- spectrum():  brightness of one object in every single exposure, against wavelength,
               grouped by sky pass ("every pixel is a spectrum, every spectrum has a history")
- lens():      stacks of exposures within chosen wavelength windows, for the
               molecule lenses (false-colour views that make chemistry visible)
- flags_map(): how often each pixel was flagged as a problem, by kind
- gaia():      Gaia DR3 stars in the field, with where each should be at each pass
"""
from __future__ import annotations

import io
import json
import threading
import warnings
from collections import OrderedDict
from pathlib import Path

import numpy as np
import requests

from . import flipbook, frames

warnings.filterwarnings("ignore")

_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_lock = threading.Lock()


def load_position(ra: float, dec: float, field_deg: float) -> dict:
    """All cleaned cutouts for a position that has already been built, kept in memory
    for the two most recent positions."""
    ra, dec = round(ra, 4), round(dec, 4)
    key = (ra, dec, field_deg)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    with _loading.setdefault(key, threading.Lock()):  # one download/load per position at a time
        with _lock:
            if key in _cache:
                return _cache[key]
        return _load(ra, dec, field_deg, key)


_loading: dict = {}


def _load(ra, dec, field_deg, key):
    res = json.loads(flipbook.saved_path(ra, dec, field_deg).read_text())
    cut_deg = round(max(0.1, field_deg * 1.5), 3)
    cdir = flipbook.place_dir(ra, dec) / f"cutouts_{cut_deg}"
    # The shared copy of the project (GitHub) carries the stacked pictures but not the
    # ~45 MB of single photos per target. Fetch any that are missing (about 2 minutes).
    listing = flipbook.place_dir(ra, dec) / "images.json"
    if listing.exists():
        from . import archive
        images = json.loads(listing.read_text())
        have = len(list(cdir.glob("*.fits"))) if cdir.exists() else 0
        if have < 0.97 * len(images):   # many missing: try again (already-saved photos are skipped)
            print(f"  downloading the single photos for RA {ra} Dec {dec} (needed for spectra and lenses)...")
            archive.fetch_all(images, ra, dec, cut_deg, cdir)
    cuts = []
    for p in sorted(cdir.glob("*.fits")):
        try:
            cuts.append(frames.load_cutout(p, ra, dec))
        except Exception:
            pass
    # use the SAME pass numbers as the saved pictures (not a fresh guess), so spectra,
    # flags and lenses always talk about the same sky passes as the flip-book
    saved = {(e.get("obs_id"), e["band"]): e["pass_index"] for e in res.get("exposures", [])}
    if all((c.obs_id, c.detector) in saved for c in cuts):
        passes = np.array([saved[(c.obs_id, c.detector)] for c in cuts])
    else:
        passes = frames.assign_passes([c.mjd for c in cuts])
    entry = dict(result=res, cuts=cuts, passes=passes, ra=ra, dec=dec, field=field_deg)
    with _lock:
        _cache[key] = entry
        while len(_cache) > 2:
            _cache.popitem(last=False)
    return entry


# ---------------------------------------------------------------- spectrum
def _aperture_flux(c: frames.Cutout, ra: float, dec: float, r_ap: float = 2.0,
                   r_in: float = 4.0, r_out: float = 7.0):
    """Sum the light within r_ap pixels of (ra, dec) minus the local background
    measured in a ring around it. Sub-pixel accurate (each pixel split 5x5).
    Returns (flux_mJy, error_mJy, problem_fraction, saturated) or None."""
    x0, y0 = c.wcs.all_world2pix(ra, dec, 0)
    ny, nx = c.image.shape
    if not (r_out <= x0 < nx - r_out and r_out <= y0 < ny - r_out):
        return None
    yy, xx = np.mgrid[:ny, :nx]
    r = np.hypot(xx - x0, yy - y0)
    # fraction of each pixel inside the aperture, from a 5x5 sub-grid
    sub = (np.arange(5) + 0.5) / 5 - 0.5
    frac = np.zeros_like(r)
    near = r < r_ap + 1
    for dy in sub:
        for dx in sub:
            frac[near] += (np.hypot(xx[near] + dx - x0, yy[near] + dy - y0) <= r_ap) / 25.0
    img, var = c.image, c.variance
    ring = (r >= r_in) & (r <= r_out) & np.isfinite(img)
    if ring.sum() < 10:
        return None
    bkg = np.median(img[ring])
    inside = frac > 0
    good = inside & np.isfinite(img)
    w_total = frac[inside].sum()
    w_good = frac[good].sum()
    if w_good < 0.6 * w_total:
        return "burnt"           # centre has no values: a saturated star
    flux = np.sum((img[good] - bkg) * frac[good]) * (w_total / w_good)
    err = np.sqrt(np.nansum(np.clip(var[good], 0, None) * frac[good] ** 2)) * (w_total / w_good)
    sat = bool(np.any(c.flags[inside & (frac > 0.3)] & frames.SATURATED) or (w_good < 0.98 * w_total))
    # MJy/sr * pixel solid angle (sr) -> MJy -> mJy
    pix_sr = np.abs(np.linalg.det(c.wcs.pixel_scale_matrix)) * (np.pi / 180) ** 2
    to_mjy = pix_sr * 1e9
    return float(flux * to_mjy), float(err * to_mjy), float(1 - w_good / w_total), sat


def _wing_flux(c: frames.Cutout, ra: float, dec: float, r1: float = 3.0, r2: float = 6.0,
               b1: float = 8.0, b2: float = 11.0):
    """For stars so bright their centre is burnt out: measure the light in a ring
    3-6 pixels out (the star's outer glow, which is not saturated), minus the sky
    8-11 pixels out. Not a total brightness, but the same ring at the same wavelength
    can be compared fairly between sky passes. Returns (flux_mJy, err_mJy) or None."""
    x0, y0 = c.wcs.all_world2pix(ra, dec, 0)
    ny, nx = c.image.shape
    if not (b2 <= x0 < nx - b2 and b2 <= y0 < ny - b2):
        return None
    yy, xx = np.mgrid[:ny, :nx]
    r = np.hypot(xx - x0, yy - y0)
    img = c.image
    ann = (r >= r1) & (r < r2)
    good = ann & np.isfinite(img) & ((c.flags & frames.SATURATED) == 0)
    bring = (r >= b1) & (r < b2) & np.isfinite(img)
    if good.sum() < 0.7 * ann.sum() or bring.sum() < 20:
        return None
    bkg = np.median(img[bring])
    scale = ann.sum() / good.sum()
    flux = np.sum(img[good] - bkg) * scale
    err = np.sqrt(np.sum(np.clip(c.variance[good], 0, None))) * scale
    pix_sr = np.abs(np.linalg.det(c.wcs.pixel_scale_matrix)) * (np.pi / 180) ** 2
    return float(flux * pix_sr * 1e9), float(err * pix_sr * 1e9)


def _follow(pos: dict, ra: float, dec: float, max_shift_px: float = 3.0) -> dict:
    """A moving object sits in a slightly different place in each pass. Find it in
    each pass's stacked picture (the band where it is clearest) so the spectrum
    follows the object instead of measuring empty sky where it used to be.
    Returns {pass_index: (ra, dec, shift_arcsec)}."""
    import base64
    res = pos["result"]
    grid, shape = frames.target_grid(pos["ra"], pos["dec"], pos["field"])
    n = shape[0]
    x0, y0 = grid.all_world2pix(ra, dec, 0)
    if not (3 <= x0 < n - 3 and 3 <= y0 < n - 3):
        return {}
    stacks = {}
    for f in res["frames"]:
        arr = np.frombuffer(base64.b64decode(f["pixels"]), dtype="<f4").reshape(shape)
        stacks[(f["band"], f["pass_index"])] = (arr, f["noise"])
    yy, xx = np.mgrid[:n, :n]
    near = np.hypot(xx - x0, yy - y0) <= max_shift_px
    # pick the band where the object stands out most
    best_band, best_snr = None, 0.0
    for b in range(7):
        imgs = [v for (bb, _), v in stacks.items() if bb == b]
        if not imgs:
            continue
        snr = np.mean([np.nanmax(a[near]) / nz for a, nz in imgs])
        if snr > best_snr:
            best_band, best_snr = b, snr
    out = {}
    if best_band is None or best_snr < 6:
        return out
    for (b, k), (a, nz) in stacks.items():
        if b != best_band:
            continue
        sub = np.where(near & np.isfinite(a), a, -np.inf)
        j = np.unravel_index(np.argmax(sub), sub.shape)
        if a[j] < 5 * nz:
            continue
        win = (np.abs(yy - j[0]) <= 2) & (np.abs(xx - j[1]) <= 2)
        w = np.clip(np.nan_to_num(a[win]) - np.nanmedian(a), 0, None)
        if w.sum() <= 0:
            continue
        cx, cy = (xx[win] * w).sum() / w.sum(), (yy[win] * w).sum() / w.sum()
        r_, d_ = grid.all_pix2world(cx, cy, 0)
        out[k] = (float(r_), float(d_), float(np.hypot(cx - x0, cy - y0) * res["pix_arcsec"]))
    return out


def spectrum(ra0: float, dec0: float, field_deg: float, ra: float, dec: float, follow: bool = True) -> dict:
    pos = load_position(ra0, dec0, field_deg)
    where = _follow(pos, ra, dec) if follow else {}
    meas = []
    for c, p in zip(pos["cuts"], pos["passes"]):
        r_, d_ = where.get(int(p), (ra, dec, 0))[:2]
        m = _aperture_flux(c, r_, d_)
        meas.append((c, p, r_, d_, m))
    # if the centre is burnt out in many exposures, switch every exposure to the
    # outer-glow ring so all points are measured the same way
    # 'burnt' = centre saturated; None = off the edge / no coverage (not counted as saturation)
    n_burnt = sum(1 for *_, m in meas if m == "burnt" or (isinstance(m, tuple) and m[3]))
    wing = n_burnt > 0.3 * len(meas)
    pts = []
    for c, p, r_, d_, m in meas:
        if wing:
            w = _wing_flux(c, r_, d_)
            m = (w[0], w[1], 0.0, False) if w else None
        if not isinstance(m, tuple) or not np.isfinite(m[0]):
            continue
        pts.append(dict(wl=round(c.wavelength_at(r_, d_), 4), flux=m[0], err=m[1], band=c.detector,
                        pass_index=int(p), mjd=c.mjd, sat=m[3]))
    # One-off bad photos (a cosmic-ray hit, a satellite) give single points far off the
    # rest. A point is flagged as an outlier when it disagrees with the photos taken at
    # nearly the same wavelength in the same sky pass by much more than their scatter.
    # Real changes move a whole pass together, so they are not affected. Outliers stay on
    # the plot (faded) but are left out of the lines.
    for q in pts:
        q["outlier"] = False
    for k in {q["pass_index"] for q in pts}:
        mine = [q for q in pts if q["pass_index"] == k]
        wl = np.array([q["wl"] for q in mine]); fl = np.array([q["flux"] for q in mine])
        for i, q in enumerate(mine):
            near = (np.abs(wl - q["wl"]) < 0.035 * q["wl"]) & (np.arange(len(mine)) != i)
            if near.sum() < 2:
                continue
            ref = np.median(fl[near])
            spread = max(1.4826 * np.median(np.abs(fl[near] - ref)), q["err"], 0.08 * abs(ref))
            if abs(q["flux"] - ref) > 5 * spread:
                q["outlier"] = True
    # smooth curve per pass: median in wavelength bins about as wide as SPHEREx's resolution
    edges = np.exp(np.linspace(np.log(0.74), np.log(5.02), 56))
    curves = []
    for k in sorted({q["pass_index"] for q in pts}):
        mine = [q for q in pts if q["pass_index"] == k and not q["outlier"]]
        wl = np.array([q["wl"] for q in mine])
        fl = np.array([q["flux"] for q in mine])
        xs, ys = [], []
        for a, b in zip(edges[:-1], edges[1:]):
            sel = (wl >= a) & (wl < b)
            if sel.sum():
                xs.append(float(np.sqrt(a * b)))
                ys.append(float(np.median(fl[sel])))
        curves.append(dict(pass_index=k, wl=xs, flux=ys))
    n_sat = int(n_burnt)
    cosd = np.cos(np.radians(dec))
    followed = {int(k): dict(ra=v[0], dec=v[1], east=((v[0] - ra + 180) % 360 - 180) * 3600 * cosd, north=(v[1] - dec) * 3600)
                for k, v in where.items()}
    return dict(ra=ra, dec=dec, points=pts, curves=curves, n=len(pts), n_saturated=n_sat,
                passes=pos["result"]["passes"], followed=followed, wing=wing)


# ---------------------------------------------------------------- lenses
# Each lens = three wavelength windows (microns) shown as red, green, blue.
# Colours are balanced so that ordinary stars come out white; anything coloured
# has an unusual spectrum.
LENSES = {
    "color": dict(name="Infrared colour", windows=[(3.0, 5.0), (1.6, 3.0), (0.75, 1.6)],
                  explain="Long wavelengths as red, middle as green, short as blue. Ordinary stars look "
                          "white. Cool, dusty or very red objects look orange-red."),
    "methane": dict(name="Methane lens", windows=[(4.1, 4.65), (3.2, 3.45), (1.95, 2.1)],
                    explain="Red = 4.1 to 4.65 µm, where cold brown dwarfs are brightest. Green = 3.2 to "
                            "3.45 µm, where methane gas absorbs. Blue = about 2 µm. Ordinary stars look white; "
                            "methane-rich brown dwarfs look red or magenta. Glowing dust (3.3 µm emission) looks green."),
    "ice": dict(name="Water-ice lens", windows=[(3.55, 3.9), (2.9, 3.15), (2.2, 2.45)],
                explain="Green = 2.9 to 3.15 µm, where water ice absorbs light. Red and blue = wavelengths "
                        "either side of it. Stars seen through icy clouds lose green and look magenta."),
    "co2": dict(name="CO₂ / CO lens", windows=[(4.55, 5.0), (4.2, 4.35), (3.8, 4.05)],
                explain="Green = 4.2 to 4.35 µm, where carbon dioxide (gas or ice) absorbs. Red = 4.55 to "
                        "5 µm (carbon monoxide region), blue = 3.8 to 4.05 µm. Ordinary stars look white."),
}


def lens(ra0: float, dec0: float, field_deg: float, key: str, pass_index: int | None = None) -> dict:
    pos = load_position(ra0, dec0, field_deg)
    L = LENSES[key]
    grid, shape = frames.target_grid(pos["ra"], pos["dec"], field_deg)
    chans, counts = [], []
    for lo, hi in L["windows"]:
        sel = [c for c, p in zip(pos["cuts"], pos["passes"])
               if lo <= c.wavelength < hi and (pass_index is None or p == pass_index)]
        counts.append(len(sel))
        if sel:
            img, _ = frames.coadd(sel, grid, shape)
        else:
            img = np.zeros(shape)
        chans.append(np.nan_to_num(frames.fill_saturated_cores(img)[0]))
    # white balance: ratio of each channel to the middle one, measured on the
    # bright-but-not-extreme pixels (mostly ordinary stars)
    ref = chans[1]
    gains = []
    for ch in chans:
        m = (ref > np.percentile(ref, 97)) & (ch > 0) & (ref < np.percentile(ref, 99.9))
        g = np.median(ref[m] / ch[m]) if m.sum() > 5 else 1.0
        gains.append(float(g) if np.isfinite(g) and g > 0 else 1.0)
    chans = [ch * g for ch, g in zip(chans, gains)]
    from astropy.stats import sigma_clipped_stats
    noises = []
    for i, ch in enumerate(chans):
        _, med, sd = sigma_clipped_stats(ch, sigma=3)
        chans[i] = ch - med
        noises.append(float(max(sd, 1e-6)))
    noise = float(np.mean(noises))
    return dict(key=key, name=L["name"], explain=L["explain"], windows=L["windows"], counts=counts,
                gains=gains, size=shape[0], noise=noise, noises=noises,
                peak=float(max(np.max(c) for c in chans)),
                channels=[flipbook._pack(c) for c in chans])


def lens_list():
    return [dict(key=k, name=v["name"], explain=v["explain"], windows=v["windows"]) for k, v in LENSES.items()]


# ---------------------------------------------------------------- flags
FLAG_GROUPS = {
    "Saturated / bloom": ["OVERFLOW", "NONLINEAR", "BLOOM"],
    "Cosmic ray / transient": ["TRANSIENT", "SUR_ERROR", "OUTLIER", "SNOWBALL"],
    "Ghost / stray light": ["GHOST", "GHOST_FPA", "GHOST_EXT", "HALO", "CROSSTALK"],
    "Satellite streak": ["STREAK"],
    "Bad / hot / dead pixel": ["NONFUNC", "HOT", "COLD", "MISSING_DATA", "DICHROIC"],
    "Persistence (afterimage)": ["PERSIST"],
}


def flags_map(ra0: float, dec0: float, field_deg: float, pass_index: int, band: int) -> dict:
    """Fraction of exposures in which each pixel had each kind of problem."""
    pos = load_position(ra0, dec0, field_deg)
    grid, shape = frames.target_grid(pos["ra"], pos["dec"], field_deg)
    sel = [c for c, p in zip(pos["cuts"], pos["passes"])
           if p == pass_index and (band == 0 or c.detector == band)]
    out = {}
    for name, bits in FLAG_GROUPS.items():
        mask = sum(frames.FLAG_BITS[b] for b in bits)
        acc = np.zeros(shape)
        for c in sel:
            m = ((c.flags & mask) != 0).astype(float)
            acc += np.nan_to_num(frames.resample(m, c.wcs, grid, shape))
        out[name] = acc / max(len(sel), 1)
    return dict(size=shape[0], n=len(sel),
                layers=[dict(name=k, max=float(v.max()), data=flipbook._pack(v)) for k, v in out.items()])


# ---------------------------------------------------------------- Gaia
GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"


def gaia(ra0: float, dec0: float, field_deg: float, gmax: float = 19.0) -> dict:
    """Gaia DR3 stars in the field, with predicted positions at each sky pass
    (proper motion + parallax, as seen from Earth)."""
    ra0, dec0 = round(ra0, 4), round(dec0, 4)
    cache = flipbook.place_dir(ra0, dec0) / f"gaia_{field_deg:.3f}.json"
    res = json.loads(flipbook.saved_path(round(ra0, 4), round(dec0, 4), field_deg).read_text())
    if cache.exists():
        stars = json.loads(cache.read_text())
    else:
        radius = field_deg * 0.75
        q = (f"SELECT source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag "
             f"FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT(ra,dec),CIRCLE({ra0},{dec0},{radius})) "
             f"AND phot_g_mean_mag < {gmax}")
        r = requests.get(GAIA_TAP, params=dict(REQUEST="doQuery", LANG="ADQL", FORMAT="csv", QUERY=q),
                         timeout=90)
        r.raise_for_status()
        import csv
        stars = []
        for row in csv.DictReader(io.StringIO(r.text)):
            f = lambda k: float(row[k]) if row[k] not in ("", None) else 0.0  # noqa: E731
            stars.append(dict(id=row["source_id"], ra=f("ra"), dec=f("dec"), pmra=f("pmra"),
                              pmdec=f("pmdec"), parallax=f("parallax"), g=f("phot_g_mean_mag")))
        cache.write_text(json.dumps(stars))
    from astropy import units as u
    from astropy.coordinates import get_body_barycentric
    from astropy.time import Time

    cosd = np.cos(np.radians(dec0))
    if not stars:
        return dict(stars=[], n=0, note="No Gaia stars found here")
    ra = np.array([s["ra"] for s in stars]); de = np.array([s["dec"] for s in stars])
    pmra = np.array([s["pmra"] for s in stars]); pmde = np.array([s["pmdec"] for s in stars])
    plx = np.array([s["parallax"] for s in stars]) / 3.6e6
    tracks = []
    for p in res["passes"]:
        t = Time(p["mjd"], format="mjd")
        dt = t.jyear - 2016.0
        r_ = ra + dt * pmra / 3.6e6 / np.cos(np.radians(de))
        d_ = de + dt * pmde / 3.6e6
        X, Y, Z = get_body_barycentric("earth", t).xyz.to_value(u.au)
        a_, dd = np.radians(r_), np.radians(d_)
        r_ = r_ + plx * (X * np.sin(a_) - Y * np.cos(a_)) / np.cos(dd)
        d_ = d_ + plx * (X * np.cos(a_) * np.sin(dd) + Y * np.sin(a_) * np.sin(dd) - Z * np.cos(dd))
        tracks.append(np.stack([((r_ - ra0 + 180) % 360 - 180) * 3600 * cosd, (d_ - dec0) * 3600], axis=1))
    tracks = np.stack(tracks, axis=1)  # star, pass, (east, north)
    half = field_deg * 1800
    out = []
    for s, tr in zip(stars, tracks):
        if np.all(np.abs(tr).max(axis=1) > half):
            continue
        out.append(dict(id=s["id"], g=round(s["g"], 2), pm=round(float(np.hypot(s["pmra"], s["pmdec"])), 1),
                        plx=round(s["parallax"], 2), track=np.round(tr, 2).tolist()))
    out.sort(key=lambda d: d["g"])
    return dict(stars=out, n=len(out), note="Gaia DR3; positions in arcsec east/north of the centre")


# ---------------------------------------------------------------- movers
def movers(ra0: float, dec0: float, field_deg: float) -> dict:
    """Blind search for anything that moved between passes (engine's spx/movers.py),
    run on the combined view and on the two longest-wavelength bands (where cold
    brown dwarfs show up), then checked against Gaia."""
    import base64
    from . import movers as mv

    pos = load_position(ra0, dec0, field_deg)
    res = pos["result"]
    grid, shape = frames.target_grid(pos["ra"], pos["dec"], field_deg)
    mjds = [p["mjd"] for p in res["passes"]]
    found = []
    for band in (0, 6, 5):
        imgs = [None] * len(mjds)
        for f in res["frames"]:
            if f["band"] == band and f["n"] >= 6:
                imgs[f["pass_index"]] = np.frombuffer(base64.b64decode(f["pixels"]), dtype="<f4").reshape(shape).astype(float)
        r = mv.find_movers(imgs, mjds, grid)
        for m in r["movers"]:
            m["band"] = band
            if not any(np.hypot((m["ra"][0] - o["ra"][0]) * 3600 * np.cos(np.radians(dec0)),
                                (m["dec"][0] - o["dec"][0]) * 3600) < 4 for o in found):
                found.append(m)
    try:
        g = gaia(ra0, dec0, field_deg)
        cache = flipbook.place_dir(round(ra0, 4), round(dec0, 4)) / f"gaia_{field_deg:.3f}.json"
        stars = json.loads(cache.read_text())
        gl = [dict(source_id=s["id"], gmag=s["g"], ra=s["ra"], dec=s["dec"], pmra=s["pmra"], pmdec=s["pmdec"],
                   parallax=s["parallax"], epoch=2016.0) for s in stars]
        mv.explain_with_gaia(found, gl, mjds)
        gaia_ok = True
    except Exception:
        for m in found:
            m["status"] = "unchecked (Gaia not reachable)"
        gaia_ok = False
    cosd = np.cos(np.radians(pos["dec"]))
    out = []
    for m in found:
        out.append(dict(status=m["status"], band=m["band"], passes=m["passes"],
                        track=[[mv.dra(r_, pos["ra"]) * 3600 * cosd, (d_ - pos["dec"]) * 3600] for r_, d_ in zip(m["ra"], m["dec"])],
                        rate=float(np.hypot(m["rate_east"], m["rate_north"])),
                        rate_east=m["rate_east"], rate_north=m["rate_north"],
                        shift=m["shift_arcsec"], sigma=m["sigma"], snr=m["snr"],
                        gaia=m.get("gaia")))
    return dict(movers=out, gaia_checked=gaia_ok)
