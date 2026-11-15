"""Local web server for the SPHEREx sky flip-book.

Start it with start.bat (or: .venv\\Scripts\\python -m uvicorn server.app:app --port 8000)
then open http://localhost:8000 in a browser.
"""
from __future__ import annotations

import json
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


@app.middleware("http")
async def no_stale_pages(request, call_next):
    """Make the browser always fetch the newest version of the page and its scripts,
    so improvements show up on a normal refresh."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-cache"
    return response
JOBS: dict[str, dict] = {}
ONE_AT_A_TIME = threading.Lock()  # be polite to the archive: one position at a time
LATEST: dict[str, str] = {}        # most recent download request per browser tab


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
            d["ready"] = flipbook.is_current(round(d["ra"], 4), round(d["dec"], 4), t["field"])
        out.append(d)
    return out


@app.post("/api/flipbook")
def start(ra: float, dec: float, field: float = 0.06, client: str = "local"):
    if not (0 <= ra < 360 and -90 <= dec <= 90):
        raise HTTPException(400, "RA must be 0-360 and Dec -90 to +90 degrees.")
    field = min(max(field, 0.02), 0.15)
    if flipbook.is_current(round(ra, 4), round(dec, 4), field):
        job_id = "cached-" + uuid.uuid4().hex[:8]
        JOBS[job_id] = dict(state="done", stage="Loaded from your computer", frac=1.0,
                            args=(ra, dec, field))
        warm(ra, dec, field)
        return dict(job=job_id)
    job_id = uuid.uuid4().hex[:12]
    job = JOBS[job_id] = dict(state="queued", stage="Stopping the patch you opened before (a few seconds)...",
                              frac=0.0, args=(ra, dec, field))
    LATEST[client] = job_id       # a newer request from the same browser tab makes its older one stop
    stop = lambda: LATEST.get(client) != job_id  # noqa: E731

    def run():
        with ONE_AT_A_TIME:
            if stop():
                job.update(state="cancelled", stage="Replaced by a newer request")
                return
            job["state"] = "running"
            try:
                def on_preview(pre):
                    job["preview"] = json.dumps(pre)
                    job["preview_n"] = pre["n_used"]
                flipbook.build(ra, dec, field, progress=lambda s, f: job.update(stage=s, frac=f), stop=stop,
                               on_preview=on_preview)
                job.pop("preview", None)
                job.update(state="done", stage="Done", frac=1.0)
                analysis._cache.pop((round(ra, 4), round(dec, 4), field), None)   # forget older copy
                warm(ra, dec, field)
            except flipbook.Cancelled:
                job.update(state="cancelled", stage="Replaced by a newer request")
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
    return {k: v for k, v in job.items() if k not in ("args", "preview")}


@app.get("/api/job/{job_id}/preview")
def preview(job_id: str):
    """A first look made from the photos downloaded so far (fairly stacked)."""
    job = JOBS.get(job_id)
    if not job or "preview" not in job:
        raise HTTPException(404, "No preview yet")
    return Response(job["preview"], media_type="application/json")


@app.get("/api/job/{job_id}/result")
def result(job_id: str):
    job = JOBS.get(job_id)
    if not job or job["state"] != "done":
        raise HTTPException(404, "Not ready")
    ra, dec, field = job["args"]
    path = flipbook.saved_path(round(ra, 4), round(dec, 4), field)
    return FileResponse(path, media_type="application/json")


def warm(ra, dec, field):
    """Load the cutouts into memory in the background so the first spectrum click is quick."""
    threading.Thread(target=lambda: analysis.load_position(ra, dec, field), daemon=True).start()


def _ready(ra, dec, field):
    if not flipbook.saved_path(round(ra, 4), round(dec, 4), field).exists():
        raise HTTPException(404, "Load this position first.")


@app.get("/api/spectrum")
def spectrum(ra0: float, dec0: float, field: float, ra: float, dec: float):
    _ready(ra0, dec0, field)
    sp = analysis.spectrum(ra0, dec0, field, ra, dec)
    try:
        from spx import objcheck
        sp["what"] = objcheck.what_is_it(sp)
    except Exception:
        pass
    return sp


@app.get("/api/lenses")
def lenses():
    return analysis.lens_list()


@app.get("/api/lens")
def lens(ra0: float, dec0: float, field: float, key: str, pass_index: int | None = None, win: str = ""):
    _ready(ra0, dec0, field)
    if key == "custom":
        # win = "lo-hi,lo-hi,lo-hi" in microns: red, green, blue
        try:
            windows = [tuple(float(x) for x in part.split("-")) for part in win.split(",")]
            assert len(windows) == 3 and all(len(w) == 2 and 0.7 <= w[0] < w[1] <= 5.1 for w in windows)
        except Exception:
            raise HTTPException(400, "Give three wavelength ranges between 0.75 and 5.0 microns, each from low to high.")
        return analysis.lens(ra0, dec0, field, key, pass_index, windows=windows)
    if key not in analysis.LENSES:
        raise HTTPException(404, "Unknown lens")
    return analysis.lens(ra0, dec0, field, key, pass_index)


@app.get("/api/window")
def window(ra0: float, dec0: float, field: float, win: str):
    """Flip-book frames from the person's own wavelength ranges: win = "lo-hi" or "lo-hi,lo-hi" (microns)."""
    _ready(ra0, dec0, field)
    try:
        windows = [tuple(float(x) for x in part.split("-")) for part in win.split(",") if part.strip()]
        assert 1 <= len(windows) <= 4 and all(len(w) == 2 and 0.7 <= w[0] < w[1] <= 5.1 for w in windows)
    except Exception:
        raise HTTPException(400, "Type wavelength ranges in microns between 0.75 and 5.0, like 3.2-3.5 or 3.2-3.5, 4.4-5.0.")
    return analysis.window_frames(ra0, dec0, field, windows)


@app.get("/api/images")
def images(ra0: float, dec0: float, field: float):
    """Where each photo of this patch lives in NASA's archive (the original full file)."""
    _ready(ra0, dec0, field)
    p = flipbook.place_dir(round(ra0, 4), round(dec0, 4)) / "images.json"
    if not p.exists():
        return []
    import json as _json
    return [dict(obs_id=i["obs_id"], detector=i["detector"], url=i["url"], collection=i.get("collection"))
            for i in _json.loads(p.read_text())]


@app.get("/api/flags")
def flags(ra0: float, dec0: float, field: float, pass_index: int, band: int):
    _ready(ra0, dec0, field)
    return analysis.flags_map(ra0, dec0, field, pass_index, band)


@app.get("/api/movers")
def movers(ra0: float, dec0: float, field: float, cats: str = "gaia"):
    _ready(ra0, dec0, field)
    return analysis.movers(ra0, dec0, field, cats)


@app.get("/api/catalogs")
def catalog_list(ra0: float = None, dec0: float = None, field: float = None):
    """The catalogues of known objects that can be switched on, with their colours, and
    whether each is already saved for this patch."""
    from spx import catalogs
    out = []
    for c in catalogs.CATALOGS:
        d = dict(c)
        if ra0 is not None:
            d["saved"] = catalogs.is_saved(ra0, dec0, field, c["key"])
            d["covered"] = catalogs.covers(c["key"], dec0)
        out.append(d)
    return out


@app.get("/api/catalog")
def catalog(ra0: float, dec0: float, field: float, cat: str):
    """One catalogue's sources in the patch. Downloaded the first time, then kept."""
    from spx import catalogs
    _ready(ra0, dec0, field)
    if cat not in catalogs.BY_KEY or cat == "gaia":
        raise HTTPException(400, "Unknown catalogue.")
    try:
        return catalogs.for_view(ra0, dec0, field, cat)
    except Exception as e:
        raise HTTPException(502, f"Could not reach the {catalogs.BY_KEY[cat]['short']} catalogue: {e}")


@app.get("/api/asteroids")
def solar_system(ra0: float, dec0: float, field: float):
    """Known asteroids/comets in the patch, photo by photo, with NASA/JPL's published risk info."""
    _ready(ra0, dec0, field)
    try:
        return analysis.solar_system(ra0, dec0, field)
    except Exception as e:
        raise HTTPException(502, f"Could not reach the asteroid services: {e}")


@app.get("/api/photo")
def photo(ra0: float, dec0: float, field: float, obs_id: str, detector: int):
    _ready(ra0, dec0, field)
    try:
        return analysis.single_photo(ra0, dec0, field, obs_id, detector)
    except KeyError:
        raise HTTPException(404, "That photo is not in this patch.")


@app.get("/api/known")
def known(ra0: float, dec0: float, field: float, cats: str = "gaia"):
    """Known things in the patch (Gaia fast movers, named objects, known asteroids)."""
    _ready(ra0, dec0, field)
    return analysis.known_objects(ra0, dec0, field, cats)


@app.get("/api/board")
def get_board(day: str = ""):
    from spx import board
    return board.board(day)


@app.post("/api/score")
async def post_score(request: Request):
    from spx import board
    b = await request.json()
    return board.add_score(b.get("name", ""), int(b.get("score", 0)), b.get("mode", "free"), b.get("day", ""), b.get("rounds", []))


@app.post("/api/explored")
async def post_explored(request: Request):
    from spx import board
    b = await request.json()
    return board.add_explored(b.get("name", ""), float(b["ra"]), float(b["dec"]))


@app.get("/api/picks")
def picks(ra0: float, dec0: float, field: float, cats: str = "gaia"):
    """Small areas the computer finds interesting (movers, brightness changes, very red objects)."""
    _ready(ra0, dec0, field)
    return analysis.picks(ra0, dec0, field, cats)


@app.get("/api/inspect")
def inspect_object(ra0: float, dec0: float, field: float, ra: float, dec: float, cats: str = "gaia"):
    """All automatic checks for one clicked object (see spx/objcheck.py)."""
    _ready(ra0, dec0, field)
    from spx import objcheck
    spec = analysis.spectrum(ra0, dec0, field, ra, dec)
    try:
        mv = analysis.movers(ra0, dec0, field, cats)
    except Exception:
        mv = None
    out = objcheck.checks(ra0, dec0, field, ra, dec, spec=spec, movers=mv, cats=cats)
    out["what"] = objcheck.what_is_it(spec)
    return out


@app.post("/api/report")
async def report(request: Request):
    """Save a volunteer's report as a file on this computer."""
    from spx import objcheck
    body = await request.json()
    return objcheck.save_report(body)


@app.get("/api/other")
def other(ra0: float, dec0: float, field: float):
    """Frames from other telescopes (WISE 2010, Canada's NEOSSat) for the patch."""
    _ready(ra0, dec0, field)
    return analysis.other_frames(ra0, dec0, field)


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
