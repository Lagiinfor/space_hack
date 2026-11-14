"""Turn stacked frames into pictures and animations."""
from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


def stretch(img: np.ndarray, soft: float, vmax: float) -> np.ndarray:
    """Map brightness to 0..1 with an asinh curve: faint stars stay visible
    without the bright star burning out. `soft` is roughly the noise level."""
    out = np.arcsinh(np.nan_to_num(img, nan=0.0) / soft) / np.arcsinh(vmax / soft)
    return np.clip(out, 0, 1)


def fig_to_image(fig) -> Image.Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=fig.dpi, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def save_gif(frames: list[Image.Image], path, ms_per_frame: int = 800):
    pal = frames[0].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    q[0].save(path, save_all=True, append_images=q[1:], duration=ms_per_frame, loop=0)
