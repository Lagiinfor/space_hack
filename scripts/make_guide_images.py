"""Make the pictures for the guide's "Is this fake?" section from real SPHEREx data
(the saved tour targets). Run:  .venv\\Scripts\\python scripts\\make_guide_images.py
"""
import base64
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
from spx import analysis, frames  # noqa: E402

OUT = ROOT / "web" / "img"
OUT.mkdir(exist_ok=True)


def stack(pos, band, k):
    res = pos["result"]
    grid, shape = frames.target_grid(pos["ra"], pos["dec"], pos["field"])
    for f in res["frames"]:
        if f["band"] == band and f["pass_index"] == k:
            return np.frombuffer(base64.b64decode(f["pixels"]), dtype="<f4").reshape(shape), f["noise"], res["passes"][k]["label"]


def single(pos, obs, det, fill=False):
    grid, shape = frames.target_grid(pos["ra"], pos["dec"], pos["field"])
    for c in pos["cuts"]:
        if c.obs_id == obs and c.detector == det:
            img = frames.resample(c.image, c.wcs, grid, shape)
            return frames.fill_saturated_cores(img)[0] if fill else img
    raise KeyError(obs)


def show(ax, img, noise, title, mark=None, vmax=None):
    v = np.arcsinh(np.nan_to_num(img, nan=0.0) / (3 * noise))
    hi = np.arcsinh((vmax or 60 * noise) / (3 * noise))
    ax.imshow(np.where(np.isfinite(img), v, np.nan), origin="lower", cmap="gray", vmin=0, vmax=hi)
    ax.set_facecolor("#3a1616")
    ax.set_title(title, color="#e8eefc", fontsize=10)
    ax.set_xticks([]); ax.set_yticks([])
    if mark:
        n = img.shape[0]
        x, y = n / 2 - mark[0] / 3.075 - 0.5, n / 2 + mark[1] / 3.075 - 0.5
        ax.add_patch(plt.Circle((x, y), 6, fill=False, color="#ffc857", lw=1.5))


def save(fig, name):
    fig.patch.set_facecolor("#101624")
    fig.tight_layout()
    fig.subplots_adjust(top=0.82)
    fig.savefig(OUT / name, dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    print("wrote", name)


# 1 + 2: the blob Lavi found near WISE 0855 (cosmic-ray flash, and an afterimage)
pos = analysis.load_position(133.7593, -7.2421, 0.06)
blob = (-55, 20)
st, nz, lab = stack(pos, 5, 2)
fig, ax = plt.subplots(1, 3, figsize=(9, 3.3))
show(ax[0], single(pos, "2026W20_1A_0939_1", 5), nz * 4, "One photo, 13 May 2026:\na flash (cosmic ray or glint)", blob, vmax=400 * nz)
show(ax[1], single(pos, "2026W20_1A_0728_1", 5), nz * 4, "Another photo, same week:\nnothing there", blob, vmax=400 * nz)
show(ax[2], st, nz, f"All photos stacked ({lab}):\nthe flash is thrown out", blob)
save(fig, "fake_cosmic_ray.png")

st6, nz6, lab6 = stack(pos, 6, 2)
fig, ax = plt.subplots(1, 2, figsize=(6.2, 3.3))
show(ax[0], single(pos, "2026W17_2A_0692_2", 6), nz6 * 4, "One photo, 26 Apr 2026:\nafterimage of an earlier bright star", blob, vmax=300 * nz6)
show(ax[1], st6, nz6, f"All photos stacked ({lab6}):\ngone", blob)
save(fig, "fake_afterimage.png")

# 3: burnt-out centre of a very bright star (R Draconis)
pos = analysis.load_position(248.1672, 66.755, 0.06)
c = next(c for c in pos["cuts"] if c.detector == 3)
fig, ax = plt.subplots(1, 2, figsize=(6.2, 3.3))
raw = single(pos, c.obs_id, 3)
show(ax[0], raw, 0.05, "Very bright star, one photo:\nthe centre is burnt out (red = no data)", vmax=30)
show(ax[1], single(pos, c.obs_id, 3, fill=True), 0.05, "The tool fills only that hole,\nso the star looks solid", vmax=30)
save(fig, "fake_saturated.png")

# 4: a real mover for comparison (Epsilon Indi B)
pos = analysis.load_position(331.097, -56.8008, 0.06)
a, na, la = stack(pos, 6, 0)
b, nb, lb = stack(pos, 6, 3)
fig, ax = plt.subplots(1, 2, figsize=(6.2, 3.3))
for axi, im, t in ((ax[0], a, la), (ax[1], b, lb)):
    show(axi, im, na, f"{t}: stack of ~20 photos", vmax=80 * na)
    n = im.shape[0]
    axi.axhline(n / 2 - 0.5, color="#6cc4ff", lw=0.6); axi.axvline(n / 2 - 0.5, color="#6cc4ff", lw=0.6)
save(fig, "real_mover.png")

# 5: a real asteroid (Eros): in single photos only
pos = analysis.load_position(29.0314, 28.7635, 0.06)
ex = sorted([c for c in pos["cuts"] if abs(c.mjd - 61053.2236) < 0.01 and c.detector == 3], key=lambda c: c.mjd)
st, nz, lab = stack(pos, 3, 1)
fig, ax = plt.subplots(1, 3, figsize=(9, 3.3))
show(ax[0], single(pos, ex[0].obs_id, 3, fill=True), nz * 4, "Asteroid Eros, one photo\n(13 Jan 2026, 05:20)", vmax=400 * nz)
show(ax[1], single(pos, ex[-1].obs_id, 3, fill=True), nz * 4, "Six minutes later:\nit has moved", vmax=400 * nz)
show(ax[2], st, nz, f"All photos stacked ({lab}):\nthrown out as a one-off (faint ring left)")
save(fig, "real_asteroid.png")
