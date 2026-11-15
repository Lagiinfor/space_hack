"""Catalogues of known objects that the volunteer can switch on.

Each catalogue is downloaded for a patch only when it is asked for, and saved next to the
patch's other files so it is never downloaded twice. Every source is kept as a position at
a stated date ("epoch"), with a motion across the sky where the catalogue gives a reliable one.

Gaia is handled by analysis.gaia (it also has parallax); everything else is here.
Fetched from: NASA/IPAC IRSA (CatWISE2020), VizieR at the Harvard-Smithsonian CfA (2MASS),
MAST at STScI (Pan-STARRS1), the SkyMapper archive (ANU) and SIMBAD.
"""
from __future__ import annotations

import datetime
import json
import threading

import numpy as np
import requests
from astropy.time import Time

from . import flipbook

# Where each catalogue is fetched from (each archive that publishes it, or a mirror that answers reliably)
VIZIER_CFA = "https://vizier.cfa.harvard.edu/viz-bin/asu-tsv"            # 2MASS
IRSA_SCS = "https://irsa.ipac.caltech.edu/SCS"                           # CatWISE2020 (and 2MASS as a fallback)
MAST_PS1 = "https://catalogs.mast.stsci.edu/api/v0.1/panstarrs/dr2/mean.csv"
SKYMAPPER = "https://skymapper.anu.edu.au/sm-cone/public/query"
NOIRLAB_TAP = "https://datalab.noirlab.edu/tap/sync"                    # CatWISE2020, when IRSA is busy


# colour = the colour of this catalogue's marks on the picture
CATALOGS = [
    dict(key="gaia", name="Gaia DR3", short="Gaia", colour="#4fd765", light="visible light",
         what="ESA's Gaia: 1.8 billion stars with very precise positions and motions. Sees visible light, "
              "so it misses very cold or very red objects.", coverage="whole sky", ref="Gaia Collaboration 2023"),
    dict(key="catwise", name="CatWISE2020", short="CatWISE", colour="#ff9f43", light="infrared (3.4 and 4.6 µm)",
         what="NASA WISE and NEOWISE, 2010 to 2018: 1.9 billion infrared sources with motions. "
              "The best catalogue for cold brown dwarfs that Gaia cannot see.", coverage="whole sky",
         ref="Marocco et al. 2021"),
    dict(key="twomass", name="2MASS", short="2MASS", colour="#ff6bd6", light="near infrared (1.2 to 2.2 µm)",
         what="Two Micron All Sky Survey, photographed 1997 to 2001: where things were about 27 years ago. "
              "No motions.", coverage="whole sky", ref="Skrutskie et al. 2006"),
    dict(key="panstarrs", name="Pan-STARRS1", short="Pan-STARRS", colour="#4cc9f0", light="visible and far-red light",
         what="Pan-STARRS1 from Hawaii, 2010 to 2014: goes much fainter than Gaia in visible and far-red light. "
              "No motions used.", coverage="north of declination -30°", ref="Chambers et al. 2016"),
    dict(key="skymapper", name="SkyMapper DR2", short="SkyMapper", colour="#b8f04c", light="visible light",
         what="SkyMapper Southern Sky Survey from Australia, 2014 to 2018: visible-light catalogue of the "
              "southern sky, where Pan-STARRS cannot look.", coverage="south of declination +2°", ref="Onken et al. 2019"),
    dict(key="simbad", name="SIMBAD", short="SIMBAD", colour="#c9a0ff", light="named objects",
         what="The CDS database of objects that astronomers have studied and named, with their type "
              "(brown dwarf, variable star, galaxy...).", coverage="whole sky (only studied objects)",
         ref="Wenger et al. 2000"),
]
BY_KEY = {c["key"]: c for c in CATALOGS}


_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


def parse_keys(cats) -> list[str]:
    """'gaia,catwise' -> ['gaia', 'catwise'] (unknown names dropped, order as in CATALOGS)."""
    if cats is None:
        return ["gaia"]
    if isinstance(cats, str):
        cats = [c.strip() for c in cats.split(",")]
    return [c["key"] for c in CATALOGS if c["key"] in cats]


def names(keys) -> str:
    return ", ".join(BY_KEY[k]["short"] for k in keys) or "no catalogue"


def covers(key: str, dec: float) -> bool:
    if key == "panstarrs":
        return dec > -30.0
    if key == "skymapper":
        return dec < 2.0
    return True


def _f(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _csv_rows(text: str) -> list[dict]:
    import csv
    import io
    return list(csv.DictReader(io.StringIO(text)))


def _get(url, params, tries=5, timeout=90):
    """GET with patience: NASA's IRSA often answers "busy" (502/503) and works a moment later."""
    import time
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code in (502, 503, 504, 429):
                last = RuntimeError(f"server busy ({r.status_code})")
                time.sleep(1.5 * (i + 1))
                continue
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"no answer from {url.split('/')[2]} ({last})")


def _vizier_2mass(ra: float, dec: float, radius_arcsec: float) -> list[dict]:
    cols = "2MASS,RAJ2000,DEJ2000,JD,Jmag,Hmag,Kmag"
    params = [("-source", "II/246/out"), ("-c", f"{ra:.6f} {dec:+.6f}"), ("-c.rs", f"{radius_arcsec:.1f}"),
              ("-out.max", "3000")] + [("-out", c) for c in cols.split(",")]
    text = _get(VIZIER_CFA, params, tries=2)
    if "#Table" not in text and "#RESOURCE" not in text:
        raise RuntimeError("unexpected answer from VizieR")
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 3:
        return []
    head = lines[0].split("\t")
    return [dict(zip(head, [v.strip() for v in ln.split("\t")])) for ln in lines[3:]]


def _year(mjd) -> float:
    return float(Time(mjd, format="mjd").jyear)


def _download(key: str, ra0: float, dec0: float, field_deg: float) -> list[dict]:
    # fast movers are listed where they were years ago, so look a little wider for the
    # catalogues that give motions (SIMBAD positions are for 2000, CatWISE for 2015)
    radius = field_deg * 3600 * 0.75 + dict(simbad=300.0, catwise=120.0).get(key, 0.0)
    out = []
    if key == "simbad":
        from . import objcheck
        q = ("SELECT TOP 300 main_id, otype, ra, dec, pmra, pmdec FROM basic WHERE "
             f"CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra0},{dec0},{radius / 3600}))=1")
        rows, last = None, None
        for url in objcheck.SIMBAD_TAPS:
            try:
                rows = objcheck._tap_csv(url, q, extra={"request": "doQuery", "lang": "adql", "format": "csv", "query": q})
                break
            except Exception as e:
                last = e
        if rows is None:
            raise RuntimeError(f"SIMBAD could not be reached ({last})")
        for r in rows:
            code = r["otype"].strip('"')
            pe, pn = _f(r.get("pmra")), _f(r.get("pmdec"))
            has = pe is not None and pn is not None
            out.append(dict(name=r["main_id"].strip('"'), ra=float(r["ra"]), dec=float(r["dec"]), epoch=2000.0,
                            pme=pe / 1000 if has else None, pmn=pn / 1000 if has else None,
                            type=objcheck.OTYPES.get(code, code), plain=code in ("*", "IR", "NIR", "Opt", "?")))
        return out
    sr = radius / 3600
    if key == "catwise":
        try:
            rows = _csv_rows(_get(IRSA_SCS, dict(table="catwise_2020", RA=ra0, DEC=dec0, SR=sr, format="csv"), tries=3))
        except RuntimeError:
            # NASA's IRSA is busy: the same catalogue is also served by NOIRLab's Astro Data Lab
            q = ("SELECT source_name,ra,dec,meanobsmjd,ra_pm,dec_pm,pmra,sigpmra,pmdec,sigpmdec,w1mpro_pm,w2mpro_pm "
                 f"FROM catwise2020.main WHERE 't'=q3c_radial_query(ra,dec,{ra0},{dec0},{sr})")
            text = _get(NOIRLAB_TAP, dict(REQUEST="doQuery", LANG="ADQL", FORMAT="csv", QUERY=q), tries=2, timeout=120)
            if not text.startswith("source_name"):
                raise RuntimeError("CatWISE could not be fetched from IRSA or NOIRLab")
            rows = _csv_rows(text)
        for r in rows:
            pe, pn, se, sn = _f(r["pmra"]), _f(r["pmdec"]), _f(r["sigpmra"]), _f(r["sigpmdec"])
            w1, w2 = _f(r["w1mpro_pm"]), _f(r["w2mpro_pm"])
            mag, band = (w2, "W2") if w2 is not None else (w1, "W1")
            moving = False
            if None not in (pe, pn, se, sn) and _f(r["ra_pm"]) is not None:
                tot = float(np.hypot(pe, pn))
                err = float(np.hypot(pe * se, pn * sn) / max(tot, 1e-6))
                moving = tot > 0.15 and tot / max(err, 1e-6) > 8
            name = "CWISE " + r["source_name"].strip()
            if moving:      # position at 2015.4 with the catalogue's own motion
                out.append(dict(name=name, ra=float(r["ra_pm"]), dec=float(r["dec_pm"]), epoch=_year(57170.0),
                                pme=pe, pmn=pn, mag=mag, band=band))
            elif _f(r["ra"]) is not None:
                out.append(dict(name=name, ra=float(r["ra"]), dec=float(r["dec"]),
                                epoch=_year(_f(r["meanobsmjd"]) or 57170.0), pme=None, pmn=None, mag=mag, band=band))
    elif key == "twomass":
        try:
            rows = _vizier_2mass(ra0, dec0, radius)
            get = lambda r: (r["2MASS"], r["RAJ2000"], r["DEJ2000"], _f(r["JD"]), r["Jmag"], r["Hmag"], r["Kmag"])  # noqa: E731
        except Exception:
            rows = _csv_rows(_get(IRSA_SCS, dict(table="fp_psc", RA=ra0, DEC=dec0, SR=sr, format="csv")))
            get = lambda r: (r["designation"], r["ra"], r["dec"], _f(r.get("jdate")), r["j_m"], r["h_m"], r["k_m"])  # noqa: E731
        for r in rows:
            nm, ra_, de_, jd, j, h, k = get(r)
            mags = [(_f(k), "K"), (_f(h), "H"), (_f(j), "J")]
            mag, band = next(((m, b) for m, b in mags if m is not None), (None, ""))
            out.append(dict(name="2MASS J" + nm.strip(), ra=float(ra_), dec=float(de_),
                            epoch=float(Time(jd, format="jd").jyear) if jd else 1999.5, pme=None, pmn=None, mag=mag, band=band))
    elif key == "panstarrs":
        cols = "[objName,raMean,decMean,epochMean,nDetections,rMeanPSFMag,iMeanPSFMag,zMeanPSFMag,yMeanPSFMag]"
        rows = _csv_rows(_get(MAST_PS1, {"ra": ra0, "dec": dec0, "radius": sr, "nDetections.gte": 3,
                                         "columns": cols, "pagesize": 5000}))
        for r in rows:
            ok = lambda v: v is not None and v > -900  # noqa: E731
            mags = [(_f(r["yMeanPSFMag"]), "y"), (_f(r["zMeanPSFMag"]), "z"), (_f(r["iMeanPSFMag"]), "i"), (_f(r["rMeanPSFMag"]), "r")]
            mag, band = next(((m, b) for m, b in mags if ok(m)), (None, ""))
            ep = _f(r["epochMean"])
            if mag is None or _f(r["raMean"]) is None:
                continue
            out.append(dict(name=r["objName"].strip(), ra=float(r["raMean"]), dec=float(r["decMean"]),
                            epoch=_year(ep) if ep and ep > 50000 else 2012.5, pme=None, pmn=None, mag=mag, band=band))
    elif key == "skymapper":
        rows = _csv_rows(_get(SKYMAPPER, dict(RA=ra0, DEC=dec0, SR=sr, RESPONSEFORMAT="CSV", CATALOG="dr2.master")))
        for r in rows:
            mags = [(_f(r["z_psf"]), "z"), (_f(r["i_psf"]), "i"), (_f(r["r_psf"]), "r"), (_f(r["g_psf"]), "g")]
            mag, band = next(((m, b) for m, b in mags if m is not None), (None, ""))
            ep = _f(r["mean_epoch"])
            if _f(r["raj2000"]) is None:
                continue
            out.append(dict(name="SMSS J" + r["smss_j"].strip(), ra=float(r["raj2000"]), dec=float(r["dej2000"]),
                            epoch=_year(ep) if ep else 2016.0, pme=None, pmn=None, mag=mag, band=band))
    return out


def path(ra0: float, dec0: float, field_deg: float, key: str):
    return flipbook.place_dir(round(ra0, 4), round(dec0, 4)) / f"cat_{key}_{field_deg:.3f}.json"


def is_saved(ra0, dec0, field_deg, key) -> bool:
    if key == "gaia":
        return (flipbook.place_dir(round(ra0, 4), round(dec0, 4)) / f"gaia_{field_deg:.3f}.json").exists()
    return path(ra0, dec0, field_deg, key).exists()


def sources(ra0: float, dec0: float, field_deg: float, key: str) -> dict:
    """The catalogue's sources around the patch: from the saved file, or downloaded once and saved.
    A failed download is not saved, so the next request tries again."""
    assert key in BY_KEY and key != "gaia"
    p = path(ra0, dec0, field_deg, key)
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(str(p), threading.Lock())
    with lock:
        return _sources_locked(p, ra0, dec0, field_deg, key)


def _sources_locked(p, ra0, dec0, field_deg, key) -> dict:
    if p.exists():
        return json.loads(p.read_text())
    if not covers(key, dec0):
        d = dict(key=key, covered=False, sources=[],
                 note=f"{BY_KEY[key]['short']} does not cover this part of the sky ({BY_KEY[key]['coverage']}).")
    else:
        d = dict(key=key, covered=True, sources=_download(key, round(ra0, 4), round(dec0, 4), field_deg))
    d["fetched"] = datetime.date.today().isoformat()
    p.write_text(json.dumps(d))
    return d


def at(s: dict, jyear: float, cosd: float):
    """Where a catalogue source is at a given date (moved along if the catalogue gives a motion)."""
    if s.get("pme") is None:
        return s["ra"], s["dec"]
    dt = jyear - s["epoch"]
    return s["ra"] + dt * s["pme"] / 3600 / cosd, s["dec"] + dt * s["pmn"] / 3600


def _mid_year(ra0, dec0, field_deg) -> float:
    res = json.loads(flipbook.saved_path(round(ra0, 4), round(dec0, 4), field_deg).read_text())
    return _year(float(np.mean([p["mjd"] for p in res["passes"]])))


def for_view(ra0: float, dec0: float, field_deg: float, key: str) -> dict:
    """Sources inside the picture, as offsets (arcsec east, north) at the middle date of the
    SPHEREx passes, for drawing. Moving sources carry their motion so the page can follow them."""
    d = sources(ra0, dec0, field_deg, key)
    jy = _mid_year(ra0, dec0, field_deg)
    cosd = np.cos(np.radians(dec0))
    half = field_deg * 1800
    out = []
    for s in d["sources"]:
        r, dd = at(s, jy, cosd)
        e, n = ((r - ra0 + 180) % 360 - 180) * 3600 * cosd, (dd - dec0) * 3600
        if max(abs(e), abs(n)) > half:
            continue
        moves = s.get("pme") is not None and float(np.hypot(s["pme"], s["pmn"])) > 0.15
        o = dict(east=round(float(e), 2), north=round(float(n), 2), name=s["name"], year=round(s["epoch"]),
                 moves=bool(moves))
        if s.get("mag") is not None:
            o["mag"], o["band"] = round(s["mag"], 1), s.get("band", "")
        if moves:
            o["ve"], o["vn"] = s["pme"], s["pmn"]
            o["pm"] = round(float(np.hypot(s["pme"], s["pmn"])), 2)
        if key == "simbad":
            o["type"], o["plain"] = s["type"], s["plain"]
        elif s.get("pme") is None:
            o["old"] = True            # position as it was in `year`; the catalogue gives no motion
        out.append(o)
    c = BY_KEY[key]
    return dict(key=key, name=c["name"], colour=c["colour"], n=len(out), sources=out, covered=d.get("covered", True),
                note=d.get("note"), mid_year=round(jy, 2), fetched=d.get("fetched"))


# ------------------------------------------------------------------ is this object known?
def match_point(s_list, ra, dec, jyear, radius=6.0):
    """Nearest catalogue source to (ra, dec) at the given date, within radius arcsec."""
    cosd = np.cos(np.radians(dec))
    best = None
    for s in s_list:
        r, d = at(s, jyear, cosd)
        sep = float(np.hypot(((r - ra + 180) % 360 - 180) * cosd, d - dec) * 3600)
        if sep <= radius and (best is None or sep < best[0]):
            best = (sep, s)
    return best


def match_moving(s_list, ra, dec, jyear, rate_e, rate_n, max_tol=10.0):
    """Does the catalogue hold an object that was at (ra, dec) at `jyear` and moves at
    (rate_e, rate_n) arcsec a year?

    - Sources with a catalogue motion are moved to `jyear`; they must be within 4.5″ and move alike.
    - Sources without one are compared with where the object would have been at the catalogue's date.
      A motion measured over about a year is rough, so that old position is uncertain; when the
      uncertainty is more than `max_tol` arcsec we do not guess (returns 'too_old').
    Returns (verdict, source, text) with verdict 'match', 'none' or 'too_old'."""
    cosd = np.cos(np.radians(dec))
    rate = float(np.hypot(rate_e, rate_n))
    too_old = False
    best = None
    for s in s_list:
        if s.get("pme") is not None:
            r, d = at(s, jyear, cosd)
            sep = float(np.hypot(((r - ra + 180) % 360 - 180) * cosd, d - dec) * 3600)
            if sep <= 4.5 and np.hypot(s["pme"] - rate_e, s["pmn"] - rate_n) <= max(0.6, 0.4 * rate):
                if best is None or sep < best[0]:
                    best = (sep, s, "with a matching motion")
        else:
            dt = jyear - s["epoch"]
            tol = 3.0 + (0.25 * rate + 0.15) * abs(dt)
            if tol > max_tol:
                too_old = True
                continue
            r0, d0 = ra - dt * rate_e / 3600 / cosd, dec - dt * rate_n / 3600
            sep = float(np.hypot(((s["ra"] - r0 + 180) % 360 - 180) * cosd, s["dec"] - d0) * 3600)
            if sep <= tol and (best is None or sep < best[0]):
                best = (sep, s, f"where this object was in {round(s['epoch'])}")
    if best:
        return "match", best[1], best[2]
    return ("too_old" if too_old else "none"), None, None


def explain_movers(found: list[dict], mjds: list[float], ra0, dec0, field_deg, keys: list[str]) -> list[str]:
    """Label each mover against the switched-on catalogues other than Gaia (Gaia's verdict is
    already in m['status']). Returns notes about catalogues that could not be reached."""
    notes = []
    data = {}
    for k in keys:
        if k == "gaia":
            continue
        try:
            data[k] = sources(ra0, dec0, field_deg, k)["sources"]
        except Exception as e:
            notes.append(f"{BY_KEY[k]['short']} could not be reached ({e}).")
    checked = [k for k in keys if k == "gaia" or k in data]
    for m in found:
        m["checked"] = [BY_KEY[k]["short"] for k in checked]
        m["known_in"] = ["Gaia"] if m.get("status", "").startswith("known") else []
        jy = _year(mjds[m["passes"][0]])
        for k, srcs in data.items():
            verdict, s, how = match_moving(srcs, m["ra"][0], m["dec"][0], jy, m["rate_east"], m["rate_north"])
            if verdict == "match":
                m["known_in"].append(BY_KEY[k]["short"])
                m.setdefault("matches", []).append(dict(cat=BY_KEY[k]["short"], name=s["name"], how=how,
                                                        type=s.get("type"), mag=s.get("mag"), band=s.get("band")))
            elif verdict == "too_old":
                m.setdefault("untraceable", []).append(BY_KEY[k]["short"])
        if m.get("status", "").startswith("known"):
            continue
        if m.get("matches"):
            x = m["matches"][0]
            what = f" as a {x['type']}" if x.get("type") else ""
            m["status"] = f"known: listed in {x['cat']}{what} ({x['name']}), {x['how']}"
        elif m.get("status", "").startswith("suspect"):
            continue
        elif not checked:
            m["status"] = "unchecked: no catalogue could be checked (none switched on, or none reachable)"
        else:
            m["status"] = f"candidate: unexplained by the catalogues checked ({names(checked)})"
    return notes


def check_point(ra0, dec0, field_deg, ra, dec, jyear, keys, motion=None) -> list[dict]:
    """For a clicked object: what each switched-on catalogue (other than Gaia) holds there."""
    out = []
    for k in keys:
        if k == "gaia":
            continue
        c = BY_KEY[k]
        row = dict(key=k, name=c["short"], light=c["light"])
        try:
            d = sources(ra0, dec0, field_deg, k)
        except Exception as e:
            row["error"] = str(e)
            out.append(row)
            continue
        if not d.get("covered", True):
            row["not_covered"] = c["coverage"]
            out.append(row)
            continue
        hit = None
        fast = motion and motion.get("rate", 0) > 0.5 and (motion.get("sigma", 0) >= 5 or motion.get("significant"))
        if fast:
            verdict, s, how = match_moving(d["sources"], ra, dec, jyear, motion["east"], motion["north"])
            if verdict == "match":
                hit = (None, s, how)
            elif verdict == "too_old":
                row["too_old"] = True
        if hit is None:
            b = match_point(d["sources"], ra, dec, jyear)
            # a moving object next to a source that the catalogue saw standing at this very spot years ago
            # is not the same thing, unless the catalogue itself says the source moves like it
            if b and not (fast and b[1].get("pme") is None and abs(jyear - b[1]["epoch"]) * motion["rate"] > 8):
                hit = (b[0], b[1], None)
        if hit:
            sep, s, how = hit
            row.update(found=True, source=s["name"], year=round(s["epoch"]), how=how,
                       ra=round(float(s["ra"]), 6), dec=round(float(s["dec"]), 6), epoch=round(float(s["epoch"]), 1),
                       sep_arcsec=round(sep, 1) if sep is not None else None)
            if s.get("mag") is not None:
                row.update(mag=round(s["mag"], 1), band=s.get("band", ""))
            if s.get("pme") is not None:
                row["pm"] = round(float(np.hypot(s["pme"], s["pmn"])), 2)
            if s.get("type"):
                row["type"] = s["type"]
        else:
            row["found"] = False
        out.append(row)
    return out
