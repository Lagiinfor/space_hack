"""Follow a known moving object (comet or asteroid) through SPHEREx and NEOSSat photos.

A fast mover is somewhere else in every photo, so an ordinary stack smears it away. Here
every photo is re-centred on where the object WAS at that moment (from NASA/JPL Horizons),
then stacked: the object adds up at the centre while the stars slide through and average out.

Used for the interstellar comet 3I/ATLAS showcase:
    .venv\\Scripts\\python scripts\\follow_object.py
Writes a flip-book result the app opens like any saved patch (one "pass" per day).
"""
import csv
import io
import json
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.time import Time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
from spx import archive, flipbook, frames, other_telescopes as ot  # noqa: E402

OBJ = dict(key="atlas3i", horizons="DES=C/2025 N1;", name="3I/ATLAS", cadc_target="3I",
           start="2025-08-10T12:00", stop="2025-08-14T12:00", field=0.06)
WORK = ROOT / "data" / f"follow_{OBJ['key']}"
WORK.mkdir(parents=True, exist_ok=True)


def horizons(mjds):
    out = []
    for i in range(0, len(mjds), 40):
        ts = mjds[i:i + 40]
        tl = " ".join(f"'{t + 2400000.5:.6f}'" for t in ts)
        r = requests.get("https://ssd.jpl.nasa.gov/api/horizons.api", timeout=120, params=dict(
            format="json", COMMAND=f"'{OBJ['horizons']}'", EPHEM_TYPE="OBSERVER", CENTER="'500@399'", TLIST=tl,
            TLIST_TYPE="JD", QUANTITIES="'1,9'", ANG_FORMAT="DEG", CSV_FORMAT="YES"))
        t = r.json()["result"]
        body = t[t.index("$$SOE") + 5:t.index("$$EOE")].strip().splitlines()
        for tt, line in zip(ts, body):
            p = line.split(",")
            out.append((tt, float(p[3]), float(p[4])))
    return out


# ---------------------------------------------------------------- 1. SPHEREx photos along the path
t0, t1 = Time(OBJ["start"]).mjd, Time(OBJ["stop"]).mjd
cache = WORK / "spherex_list.json"
if cache.exists():
    photos = json.loads(cache.read_text())
else:
    samples = horizons(list(np.arange(t0, t1, 1.5 / 24)))

    def ask(s):
        t, ra, dec = s
        for attempt in range(3):
            try:
                r = requests.get(archive.SIA, timeout=180, params={"COLLECTION": "spherex_dr1", "POS": f"circle {ra} {dec} 0.03",
                                                                   "TIME": f"{t - 0.035} {t + 0.035}", "RESPONSEFORMAT": "csv"})
                return [dict(obs=row["obs_id"], det=int(row["energy_bandpassname"][-1]), mjd=float(row["t_min"]) + 57 / 86400,
                             url=row["access_url"]) for row in csv.DictReader(io.StringIO(r.text))]
            except Exception:
                time.sleep(3)
        return []
    print(f"asking the SPHEREx archive at {len(samples)} moments along the path...", flush=True)
    with ThreadPoolExecutor(6) as pool:
        found = [x for xs in pool.map(ask, samples) for x in xs]
    uniq = {(x["obs"], x["det"]): x for x in found}
    photos = sorted(uniq.values(), key=lambda x: x["mjd"])
    eph = horizons([x["mjd"] for x in photos])
    for x, (_, ra, dec) in zip(photos, eph):
        x["ra"], x["dec"] = ra, dec
    cache.write_text(json.dumps(photos))
print(len(photos), "SPHEREx photos near the object's path", flush=True)


def get(x):
    p = WORK / "spherex" / f"{x['obs']}_D{x['det']}.fits"
    p.parent.mkdir(exist_ok=True)
    if not p.exists():
        data = archive._stream_image_layers(x["url"], {"center": f"{x['ra']},{x['dec']}d", "size": "0.1"})
        if not data:
            return None
        p.write_bytes(data)
    try:
        c = frames.load_cutout(p, x["ra"], x["dec"])
        ny, nx = c.image.shape
        px, py = c.wcs.all_world2pix(x["ra"], x["dec"], 0)
        if not (8 < px < nx - 8 and 8 < py < ny - 8):
            return None                       # the object is off this photo's edge
        return x, c
    except Exception:
        return None


with ThreadPoolExecutor(12) as pool:
    got = [g for g in pool.map(get, photos) if g]
print(len(got), "contain the object", flush=True)

field = OBJ["field"]
days = sorted({Time(x["mjd"], format="mjd").strftime("%Y-%m-%d") for x, _ in got})
pass_info, frame_list, exposures = [], [], []
ref_grid, shape = frames.target_grid(0.0, 0.0, field)
for k, day in enumerate(days):
    mine = [(x, c) for x, c in got if Time(x["mjd"], format="mjd").strftime("%Y-%m-%d") == day]
    mj = [x["mjd"] for x, _ in mine]
    pass_info.append(dict(index=k, label=Time(np.mean(mj), format="mjd").strftime("%d %b %Y"), mjd=float(np.mean(mj)),
                          start=Time(min(mj), format="mjd").strftime("%Y-%m-%d %H:%M"),
                          end=Time(max(mj), format="mjd").strftime("%Y-%m-%d %H:%M"), n=len(mine)))
    stacks = []
    for d in range(1, 7):
        sel = [(x, c) for x, c in mine if x["det"] == d]
        if len(sel) < 3:
            continue
        cube = []
        for x, c in sel:
            g, _ = frames.target_grid(x["ra"], x["dec"], field)      # grid centred on the object at that moment
            cube.append(frames.resample(c.image, c.wcs, g, shape))
        img = np.nanmedian(cube, axis=0)                              # stars slide through and drop out
        stacks.append(img)
        frame_list.append(dict(pass_index=k, band=d, n=len(sel), wl_min=min(c.wavelength for _, c in sel),
                               wl_max=max(c.wavelength for _, c in sel), limited=False, data=img))
    if stacks:
        frame_list.append(dict(pass_index=k, band=0, n=len(mine), wl_min=0.75, wl_max=5.0, n_detectors=len(stacks),
                               detectors=[f["band"] for f in frame_list if f["pass_index"] == k and f["band"]],
                               limited=False, data=np.nanmean(stacks, axis=0)))
    for x, c in mine:
        exposures.append(dict(mjd=x["mjd"], band=x["det"], wl=c.wavelength, pass_index=k, obs_id=x["obs"]))

noise = {}
for b in range(7):
    imgs = [f["data"] for f in frame_list if f["band"] == b]
    if imgs:
        _, _, s = sigma_clipped_stats(np.concatenate([i[np.isfinite(i)] for i in imgs]), sigma=3)
        noise[b] = float(max(s, 1e-6))
n = shape[0]
c0 = n // 2
print("signal at the centre, in units of the noise:")
for f in frame_list:
    d = f["data"]
    snr = float(np.nanmax(d[c0 - 2:c0 + 2, c0 - 2:c0 + 2]) / noise[f["band"]])
    f["snr"] = round(snr, 1)
    print(f"  {pass_info[f['pass_index']]['label']} band {f['band']}: {f['n']} photos, centre {snr:.1f}x noise", flush=True)
for f in frame_list:
    d = f.pop("data")
    f["noise"] = noise[f["band"]]
    f["peak"] = float(max(np.nanmax(d), 20 * noise[f["band"]]))
    f["filled_px"] = 0; f["nodata_px"] = int((~np.isfinite(d)).sum())
    f["pixels"] = flipbook._pack(d)

# ---------------------------------------------------------------- 2. NEOSSat photos of the same object
other = []
try:
    q = ("SELECT o.observationID, p.productID, p.time_bounds_lower, a.uri FROM caom2.Observation o "
         "JOIN caom2.Plane p ON o.obsID=p.obsID JOIN caom2.Artifact a ON a.planeID=p.planeID "
         f"WHERE o.collection='NEOSSAT' AND o.target_name='{OBJ['cadc_target']}' "
         f"AND p.time_bounds_lower > {t0} AND p.time_bounds_lower < {t1}")
    rows = list(csv.DictReader(io.StringIO(ot._get(ot.CADC_TAP, {"LANG": "ADQL", "FORMAT": "csv", "QUERY": q}).text)))
    rows = [r for r in rows if r["uri"].endswith("_cord.fits")]
    neo = sorted(({"file": r["uri"].split("/")[-1], "mjd": float(r["time_bounds_lower"])} for r in rows), key=lambda x: x["mjd"])
    print(len(neo), "cleaned NEOSSat photos of the object in this window", flush=True)
    summary = dict(n_images=len(neo))
    for day in days:
        mine = [x for x in neo if Time(x["mjd"], format="mjd").strftime("%Y-%m-%d") == day]
        if len(mine) < 8:
            continue
        # one visit: the first run of photos without a gap of more than 20 minutes
        visit = [mine[0]]
        for x in mine[1:]:
            if x["mjd"] - visit[-1]["mjd"] > 20 / 1440:
                if len(visit) >= 12:
                    break
                visit = []
            visit.append(x)
        visit = visit[:22]
        eph = horizons([x["mjd"] + 60 / 86400 for x in visit])
        stars = ot._gaia_stars(eph[0][1], eph[0][2], 0.6, Time(visit[0]["mjd"], format="mjd").jyear)

        def fetch(x):
            p = WORK / "neossat" / x["file"]
            p.parent.mkdir(exist_ok=True)
            if not p.exists():
                p.write_bytes(ot._get(ot.CADC_DATA + x["file"], timeout=300).content)
            return p
        with ThreadPoolExecutor(6) as pool:
            paths = list(pool.map(fetch, visit))
        cube, hint = [], None
        for x, p, (_, ra, dec) in zip(visit, paths, eph):
            with fits.open(p) as h:
                img = h[0].data.astype(float); H = h[0].header
            img = np.nan_to_num(img - np.nanmedian(img))
            hra = ot._hms(H.get("OBJCTRA") or H.get("RA")); hde = ot._dms(H.get("OBJCTDEC") or H.get("DEC"))
            w = ot._solve(img, hra, hde, stars, hint=hint) or (hint and ot._solve(img, hra, hde, stars))
            if not w:
                continue
            hint = w._hint
            g, _ = frames.target_grid(ra, dec, field)
            cube.append(frames.resample(img, w, g, shape))
        if len(cube) < 6:
            print(f"  NEOSSat {day}: only {len(cube)} photos could be lined up; skipped", flush=True)
            continue
        img = np.nanmedian(cube, axis=0)
        med, sd = ot._robust_noise(img)
        img = img - med
        snr = float(np.nanmax(img[c0 - 2:c0 + 2, c0 - 2:c0 + 2]) / sd)
        print(f"  NEOSSat {day}: {len(cube)} photos stacked, centre {snr:.1f}x noise", flush=True)
        mjd = float(np.mean([x["mjd"] for x in visit]))
        other.append(dict(source="NEOSSat", band="visible", wl=0.6, mjd=mjd, date_text=Time(mjd, format="mjd").strftime("%d %b %Y"),
                          start=visit[0]["mjd"], end=visit[-1]["mjd"], n=len(cube), snr=round(snr, 1),
                          note=f"Canada's NEOSSat (Canadian Space Agency), {len(cube)} two-minute photos re-centred on the comet "
                               "and stacked; images from the Canadian Astronomy Data Centre",
                          noise=float(sd), peak=float(max(np.nanmax(img), 20 * sd)), pixels=flipbook._pack(img)))
except Exception as e:
    print("NEOSSat part failed:", e, flush=True)
    summary = dict(n_images=0, error=str(e))

# ---------------------------------------------------------------- 3. save as a patch the app can open
mid = [x for x, _ in got if Time(x["mjd"], format="mjd").strftime("%Y-%m-%d") == days[0]]
ra0 = round(float(np.mean([x["ra"] for x in mid])), 4); dec0 = round(float(np.mean([x["dec"] for x in mid])), 4)
result = dict(
    ra=ra0, dec=dec0, field_deg=field, size=shape[0], pix_arcsec=3.075, passes=pass_info,
    bands=[dict(band=0, name="All bands", wl_min=0.75, wl_max=5.0)] +
          [dict(band=d, name=f"Band {d}", wl_min=a, wl_max=b) for d, (a, b) in flipbook.BANDS.items()],
    frames=frame_list, exposures=exposures, n_images=len(photos), n_used=len(got), complete=True,
    version=flipbook.RESULT_VERSION, built=Time.now().strftime("%Y-%m-%d"), collections=archive.COLLECTIONS,
    follow=dict(name=OBJ["name"], other=other, neossat=summary,
                note=f"Every photo is re-centred on where {OBJ['name']} was at that moment (positions from NASA/JPL Horizons), "
                     "then stacked. The object stays at the centre; stars slide through and drop out."),
)
out = flipbook.result_path(ra0, dec0, field)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result))
tj = ROOT / "data" / "tour.json"
t = json.loads(tj.read_text())
t[OBJ["key"]] = dict(ra=ra0, dec=dec0, how=f"Where {OBJ['name']} was on {days[0]} (NASA/JPL Horizons)")
tj.write_text(json.dumps(t, indent=1))
print("saved", out)
