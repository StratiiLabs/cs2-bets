#!/usr/bin/env python3
"""Pull rank + recent form for every team in today's saved odds snapshot.

Reads the most recent data/odds_*.json, derives team slugs from match slugs,
and prints a compact table via fetch_stats helpers.
"""
import glob
import json
import os
from pathlib import Path

import fetch_stats as fs

DATA = Path(__file__).resolve().parent.parent / "data"


def latest_odds():
    files = sorted(glob.glob(str(DATA / "odds_*.json")), key=os.path.getmtime)
    return files[-1] if files else None


def teams_from_slug(slug):
    left, _, right = slug.partition("-vs-")
    right = "-".join(right.split("-")[:-3])
    return left, right


def main():
    f = latest_odds()
    snapshot = json.loads(Path(f).read_text())
    print(f"Snapshot: {f}\n")
    for match in snapshot:
        slug = match["slug"]
        a, b = teams_from_slug(slug)
        print(f"==== {slug}  (ML {match.get('team1_coeff')} / "
              f"{match.get('team2_coeff')}) ====")
        for t in (a, b):
            try:
                info = fs.team_info(t)
                tid = info.get("id")
                w, n, _ = fs.recent_form(tid)
                form = f"{w}-{n - w} ({w / n:.0%})" if n else "n/a"
                print(f"  {info.get('name'):20s} rank {str(info.get('rank')):>4s}"
                      f"  form {form}")
            except Exception as e:
                print(f"  {t}: FAIL {e}")
        print()


if __name__ == "__main__":
    main()
