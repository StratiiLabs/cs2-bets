#!/usr/bin/env python3
"""EV calculator for CS2 Bo3 markets: moneyline, correct score, totals, handicaps, expresses.

Takes your model's SERIES win probability per match and derives consistent
score/total/handicap probabilities, then compares against an odds snapshot
produced by fetch_odds.py.

Usage:
    python3 scripts/ev_calc.py data/odds_<stamp>.json --probs predictions.json
    python3 scripts/ev_calc.py data/odds_<stamp>.json --prob vitality-vs-9z-12-06-2026=0.80

predictions.json format: {"<slug>": 0.80, ...}  (probability TEAM 1 wins the series)
"""
import argparse
import itertools
import json
from pathlib import Path

KELLY_FRACTION = 0.25
MIN_EDGE = 0.03  # ignore edges below 3%


def map_p_from_series(p_series):
    """Invert P(win Bo3) = p^2 * (3 - 2p) by bisection -> per-map win prob."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if mid * mid * (3 - 2 * mid) < p_series:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def score_probs(p_series):
    """Return dict of score probabilities for team1 given series win prob."""
    p = map_p_from_series(p_series)
    q = 1 - p
    return {
        "2_0": p * p,
        "2_1": 2 * p * p * q,
        "1_2": 2 * p * q * q,
        "0_2": q * q,
    }


def market_probs(p_series):
    """Model probability for every bet_type bo3.gg exposes."""
    s = score_probs(p_series)
    return {
        "score_2_0": s["2_0"],
        "score_2_1": s["2_1"],
        "score_1_2": s["1_2"],
        "score_0_2": s["0_2"],
        "total_maps_over_2_5": s["2_1"] + s["1_2"],
        "total_maps_under_2_5": s["2_0"] + s["0_2"],
        "total_maps_even": s["2_0"] + s["0_2"],
        "total_maps_odd": s["2_1"] + s["1_2"],
        # bo3.gg naming verified against live board: over_1_5 = +1.5 line
        # (covers by winning >= 1 map), under_1_5 = -1.5 line (wins 2-0).
        "team_1_handicap_over_1_5": 1 - s["0_2"],
        "team_1_handicap_under_1_5": s["2_0"],
        "team_2_handicap_over_1_5": 1 - s["2_0"],
        "team_2_handicap_under_1_5": s["0_2"],
        "team_1_to_win_at_least_one_map": 1 - s["0_2"],
        "team_1_to_not_win_at_least_one_map": s["0_2"],
    }


def kelly(prob, coeff):
    edge = prob * coeff - 1
    if edge <= 0 or coeff <= 1:
        return 0.0
    return KELLY_FRACTION * edge / (coeff - 1)


def analyze(odds_file, probs):
    snapshot = json.loads(Path(odds_file).read_text())
    value_bets = []

    for match in snapshot:
        slug = match["slug"]
        if slug not in probs:
            continue
        if match.get("status") == "current":
            print(f"\n=== {slug} === SKIPPED: match is LIVE, in-play odds "
                  "cannot be compared against pre-match model probabilities")
            continue
        p1 = probs[slug]
        rows = []

        ml1, ml2 = match.get("team1_coeff"), match.get("team2_coeff")
        if ml1:
            rows.append(("team_1_ml", ml1, p1))
        if ml2:
            rows.append(("team_2_ml", ml2, 1 - p1))

        mp = market_probs(p1)
        for bet_type, m in match.get("markets", {}).items():
            if bet_type in mp and m.get("coeff"):
                rows.append((bet_type, m["coeff"], mp[bet_type]))

        print(f"\n=== {slug}  (model: team1 {p1:.0%}) ===")
        for bet_type, coeff, prob in rows:
            ev = prob * coeff - 1
            flag = ""
            if ev >= MIN_EDGE:
                flag = "  <-- VALUE"
                value_bets.append({"slug": slug, "bet": bet_type, "coeff": coeff,
                                   "prob": prob, "ev": ev, "kelly": kelly(prob, coeff)})
            print(f"  {bet_type:38s} coef {coeff:7.3f}  model {prob:5.1%}  EV {ev:+7.1%}{flag}")

    if not value_bets:
        print("\nNo value bets found. Correct action: no bet today.")
        return

    print("\n" + "=" * 70)
    print("VALUE BETS (singles), stake = quarter-Kelly % of bankroll:")
    for v in sorted(value_bets, key=lambda x: -x["ev"]):
        print(f"  {v['slug']:45s} {v['bet']:30s} coef {v['coeff']:.2f} "
              f"EV {v['ev']:+.1%}  stake {v['kelly']:.1%}")

    # Expresses: combine value legs from DIFFERENT matches only.
    print("\nEXPRESS CANDIDATES (legs from different matches, edges multiply):")
    combos = [c for c in itertools.combinations(value_bets, 2)
              if c[0]["slug"] != c[1]["slug"]]
    scored = []
    for a, b in combos:
        coeff = a["coeff"] * b["coeff"]
        prob = a["prob"] * b["prob"]
        scored.append((prob * coeff - 1, prob, coeff, a, b))
    for ev, prob, coeff, a, b in sorted(scored, key=lambda t: t[0],
                                        reverse=True)[:5]:
        print(f"  [{a['slug']}:{a['bet']}] x [{b['slug']}:{b['bet']}]")
        print(f"    coef {coeff:.2f}  win prob {prob:.1%}  EV {ev:+.1%}")
    print("\nWARNING: if all value legs point the same direction (e.g. every")
    print("underdog +1.5), the edge is ONE model assumption, not independent")
    print("edges. Cap express stakes at 0.5% bankroll.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("odds_file")
    ap.add_argument("--probs", help="JSON file {slug: team1_series_prob}")
    ap.add_argument("--prob", action="append", default=[],
                    help="inline slug=prob, repeatable")
    args = ap.parse_args()

    probs = {}
    if args.probs:
        probs.update(json.loads(Path(args.probs).read_text()))
    for item in args.prob:
        slug, _, val = item.partition("=")
        probs[slug] = float(val)
    if not probs:
        ap.error("provide --probs file or at least one --prob slug=value")

    analyze(args.odds_file, probs)


if __name__ == "__main__":
    main()
