"""Talk to the IRSA archive: find SPHEREx images covering a sky position and
download small cutouts around it.

Everything is cached on disk, so repeating a request costs nothing. To pick up a
new data release, add its collection name to COLLECTIONS (first one wins when the
same exposure appears in two releases).
"""
from __future__ import annotations

import csv
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

IRSA = "https://irsa.ipac.caltech.edu"
SIA = f"{IRSA}/SIA"
# Preferred release first.
COLLECTIONS = ["spherex_dr1", "spherex_qr3"]

_session = requests.Session()


def _get(url, params=None, tries=5, timeout=120):
    """GET with retries (the archive drops a connection now and then)."""
    last = None
    for i in range(tries):
        try:
            r = _session.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code} for {r.url}")
        except requests.RequestException as e:  # network hiccup
            last = e
        time.sleep(1.5 * (i + 1))
    raise last


def find_images(ra: float, dec: float, cache_dir: Path) -> list[dict]:
    """List every SPHEREx exposure whose footprint contains (ra, dec) in degrees.

    Returns one dict per exposure+detector: obs_id, detector (1-6), mjd,
    collection, url (where the full image file lives).
    Uses IRSA's image search service (SIA), which answers in about a second.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / "images.json"
    if cache.exists():
        return json.loads(cache.read_text())
    best: dict[tuple, dict] = {}
    complete = True
    for rank, coll in enumerate(COLLECTIONS):
        try:
            r = _get(SIA, params={"COLLECTION": coll, "POS": f"circle {ra} {dec} 0.0003",
                                  "RESPONSEFORMAT": "csv"}, tries=3)
        except Exception as e:  # one release unavailable: use the others, ask again next time
            print(f"  archive search failed for {coll}: {e}")
            complete = False
            continue
        for row in csv.DictReader(io.StringIO(r.text)):
            det = int(row["energy_bandpassname"][-1])
            key = (row["obs_id"], det)
            if key in best and best[key]["rank"] <= rank:
                continue
            best[key] = dict(obs_id=key[0], detector=det, mjd=float(row["t_min"]),
                             collection=coll, url=row["access_url"], rank=rank)
    out = sorted(best.values(), key=lambda d: (d["mjd"], d["detector"]))
    if complete:
        cache.write_text(json.dumps(out))
    return out


def _stream_image_layers(url, params, tries=6, timeout=120) -> bytes | None:
    """Download a cutout but stop as soon as the picture layers (IMAGE, FLAGS,
    VARIANCE, ZODI) have arrived. Each file also carries a ~4 MB star-shape table
    we don't need yet; skipping it makes downloads ~30x smaller."""
    marker = b"XTENSION= 'BINTABLE'"
    for i in range(tries):
        try:
            with _session.get(url, params=params, timeout=timeout, stream=True) as r:
                if r.status_code == 200:
                    buf = bytearray()
                    for chunk in r.iter_content(32768):
                        buf += chunk
                        j = buf.find(marker, max(0, len(buf) - len(chunk) - 40))
                        if j >= 0 and j % 2880 == 0:
                            return bytes(buf[:j])
                    if bytes(buf[:6]) == b"SIMPLE":
                        return bytes(buf)
                    # "Server busy, retry later." -> fall through and retry
        except requests.RequestException:
            pass
        time.sleep(2.0 * (i + 1))
    return None


def fetch_cutout(img: dict, ra: float, dec: float, size_deg: float, cache_dir: Path) -> Path | None:
    """Download a small cutout of one exposure around (ra, dec). Returns the
    local file path, or None if the archive could not provide it."""
    path = cache_dir / f"{img['obs_id']}_D{img['detector']}.fits"
    if path.exists() and path.stat().st_size > 2880:
        return path
    try:
        data = _stream_image_layers(img["url"], {"center": f"{ra},{dec}d", "size": f"{size_deg}"})
        if not data:
            print(f"  skipped {img['obs_id']} D{img['detector']}: archive did not answer")
            return None
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return path
    except Exception as e:  # keep going; one missing exposure is not fatal
        print(f"  skipped {img['obs_id']} D{img['detector']}: {e}")
        return None


def fetch_all(images: list[dict], ra: float, dec: float, size_deg: float,
              cache_dir: Path, workers: int = 8, progress=None, stop=None) -> list[tuple[dict, Path]]:
    """Download all cutouts in parallel. progress(done, total) is called as they arrive."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    done = [0]

    def one(im):
        if stop and stop():   # the person moved on to another patch: skip the rest quickly
            return None
        p = fetch_cutout(im, ra, dec, size_deg, cache_dir)
        done[0] += 1
        if progress:
            progress(done[0], len(images))
        return p

    with ThreadPoolExecutor(workers) as pool:
        paths = list(pool.map(one, images))
    return [(im, p) for im, p in zip(images, paths) if p is not None]
