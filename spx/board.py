"""Scores, explorers and the confirmed-discoveries board.

Everything is kept in small files on this computer (folder `profile/` and `reports/`).
There is no shared server yet; the data layout is simple on purpose so that the same
calls can later be answered by a shared server when the site goes online.

Rules that keep it honest:
- game points only come from rounds with a known answer;
- real exploring is counted (patches explored), never scored for being "right";
- discovery points are given only for reports whose status is "confirmed" (by astronomers).
  Nothing can be confirmed automatically, so until someone changes a report's status the
  discoveries board stays empty. It never shows made-up entries.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profile"
REPORTS = ROOT / "reports"

# points for a confirmed discovery, by how rare that kind of find is
DISCOVERY_POINTS = [
    ("variable", "New variable star", 40),
    ("asteroid", "New asteroid (main belt)", 50),
    ("red_dwarf", "New nearby red dwarf", 60),
    ("wide_pair", "New wide pair travelling together", 80),
    ("near_earth", "New near-Earth asteroid", 150),
    ("comet", "New comet", 200),
    ("brown_dwarf_L", "New warm brown dwarf (L type)", 250),
    ("brown_dwarf_T", "New cold brown dwarf (T type)", 400),
    ("brown_dwarf_Y", "New very cold brown dwarf (Y type)", 1000),
    ("interstellar", "New interstellar visitor", 5000),
]
RANKS = [(0, "Stargazer"), (5000, "Sky Scout"), (20000, "Mover Hunter"), (50000, "Night Watch"), (100000, "Discoverer")]


def _load(name, default):
    p = PROFILE / name
    try:
        return json.loads(p.read_text()) if p.exists() else default
    except Exception:
        return default


def _save(name, data):
    PROFILE.mkdir(exist_ok=True)
    (PROFILE / name).write_text(json.dumps(data, indent=1))


def add_score(name: str, score: int, mode: str, day: str, rounds: list) -> dict:
    name = (name or "Anonymous").strip()[:40]
    scores = _load("scores.json", [])
    if mode == "daily" and any(s["name"] == name and s["mode"] == "daily" and s["day"] == day for s in scores):
        return dict(saved=False, why="Today's challenge was already played under this name; only the first try counts.")
    scores.append(dict(name=name, score=int(max(0, min(5000, score))), mode=mode, day=day, rounds=rounds,
                       when=time.strftime("%Y-%m-%d %H:%M")))
    _save("scores.json", scores)
    return dict(saved=True)


def add_explored(name: str, ra: float, dec: float) -> dict:
    name = (name or "Anonymous").strip()[:40]
    ex = _load("explored.json", {})
    key = f"{ra:.3f},{dec:.3f}"
    lst = ex.setdefault(name, [])
    if key not in lst:
        lst.append(key)
        _save("explored.json", ex)
    return dict(count=len(lst))


def rank(total: int) -> str:
    r = RANKS[0][1]
    for pts, nm in RANKS:
        if total >= pts:
            r = nm
    return r


def board(day: str) -> dict:
    scores = _load("scores.json", [])
    totals: dict = {}
    for s in scores:
        t = totals.setdefault(s["name"], dict(name=s["name"], total=0, games=0, best=0))
        t["total"] += s["score"]; t["games"] += 1; t["best"] = max(t["best"], s["score"])
    players = sorted(totals.values(), key=lambda t: -t["total"])
    for t in players:
        t["rank"] = rank(t["total"])
    daily = sorted([s for s in scores if s["mode"] == "daily" and s["day"] == day], key=lambda s: -s["score"])
    ex = _load("explored.json", {})
    explorers = sorted(({"name": k, "patches": len(v)} for k, v in ex.items()), key=lambda e: -e["patches"])
    # discoveries: one line per saved report, with its real status
    pts = {k: p for k, _, p in DISCOVERY_POINTS}
    reports, conf = [], {}
    if REPORTS.exists():
        for p in sorted(REPORTS.glob("*.json")):
            try:
                r = json.loads(p.read_text())
            except Exception:
                continue
            status = r.get("status", "reported")
            kind = r.get("confirmed_as")
            score = pts.get(kind, 0) if status == "confirmed" else 0
            reports.append(dict(name=r.get("name") or "Anonymous", when=(r.get("saved") or "")[:10], status=status,
                                ra=r.get("ra"), dec=r.get("dec"), confirmed_as=kind, points=score, file=p.name))
            if score:
                c = conf.setdefault(r.get("name") or "Anonymous", dict(name=r.get("name") or "Anonymous", points=0, finds=0))
                c["points"] += score; c["finds"] += 1
    return dict(players=players[:20], daily=daily[:20], explorers=explorers[:20], reports=reports[-50:][::-1],
                discoverers=sorted(conf.values(), key=lambda c: -c["points"]),
                points_table=[dict(key=k, label=l, points=p) for k, l, p in DISCOVERY_POINTS],
                ranks=[dict(points=p, name=n) for p, n in RANKS], shared=False)
