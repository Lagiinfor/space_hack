"""Step 1 proof of concept: Barnard's Star flip-book from SPHEREx.

Run from the project folder:   python3 scripts/barnard_demo.py
Outputs go to output/barnard/.
"""
import json
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.time import Time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spx import archive, astrometry, frames, render  # noqa: E402
from spx.targets import TARGETS  # noqa: E402

warnings.filterwarnings("ignore")
NAME = "barnard"
STAR = TARGETS[NAME]
CUTOUT_DEG = 0.1          # size requested from the archive
FIELD_DEG = 0.06          # size shown (3.6 arcmin)
DATA = ROOT / "data" / NAME
OUT = ROOT / "output" / NAME
OUT.mkdir(parents=True, exist_ok=True)
BLUE, ORANGE, INK, MUTED, SURFACE = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#fcfcfb"

# ---- 1. find + download -------------------------------------------------
ra0, dec0 = astrometry.predict_position(STAR, Time("2026-03-01").mjd)  # field centre
ra0, dec0 = round(ra0, 4), round(dec0, 4)
images = archive.find_images(ra0, dec0, DATA)
got = archive.fetch_all(images, ra0, dec0, CUTOUT_DEG, DATA / "cutouts")
cuts = [frames.load_cutout(p, ra0, dec0) for _, p in got]
passes = frames.assign_passes([c.mjd for c in cuts])
n_pass = passes.max() + 1
pass_date = [Time(np.mean([c.mjd for c, p in zip(cuts, passes) if p == k]), format="mjd") for k in range(n_pass)]
label = [t.strftime("%b %Y") for t in pass_date]
print(f"{len(cuts)} exposures in {n_pass} sky passes: {label}")

# ---- 2. stack per pass and detector -------------------------------------
grid, shape = frames.target_grid(ra0, dec0, FIELD_DEG)
stack, wl = {}, {}
for k in range(n_pass):
    for d in range(1, 7):
        sel = [c for c, p in zip(cuts, passes) if p == k and c.detector == d]
        stack[k, d], _ = frames.coadd(sel, grid, shape)
        wl[k, d] = (min(c.wavelength for c in sel), max(c.wavelength for c in sel), len(sel))
    stack[k, 0] = np.nanmean([stack[k, d] for d in range(1, 7)], axis=0)  # all six together

# ---- 3. measure the star in every exposure ------------------------------
rows = []
for c, p in zip(cuts, passes):
    pred = astrometry.predict_position(STAR, c.mjd)
    m = astrometry.measure_position(c, *pred)
    if m is None:
        continue
    cosd = np.cos(np.radians(dec0))
    rows.append((p, c.detector, c.mjd,
                 (m[0] - ra0) * 3600 * cosd, (m[1] - dec0) * 3600,
                 (pred[0] - ra0) * 3600 * cosd, (pred[1] - dec0) * 3600))
rows = np.array(rows)


def robust(a):
    med = np.median(a)
    return med, 1.4826 * np.median(np.abs(a - med)) / np.sqrt(len(a)) * 1.25


summary = []
for k in range(n_pass):
    s = rows[rows[:, 0] == k]
    (mx, ex), (my, ey) = robust(s[:, 3]), robust(s[:, 4])
    summary.append(dict(pass_label=label[k], mjd=float(s[:, 2].mean()), n=len(s),
                        meas_east=mx, meas_east_err=ex, meas_north=my, meas_north_err=ey,
                        pred_east=float(np.median(s[:, 5])), pred_north=float(np.median(s[:, 6]))))
for a, b in [(0, 1), (0, 2), (1, 2)][: max(0, n_pass * (n_pass - 1) // 2)]:
    A, B = summary[a], summary[b]
    print(f"{A['pass_label']} -> {B['pass_label']}: "
          f"measured north {B['meas_north']-A['meas_north']:+.2f}\" east {B['meas_east']-A['meas_east']:+.2f}\"  |  "
          f"predicted north {B['pred_north']-A['pred_north']:+.2f}\" east {B['pred_east']-A['pred_east']:+.2f}\"")
(OUT / "measurements.json").write_text(json.dumps(summary, indent=1))

# ---- 4. flip-book GIFs ---------------------------------------------------
BANDS = {1: "0.75-1.1", 2: "1.1-1.6", 3: "1.6-2.4", 4: "2.4-3.8", 5: "3.8-4.4", 6: "4.4-5.0"}
half = FIELD_DEG * 3600 / 2
ext = [half, -half, -half, half]  # east to the left


def scale_for(d):
    ref = stack[0, d]
    soft = 3 * 1.4826 * np.nanmedian(np.abs(ref - np.nanmedian(ref)))
    return soft, np.nanpercentile(ref, 99.9)


def draw(ax, k, d, mark=True):
    soft, vmax = scale_for(d)
    ax.imshow(render.stretch(stack[k, d], soft, vmax), origin="lower", cmap="gray",
              vmin=0, vmax=1, extent=ext, interpolation="nearest")
    if mark:  # fixed ring where the star was in the first pass
        ax.add_patch(plt.Circle((-summary[0]["meas_east"], summary[0]["meas_north"]), 9,
                                fill=False, color=ORANGE, lw=1.8))
    ax.set_xticks([]); ax.set_yticks([])


six = []
for k in range(n_pass):
    fig, axes = plt.subplots(2, 3, figsize=(9, 6.5), dpi=100, facecolor="black")
    for d, ax in zip(range(1, 7), axes.ravel()):
        draw(ax, k, d)
        ax.set_title(f"Detector {d}: {BANDS[d]} µm  ({wl[k, d][2]} exposures)", color="white", fontsize=9)
    fig.suptitle(f"Barnard's Star seen by SPHEREx, sky pass {k+1} of {n_pass}: {label[k]}",
                 color="white", fontsize=13)
    fig.text(0.5, 0.012, "Each panel is 3.6 arcmin wide, north up, east left. "
             "Orange ring = where the star was in the first pass.", color="#c3c2b7", ha="center", fontsize=9)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.9, bottom=0.05, wspace=0.03, hspace=0.12)
    six.append(render.fig_to_image(fig))
render.save_gif(six, OUT / "barnard_flipbook_6detectors.gif")

zoom = []
for k in range(n_pass):
    fig, ax = plt.subplots(figsize=(6, 6.5), dpi=100, facecolor="black")
    draw(ax, k, 0)
    ax.set_xlim(60, -60); ax.set_ylim(-60, 60)
    ax.plot([-52, -42], [-52, -52], color="white", lw=2)
    ax.text(-47, -49, '10"', color="white", ha="center", fontsize=10)
    ax.set_title(f"Barnard's Star, {label[k]}  (all detectors combined)", color="white", fontsize=13)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.93, bottom=0.01)
    zoom.append(render.fig_to_image(fig))
render.save_gif(zoom, OUT / "barnard_flipbook_zoom.gif")

# ---- 5. difference image -------------------------------------------------
if n_pass >= 3:
    diff = stack[2, 0] - stack[0, 0]
    lim = np.nanpercentile(np.abs(diff), 99.7)
    fig, ax = plt.subplots(figsize=(6, 6.4), dpi=110, facecolor=SURFACE)
    ax.imshow(diff, origin="lower", cmap="gray", vmin=-lim, vmax=lim, extent=ext, interpolation="nearest")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(f"{label[2]} minus {label[0]}: only what changed is left\n"
                 "white = light that arrived, black = light that left", color=INK, fontsize=11)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.9, bottom=0.01)
    render.fig_to_image(fig).save(OUT / "barnard_difference.png")

# ---- 6. measured vs predicted chart --------------------------------------
t_line = np.linspace(pass_date[0].mjd - 40, pass_date[-1].mjd + 40, 300)
track = np.array([astrometry.predict_position(STAR, t) for t in t_line])
tr_e = (track[:, 0] - ra0) * 3600 * np.cos(np.radians(dec0))
tr_n = (track[:, 1] - dec0) * 3600
e0, n0 = summary[0]["pred_east"], summary[0]["pred_north"]
dates = Time(t_line, format="mjd").to_datetime()
pd = [Time(s["mjd"], format="mjd").to_datetime() for s in summary]
fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), dpi=110, facecolor=SURFACE)
for ax, tr, key, zero, ttl in [
        (axes[0], tr_n, "north", n0, "Northward drift (arcseconds)"),
        (axes[1], tr_e, "east", e0, "East-west position (arcseconds, east is up)")]:
    ax.set_facecolor(SURFACE)
    ax.plot(dates, tr - zero, color=BLUE, lw=2, label="Predicted from the Gaia catalogue")
    ax.errorbar(pd, [s[f"meas_{key}"] - zero for s in summary],
                yerr=[s[f"meas_{key}_err"] for s in summary], fmt="o", ms=8, color=ORANGE,
                mec=SURFACE, mew=1.5, ecolor=ORANGE, capsize=3, label="Measured in SPHEREx images", zorder=3)
    ax.set_title(ttl, color=INK, fontsize=11, loc="left")
    ax.grid(color="#e4e3df", lw=0.8); ax.set_axisbelow(True)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(colors=MUTED, length=0, labelsize=9)
    ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %Y"))
axes[0].legend(frameon=False, fontsize=9, loc="upper left", labelcolor=INK)
axes[1].annotate("Feb to Mar 2026 pass: telescope was\nflipped 180 degrees, see note",
                 (pd[1], summary[1]["meas_east"] - e0), xytext=(12, -6), textcoords="offset points",
                 fontsize=8.5, color=MUTED, va="top")
fig.suptitle("Barnard's Star: SPHEREx measurements against the textbook prediction", color=INK,
             fontsize=13, x=0.01, ha="left")
fig.tight_layout(rect=(0, 0, 1, 0.94))
render.fig_to_image(fig).save(OUT / "barnard_motion_check.png")
print("outputs written to", OUT)
