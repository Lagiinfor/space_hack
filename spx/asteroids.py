"""Known asteroids and comets in a patch, photo by photo, plus NASA's published risk info.

1. Which known solar-system objects were in the patch when each photo was taken?
   The IMCCE SkyBoT service predicts where every known asteroid and comet is at a given
   moment. Photos are grouped into short time windows (within ~1 hour) and SkyBoT is asked
   once per window; each object's position at each photo's exact time is then worked out
   from the rate of motion SkyBoT returns.

2. Did SPHEREx actually catch it? Asteroids move fast: in one pass, the photos of a spot are
   days apart, so an asteroid shows up in only one photo or a few. We therefore check every
   single photo (not the stacked pictures, where one-off light is rejected as a glitch): the
   brightness at the predicted spot is compared with the same spot in the other photos of
   that pass. Clearly brighter = caught.

3. Is it a near-Earth object, and does NASA list any impact risk? We never compute a risk
   ourselves (a few SPHEREx photos cannot pin down an orbit). For each object we show what
   NASA/JPL publishes: its orbit class and near-Earth / potentially-hazardous status (SBDB),
   whether it is on the Sentry impact-monitoring list and the probability listed there, and
   its next close approach to Earth (close-approach data).
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from astropy.time import Time

SKYBOT = "https://ssp.imcce.fr/webservices/skybot/api/conesearch.php"
JPL = "https://ssd-api.jpl.nasa.gov"
_session = requests.Session()


def _get_json(url, params, tries=3, timeout=60):
    last = None
    for i in range(tries):
        try:
            r = _session.get(url, params=params, timeout=timeout)
            if r.status_code == 204:
                return []                  # "no content": nothing known in that spot
            if r.status_code == 200:
                txt = r.text.strip()
                if not txt or not txt.startswith(("[", "{")):
                    return []          # SkyBoT answers with plain text when nothing is there
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code}")
        except (requests.RequestException, ValueError) as e:
            last = e
        time.sleep(1.5 * (i + 1))
    raise last


def _hms_to_deg(h):
    a = [float(x) for x in str(h).split()]
    return 15 * (a[0] + a[1] / 60 + a[2] / 3600)


def _dms_to_deg(d):
    s = str(d).strip()
    sign = -1 if s.startswith("-") else 1
    a = [abs(float(x)) for x in s.replace("+", "").replace("-", "").split()]
    return sign * (a[0] + a[1] / 60 + a[2] / 3600)


def _time_groups(cuts, window_h=1.0):
    order = sorted(range(len(cuts)), key=lambda i: cuts[i].mjd)
    groups, cur = [], []
    for i in order:
        if cur and (cuts[i].mjd - cuts[cur[0]].mjd) * 24 > window_h:
            groups.append(cur)
            cur = []
        cur.append(i)
    if cur:
        groups.append(cur)
    return groups


def in_patch(pos: dict, field_deg: float, progress=lambda s: None) -> dict:
    """Known solar-system objects in the patch, per photo, with 'caught' flags."""
    from . import analysis

    cuts, passes = pos["cuts"], pos["passes"]
    ra0, dec0 = pos["ra"], pos["dec"]
    radius = field_deg * 0.75 + 0.02            # field corners + a little room
    groups = _time_groups(cuts)

    def ask(g):
        mjd = float(np.mean([cuts[i].mjd for i in g]))
        rows = _get_json(SKYBOT, {"-ep": mjd + 2400000.5, "-ra": ra0, "-dec": dec0, "-rd": radius,
                                  "-mime": "json", "-output": "all", "-loc": "500", "-filter": "0"})
        return g, mjd, rows if isinstance(rows, list) else []

    progress("Asking the asteroid database which known objects passed through")
    with ThreadPoolExecutor(6) as pool:
        answers = list(pool.map(ask, groups))

    cosd = np.cos(np.radians(dec0))
    objects: dict = {}
    for g, mjd, rows in answers:
        for row in rows:
            name = str(row.get("Name"))
            num = row.get("Num")
            key = str(num) if num not in (None, "", "-") else name
            o = objects.setdefault(key, dict(name=name, number=num if num not in ("", "-") else None,
                                             kind=row.get("Class", ""), vmag=row.get("VMag (mag)"),
                                             photos=[]))
            ra = _hms_to_deg(row["RA (hms)"])
            de = _dms_to_deg(row["DEC (dms)"])
            dra_h = float(row.get("dRA (arcsec/h)") or 0)       # includes cos(dec)
            dde_h = float(row.get("dDEC (arcsec/h)") or 0)
            for i in g:
                c = cuts[i]
                dt_h = (c.mjd - mjd) * 24
                r_ = ra + dt_h * dra_h / 3600 / max(np.cos(np.radians(de)), 1e-6)
                d_ = de + dt_h * dde_h / 3600
                east = ((r_ - ra0 + 180) % 360 - 180) * 3600 * cosd
                north = (d_ - dec0) * 3600
                if max(abs(east), abs(north)) > field_deg * 1800:
                    continue                      # outside the patch shown
                o["photos"].append(dict(i=i, obs_id=c.obs_id, mjd=c.mjd, pass_index=int(passes[i]), detector=c.detector,
                                        wl=c.wavelength, ra=r_, dec=d_, east=east, north=north,
                                        rate=float(np.hypot(dra_h, dde_h))))
    objects = {k: o for k, o in objects.items() if o["photos"]}

    # did SPHEREx catch it? compare each photo with the other photos of the same pass
    progress("Checking each photo for the asteroids")
    for o in objects.values():
        caught = 0
        for ph in o["photos"]:
            c = cuts[ph["i"]]
            m = analysis._aperture_flux(c, ph["ra"], ph["dec"])
            if not isinstance(m, tuple):
                ph["seen"] = None
                continue
            others = []
            for j, (c2, p2) in enumerate(zip(cuts, passes)):
                if j != ph["i"] and int(p2) == ph["pass_index"] and c2.detector == c.detector:
                    m2 = analysis._aperture_flux(c2, ph["ra"], ph["dec"])
                    if isinstance(m2, tuple) and np.isfinite(m2[0]):
                        others.append(m2[0])
            if len(others) < 3:
                ph["seen"] = None
                continue
            base = float(np.median(others))
            spread = float(1.4826 * np.median(np.abs(np.array(others) - base)))
            excess = m[0] - base
            ph["excess_mjy"] = round(float(excess), 3)
            ph["seen"] = bool(excess > 5 * max(spread, m[1], 0.02))
            caught += ph["seen"]
        o["n_photos"] = len(o["photos"])
        o["n_caught"] = caught
        for ph in o["photos"]:
            ph.pop("i", None)
    out = sorted(objects.values(), key=lambda o: (-o["n_caught"], o["vmag"] if o["vmag"] is not None else 99))
    return dict(objects=out, n_queries=len(groups), source="IMCCE SkyBoT (positions); SPHEREx photos (caught or not)")


# ---------------------------------------------------------------- NASA/JPL published risk
_risk_cache: dict = {}


def risk_info(designation: str) -> dict:
    """What NASA/JPL publishes about one object. We do not compute any risk ourselves."""
    if designation in _risk_cache:
        return _risk_cache[designation]
    info = dict(designation=designation)
    try:
        sb = _get_json(f"{JPL}/sbdb.api", {"sstr": designation})
        obj = sb.get("object", {}) if isinstance(sb, dict) else {}
        info.update(fullname=obj.get("fullname"), neo=bool(obj.get("neo")), pha=bool(obj.get("pha")),
                    orbit_class=(obj.get("orbit_class") or {}).get("name"), des=obj.get("des"))
    except Exception as e:
        info["sbdb_error"] = str(e)
    des = info.get("des") or designation
    try:
        st = _get_json(f"{JPL}/sentry.api", {"des": des})
        if isinstance(st, dict) and "summary" in st:
            s = st["summary"]
            info["sentry"] = dict(listed=True, impact_probability=s.get("ip"), palermo=s.get("ps_cum"),
                                  torino=s.get("ts_max"), years=s.get("range"))
        else:
            info["sentry"] = dict(listed=False, note=(st.get("error") if isinstance(st, dict) else None))
    except Exception as e:
        info["sentry_error"] = str(e)
    if info.get("neo"):
        try:
            ca = _get_json(f"{JPL}/cad.api", {"des": des, "date-min": "now", "date-max": "2126-01-01",
                                               "dist-max": "0.2", "sort": "date", "limit": "1"})
            if isinstance(ca, dict) and ca.get("count", 0) and ca.get("data"):
                f = ca["fields"]; d = dict(zip(f, ca["data"][0]))
                info["next_close_approach"] = dict(date=d.get("cd"), distance_au=float(d.get("dist")),
                                                   distance_lunar=round(float(d.get("dist")) * 389.17, 1))
            else:
                info["next_close_approach"] = None
        except Exception as e:
            info["cad_error"] = str(e)
    _risk_cache[designation] = info
    return info
