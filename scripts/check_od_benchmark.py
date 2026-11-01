"""Re-run the Google OD benchmark against the current cost policy.

    uv run python scripts/check_od_benchmark.py
    uv run python scripts/check_od_benchmark.py --at 14:05 --strict

`tests/data/od_benchmark.json` holds 40 pairs taken from Google Maps transit
directions: 20 were used to fit the search constants, 20 were held out. Both
ends are exact WGS84 pairs, so a place name cannot resolve differently in the
two planners.

The comparison is

    ridden + waited / wait_perception + walked + access

against Google's fastest card, because `waited` already carries the perception
multiplier and the transfer penalty is a ranking device with no real-world
counterpart.

Route choice is printed for a human to judge: the labels on the two sides are
worded differently ("港島綫" against "港島線", a merged "269B268B" for two
variants), so a machine match would be a guess. The exit status depends on the
**time error only**:

    median absolute error <= 8 minutes and |bias| <= 3 minutes, on both halves.

Current reading at 2026-11-01: train median 4.3 / bias -0.2, test median 4.8 /
bias +0.7, route agreement 14/20 and 15/20.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from hk_transport import journey as J

BENCH = Path(__file__).resolve().parents[1] / "tests" / "data" / "od_benchmark.json"
MAX_MEDIAN = 8.0
MAX_BIAS = 3.0


def comparable(option: dict, wait_perception: float) -> float:
    policy = option["policy"]
    return (
        policy["ridden_minutes"]
        + policy["waited_minutes"] / wait_perception
        + policy["walked_minutes"]
        + policy.get("access_minutes", 0.0)
    )


def run(pairs: list[dict], at: str) -> list[dict]:
    rows = []
    for pair in pairs:
        result = J.journey(pair["from"], pair["to"], at=at, explain=True)
        if not result["data"]:
            rows.append({**pair, "ours": None, "error": None, "rides": "接不上"})
            continue
        option = sorted(
            result["data"]["options"], key=lambda item: item["policy"]["policy_minutes"]
        )[0]
        ours = comparable(option, J.COST["wait_perception"])
        rows.append(
            {
                **pair,
                "ours": round(ours, 1),
                "error": round(ours - pair["google_minutes"], 1),
                "rides": "+".join(
                    leg["route"] for leg in option["legs"] if leg["type"] == "ride"
                ),
            }
        )
    return rows


def report(rows: list[dict]) -> dict:
    errors = [row["error"] for row in rows if row["error"] is not None]
    absolute = [abs(value) for value in errors]
    return {
        "n": len(rows),
        "missing": sum(1 for row in rows if row["error"] is None),
        "median_abs": round(statistics.median(absolute), 2),
        "mean_abs": round(sum(absolute) / len(absolute), 2),
        "bias": round(sum(errors) / len(errors), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--at", default="14:05")
    parser.add_argument("--strict", action="store_true", help="exit 1 on a miss")
    args = parser.parse_args()

    bench = json.loads(BENCH.read_text(encoding="utf-8"))
    pairs = bench["pairs"]
    failed = False
    for role in ("train", "test"):
        rows = run([pair for pair in pairs if pair["role"] == role], args.at)
        stats = report(rows)
        print(f"== {role}: {stats['n']} pairs")
        for row in rows:
            error = "     -" if row["error"] is None else f"{row['error']:+6.1f}"
            print(
                f"  {row['id']:6} {row['name'][:14]:14} "
                f"G={row['google_minutes']:4} ours={row['ours']} ({error})  {row['rides'][:34]}"
            )
        print(
            f"  median {stats['median_abs']}  mean {stats['mean_abs']}  "
            f"bias {stats['bias']:+.2f}  missing {stats['missing']}"
        )
        if stats["median_abs"] > MAX_MEDIAN or abs(stats["bias"]) > MAX_BIAS:
            failed = True
            print(f"  FAIL: limits are median <= {MAX_MEDIAN} and |bias| <= {MAX_BIAS}")
        else:
            print("  ok")
        print()

    if failed and args.strict:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
