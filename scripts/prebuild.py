"""Download and stack the five tour targets ahead of time so they open instantly.
Run:  .venv\\Scripts\\python scripts\\prebuild.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spx import flipbook  # noqa: E402
from spx.resolve import resolve  # noqa: E402
from spx.tour import TOUR  # noqa: E402

only = set(sys.argv[1:])
tour_file = ROOT / "data" / "tour.json"
saved = json.loads(tour_file.read_text()) if tour_file.exists() else {}
for t in TOUR:
    if only and t["key"] not in only:
        continue
    pos = resolve(t["query"])
    t0 = time.time()
    print(f"{t['name']}: {pos['ra']:.4f} {pos['dec']:+.4f}", flush=True)
    try:
        r = flipbook.build(pos["ra"], pos["dec"], t["field"],
                           progress=lambda s, f: None)
        saved[t["key"]] = dict(ra=round(pos["ra"], 4), dec=round(pos["dec"], 4), how=pos.get("how", ""))
        tour_file.write_text(json.dumps(saved, indent=1))
        print(f"  done: {r['n_used']} images, {len(r['passes'])} passes, {time.time() - t0:.0f} s", flush=True)
    except Exception as e:
        print(f"  FAILED: {e}", flush=True)
