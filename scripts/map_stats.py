#!/usr/bin/env python3
"""Per-map win rates for both teams in a match, from bo3.gg game data.

bo3.gg exposes /games per match with map_name + winner_clan_name, so we can
reconstruct each team's recent map record (which maps they play and win).
This approximates the veto picture: maps a team rarely plays are likely
permabans; maps both teams play often are the likely battleground.

Usage:
    python3 scripts/map_stats.py --slug the-mongolz-vs-monte-14-06-2026
    python3 scripts/map_stats.py --slug <slug> --n 15
"""
import argparse
import json
import urllib.parse
import urllib.request
from collections import defaultdict

API = "https://api.bo3.gg/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125"}
_games_cache = {}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))


def team_info(slug):
    return get(f"{API}/teams/{slug}")


def recent_match_ids(team_id, n=15):
    out = []
    for side in ("team1_id", "team2_id"):
        params = urllib.parse.urlencode({
            "filter[matches.status][eq]": "finished",
            f"filter[matches.{side}][eq]": str(team_id),
            "page[size]": str(n),
            "sort": "-start_date",
        })
        out += get(f"{API}/matches?{params}").get("results", [])
    out.sort(key=lambda m: m.get("start_date", ""), reverse=True)
    return out[:n]


def games_for(match_id):
    if match_id in _games_cache:
        return _games_cache[match_id]
    params = urllib.parse.urlencode({"filter[games.match_id][eq]": str(match_id)})
    try:
        g = get(f"{API}/games?{params}")
        g = g if isinstance(g, list) else g.get("results", [])
    except Exception:
        g = []
    _games_cache[match_id] = g
    return g


def _norm(s):
    s = (s or "").lower()
    for junk in ("the ", " team", "team ", " esports", " gaming", " cs2",
                 " cs", " "):
        s = s.replace(junk, "")
    return s.strip()


def _sim(a, b):
    return bool(a) and bool(b) and (a in b or b in a)


def _our_result(team_name, g):
    """True=win, False=loss, None=cannot attribute (skip)."""
    t = _norm(team_name)
    w, lo = _norm(g.get("winner_clan_name")), _norm(g.get("loser_clan_name"))
    win, loss = _sim(t, w), _sim(t, lo)
    if win and not loss:
        return True
    if loss and not win:
        return False
    return None


def map_record(team_id, team_name, n=15):
    rec = defaultdict(lambda: [0, 0])  # map -> [wins, played]
    for m in recent_match_ids(team_id, n):
        for g in games_for(m["id"]):
            if g.get("state") != "done":
                continue
            mp = (g.get("map_name") or "").replace("de_", "")
            if not mp:
                continue
            res = _our_result(team_name, g)
            if res is None:
                continue
            rec[mp][1] += 1
            if res:
                rec[mp][0] += 1
    return rec


def teams_from_slug(slug):
    left, _, right = slug.partition("-vs-")
    right = "-".join(right.split("-")[:-3])
    return left, right


def fmt(rec):
    rows = sorted(rec.items(), key=lambda kv: (-kv[1][1], -kv[1][0]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--n", type=int, default=15)
    args = ap.parse_args()

    a, b = teams_from_slug(args.slug)
    ia, ib = team_info(a), team_info(b)
    na, nb = ia["name"], ib["name"]
    ra = map_record(ia["id"], na, args.n)
    rb = map_record(ib["id"], nb, args.n)

    print(f"\n=== {na} (rank {ia.get('rank')}) vs "
          f"{nb} (rank {ib.get('rank')}) ===")
    print(f"\n{na} map record (last {args.n} matches):")
    for mp, (w, p) in fmt(ra):
        print(f"  {mp:12s} {w}-{p - w}  ({w / p:.0%})  n={p}")
    print(f"\n{nb} map record (last {args.n} matches):")
    for mp, (w, p) in fmt(rb):
        print(f"  {mp:12s} {w}-{p - w}  ({w / p:.0%})  n={p}")

    # likely battleground: maps both teams have played (>=2 each)
    common = sorted(
        set(m for m, v in ra.items() if v[1] >= 2)
        & set(m for m, v in rb.items() if v[1] >= 2))
    print("\nLikely-played maps (both play >=2) with edge:")
    for mp in common:
        wa, pa = ra[mp]
        wb, pb = rb[mp]
        wra, wrb = wa / pa, wb / pb
        edge = na if wra > wrb else nb
        print(f"  {mp:12s} {na} {wra:.0%} (n{pa})  vs  {nb} {wrb:.0%} "
              f"(n{pb})  -> {edge}")


if __name__ == "__main__":
    main()
