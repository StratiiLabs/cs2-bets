#!/usr/bin/env python3
"""Opponent-adjusted strength via Elo ratings — overall and per-map.

Raw win rate is misleading: 70% vs weak teams < 50% vs top teams. Elo fixes
this because beating a strong opponent adds more rating than beating a weak
one. We build:
  - overall Elo per team (from match winners)
  - per-map Elo per team (from individual game winners)
and convert a rating gap into a win probability:
    P(A) = 1 / (1 + 10**((Rb - Ra) / 400))

Usage:
    python3 scripts/elo.py build --days 180 --map-days 90
    python3 scripts/elo.py predict --slug mousesports-vs-fut-cs2-14-06-2026
"""
import argparse
import datetime as dt
import json
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

API = "https://api.bo3.gg/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64) Chrome/125"}
STORE = Path(__file__).resolve().parent.parent / "data" / "elo.json"
BASE = 1500.0
K_MATCH = 32.0
K_MAP = 24.0
_name_cache = {}
_games_cache = {}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))


def team_name(team_id):
    if team_id in _name_cache:
        return _name_cache[team_id]
    try:
        n = get(f"{API}/teams/{team_id}").get("name", str(team_id))
    except Exception:
        n = str(team_id)
    _name_cache[team_id] = n
    return n


def finished_matches(days):
    """Recent finished tier s/a matches within `days`, returned oldest first.

    The API's start_date range filter is unreliable, so we page newest-first
    and stop once we pass the cutoff date, then reverse for chronological Elo.
    """
    cutoff = (dt.datetime.now(dt.timezone.utc)
              - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    out, offset, size = [], 0, 50
    while True:
        params = urllib.parse.urlencode({
            "filter[matches.status][eq]": "finished",
            "filter[matches.tier][in]": "s,a",
            "page[size]": str(size),
            "page[offset]": str(offset),
            "sort": "-start_date",
        })
        res = get(f"{API}/matches?{params}").get("results", [])
        if not res:
            break
        out += res
        if res[-1].get("start_date", "")[:10] < cutoff:
            break
        offset += size
        if offset > 6000:
            break
    out = [m for m in out if m.get("start_date", "")[:10] >= cutoff]
    out.sort(key=lambda m: m.get("start_date", ""))  # oldest first
    return out


def games_for(match_id):
    if match_id in _games_cache:
        return _games_cache[match_id]
    p = urllib.parse.urlencode({"filter[games.match_id][eq]": str(match_id)})
    try:
        g = get(f"{API}/games?{p}")
        g = g if isinstance(g, list) else g.get("results", [])
    except Exception:
        g = []
    _games_cache[match_id] = g
    return g


def expected(ra, rb):
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def _norm(s):
    s = (s or "").lower()
    for j in ("the ", " team", "team ", " esports", " gaming", " cs2",
              " cs", " "):
        s = s.replace(j, "")
    return s.strip()


def _sim(a, b):
    return bool(a) and bool(b) and (a in b or b in a)


def build(days, map_days):
    matches = finished_matches(days)
    print(f"Fetched {len(matches)} finished matches over {days}d")

    overall = defaultdict(lambda: BASE)
    games_played = defaultdict(int)
    for m in matches:
        a, b, w = m.get("team1_id"), m.get("team2_id"), m.get("winner_team_id")
        if not a or not b or not w:
            continue
        ra, rb = overall[a], overall[b]
        ea = expected(ra, rb)
        sa = 1.0 if w == a else 0.0
        overall[a] = ra + K_MATCH * (sa - ea)
        overall[b] = rb + K_MATCH * ((1 - sa) - (1 - ea))
        games_played[a] += 1
        games_played[b] += 1

    # per-map Elo over a (shorter) recent window
    cutoff = (dt.datetime.now(dt.timezone.utc)
              - dt.timedelta(days=map_days)).strftime("%Y-%m-%d")
    recent = [m for m in matches if m.get("start_date", "") >= cutoff]
    maps = defaultdict(lambda: defaultdict(lambda: BASE))
    print(f"Building per-map Elo from {len(recent)} recent matches "
          f"(this fetches games, be patient)...")
    for i, m in enumerate(recent):
        a, b = m.get("team1_id"), m.get("team2_id")
        if not a or not b:
            continue
        na, nb = team_name(a), team_name(b)
        for g in games_for(m["id"]):
            if g.get("state") != "done":
                continue
            mp = (g.get("map_name") or "").replace("de_", "")
            if not mp:
                continue
            wn = _norm(g.get("winner_clan_name"))
            ta, tb = _norm(na), _norm(nb)
            if _sim(ta, wn) and not _sim(tb, wn):
                win = a
            elif _sim(tb, wn) and not _sim(ta, wn):
                win = b
            else:
                continue
            ra, rb = maps[mp][a], maps[mp][b]
            ea = expected(ra, rb)
            sa = 1.0 if win == a else 0.0
            maps[mp][a] = ra + K_MAP * (sa - ea)
            maps[mp][b] = rb + K_MAP * ((1 - sa) - (1 - ea))

    data = {
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "days": days, "map_days": map_days,
        "overall": {str(k): round(v, 1) for k, v in overall.items()},
        "games_played": {str(k): v for k, v in games_played.items()},
        "maps": {mp: {str(k): round(v, 1) for k, v in d.items()}
                 for mp, d in maps.items()},
        "names": {str(k): v for k, v in _name_cache.items()},
    }
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2))
    print(f"Saved Elo to {STORE}")
    top = sorted(overall.items(), key=lambda kv: -kv[1])[:15]
    print("\nTop 15 by overall Elo:")
    for tid, r in top:
        print(f"  {team_name(tid):20s} {r:6.0f}  (n={games_played[tid]})")


def predict(slug):
    data = json.loads(STORE.read_text())
    overall = data["overall"]
    maps = data["maps"]
    names = data["names"]
    m = get(f"{API}/matches/{slug}")
    a, b = str(m.get("team1_id")), str(m.get("team2_id"))
    na = names.get(a) or team_name(int(a))
    nb = names.get(b) or team_name(int(b))
    ra, rb = overall.get(a, BASE), overall.get(b, BASE)
    pa = expected(ra, rb)
    print(f"\n=== {na} (Elo {ra:.0f}) vs {nb} (Elo {rb:.0f}) ===")
    print(f"Overall: {na} {pa:.0%}  /  {nb} {1 - pa:.0%}")
    print("\nPer-map (only maps both have data):")
    rows = []
    for mp, d in sorted(maps.items()):
        if a in d and b in d:
            pma = expected(d[a], d[b])
            rows.append((mp, d[a], d[b], pma))
    for mp, da, db, pma in sorted(rows, key=lambda r: -abs(r[3] - 0.5)):
        edge = na if pma >= 0.5 else nb
        print(f"  {mp:10s} {na} {pma:4.0%} / {nb} {1 - pma:4.0%}  "
              f"(Elo {da:.0f} vs {db:.0f})  -> {edge}")
    if not rows:
        print("  (no shared map history)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    bp = sub.add_parser("build")
    bp.add_argument("--days", type=int, default=180)
    bp.add_argument("--map-days", type=int, default=90, dest="map_days")
    pp = sub.add_parser("predict")
    pp.add_argument("--slug", required=True)
    args = ap.parse_args()
    if args.cmd == "build":
        build(args.days, args.map_days)
    else:
        predict(args.slug)


if __name__ == "__main__":
    main()
