#!/usr/bin/env python3
"""Enrich a match with team stats from bo3.gg: world rank + recent form.

bo3.gg is NOT behind Cloudflare (unlike HLTV/Liquipedia HTML), so its public
JSON API is our reliable source for ranks, recent results and head-to-head.

Usage:
    python3 scripts/fetch_stats.py --teams the-mongolz,natus-vincere
    python3 scripts/fetch_stats.py --slug natus-vincere-vs-the-mongolz-13-06-2026
"""
import argparse
import json
import urllib.parse
import urllib.request

API = "https://api.bo3.gg/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125"}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))


def team_info(slug):
    return get(f"{API}/teams/{slug}")


def recent_form(team_id, n=10):
    """Last n finished matches for a team id."""
    params = urllib.parse.urlencode({
        "filter[matches.status][eq]": "finished",
        "filter[matches.team1_id][eq]": str(team_id),
        "page[size]": str(n),
        "sort": "-start_date",
    })
    a = get(f"{API}/matches?{params}").get("results", [])
    params2 = urllib.parse.urlencode({
        "filter[matches.status][eq]": "finished",
        "filter[matches.team2_id][eq]": str(team_id),
        "page[size]": str(n),
        "sort": "-start_date",
    })
    b = get(f"{API}/matches?{params2}").get("results", [])
    games = sorted(a + b, key=lambda m: m.get("start_date", ""), reverse=True)[:n]
    wins = sum(1 for m in games if m.get("winner_team_id") == team_id)
    return wins, len(games), games


def describe(slug):
    info = team_info(slug)
    tid = info.get("id")
    name = info.get("name")
    rank = info.get("rank")
    wins, total, games = recent_form(tid)
    print(f"\n{name}  (bo3 world rank {rank}, id {tid})")
    if total:
        print(f"  Recent form: {wins}-{total - wins} in last {total} "
              f"({wins / total:.0%} win rate)")
    for m in games[:8]:
        opp_id = m["team2_id"] if m["team1_id"] == tid else m["team1_id"]
        res = "W" if m.get("winner_team_id") == tid else "L"
        sc = f"{m.get('team1_score')}-{m.get('team2_score')}"
        print(f"    {res}  {sc}  tier={m.get('tier')}  {m.get('slug','')[:50]}")
    return {"name": name, "rank": rank, "form_wins": wins, "form_total": total}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", help="comma-separated team slugs")
    ap.add_argument("--slug", help="match slug team-a-vs-team-b-date")
    args = ap.parse_args()

    teams = []
    if args.teams:
        teams = [t.strip() for t in args.teams.split(",")]
    elif args.slug:
        # crude split on -vs- then strip trailing date
        left, _, right = args.slug.partition("-vs-")
        right = "-".join(right.split("-")[:-3])  # drop dd-mm-yyyy
        teams = [left, right]
    else:
        ap.error("provide --teams or --slug")

    for t in teams:
        try:
            describe(t)
        except Exception as e:
            print(f"\n{t}: FAIL {e}")


if __name__ == "__main__":
    main()
