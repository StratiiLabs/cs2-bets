#!/usr/bin/env python3
"""HLTV scraper via curl_cffi TLS-impersonation (no browser needed).

What works through curl_cffi: the main HLTV site — match pages (with the MAP
VETO, lineups, head-to-head), /results, /team pages. These pass Cloudflare's
passive check with browser TLS impersonation.

What does NOT work: the /stats/* section (Dust2 win-rate tables etc.) — HLTV
guards it with an ACTIVE JavaScript challenge that needs a real browser
(Playwright / FlareSolverr). For map strength we instead use the veto (actual
maps played) plus our bo3.gg Elo.

REQUIRES the curl_cffi venv:
    python3 -m venv ~/cfvenv --without-pip
    curl -sS https://bootstrap.pypa.io/get-pip.py | ~/cfvenv/bin/python
    ~/cfvenv/bin/pip install curl_cffi
Run with:  ~/cfvenv/bin/python scripts/hltv.py ...

Usage:
    ~/cfvenv/bin/python scripts/hltv.py matches
    ~/cfvenv/bin/python scripts/hltv.py veto --find "MOUZ vs FUT"
    ~/cfvenv/bin/python scripts/hltv.py veto --url https://www.hltv.org/matches/123/x
"""
import argparse
import html
import re

from curl_cffi import requests

BASE = "https://www.hltv.org"


def session():
    s = requests.Session(impersonate="chrome")
    s.get(BASE + "/", timeout=20)
    return s


def list_matches(s):
    body = s.get(BASE + "/matches", timeout=20).text
    links = re.findall(r'href="(/matches/\d+/[a-z0-9\-]+)"', body)
    return list(dict.fromkeys(links))


def find_match(s, query):
    """Match a 'TeamA vs TeamB' query against listed match slugs."""
    words = [w.lower() for w in re.split(r"\s+vs\.?\s+|\s+", query) if w]
    for link in list_matches(s):
        slug = link.lower()
        if sum(1 for w in words if w in slug) >= max(2, len(words) - 1):
            return BASE + link
    return None


def parse_veto(body):
    # the veto block: lines like "1. MOUZ removed Inferno"
    actions = re.findall(
        r'\d+\.\s*([A-Za-z0-9\.\-\' ]+?)\s+(removed|picked)\s+([A-Z][a-z0-9]+)',
        body)
    leftover = re.search(
        r'\d+\.\s*([A-Z][a-z0-9]+)\s+was left over', body)
    return actions, (leftover.group(1) if leftover else None)


def cmd_matches(args):
    s = session()
    for link in list_matches(s)[:30]:
        print(BASE + link)


def cmd_veto(args):
    s = session()
    url = args.url or find_match(s, args.find)
    if not url:
        print("Match not found in /matches list.")
        return
    body = s.get(url, timeout=20).text
    title = re.findall(r"<title>([^<]+)", body)
    print(html.unescape(title[0]) if title else url)
    actions, leftover = parse_veto(body)
    if not actions:
        print("  No veto published yet (set shortly before match start).")
        return
    picked = []
    print("  Veto:")
    for team, act, mp in actions:
        print(f"    {team.strip():18s} {act} {mp}")
        if act == "picked":
            picked.append(mp)
    if leftover:
        picked.append(leftover)
        print(f"    (decider) {leftover}")
    print(f"  MAPS PLAYED -> {', '.join(picked) if picked else '?'}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("matches").set_defaults(func=cmd_matches)
    v = sub.add_parser("veto")
    v.add_argument("--url")
    v.add_argument("--find", help='e.g. "MOUZ vs FUT"')
    v.set_defaults(func=cmd_veto)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
