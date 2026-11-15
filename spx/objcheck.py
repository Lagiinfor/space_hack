"""Everything the tool can check automatically about one clicked object:

- what_is_it():   a plain-language guess from the shape of its spectrum
- checks():       is it already known (Gaia, SIMBAD)? did a known asteroid pass here? how does
                  it move? does it have a partner star moving the same way?
- save_report():  keep a report on this computer (with the finder's name for credit)

Nothing here decides for the person: every check says what it looked at and how sure it is.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
from pathlib import Path

import numpy as np
import requests
from astropy.time import Time

from . import flipbook

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
SIMBAD_TAPS = ["https://simbad.cfa.harvard.edu/simbad/sim-tap/sync",
               "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"]
_s = requests.Session()


# ---------------------------------------------------------------- what is it?
def _band(wl, fl, lo, hi):
    m = (wl >= lo) & (wl < hi) & np.isfinite(fl)
    return float(np.median(fl[m])) if m.sum() >= 2 else np.nan


# ---- the published library of SPHEREx brown-dwarf spectra (Gagne et al. 2026, arXiv:2604.22012)
# One standard template per spectral type M8 ... Y1, built from 6,003 SPHEREx spectra of
# ultracool dwarfs. A local copy ships with the app (spx/templates), so this works offline.
_TEMPLATES = None
TYPE_ORDER = ["M8", "M9"] + [f"L{i}" for i in range(10)] + [f"T{i}" for i in range(10)] + ["Y0", "Y1"]


def _templates():
    global _TEMPLATES
    if _TEMPLATES is None:
        f = Path(__file__).parent / "templates" / "spiff_ultracool_templates.json"
        d = json.loads(f.read_text())["templates"]
        _TEMPLATES = {k: (np.array(v["wl"]), np.array(v["flam"])) for k, v in d.items()}
    return _TEMPLATES


def _plain(t):
    kind = {"M": "a very cool red dwarf star, at the border between stars and brown dwarfs",
            "L": "a warm brown dwarf (or the very coolest kind of star)",
            "T": "a cold brown dwarf with methane in its air",
            "Y": "one of the coldest brown dwarfs known"}[t[0]]
    return kind


def template_match(spec: dict) -> dict | None:
    """Compare the spectrum with every template and with a plain glowing body (a star with
    no molecule dips, any temperature). Returns the best type and how much better it fits."""
    pts = [p for p in spec.get("points", []) if not p.get("outlier")]
    if len(pts) < 40:
        return None
    wl = np.array([p["wl"] for p in pts]); fnu = np.array([p["flux"] for p in pts]); er = np.array([p["err"] for p in pts])
    ok = (wl > 1.02) & (wl < 4.95) & np.isfinite(fnu)
    wl, fnu, er = wl[ok], fnu[ok], er[ok]
    if len(wl) < 40:
        return None
    flam = fnu / wl ** 2                      # templates are per unit wavelength
    sig = np.sqrt((er / wl ** 2) ** 2 + (0.08 * np.abs(flam)) ** 2 + (0.02 * np.nanmedian(np.abs(flam))) ** 2)

    def chi2(model):
        w = 1 / sig ** 2
        a = np.sum(w * flam * model) / np.sum(w * model * model)
        if a <= 0:
            return np.inf
        return float(np.sum(w * (flam - a * model) ** 2) / (len(wl) - 1))

    fits = {}
    for name, (tw, tf) in _templates().items():
        fits[name] = chi2(np.interp(wl, tw, tf))
    # plain glowing bodies (Planck curves), 1,200 K to 20,000 K
    best_bb = np.inf
    for T in [1200, 1500, 1800, 2200, 2600, 3000, 3500, 4000, 5000, 6000, 8000, 12000, 20000]:
        x = 14387.8 / (wl * T)
        best_bb = min(best_bb, chi2(1 / (wl ** 5 * np.expm1(np.clip(x, 1e-6, 500)))))
    order = sorted(fits, key=fits.get)
    best = order[0]
    close = [t for t in order if fits[t] <= fits[best] * 1.25 + 0.3]
    idx = sorted(TYPE_ORDER.index(t) for t in close)
    return dict(best=best, chi2=round(fits[best], 2), chi2_plain=round(best_bb, 2),
                range=[TYPE_ORDER[idx[0]], TYPE_ORDER[idx[-1]]], n_close=len(close),
                better=round(best_bb / max(fits[best], 1e-6), 1))


def what_is_it(spec: dict) -> dict:
    """First the published SPHEREx brown-dwarf templates; if none fits clearly better than a
    plain star, fall back to simple shape rules (which also cover dusty objects)."""
    rule = _what_by_rules(spec)
    if spec.get("wing") or rule["confidence"] == "none":
        return rule
    try:
        m = template_match(spec)
    except Exception:
        m = None
    if not m:
        return rule
    rule["template"] = m
    dusty = rule["label"].startswith("Extra infrared glow")
    # a template wins when it fits much better than any plain star AND fits decently in itself
    if m["better"] >= 3 and m["chi2"] < 6 and not (dusty and m["best"][0] in "ML" and m["better"] < 6):
        lo, hi = m["range"]
        span = TYPE_ORDER.index(hi) - TYPE_ORDER.index(lo)
        rng = m["best"] if span == 0 else f"{lo} to {hi}"
        conf = ("fairly confident" if m["better"] >= 8 and m["chi2"] < 3 and span <= 4 else "a reasonable guess")
        why = [f"Best match among the 24 published SPHEREx brown-dwarf templates: type {m['best']}"
               + (f" (types {rng} fit about equally well)" if span else "") + ".",
               f"It fits {m['better']:.0f} times better than any plain star without molecule dips.",
               "Templates: SPIFF library of 6,003 SPHEREx spectra of ultracool dwarfs (Gagné et al. 2026)."]
        if m["chi2"] > 3:
            why.append("The match is not tight, so the object may be blended with a neighbour or unusual.")
        return dict(label=f"Looks like {_plain(m['best'])} (type {m['best']})", confidence=conf, why=why,
                    template=m, numbers=rule.get("numbers"), method="templates")
    rule["why"].insert(-1, "No published brown-dwarf template fits clearly better than a plain star "
                           f"(best: {m['best']}, {m['better']:.1f} times better).")
    rule["method"] = "rules"
    return rule


def _what_by_rules(spec: dict) -> dict:
    """A cautious, rule-based reading of the spectrum's shape. It compares the brightness
    in a few wavelength windows with what a plain, hot star would show (brightness falling
    as 1/wavelength^2 in the infrared) and looks for the dips molecules leave."""
    pts = [p for p in spec.get("points", []) if not p.get("outlier")]
    if len(pts) < 30:
        return dict(label="Not enough clean measurements to tell what this is.", confidence="none", why=[])
    wl = np.array([p["wl"] for p in pts]); fl = np.array([p["flux"] for p in pts]); er = np.array([p["err"] for p in pts])
    snr = float(np.median(np.abs(fl)) / max(np.median(er), 1e-9))
    f10, f13, f14, f16 = _band(wl, fl, 1.0, 1.1), _band(wl, fl, 1.22, 1.32), _band(wl, fl, 1.36, 1.45), _band(wl, fl, 1.55, 1.72)
    f22, f33, f40, f46 = _band(wl, fl, 2.1, 2.3), _band(wl, fl, 3.2, 3.45), _band(wl, fl, 3.9, 4.15), _band(wl, fl, 4.5, 4.9)
    why, wing = [], bool(spec.get("wing"))
    if not np.isfinite([f22, f33, f40, f46]).all() or max(f22, f40, f46) <= 0:
        return dict(label="Too faint or too patchy to tell what this is.", confidence="none", why=[])
    # ratios, each divided by what a plain hot star gives (1/wavelength^2)
    methane = (f40 / f33) / (3.3 / 4.0) ** 2 if f33 > 0 else np.inf       # >1: dip at 3.3 um
    red = (f46 / f22) / (2.2 / 4.7) ** 2 if f22 > 0 else np.inf           # >1: extra light at long wavelengths
    water = (0.5 * (f13 + f16) / f14) if np.isfinite([f13, f14, f16]).all() and f14 > 0 else np.nan
    sig33 = np.median(er[(wl >= 3.2) & (wl < 3.45)]) if ((wl >= 3.2) & (wl < 3.45)).any() else np.inf
    strong = snr > 8
    if snr < 2.5 and not (f40 > 4 * sig33 or f46 > 4 * sig33):
        return dict(label="Too faint for SPHEREx to tell what this is.", confidence="none",
                    why=[f"Typical signal is only {snr:.1f} times the noise."])
    if methane > 2.0 and (methane > 2.5 or red > 2) and f40 > 3 * sig33:
        label = "Looks like a cold brown dwarf (T or Y type)"
        why.append(f"It is {methane:.1f} times brighter at 4.0 µm than at 3.3 µm, compared with an ordinary star: "
                   "the mark of methane gas absorbing light at 3.3 µm.")
        if red > 3:
            why.append("It is also far brighter at long wavelengths than a star would be, as cold objects are.")
        conf = "fairly confident" if strong and methane > 3 else "a reasonable guess"
    elif np.isfinite(water) and water > 1.5 and red < 4:
        label = "Looks like a cool red star or a warm brown dwarf (M or L type), or a cool giant"
        why.append(f"It dips by {100 * (1 - 1 / water):.0f}% near 1.4 µm, where water vapour absorbs. "
                   "Only cool objects (below about 3,500 K) keep water vapour in their air.")
        conf = "fairly confident" if strong else "a reasonable guess"
    elif red > 2.5:
        label = "Extra infrared glow: probably warm dust (a young star with a disk, a dusty old giant, or a galaxy)"
        why.append(f"It is {red:.1f} times brighter at 4.7 µm, relative to 2.2 µm, than a plain star would be.")
        conf = "fairly confident" if strong else "a reasonable guess"
    elif np.isfinite(water) and water > 1.25:
        label = "Looks like a cool red star or a warm brown dwarf (M or L type), or a cool giant"
        why.append(f"It dips by {100 * (1 - 1 / water):.0f}% near 1.4 µm, where water vapour absorbs. "
                   "Only cool objects (below about 3,500 K) keep water vapour in their air.")
        conf = "fairly confident" if strong else "a reasonable guess"
    else:
        label = "Looks like an ordinary star"
        why.append("Its brightness falls smoothly toward longer wavelengths, with no clear molecule dips.")
        conf = "fairly confident" if strong else "a reasonable guess"
    if wing:
        conf = "a rough guess"
        why.append("Careful: this object is so bright that only its outer glow could be measured.")
    why.append("This is a rule-of-thumb reading of the spectrum's shape, not a proper classification.")
    return dict(label=label, confidence=conf, why=why,
                numbers=dict(methane=round(float(methane), 2) if np.isfinite(methane) else None,
                             red=round(float(red), 2) if np.isfinite(red) else None,
                             water=round(float(water), 2) if np.isfinite(water) else None, snr=round(snr, 1)))


# ---------------------------------------------------------------- catalogues
def _tap_csv(url, query, timeout=45, extra=None):
    params = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}
    params.update(extra or {})
    try:
        r = _s.get(url, params=params, timeout=timeout)
    except requests.ConnectionError:      # archives drop a connection now and then: one more try
        import time
        time.sleep(1.0)
        r = _s.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    if not r.text.lstrip().lower().startswith(("main_id", "source_id", '"main_id', "ra", "designation")):
        raise RuntimeError("unexpected answer")
    return list(csv.DictReader(io.StringIO(r.text)))


OTYPES = {"*": "star", "Bla": "blazar (active galaxy)", "BLL": "blazar (active galaxy)", "Rad": "radio source", "X": "X-ray source", "GiC": "galaxy in a cluster", "EmG": "galaxy with emission lines", "RR*": "pulsating star (RR Lyrae type)", "EB*": "eclipsing double star", "PM*": "star with large motion across the sky", "BD*": "brown dwarf", "LM*": "low-mass star",
          "TT*": "young star (T Tauri type)", "Or*": "young variable star", "Mi*": "pulsating red giant (Mira type)",
          "LP*": "long-period variable star", "V*": "variable star", "G": "galaxy", "SBG": "starburst galaxy",
          "IG": "interacting galaxy", "DNe": "dark cloud", "MoC": "molecular cloud", "**": "double star",
          "SB*": "double star", "WD*": "white dwarf", "C*": "carbon star", "AB*": "old giant star (AGB)",
          "RG*": "red giant", "HB*": "old star", "Em*": "star with emission lines", "QSO": "quasar",
          "AGN": "active galaxy", "PN": "planetary nebula", "Y*O": "young star", "IR": "infrared source",
          "NIR": "infrared source", "HV*": "very fast star", "Pe*": "peculiar star", "Ro*": "rotating variable star",
          "Er*": "flare star", "RR*": "pulsating star (RR Lyrae type)", "Ce*": "pulsating star (Cepheid)"}


def simbad_near(ra, dec, radius_arcsec=12.0, also=None):
    """Named objects in SIMBAD near a position; `also` = a second position to try (where a
    fast mover was in the year 2000, which is where SIMBAD lists it)."""
    out, err = [], None
    for (r_, d_, tag) in [(ra, dec, "here")] + ([(also[0], also[1], "where it was in 2000")] if also else []):
        q = ("SELECT TOP 12 main_id, otype, sp_type, ra, dec, pmra, pmdec FROM basic WHERE "
             f"CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{r_},{d_},{radius_arcsec / 3600}))=1 AND otype <> 'Pl'")
        for url in SIMBAD_TAPS:
            try:
                rows = _tap_csv(url, q, extra={"request": "doQuery", "lang": "adql", "format": "csv", "query": q})
                for row in rows:
                    sep = float(np.hypot((float(row["ra"]) - r_) * np.cos(np.radians(d_)), float(row["dec"]) - d_) * 3600)
                    out.append(dict(name=row["main_id"].strip('"'), type_code=row["otype"].strip('"'),
                                    type=OTYPES.get(row["otype"].strip('"'), row["otype"].strip('"')),
                                    sp_type=(row.get("sp_type") or "").strip('"') or None,
                                    sep_arcsec=round(sep, 1), found=tag))
                err = None
                break
            except Exception as e:
                err = str(e)
    seen, uniq = set(), []
    for o in sorted(out, key=lambda o: o["sep_arcsec"]):
        if o["name"] not in seen:
            seen.add(o["name"]); uniq.append(o)
    return uniq, err


def gaia_movers_near(ra, dec, radius_deg=0.5, min_pm=80.0):
    """Gaia stars with clear motion across the sky in a wide circle (for partner search)."""
    q = (f"SELECT source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag FROM gaiadr3.gaia_source WHERE "
         f"1=CONTAINS(POINT(ra,dec),CIRCLE({ra},{dec},{radius_deg})) AND pm > {min_pm}")
    rows = _tap_csv(GAIA_TAP, q, timeout=12)
    f = lambda v: float(v) if v not in ("", None) else 0.0  # noqa: E731
    return [dict(id=r["source_id"], ra=f(r["ra"]), dec=f(r["dec"]), pmra=f(r["pmra"]), pmdec=f(r["pmdec"]),
                 parallax=f(r["parallax"]), g=f(r["phot_g_mean_mag"])) for r in rows]


def _gaia_now(s, jyear):
    dt = jyear - 2016.0
    return (s["ra"] + dt * s["pmra"] / 3.6e6 / np.cos(np.radians(s["dec"])), s["dec"] + dt * s["pmdec"] / 3.6e6)


def checks(ra0, dec0, field_deg, ra, dec, spec=None, movers=None, cats="gaia") -> dict:
    """Run every automatic check for the object at (ra, dec). Each part can fail on its own
    (a catalogue may be unreachable); the result then says so instead of guessing."""
    res = json.loads(flipbook.saved_path(round(ra0, 4), round(dec0, 4), field_deg).read_text())
    mid = float(np.mean([p["mjd"] for p in res["passes"]]))
    jyear = Time(mid, format="mjd").jyear
    cosd = np.cos(np.radians(dec))
    sep = lambda a, b: float(np.hypot(((a - ra + 180) % 360 - 180) * cosd, b - dec) * 3600)  # noqa: E731
    from . import catalogs
    keys = catalogs.parse_keys(cats)
    out = dict(ra=ra, dec=dec, epoch=round(jyear, 2), checked=[catalogs.BY_KEY[k]["short"] for k in keys])

    # ---- motion: from the automatic mover search if this object is one of its finds,
    #      otherwise from where the spectrum measurement found it in each pass
    motion = None
    for m in (movers or {}).get("movers", []):
        e0, n0 = ((ra - ra0 + 180) % 360 - 180) * 3600 * np.cos(np.radians(dec0)), (dec - dec0) * 3600
        if min(np.hypot(t[0] - e0, t[1] - n0) for t in m["track"]) < 10:
            motion = dict(east=m["rate_east"], north=m["rate_north"], rate=m["rate"], source="mover search",
                          sigma=m["sigma"], status=m["status"], known_in=m.get("known_in", []),
                          matches=m.get("matches", []))
    if motion is None and spec and len(spec.get("followed", {})) >= 2 and not spec.get("wing"):
        ks = sorted(spec["followed"], key=int)
        a, b = spec["followed"][ks[0]], spec["followed"][ks[-1]]
        yrs = (res["passes"][int(ks[-1])]["mjd"] - res["passes"][int(ks[0])]["mjd"]) / 365.25
        if yrs > 0.3:
            e, n = (b["east"] - a["east"]) / yrs, (b["north"] - a["north"]) / yrs
            motion = dict(east=float(e), north=float(n), rate=float(np.hypot(e, n)), source="position in each pass",
                          significant=bool(np.hypot(b["east"] - a["east"], b["north"] - a["north"]) > 2.5))
    out["motion"] = motion

    # ---- Gaia: is there a catalogued star here?
    try:
        if "gaia" not in keys:
            raise LookupError("off")
        cache = flipbook.place_dir(round(ra0, 4), round(dec0, 4)) / f"gaia_{field_deg:.3f}.json"
        if not cache.exists():
            from . import analysis
            analysis.gaia(ra0, dec0, field_deg)
        stars = json.loads(cache.read_text())
        best = None
        for s in stars:
            r_, d_ = _gaia_now(s, jyear)
            d = sep(r_, d_)
            if best is None or d < best[0]:
                best = (d, s)
        if best and best[0] < 6:
            s = best[1]
            pm = float(np.hypot(s["pmra"], s["pmdec"])) / 1000
            dist = 3261.6 / s["parallax"] if s["parallax"] > 0.3 else None
            # a clearly moving object next to a Gaia star that stands still = two different things
            other = bool(motion and motion["rate"] > 0.5 and motion.get("sigma", 0) >= 5
                         and abs(pm - motion["rate"]) > max(1.0, 0.5 * motion["rate"]))
            out["gaia"] = dict(found=not other, background_star=other, sep_arcsec=round(best[0], 1),
                               g=round(s["g"], 1), id=s["id"], pm=round(pm, 3), pmra=s["pmra"], pmdec=s["pmdec"],
                               distance_ly=round(dist) if dist else None,
                               parallax=round(float(s["parallax"]), 2) if s.get("parallax") is not None else None,
                               ra=round(float(s["ra"]), 6), dec=round(float(s["dec"]), 6), epoch=2016.0)
        else:
            out["gaia"] = dict(found=False, nearest_arcsec=round(best[0], 1) if best else None)
    except LookupError:
        out["gaia"] = dict(off=True)
    except Exception as e:
        out["gaia"] = dict(error=str(e))

    # ---- the other switched-on catalogues
    try:
        out["catalogs"] = catalogs.check_point(ra0, dec0, field_deg, ra, dec, jyear,
                                               [k for k in keys if k != "simbad"], motion=motion)
    except Exception as e:
        out["catalogs"] = []
        out["catalogs_error"] = str(e)

    # ---- SIMBAD: does it have a name? (fast movers are listed where they were in 2000)
    also = None
    g = out.get("gaia", {})
    if g.get("found") and g["pm"] > 0.1:
        dt = jyear - 2000.0
        also = (ra - dt * g["pmra"] / 3.6e6 / cosd, dec - dt * g["pmdec"] / 3.6e6)
    elif motion and motion["rate"] > 0.5:
        dt = jyear - 2000.0
        also = (ra - dt * motion["east"] / 3600 / cosd, dec - dt * motion["north"] / 3600)
    try:
        if "simbad" not in keys:
            raise LookupError("off")
        radius = 12.0
        named, err = simbad_near(ra, dec, radius, also=also)
        if also and motion and not g.get("found"):
            # measured motions are rough, so the year-2000 position is uncertain: look wider there
            more, _ = simbad_near(also[0], also[1], max(20.0, 0.15 * motion["rate"] * (jyear - 2000.0)))
            for o in more:
                o["found"] = "where it was in 2000"
                if o["name"] not in {x["name"] for x in named} and (o["type_code"] in ("BD*", "PM*", "LM*", "HV*", "*", "**")):
                    named.append(o)
        out["simbad"] = dict(objects=named[:4], error=err)
    except LookupError:
        out["simbad"] = dict(objects=[], off=True)
    except Exception as e:
        out["simbad"] = dict(objects=[], error=str(e))

    # ---- known asteroids that passed over this spot
    try:
        ast = flipbook.place_dir(round(ra0, 4), round(dec0, 4)) / f"asteroids_{field_deg:.3f}.json"
        hits = []
        if ast.exists():
            for o in json.loads(ast.read_text()).get("objects", []):
                for ph in o["photos"]:
                    d = sep(ph["ra"], ph["dec"])
                    if d < 15:
                        hits.append(dict(name=o["name"], sep_arcsec=round(d, 1), seen=ph.get("seen"),
                                         date=Time(ph["mjd"], format="mjd").strftime("%Y-%m-%d %H:%M")))
                        break
            out["asteroids"] = dict(checked=True, hits=hits)
        else:
            out["asteroids"] = dict(checked=False, hits=[])
    except Exception as e:
        out["asteroids"] = dict(checked=False, hits=[], error=str(e))

    # ---- partner: another star moving the same way (a wide pair travelling together)
    try:
        my = None
        if g.get("found") and g["pm"] >= 0.1:
            my = (g["pmra"] / 1000, g["pmdec"] / 1000, 0.03, g.get("id"))          # arcsec/yr, tolerance
        elif motion and motion["rate"] >= 0.5 and (motion.get("sigma", 0) >= 5 or motion.get("significant")):
            my = (motion["east"], motion["north"], 1.0, None)
        if my and "gaia" not in keys:
            out["partner"] = dict(checked=False, off=True)
        elif my:
            partners = []
            for s in gaia_movers_near(ra, dec):
                if my[3] and s["id"] == my[3]:
                    continue
                pe, pn = s["pmra"] / 1000, s["pmdec"] / 1000
                pm = float(np.hypot(pe, pn))
                diff = float(np.hypot(pe - my[0], pn - my[1]))
                r_, d_ = _gaia_now(s, jyear)
                d = sep(r_, d_)
                if d < 3 or pm < 0.1:
                    continue
                if diff <= max(my[2], 0.12 * pm):
                    partners.append(dict(id=s["id"], g=round(s["g"], 1), sep_arcsec=round(d), pm=round(pm, 2),
                                         diff=round(diff, 2),
                                         distance_ly=round(3261.6 / s["parallax"]) if s["parallax"] > 0.3 else None))
            out["partner"] = dict(checked=True, mine=round(float(np.hypot(my[0], my[1])), 2),
                                  partners=sorted(partners, key=lambda p: p["sep_arcsec"])[:3])
        else:
            out["partner"] = dict(checked=False, why="Partner search needs an object moving at least 0.1″ per year "
                                                     "(0.5″ per year when measured from SPHEREx alone).")
    except Exception as e:
        out["partner"] = dict(checked=False, error=str(e))

    # ---- reports already saved on this computer
    prev = []
    if REPORTS.exists():
        for p in sorted(REPORTS.glob("*.json")):
            try:
                r = json.loads(p.read_text())
                if sep(r["ra"], r["dec"]) < 12:
                    prev.append(dict(by=r.get("name") or "someone", when=r.get("saved", "")[:10], file=p.name))
            except Exception:
                pass
    out["reports_here"] = prev
    return out


def save_report(report: dict) -> dict:
    """Keep a report as a file on this computer. There is no shared server yet, so
    'already reported' can only know about reports saved on this same computer."""
    REPORTS.mkdir(exist_ok=True)
    report = dict(report)
    report["saved"] = time.strftime("%Y-%m-%d %H:%M:%S")
    safe = re.sub(r"[^A-Za-z0-9]+", "_", str(report.get("name") or "anonymous"))[:30]
    name = f"report_{time.strftime('%Y%m%d_%H%M%S')}_{safe}.json"
    (REPORTS / name).write_text(json.dumps(report, indent=1))
    return dict(file=name, folder=str(REPORTS))
