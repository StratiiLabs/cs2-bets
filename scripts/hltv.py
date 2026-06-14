#!/usr/bin/env python3
"""HLTV scraper via curl_cffi TLS-impersonation (no browser needed).

Works (passes Cloudflare's passive check): the main HLTV site — match pages
(MAP VETO, lineups, world ranks), /team pages (recent form, stand-ins),
/news. Does NOT work: /stats/* (active JS challenge -> needs a real browser;
see scripts/hltv_browser.py).

REQUIRES the curl_cffi venv (see requirements.txt):
    python3 -m venv ~/cfvenv --without-pip
    curl -sS https://bootstrap.pypa.io/get-pip.py | ~/cfvenv/bin/python
    ~/cfvenv/bin/pip install curl_cffi
Run with:  ~/cfvenv/bin/python scripts/hltv.py ...

Usage:
    ~/cfvenv/bin/python scripts/hltv.py match --find "MOUZ vs FUT"
    ~/cfvenv/bin/python scripts/hltv.py form  --team 4494/mouz
    ~/cfvenv/bin/python scripts/hltv.py news  --keywords "stand-in,bench,visa"
"""
import argparse
import html
import re

from curl_cffi import requests

BASE = "https://www.hltv.org"
_session = None


def session():
    global _session
    if _session is None:
        _session = requests.Session(impersonate="chrome")
        _session.get(BASE + "/", timeout=20)
    return _session


def text(s, n=20):
    return re.sub(r"\s+", " ", s).strip()[:n] if s else ""


def list_match_links(s):
    body = s.get(BASE + "/matches", timeout=20).text
    links = re.findall(r'href="(/matches/\d+/[a-z0-9\-]+)"', body)
    return list(dict.fromkeys(links))


def find_match_url(s, query):
    words = [w.lower() for w in re.split(r"\s+vs\.?\s+|\s+", query) if w]
    best, best_score = None, 0
    for link in list_match_links(s):
        slug = link.lower()
        score = sum(1 for w in words if w in slug)
        if score > best_score:
            best, best_score = link, score
    if best and best_score >= max(2, len(words) - 1):
        return BASE + best
    return None


# ---------- match report ----------
def parse_veto(body):
    block = re.search(r'preformatted-text">((?:[^<]*?(?:removed|picked|'
                      r'left over)[^<]*?\n?)+)', body)
    actions, leftover = [], None
    src = block.group(1) if block else body
    for line in re.findall(r'\d+\.\s*([^\n<]+)', src):
        m = re.match(r'(.+?)\s+(removed|picked)\s+([A-Z][a-z0-9]+)',
                     line.strip())
        if m:
            actions.append((m.group(1).strip(), m.group(2), m.group(3)))
            continue
        lo = re.match(r'([A-Z][a-z0-9]+)\s+was left over', line.strip())
        if lo:
            leftover = lo.group(1)
    return actions, leftover


def cmd_match(args):
    s = session()
    url = args.url or find_match_url(s, args.find)
    if not url:
        print("Match not found in /matches list.")
        return
    body = s.get(url, timeout=20).text
    title = re.findall(r"<title>([^<]+)", body)
    print(html.unescape(title[0]) if title else url)
    print(url)

    fmt = re.search(r'preformatted-text">(Best of[^<]+)', body)
    if fmt:
        print("  Format:", html.unescape(fmt.group(1).strip()))

    teams = re.findall(r'/team/\d+/[a-z0-9\-]+"><img alt="([^"]+)"', body)
    ranks = re.findall(r'World rank:\s*</span>#(\d+)', body)
    for i, t in enumerate(dict.fromkeys(teams)[:2] if False else teams[:2]):
        r = ranks[i] if i < len(ranks) else "?"
        print(f"  Team {i + 1}: {html.unescape(t):20s} HLTV rank #{r}")

    actions, leftover = parse_veto(body)
    played = [m for who, act, m in actions if act == "picked"]
    if leftover:
        played.append(leftover)
    if actions:
        print("  Veto:")
        for who, act, mp in actions:
            print(f"    {who:18s} {act} {mp}")
        if leftover:
            print(f"    (decider) {leftover}")
        print(f"  MAPS PLAYED -> {', '.join(played)}")
    else:
        print("  Veto: not published yet (set ~just before start).")

    # stand-in detection in lineup area
    lu = re.search(r'id="lineups".*?(?:id="|<footer)', body, re.S)
    area = lu.group(0) if lu else body
    standins = len(re.findall(r'stand-?in', area, re.I))
    if standins:
        print(f"  ⚠ STAND-IN flagged in lineups ({standins} mentions) "
              f"— verify roster, line may move!")
    else:
        print("  Lineups: no stand-in flag detected.")


# ---------- form ----------
def cmd_form(args):
    s = session()
    url = f"{BASE}/team/{args.team}"
    body = s.get(url, timeout=25).text
    if "Just a moment" in body:
        print("blocked")
        return
    name = re.findall(r"<title>([^<]+)", body)
    print(html.unescape(name[0]) if name else url)
    streak = re.search(r'<div class="stat">([^<]+)</div>\s*'
                       r'<div class="description">Current win streak', body)
    if streak:
        print("  Current win streak:", streak.group(1).strip())
    # recent results: rows in the 'Recent results' match-table
    seg = re.search(r'Recent results for.*?</table>', body, re.S)
    own = re.findall(r'/team/(\d+)/', args.team + "/x")
    own_id = own[0] if own else args.team.split("/")[0]
    if seg:
        rows = re.findall(r'<tr class="team-row">(.*?)</tr>',
                          seg.group(0), re.S)
        print("  Recent results (newest first):")
        wins = 0
        shown = []
        for row in rows[:12]:
            scores = re.findall(r'class="score[^"]*">(\d+)<', row)
            titles = re.findall(r'team-logo[^"]*"[^>]*title="([^"]+)"', row)
            titles = list(dict.fromkeys(titles))
            opp = titles[1] if len(titles) > 1 else (
                titles[0] if titles else "?")
            if len(scores) < 2:
                continue
            # team-1 (page team) is listed first -> first score is ours
            res = "W" if int(scores[0]) > int(scores[1]) else "L"
            sc = f"{scores[0]}:{scores[1]}"
            if res == "W":
                wins += 1
            shown.append((res, sc, opp))
        for res, sc, opp in shown[:10]:
            print(f"    {res}  {sc:>4s}  vs {html.unescape(opp)}")
        if shown:
            print(f"  Form: {wins}-{len(shown) - wins} "
                  f"({wins / len(shown):.0%}) last {len(shown)}")
    else:
        print("  (recent results table not found)")


# ---------- news ----------
def cmd_news(args):
    s = session()
    body = s.get(BASE + "/news", timeout=20).text
    items = re.findall(r'/news/\d+/[a-z0-9\-]+"[^>]*>\s*'
                       r'(?:<[^>]+>)*([^<]{8,120})', body)
    kws = [k.strip().lower() for k in (args.keywords or "").split(",")
           if k.strip()]
    print("Latest HLTV news:")
    shown = 0
    for headline in dict.fromkeys(items):
        h = html.unescape(headline.strip())
        if kws and not any(k in h.lower() for k in kws):
            continue
        print("  -", h)
        shown += 1
        if shown >= 25:
            break
    if kws and shown == 0:
        print("  (no headlines matching:", ", ".join(kws), ")")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("match")
    m.add_argument("--url")
    m.add_argument("--find", help='e.g. "MOUZ vs FUT"')
    m.set_defaults(func=cmd_match)
    f = sub.add_parser("form")
    f.add_argument("--team", required=True, help="id/slug e.g. 4494/mouz")
    f.set_defaults(func=cmd_form)
    n = sub.add_parser("news")
    n.add_argument("--keywords", help="comma filter, e.g. stand-in,bench,visa")
    n.set_defaults(func=cmd_news)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
