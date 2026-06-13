#!/usr/bin/env python3
"""Append a bet to bets.csv and report running bankroll stats.

Usage:
    # add a placed (pending) bet
    python3 scripts/log_bet.py add --event "IEM Cologne Major 2026" \
        --team1 "Team Vitality" --team2 "9z Team" \
        --market handicap_maps --selection "9z (+1.5)" \
        --coeff 2.92 --stake 10 --model-prob 0.49 --notes "value EV+46%"

    # settle an existing bet by id
    python3 scripts/log_bet.py settle --bet-id 2677... --status won

    # show stats
    python3 scripts/log_bet.py stats
"""
import argparse
import csv
import time
from pathlib import Path

CSV = Path(__file__).resolve().parent.parent / "bets.csv"
FIELDS = ["bet_id", "placed_at", "event", "team1", "team2", "market",
          "selection", "coeff", "stake", "status", "payout", "profit",
          "model_prob", "match_slug", "market_key", "close_coeff",
          "clv_pct", "notes"]


def read_rows():
    if not CSV.exists():
        return []
    with CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(rows):
    with CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def cmd_add(args):
    rows = read_rows()
    bet_id = args.bet_id or str(int(time.time() * 1000))
    rows.append({
        "bet_id": bet_id,
        "placed_at": args.placed_at or time.strftime("%Y-%m-%dT%H:%M"),
        "event": args.event, "team1": args.team1, "team2": args.team2,
        "market": args.market, "selection": args.selection,
        "coeff": f"{args.coeff:.2f}", "stake": f"{args.stake:.2f}",
        "status": "pending", "payout": "", "profit": "",
        "model_prob": f"{args.model_prob:.3f}" if args.model_prob else "",
        "match_slug": args.match_slug or "",
        "market_key": args.market_key or "",
        "close_coeff": "", "clv_pct": "",
        "notes": args.notes or "",
    })
    write_rows(rows)
    print(f"Added bet {bet_id}: {args.selection} @ {args.coeff}")


def cmd_settle(args):
    rows = read_rows()
    found = False
    for r in rows:
        if r["bet_id"] == args.bet_id:
            found = True
            stake = float(r["stake"])
            coeff = float(r["coeff"])
            r["status"] = args.status
            if args.status == "won":
                payout = stake * coeff
                r["payout"] = f"{payout:.2f}"
                r["profit"] = f"{payout - stake:.2f}"
            elif args.status == "lost":
                r["payout"] = "0.00"
                r["profit"] = f"{-stake:.2f}"
            elif args.status == "void":
                r["payout"] = f"{stake:.2f}"
                r["profit"] = "0.00"
    if not found:
        print(f"Bet id {args.bet_id} not found")
        return
    write_rows(rows)
    print(f"Settled {args.bet_id} as {args.status}")


def cmd_stats(args):
    rows = read_rows()
    settled = [r for r in rows if r["status"] in ("won", "lost", "void")]
    staked = sum(float(r["stake"]) for r in settled)
    profit = sum(float(r["profit"]) for r in settled if r["profit"])
    wins = sum(1 for r in settled if r["status"] == "won")
    losses = sum(1 for r in settled if r["status"] == "lost")
    pending = [r for r in rows if r["status"] == "pending"]
    print(f"Settled bets : {len(settled)}  (W {wins} / L {losses})")
    if settled:
        print(f"Win rate     : {wins / len(settled):.1%}")
    print(f"Total staked : ${staked:.2f}")
    print(f"Net profit   : ${profit:+.2f}")
    if staked:
        print(f"ROI          : {profit / staked:+.1%}")
    if pending:
        print(f"Pending      : {len(pending)} bet(s), "
              f"${sum(float(r['stake']) for r in pending):.2f} at risk")

    clv_rows = [r for r in rows if r.get("clv_pct")]
    if clv_rows:
        clvs = [float(r["clv_pct"]) for r in clv_rows]
        beat = sum(1 for c in clvs if c > 0)
        avg = sum(clvs) / len(clvs)
        pct = beat / len(clv_rows)
        print("\n--- CLV (the real edge signal) ---")
        print(f"Bets w/ CLV  : {len(clv_rows)}")
        print(f"Beat close   : {beat}/{len(clv_rows)} ({pct:.0%})")
        print(f"Avg CLV      : {avg:+.1%}")
        if avg > 0.005:
            print("  -> positive avg CLV = early signal of edge")
        else:
            print("  -> non-positive CLV = no proven edge yet (~50+ bets)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("--bet-id")
    a.add_argument("--placed-at")
    a.add_argument("--event", required=True)
    a.add_argument("--team1", required=True)
    a.add_argument("--team2", required=True)
    a.add_argument("--market", required=True)
    a.add_argument("--selection", required=True)
    a.add_argument("--coeff", type=float, required=True)
    a.add_argument("--stake", type=float, required=True)
    a.add_argument("--model-prob", type=float, dest="model_prob")
    a.add_argument("--match-slug", dest="match_slug",
                   help="bo3.gg match slug, enables CLV capture")
    a.add_argument("--market-key", dest="market_key",
                   help="bo3 market key, e.g. team_1_ml, "
                        "team_2_handicap_over_1_5")
    a.add_argument("--notes")
    a.set_defaults(func=cmd_add)

    s = sub.add_parser("settle")
    s.add_argument("--bet-id", required=True)
    s.add_argument("--status", required=True,
                   choices=["won", "lost", "void"])
    s.set_defaults(func=cmd_settle)

    st = sub.add_parser("stats")
    st.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
