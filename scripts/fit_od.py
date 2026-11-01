"""Fit the search-time policy constants against a Google OD benchmark.

    uv run python scripts/fit_od.py .cache/od/google_od_coords.json

The benchmark is a JSON file with pairs of WGS84 coordinate pairs and the
minutes Google gives for the same trip:

    {"pairs": [{"id": "A1", "from": "22.28,114.15", "to": "22.28,114.18",
                "cards": [[10, "港島綫"], [20, "電車"]]}, ...]}

Every pair is compared against Google's fastest card. The model's comparable
minutes are

    ridden + waited / wait_perception + walked + access

because `waited` already carries the perception multiplier and the transfer
penalty is a ranking device with no real-world counterpart.

Only the constants that are applied when the search runs can be fitted here:
`wait_perception`, `transfer_penalty_minutes` and `access_minutes`. Line and
ferry speeds are baked into the ride edges, so changing them needs a graph
rebuild; fit those by hand, one at a time, and re-run this script.

Five pairs are held out and scored once for the winner, so the reported error
is not the number the grid was chosen on.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from hk_transport import journey as J

DEFAULT_BENCH = Path(".cache/od/google_od_coords.json")


def load(bench: Path) -> list[dict]:
    payload = json.loads(bench.read_text(encoding="utf-8"))
    pairs = []
    for row in payload.get("pairs", []):
        cards = row.get("cards") or []
        if not cards or not row.get("from") or not row.get("to"):
            continue
        pairs.append(
            {
                "id": row.get("id"),
                "from": row["from"],
                "to": row["to"],
                "google": min(card[0] for card in cards),
                "label": row.get("o"),
            }
        )
    return pairs


def comparable(option: dict, wait_perception: float) -> float:
    policy = option["policy"]
    return (
        policy["ridden_minutes"]
        + policy["waited_minutes"] / wait_perception
        + policy["walked_minutes"]
        + policy.get("access_minutes", 0.0)
    )


def apply(units: dict, base_access: dict, wait: float, transfer: float, access: float) -> None:
    units["wait_perception"] = wait
    units["transfer_penalty"] = round(transfer * J.COST["units_per_minute"])
    units["access"] = {
        mode: round(minutes * access * J.COST["units_per_minute"])
        for mode, minutes in base_access.items()
    }


def score(pairs: list[dict], wait: float) -> list[float]:
    errors = []
    for pair in pairs:
        result = J.journey(pair["from"], pair["to"], at=pair.get("at"), explain=True)
        if not result["data"]:
            errors.append(abs(pair["google"]))  # a miss is as bad as it gets
            continue
        rows = sorted(result["data"]["options"], key=lambda o: o["policy"]["policy_minutes"])
        errors.append(comparable(rows[0], wait) - pair["google"])
    return errors


def summarise(errors: list[float]) -> dict:
    absolute = [abs(value) for value in errors]
    return {
        "n": len(errors),
        "median_abs": round(statistics.median(absolute), 2),
        "mean_abs": round(sum(absolute) / len(absolute), 2),
        "bias": round(sum(errors) / len(errors), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bench", nargs="?", default=str(DEFAULT_BENCH))
    parser.add_argument("--holdout", type=int, default=5)
    parser.add_argument("--wait", default="1.0,1.25,1.5,1.75")
    parser.add_argument("--transfer", default="0,2,3,4,6")
    parser.add_argument("--access", default="0,0.5,1.0,1.5")
    parser.add_argument("--at", default="14:05")
    args = parser.parse_args()

    pairs = load(Path(args.bench))
    for pair in pairs:
        pair["at"] = args.at
    step = max(len(pairs) // args.holdout, 1)
    held = [pair for index, pair in enumerate(pairs) if index % step == 0][: args.holdout]
    held_ids = {id(pair) for pair in held}
    train = [pair for pair in pairs if id(pair) not in held_ids]
    print(f"{len(pairs)} pairs: {len(train)} train, {len(held)} holdout")

    graph = J._graph()
    units = graph["units"]
    base_access = dict(J.COST["access_minutes"])
    original = dict(units)
    try:
        rows = []
        for wait in [float(v) for v in args.wait.split(",")]:
            for transfer in [float(v) for v in args.transfer.split(",")]:
                for access in [float(v) for v in args.access.split(",")]:
                    apply(units, base_access, wait, transfer, access)
                    errors = score(train, wait)
                    stats = summarise(errors)
                    rows.append((stats["mean_abs"], wait, transfer, access, stats))
                    print(
                        f"wait {wait:g}  transfer {transfer:g}  access x{access:g}"
                        f"  -> mean {stats['mean_abs']:.2f}  median {stats['median_abs']:.2f}"
                        f"  bias {stats['bias']:+.2f}"
                    )
        rows.sort()
        best = rows[0]
        _, wait, transfer, access, stats = best
        print()
        print(
            f"best on train: wait {wait:g}, transfer {transfer:g}, access x{access:g}"
            f" (mean {stats['mean_abs']:.2f}, median {stats['median_abs']:.2f})"
        )
        apply(units, base_access, wait, transfer, access)
        held_stats = summarise(score(held, wait))
        print(
            f"holdout: mean {held_stats['mean_abs']:.2f}, median {held_stats['median_abs']:.2f},"
            f" bias {held_stats['bias']:+.2f} on {held_stats['n']} pairs"
        )
        print()
        print("current COST:", f"wait {J.COST['wait_perception']:g},",
              f"transfer {J.COST['transfer_penalty_minutes']:g}")
    finally:
        units.clear()
        units.update(original)


if __name__ == "__main__":
    main()
