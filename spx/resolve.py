"""Turn what a person types into a sky position.

Names are looked up with the CDS Sesame service, which also returns the object's
proper motion. Catalogue positions are for the year 2000, so fast movers (Barnard's
Star, WISE 0855, eps Indi B) are carried forward to the SPHEREx era (2026.2,
the middle of the first three sky passes); otherwise they'd sit off-centre.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

import requests

SESAME = "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV"
EPOCH_NOW = 2026.2
# SIMBAD (behind Sesame) gives positions for the year 2000 (it carries objects with a
# known proper motion to that date), so we move them from 2000 to EPOCH_NOW.
# Checked on WISE 0855: SIMBAD's position sits 87" east of the 2010 AllWISE position,
# exactly 10.5 years of its westward motion, i.e. it is for the year 2000.


def _num(node, path):
    el = node.find(path)
    try:
        return float(el.text) if el is not None and el.text else None
    except ValueError:
        return None


def lookup_name(name: str) -> dict | None:
    r = requests.get(f"{SESAME}?{requests.utils.quote(name)}", timeout=30)
    if r.status_code != 200 or "<jradeg>" not in r.text:
        return None
    root = ET.fromstring(r.text)
    res = root.find(".//Resolver")
    if res is None:
        return None
    ra, dec = _num(res, "jradeg"), _num(res, "jdedeg")
    if ra is None or dec is None:
        return None
    pmra, pmde = _num(res, ".//pmRA") or 0.0, _num(res, ".//pmDE") or 0.0  # mas/yr, pmRA includes cos(dec)
    plx = _num(res, "plx/v") or 0.0
    oname = (res.findtext("oname") or name).strip()
    epoch = 2000.0
    dt = EPOCH_NOW - epoch
    ra_now = ra + dt * pmra / 3.6e6 / max(math.cos(math.radians(dec)), 1e-6)
    dec_now = dec + dt * pmde / 3.6e6
    moved = math.hypot(dt * pmra, dt * pmde) / 1000  # arcsec
    return dict(ra=ra_now % 360, dec=dec_now, name=oname, pmra=pmra, pmdec=pmde, parallax=plx,
                ra2000=ra, dec2000=dec, moved_arcsec=moved,
                how=((f"{oname}: catalogue position moved forward to {EPOCH_NOW} "
                      f"({moved:.0f}″ of motion since {epoch:.0f})") if moved > 1 else oname)
)


def resolve(q: str) -> dict:
    from astropy import units as u
    from astropy.coordinates import SkyCoord

    q = q.strip()
    parts = re.split(r"[\s,]+", q)
    if len(parts) == 2:
        try:
            return dict(ra=float(parts[0]) % 360, dec=float(parts[1]), how="decimal degrees")
        except ValueError:
            pass
    if re.match(r"^[\d\s:.hmsd+\-]+$", q):
        try:
            c = SkyCoord(q, unit=(u.hourangle, u.deg))
            return dict(ra=c.ra.deg, dec=c.dec.deg, how="hours / degrees")
        except Exception:
            pass
    hit = lookup_name(q)
    if hit:
        return hit
    raise ValueError(f"Could not understand '{q}'. Try numbers like: 269.4464 4.7686")
