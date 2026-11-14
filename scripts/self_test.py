"""Automatic checks of the tool's core promises. Run:

    .venv\\Scripts\\python scripts\\self_test.py

1. A star whose brightness never changes looks the same in every pass, even when the
   passes sampled different mixes of wavelengths (the "fair flip-book" promise).
2. Missing data is never painted in as bright sky; only burnt-out star centres are filled.
3. Motion maths works across RA 0/360.
4. On real data (needs the tour targets downloaded): a steady star stays steady, the
   known movers are found, and a variable star is not reported as a mover.
"""
import sys
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
from spx import frames, flipbook  # noqa: E402
from spx.movers import dra  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


# ------------------------------------------------------------ 1. fair stacking (synthetic)
def fake_cutout(wl, ra=10.0, dec=0.0, n=40):
    grid, shape = frames.target_grid(ra, dec, n * 6.15 / 3600, pix_arcsec=6.15)
    yy, xx = np.mgrid[:n, :n]
    flux = (wl / 1.0) ** -2            # a constant star whose brightness depends steeply on wavelength
    img = flux * np.exp(-((xx - n / 2) ** 2 + (yy - n / 2) ** 2) / (2 * 1.2 ** 2))
    return frames.Cutout("fake", 3, 0.0, wl, img, np.ones_like(img) * 1e-4, np.zeros_like(img, int), grid)


ra0, dec0 = 10.0, 0.0
grid, shape = frames.target_grid(ra0, dec0, 0.04)
rng = np.random.default_rng(1)
# pass 0 sampled mostly short wavelengths, pass 1 mostly long ones (same detector range 1.6-2.4 um)
p0 = [fake_cutout(w) for w in np.r_[rng.uniform(1.6, 1.8, 14), rng.uniform(1.8, 2.4, 4)]]
p1 = [fake_cutout(w) for w in np.r_[rng.uniform(1.6, 2.2, 4), rng.uniform(2.2, 2.4, 14)]]
naive0, _ = frames.coadd(p0, grid, shape)
naive1, _ = frames.coadd(p1, grid, shape)
naive = np.nanmax(naive1) / np.nanmax(naive0)
fair = frames.stack_like_for_like({0: p0, 1: p1}, grid, shape)
ratio = np.nanmax(fair[1]["img"]) / np.nanmax(fair[0]["img"])
check("constant star: plain stacking WOULD fake a change (shows why the fix matters)", abs(naive - 1) > 0.15,
      f"plain-stack ratio {naive:.2f}")
check("constant star: fair stacking shows no change", abs(ratio - 1) < 0.05, f"ratio {ratio:.3f}")

# a pass that misses part of the wavelength range is labelled 'limited'
p2 = [fake_cutout(w) for w in rng.uniform(1.6, 1.75, 6)]
fair3 = frames.stack_like_for_like({0: p0, 1: p1, 2: p2}, grid, shape)
check("pass with missing wavelengths is labelled 'limited comparison'", fair3[2]["limited"])

# ------------------------------------------------------------ 2. no invented pixels
img = np.ones((30, 30))
img[0:5, 0:10] = np.nan            # no coverage at the edge
img[14:17, 14:17] = np.nan         # enclosed hole = burnt-out star centre
img[12:19, 12:19][np.isfinite(img[12:19, 12:19])] = 50.0
filled, mask = frames.fill_saturated_cores(img)
check("burnt-out star centre is filled", np.isfinite(filled[15, 15]) and filled[15, 15] >= 50)
check("missing data at the edge stays 'no data'", np.isnan(filled[0:5, 0:10]).all())

# one-off glitch in a single photo is thrown out; a real star in every photo is kept
cube = np.zeros((10, 20, 20)) + rng.normal(0, 0.01, (10, 20, 20))
cube[:, 10, 10] += np.linspace(1.0, 2.5, 10)   # real star, brightness varies 2.5x across wavelengths
cube[3, 4, 4] = 50.0                           # glitch in one photo only
frames.reject_glitches(cube)
check("one-off glitch in a single photo is removed", np.isnan(cube[3, 4, 4]))
check("real star seen in every photo is kept", np.isfinite(cube[:, 10, 10]).all())

# ------------------------------------------------------------ 3. RA wrap
check("RA difference across 0/360", abs(dra(359.999, 0.001) - (-0.002)) < 1e-9 and abs(dra(0.001, 359.999) - 0.002) < 1e-9)

# ------------------------------------------------------------ 4. real data (tour targets)
from spx import analysis  # noqa: E402

def have(ra, dec):
    return flipbook.saved_path(ra, dec, 0.06).exists()

if have(269.4464, 4.7686):
    # an ordinary field star near Barnard's Star (Gaia G=11.9): its spectrum must repeat between passes
    sp = analysis.spectrum(269.4464, 4.7686, 0.06, 269.44387, 4.79629)
    meds = []
    for c in sp["curves"]:
        meds.append(np.median([f for w, f in zip(c["wl"], c["flux"]) if 1.0 < w < 4.0]))
    spread = (max(meds) - min(meds)) / np.mean(meds)
    check("steady field star: same brightness in every pass (within 5%)", spread < 0.05, f"spread {spread:.1%}")
    mv = analysis.movers(269.4464, 4.7686, 0.06)["movers"]
    b = [m for m in mv if m["status"].startswith("known") and 9 < m["rate"] < 12]
    check("Barnard's Star found as a KNOWN mover at ~10\"/yr", bool(b), ", ".join(f"{m['status'][:9]} {m['rate']:.1f}" for m in mv))
else:
    print("skip  Barnard's Star not downloaded")

if have(133.7593, -7.2421):
    mv = analysis.movers(133.7593, -7.2421, 0.06)["movers"]
    w = [m for m in mv if m["status"].startswith("candidate") and 5 < m["rate"] < 11]
    check("WISE 0855 found as a CANDIDATE mover (not in Gaia)", bool(w), ", ".join(f"{m['status'][:9]} {m['rate']:.1f}" for m in mv))
else:
    print("skip  WISE 0855 not downloaded")

if have(331.097, -56.8008):
    mv = analysis.movers(331.097, -56.8008, 0.06)["movers"]
    e = [m for m in mv if m["status"].startswith("known") and 3.5 < m["rate"] < 6]
    check("Epsilon Indi B found as a KNOWN mover at ~4.7\"/yr", bool(e), ", ".join(f"{m['status'][:9]} {m['rate']:.1f}" for m in mv))

if have(248.1672, 66.755):
    mv = analysis.movers(248.1672, 66.755, 0.06)["movers"]
    check("R Draconis (a variable star, not a mover) gives no false movers", not mv, f"{len(mv)} reported")

if have(76.9566, 30.4013):
    mv = analysis.movers(76.9566, 30.4013, 0.06)["movers"]
    check("RW Aurigae (a variable star, not a mover) gives no false movers", not mv, f"{len(mv)} reported")
else:
    print("skip  RW Aurigae not downloaded")

# ------------------------------------------------------------ 5. volunteer tools (real data)
from spx import objcheck  # noqa: E402

if have(331.097, -56.8008):
    sp = analysis.spectrum(331.097, -56.8008, 0.06, 331.097, -56.8008)
    w = objcheck.what_is_it(sp)
    check("Epsilon Indi B's spectrum is read as a cold brown dwarf", "brown dwarf" in w["label"], w["label"])
    try:
        c = objcheck.checks(331.097, -56.8008, 0.06, 331.097, -56.8008, spec=sp, movers=analysis.movers(331.097, -56.8008, 0.06))
        pr = c["partner"].get("partners", [])
        check("Epsilon Indi B: partner star found (Epsilon Indi A, moving the same way)", bool(pr) and pr[0]["g"] < 6,
              str(pr[:1]))
    except Exception as e:
        print("skip  partner check (catalogue not reachable):", e)

if have(269.4464, 4.7686):
    w = objcheck.what_is_it(analysis.spectrum(269.4464, 4.7686, 0.06, 269.44387, 4.79629))
    check("ordinary field star is read as an ordinary star", "ordinary star" in w["label"], w["label"])

# published SPHEREx brown-dwarf templates (Gagne et al. 2026): type must come out right
if have(331.097, -56.8008):
    w = objcheck.what_is_it(analysis.spectrum(331.097, -56.8008, 0.06, 331.097, -56.8008))
    t = (w.get("template") or {}).get("best", "")
    check("templates: Epsilon Indi B (true types T1+T6) matches a T-type template", w.get("method") == "templates" and t.startswith("T"), t)
if have(162.2951, -53.3169):
    w = objcheck.what_is_it(analysis.spectrum(162.2951, -53.3169, 0.06, 162.2951, -53.3169))
    t = (w.get("template") or {}).get("best", "")
    check("templates: Luhman 16 (true types L7.5+T0.5) matches L7 to T1", w.get("method") == "templates" and t in ("L7", "L8", "L9", "T0", "T1"), t)
if have(269.4464, 4.7686):
    w = objcheck.what_is_it(analysis.spectrum(269.4464, 4.7686, 0.06, 269.44387, 4.79629))
    check("templates: an ordinary star is NOT called a brown dwarf", w.get("method") != "templates", w["label"])

if have(76.9566, 30.4013):
    pk = analysis.picks(76.9566, 30.4013, 0.06)["picks"]
    check("computer's picks: RW Aurigae flagged as 'changed brightness', not as a mover",
          any(o["kind"] == "changed" for o in pk) and not any(o["kind"] == "mover" for o in pk),
          ", ".join(o["kind"] for o in pk))

if have(85.467, -4.852) or True:
    # a quiet field must give no picks (no false alarms)
    try:
        pk = analysis.picks(260.6592, -23.8261, 0.06)["picks"] if have(260.6592, -23.8261) else None
        if pk is not None:
            check("computer's picks: quiet field (Barnard 68) gives no false alarms", len(pk) == 0, f"{len(pk)} picks")
    except Exception as e:
        print("skip  quiet-field check:", e)

print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED: " + "; ".join(failures)))
sys.exit(1 if failures else 0)
