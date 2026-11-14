"""Local web server for the SPHEREx sky flip-book.

Start it with start.bat (or: .venv\\Scripts\\python -m uvicorn server.app:app --port 8000)
then open http://localhost:8000 in a browser.
"""
from __future__ import annotations

import sys
import threading
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spx import analysis, flipbook, resolve  # noqa: E402
from spx.tour import TOUR  # noqa: E402

app = FastAPI(title="SPHEREx sky flip-book")
JOBS: dict[str, dict] = {}
ONE_AT_A_TIME = threading.Lock()  # be polite to the archive: one position at a time


@app.get("/api/resolve")
def resolve_q(q: str):
    """Turn what the user typed into RA/Dec in degrees.
    Accepts '269.45 4.69', '17 57 48.5 +04 41 36', or a name (moved forward for proper motion)."""
    try:
        return resolve.resolve(q)
    except Exception as e:
        raise HTTPException(404, str(e))


@app.get("/api/tour")
def tour_list():
    """The five test targets. Positions come from data/tour.json (written by
    scripts/prebuild.py) so the tour works without a name lookup."""
    import json
    saved = {}
    tj = ROOT / "data" / "tour.json"
    if tj.exists():
        saved = json.loads(tj.read_text())
    out = []
    for t in TOUR:
        d = dict(t)
        if t["key"] in saved:
            d.update(saved[t["key"]])
            d["ready"] = flipbook.result_path(round(d["ra"], 4), round(d["dec"], 4), t["field"]).exists()
        out.append(d)
    return out


@app.post("/api/flipbook")
def start(ra: float, dec: float, field: float = 0.06):
    if not (0 <= ra < 360 and -90 <= dec <= 90):
        raise HTTPException(400, "RA must be 0-360 and Dec -90 to +90 degrees.")
    field = min(max(field, 0.02), 0.15)
    if flipbook.result_path(round(ra, 4), round(dec, 4), field).exists():
        job_id = "cached-" + uuid.uuid4().hex[:8]
        JOBS[job_id] = dict(state="done", stage="Loaded from your computer", frac=1.0,
                            args=(ra, dec, field))
        warm(ra, dec, field)
        return dict(job=job_id)
    job_id = uuid.uuid4().hex[:12]
    job = JOBS[job_id] = dict(state="queued", stage="Waiting for the previous request", frac=0.0,
                              args=(ra, dec, field))

    def run():
        with ONE_AT_A_TIME:
            job["state"] = "running"
            try:
                flipbook.build(ra, dec, field, progress=lambda s, f: job.update(stage=s, frac=f))
                job.update(state="done", stage="Done", frac=1.0)
                warm(ra, dec, field)
            except Exception as e:
                traceback.print_exc()
                job.update(state="error", stage=str(e))

    threading.Thread(target=run, daemon=True).start()
    return dict(job=job_id)


@app.get("/api/job/{job_id}")
def status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown request")
    return {k: v for k, v in job.items() if k != "args"}


@app.get("/api/job/{job_id}/result")
def result(job_id: str):
    job = JOBS.get(job_id)
    if not job or job["state"] != "done":
        raise HTTPException(404, "Not ready")
    ra, dec, field = job["args"]
    path = flipbook.result_path(round(ra, 4), round(dec, 4), field)
    if not path.exists():
        path = path.with_name(path.stem + "_partial.json")
    return FileResponse(path, media_type="application/json")


def warm(ra, dec, field):
    """Load the cutouts into memory in the background so the first spectrum click is quick."""
    threading.Thread(target=lambda: analysis.load_position(ra, dec, field), daemon=True).start()


def _ready(ra, dec, field):
    if not flipbook.result_path(round(ra, 4), round(dec, 4), field).exists():
        raise HTTPException(404, "Load this position first.")


@app.get("/api/spectrum")
def spectrum(ra0: float, dec0: float, field: float, ra: float, dec: float):
    _ready(ra0, dec0, field)
    return analysis.spectrum(ra0, dec0, field, ra, dec)


@app.get("/api/lenses")
def lenses():
    return analysis.lens_list()


@app.get("/api/lens")
def lens(ra0: float, dec0: float, field: float, key: str, pass_index: int | None = None):
    _ready(ra0, dec0, field)
    if key not in analysis.LENSES:
        raise HTTPException(404, "Unknown lens")
    return analysis.lens(ra0, dec0, field, key, pass_index)


@app.get("/api/flags")
def flags(ra0: float, dec0: float, field: float, pass_index: int, band: int):
    _ready(ra0, dec0, field)
    return analysis.flags_map(ra0, dec0, field, pass_index, band)


@app.get("/api/movers")
def movers(ra0: float, dec0: float, field: float):
    _ready(ra0, dec0, field)
    return analysis.movers(ra0, dec0, field)


@app.get("/api/gaia")
def gaia(ra0: float, dec0: float, field: float):
    _ready(ra0, dec0, field)
    try:
        return analysis.gaia(ra0, dec0, field)
    except Exception as e:
        raise HTTPException(502, f"Could not reach the Gaia archive: {e}")


@app.post("/api/gif")
async def make_gif(request: Request):
    """The page sends the frames it is showing (as PNG pictures); we glue them into an
    animated GIF the user can save and share."""
    import base64
    import io
    from PIL import Image

    body = await request.json()
    frames = []
    for d in body.get("frames", [])[:12]:
        raw = base64.b64decode(d.split(",", 1)[1])
        frames.append(Image.open(io.BytesIO(raw)).convert("RGB"))
    if not frames:
        raise HTTPException(400, "No frames")
    pal = frames[0].quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    buf = io.BytesIO()
    q[0].save(buf, format="GIF", save_all=True, append_images=q[1:],
              duration=int(body.get("ms", 700)), loop=0)
    return Response(buf.getvalue(), media_type="image/gif")


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
