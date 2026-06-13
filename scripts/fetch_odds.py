#!/usr/bin/env python3
"""Fetch upcoming CS2 matches and bookmaker odds from the bo3.gg API.

Usage (from WSL, workdir /mnt/c/Users/stratiiv/projects/cs2-bets):
    python3 scripts/fetch_odds.py               # upcoming tier-S/A matches
    python3 scripts/fetch_odds.py --slug a,b    # specific match slugs
Saves raw JSON snapshots into data/ with a timestamp.
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.bo3.gg/api/v1/matches"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0",
}
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))


def fetch_upcoming(size=30):
    params = urllib.parse.urlencode({
        "filter[matches.status][in]": "current,upcoming",
        "page[size]": str(size),
        "sort": "start_date",
    })
    return get(f"{API}?{params}").get("results", [])


def fetch_match(slug):
    return get(f"{API}/{slug}")


def extract_odds(match):
    bu = match.get("bet_updates") or {}
    out = {
        "slug": match.get("slug"),
        "start_date": match.get("start_date"),
        "status": match.get("status"),
        "tier": match.get("tier"),
        "team1_coeff": (bu.get("team_1") or {}).get("coeff"),
        "team2_coeff": (bu.get("team_2") or {}).get("coeff"),
        "markets": {},
    }
    for m in bu.get("additional_markets", []):
        out["markets"][m.get("bet_type")] = {
            "coeff": m.get("coeff"),
            "max_coeff": m.get("max_coeff"),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug",
                    help="fetch specific match(es), comma-separated slugs")
    ap.add_argument("--tier", default="s,a", help="comma list of tiers to keep (default s,a)")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

    if args.slug:
        slugs = [s.strip() for s in args.slug.split(",") if s.strip()]
    else:
        tiers = set(args.tier.split(","))
        matches = fetch_upcoming()
        slugs = [m["slug"] for m in matches if m.get("tier") in tiers]
        if not slugs:
            print("No upcoming matches in tiers:", tiers, file=sys.stderr)
            slugs = [m["slug"] for m in matches]

    snapshot = []
    for slug in slugs:
        try:
            match = fetch_match(slug)
        except Exception as e:
            print(f"FAIL {slug}: {e}", file=sys.stderr)
            continue
        odds = extract_odds(match)
        snapshot.append(odds)
        ml1, ml2 = odds["team1_coeff"], odds["team2_coeff"]
        print(f"{slug}  ML {ml1} / {ml2}  ({len(odds['markets'])} markets)")

    out_file = DATA_DIR / f"odds_{stamp}.json"
    out_file.write_text(json.dumps(snapshot, indent=2))
    print(f"\nSaved {len(snapshot)} matches -> {out_file}")


if __name__ == "__main__":
    main()
