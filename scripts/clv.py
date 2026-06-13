#!/usr/bin/env python3
"""Closing Line Value (CLV) tracking — the single best long-term edge detector.

Idea: the coeff just before a match locks (the "closing line") is the
sharpest estimate the market ever produces. If you CONSISTENTLY bet at
higher coeffs than the close, you have genuine edge — regardless of whether
individual bets win. If you don't beat the close, your wins are luck and
the bankroll dies long-term.

CLV% = your_bet_coeff / closing_coeff - 1   (positive = you beat the close)

Workflow:
    # As close to match start as possible (this captures the CLOSING line):
    python3 scripts/clv.py capture
    # Anytime, see the running CLV verdict:
    python3 scripts/clv.py report
"""
import argparse
import csv
import sys
from pathlib import Path

import fetch_odds as fo

CSV = Path(__file__).resolve().parent.parent / "bets.csv"


def read_rows():
    with CSV.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return list(r), r.fieldnames


def write_rows(rows, fields):
    with CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def coeff_for_key(match, key):
    """Resolve a market_key to its current coeff in a fetched match."""
    if key == "team_1_ml":
        return (match.get("bet_updates") or {}).get("team_1", {}).get("coeff")
    if key == "team_2_ml":
        return (match.get("bet_updates") or {}).get("team_2", {}).get("coeff")
    for m in (match.get("bet_updates") or {}).get("additional_markets", []):
        if m.get("bet_type") == key:
            return m.get("coeff")
    return None


def cmd_capture(args):
    rows, fields = read_rows()
    captured = 0
    for r in rows:
        if r["status"] != "pending":
            continue
        slug, key = r["match_slug"], r["market_key"]
        if not slug or not key:
            continue
        try:
            match = fo.fetch_match(slug)
        except Exception as e:
            print(f"  {r['selection']}: fetch fail {e}", file=sys.stderr)
            continue
        # Only (re)capture while the match is still UPCOMING. The last such
        # snapshot before lock is the true closing line. Once the match is
        # live/finished, keep what we already stored.
        if match.get("status") != "upcoming":
            if r["close_coeff"]:
                print(f"  {r['selection']:18s} locked, keeping close "
                      f"{r['close_coeff']}")
            else:
                print(f"  {r['selection']:18s} already live/closed, "
                      f"no pre-lock capture -> CLV unavailable",
                      file=sys.stderr)
            continue
        close = coeff_for_key(match, key)
        if close is None:
            print(f"  {r['selection']}: market {key} not found "
                  f"(match may be live/closed)", file=sys.stderr)
            continue
        bet_coeff = float(r["coeff"])
        clv = bet_coeff / close - 1
        r["close_coeff"] = f"{close:.3f}"
        r["clv_pct"] = f"{clv:.4f}"
        captured += 1
        flag = "BEAT" if clv > 0 else "miss"
        print(f"  {r['selection']:18s} bet {bet_coeff:.2f} vs close "
              f"{close:.2f}  CLV {clv:+.1%}  [{flag}]")
    if captured:
        write_rows(rows, fields)
    print(f"\nCaptured closing line for {captured} bet(s).")


def cmd_report(args):
    rows, _ = read_rows()
    clv_rows = [r for r in rows if r.get("clv_pct")]
    if not clv_rows:
        print("No CLV data yet. Run 'capture' near match start.")
        return
    clvs = [(r["selection"], float(r["clv_pct"]), float(r["coeff"]),
             float(r["close_coeff"]), r["status"]) for r in clv_rows]
    print(f"{'selection':20s} {'bet':>6s} {'close':>6s} {'CLV':>8s}  result")
    for sel, clv, bet, close, status in clvs:
        print(f"{sel:20s} {bet:6.2f} {close:6.2f} {clv:+7.1%}  {status}")
    vals = [c[1] for c in clvs]
    beat = sum(1 for v in vals if v > 0)
    avg = sum(vals) / len(vals)
    print("-" * 50)
    print(f"Beat close: {beat}/{len(vals)} ({beat / len(vals):.0%})   "
          f"Avg CLV: {avg:+.1%}")
    print()
    if len(vals) < 30:
        print(f"Sample too small ({len(vals)} bets). Need ~30-50 before the")
        print("CLV verdict is trustworthy. Keep capturing every bet.")
    elif avg > 0.01:
        print("VERDICT: positive avg CLV over a real sample = you have edge.")
    elif avg > -0.01:
        print("VERDICT: ~flat CLV = no clear edge; results mostly variance.")
    else:
        print("VERDICT: negative CLV = market is sharper than us. "
              "Expect the bankroll to bleed long-term.")


def cmd_endtime(args):
    """Print epoch seconds (UTC) of the LAST pending match start.

    The auto-capture loop runs until this moment + buffer: once the final
    match locks, every close_coeff is frozen and there is nothing left to do.
    Prints nothing if no pending bets carry a match_slug.
    """
    import datetime as dt
    rows, _ = read_rows()
    starts = []
    seen = set()
    for r in rows:
        if r["status"] != "pending" or not r["match_slug"]:
            continue
        if r["match_slug"] in seen:
            continue
        seen.add(r["match_slug"])
        try:
            m = fo.fetch_match(r["match_slug"])
            sd = m.get("start_date")
            if sd:
                t = dt.datetime.fromisoformat(sd.replace("Z", "+00:00"))
                starts.append(t.timestamp())
        except Exception:
            continue
    if starts:
        print(int(max(starts)))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("capture").set_defaults(func=cmd_capture)
    sub.add_parser("report").set_defaults(func=cmd_report)
    sub.add_parser("endtime").set_defaults(func=cmd_endtime)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
