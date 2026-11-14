"""Download every SPHEREx photo for the five tour targets (or for positions you give).

    .venv\Scripts\python scripts\download_photos.py              # the five tour targets
    .venv\Scripts\python scripts\download_photos.py 269.4464 4.7686   # one position, 3.6' field

Photos already on this computer are skipped, so it is safe to run again.
"""
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
from spx import analysis, flipbook  # noqa: E402

positions = []
if len(sys.argv) >= 3:
    positions.append((float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]) if len(sys.argv) > 3 else 0.06))
else:
    tour = json.loads((ROOT / "data" / "tour.json").read_text())
    positions = [(t["ra"], t["dec"], 0.06) for t in tour.values()]

for ra, dec, field in positions:
    print(f"\nRA {ra}  Dec {dec}:")
    if not flipbook.is_current(round(ra, 4), round(dec, 4), field):
        # a brand-new position: find, download and stack everything
        flipbook.build(ra, dec, field, progress=lambda s, f: print("  " + s, end="\r"))
    pos = analysis.load_position(ra, dec, field)  # downloads any missing photos
    print(f"  {len(pos['cuts'])} photos ready.")
print("\nAll done. You can close this window.")
