#!/usr/bin/env bash
# Call one hk_transport function and print its JSON envelope.
#
#   bash ./mtr.sh                         # introduction and one line per command
#   bash ./mtr.sh help                    # same page
#   bash ./mtr.sh help <command>          # manual page for that command
#   bash ./mtr.sh <command> [args...]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
    echo "mtr.sh: uv is not on PATH" >&2
    exit 1
fi

exec uv run --project "$ROOT" python - "$@" <<'PY'
import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
import json

from hk_transport import (
    address_lookup,
    light_rail,
    light_rail_next,
    mtr_airport_express_fare,
    mtr_barrier_free,
    mtr_bus,
    mtr_exits,
    mtr_fare,
    mtr_journey,
    mtr_lines,
    mtr_next_train,
    mtr_ride_estimate,
    special_traffic_arrangements,
    special_traffic_news,
)
from hk_transport._result import MtrError


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _required(value: str) -> str:
    return value.strip()


@dataclass(frozen=True)
class Arg:
    """One positional parameter or one option on a command."""

    dest: str
    text: str
    flag: str | None = None
    metavar: str | None = None
    nargs: str | None = None
    kind: type | None = None

    @property
    def label(self) -> str:
        name = self.metavar or self.dest
        if self.flag:
            return f"{self.flag} {name}"
        if self.nargs == "+":
            return f"{name}..."
        return name

    @property
    def synopsis_piece(self) -> str:
        if self.flag:
            return f"[{self.label}]"
        return self.label


@dataclass(frozen=True)
class Command:
    name: str
    summary: str
    description: tuple[str, ...]
    run: Callable[[argparse.Namespace], dict]
    args: tuple[Arg, ...] = ()

    @property
    def synopsis(self) -> str:
        parts = ["mtr.sh", self.name, *(arg.synopsis_piece for arg in self.args)]
        return " ".join(parts)


def _commands() -> tuple[Command, ...]:
    return (
        Command(
            "mtr_lines",
            "Stations on one line, or lines through one station",
            (
                "Station order on a heavy-rail line, or which lines serve a station.",
                "Give a line, a station, or both. With no arguments, list every line.",
            ),
            lambda ns: mtr_lines(line=_text(ns.line), station=_text(ns.station)),
            (
                Arg("line", "Line name. Omit to include every line.", flag="--line", metavar="line"),
                Arg(
                    "station",
                    "Station name. Omit to include every station on the chosen lines.",
                    flag="--station",
                    metavar="station",
                ),
            ),
        ),
        Command(
            "mtr_journey",
            "Path and transfers between two stations",
            (
                "One path: which line to ride, where to transfer, and the stations in between.",
                "No journey minutes. Fewer transfers first, then fewer stops.",
            ),
            lambda ns: mtr_journey(_required(ns.origin), _required(ns.destination)),
            (
                Arg("origin", "Origin station, in Chinese or English.", metavar="origin"),
                Arg("destination", "Destination station, in Chinese or English.", metavar="destination"),
            ),
        ),
        Command(
            "mtr_fare",
            "Heavy-rail fare between two stations",
            (
                "Heavy-rail fare is station to station. The path does not change it.",
                "For the Airport Express, use mtr_airport_express_fare.",
            ),
            lambda ns: mtr_fare(_required(ns.origin), _required(ns.destination)),
            (
                Arg("origin", "Origin station, in Chinese or English.", metavar="origin"),
                Arg("destination", "Destination station, in Chinese or English.", metavar="destination"),
            ),
        ),
        Command(
            "mtr_airport_express_fare",
            "Airport Express fare",
            (
                "Airport Express fare between two stations. Adult and child only.",
                "Do not copy elderly, student, or JoyYou fares from heavy rail.",
            ),
            lambda ns: mtr_airport_express_fare(_required(ns.origin), _required(ns.destination)),
            (
                Arg("origin", "Origin station, in Chinese or English.", metavar="origin"),
                Arg("destination", "Destination station, in Chinese or English.", metavar="destination"),
            ),
        ),
        Command(
            "mtr_next_train",
            "Next trains at one station on one line",
            (
                "Up to four trains in each direction, and whether this response has a special arrangement.",
                "Airport Express and the Disneyland Resort Line use this command too.",
                "This is not the first or last train.",
                "When there is no alert, quote note. Do not rewrite it as all services normal.",
                "When note says to check traffic news, run special_traffic_news next.",
            ),
            lambda ns: mtr_next_train(_required(ns.line), _required(ns.station)),
            (
                Arg("line", "Heavy-rail line, in Chinese or English.", metavar="line"),
                Arg("station", "Station name, in Chinese or English.", metavar="station"),
            ),
        ),
        Command(
            "mtr_ride_estimate",
            "In-vehicle minutes estimated from live arrivals",
            (
                "Minutes between adjacent stations, from the same train's arrival times.",
                "Not a published timetable. Excludes interchange walking and waiting.",
                "If any link does not agree, do not add the other links into a total.",
                "Two trains at the same station give the headway, not the previous link. Do not add 30 seconds per station.",
            ),
            lambda ns: mtr_ride_estimate(_required(ns.origin), _required(ns.destination)),
            (
                Arg("origin", "Origin station, in Chinese or English.", metavar="origin"),
                Arg("destination", "Destination station, in Chinese or English.", metavar="destination"),
            ),
        ),
        Command(
            "mtr_barrier_free",
            "Barrier-free facilities at one station",
            (
                "Which barrier-free facilities a station has, and at which exit.",
                "Does not return exit coordinates. Use mtr_exits for coordinates.",
            ),
            lambda ns: mtr_barrier_free(_required(ns.station)),
            (Arg("station", "Station name, in Chinese or English.", metavar="station"),),
        ),
        Command(
            "light_rail_next",
            "Next Light Rail departures from one stop",
            ("Departures about to leave this Light Rail stop, including special departures.",),
            lambda ns: light_rail_next(_required(ns.station)),
            (Arg("station", "Light Rail stop name, in Chinese or English.", metavar="station"),),
        ),
        Command(
            "light_rail",
            "Light Rail stop order or fare",
            (
                "Stop order in one direction of a route, and the fare between two stops.",
                "Give a route, or both an origin and a destination.",
            ),
            lambda ns: light_rail(
                line=_text(ns.line),
                origin=_text(ns.origin),
                destination=_text(ns.destination),
            ),
            (
                Arg("line", "Route number, for example 610.", flag="--line", metavar="route"),
                Arg(
                    "origin",
                    "Origin stop. Required together with destination when asking for a fare.",
                    flag="--origin",
                    metavar="origin",
                ),
                Arg(
                    "destination",
                    "Destination stop. Required together with origin when asking for a fare.",
                    flag="--destination",
                    metavar="destination",
                ),
            ),
        ),
        Command(
            "mtr_bus",
            "MTR bus stops, fare, and arrivals",
            (
                "Stop order, the route fare, and the next departure at each stop.",
                "The fare is per route, not per segment. Scheduled trips and live positions stay separate.",
            ),
            lambda ns: mtr_bus(_required(ns.route)),
            (Arg("route", "Route id, for example K52.", metavar="route"),),
        ),
        Command(
            "address_lookup",
            "Match an address or place name",
            (
                "Match a place name with the Lands Department address lookup.",
                "score is a match score, not a distance. A nonsense string still returns suggestions. Check the name.",
                "This command does not pick a station.",
            ),
            lambda ns: address_lookup(
                " ".join(part.strip() for part in ns.query if part.strip()),
                n=ns.n,
            ),
            (
                Arg("query", "Address or place name. Extra words are joined.", metavar="query", nargs="+"),
                Arg("n", "Maximum number of matches.", flag="--n", metavar="count", kind=int),
            ),
        ),
        Command(
            "mtr_exits",
            "Heavy-rail exit coordinates",
            (
                "Coordinates of heavy-rail station exits. Latitude and longitude are already converted.",
                "With no arguments this returns every station. Pass --station for one station.",
                "This is a snapshot of about one year. Do not download it again.",
                "If note says the snapshot is older than a year, say so and still use the coordinates.",
                "This command does not pick the nearest station. A distance you compute is straight-line, not walking time.",
            ),
            lambda ns: mtr_exits(_text(ns.station)),
            (
                Arg(
                    "station",
                    "Station name, in Chinese or English. Omit to include every station.",
                    flag="--station",
                    metavar="station",
                ),
            ),
        ),
        Command(
            "special_traffic_news",
            "Current territory-wide traffic incidents",
            (
                "Transport Department incidents for the whole territory, not only the MTR.",
                "Do not filter the feed, and do not poll it. An empty list means there is no incident now.",
            ),
            lambda ns: special_traffic_news(),
        ),
        Command(
            "special_traffic_arrangements",
            "Published traffic arrangements",
            (
                "Transport Department arrangements published in advance, for the whole territory, not only the MTR.",
                "Do not filter the feed, and do not poll it. This is not the live incident feed.",
                "For incidents happening now, use special_traffic_news.",
            ),
            lambda ns: special_traffic_arrangements(),
        ),
    )


COMMANDS = _commands()
BY_NAME = {command.name: command for command in COMMANDS}


def _indent(lines: tuple[str, ...] | list[str]) -> list[str]:
    return [f"     {line}" if line else "" for line in lines]


def index_page() -> str:
    width = max(len(command.name) for command in COMMANDS)
    lines = [
        "NAME",
        "     mtr.sh — Hong Kong MTR tools",
        "",
        "SYNOPSIS",
        "     mtr.sh <command> [arguments...]",
        "     mtr.sh help [<command>]",
        "",
        "DESCRIPTION",
        *_indent(
            (
                "Run one hk_transport function and print its JSON on stdout.",
                "This page is the feature list. Pick a command below, run",
                "mtr.sh help <command> for its arguments, then run the command.",
                "Every result has dataset_id, endpoint, retrieved_at, data_at,",
                "update_frequency, data, and note. Read note and data first.",
                "Station and line names may be Chinese or English.",
            )
        ),
        "",
        "COMMANDS",
    ]
    for command in COMMANDS:
        lines.append(f"     {command.name:<{width}}  {command.summary}")
    lines.extend(["", "     Arguments and description of one command: mtr.sh help <command>"])
    return "\n".join(lines) + "\n"


def command_page(name: str) -> str | None:
    command = BY_NAME.get(name)
    if command is None:
        return None
    lines = [
        "NAME",
        f"     mtr.sh {command.name} — {command.summary}",
        "",
        "SYNOPSIS",
        f"     {command.synopsis}",
        "",
        "DESCRIPTION",
        *_indent(command.description),
    ]
    if command.args:
        lines.extend(["", "ARGUMENTS"])
        for arg in command.args:
            lines.append(f"     {arg.label}")
            lines.append(f"             {arg.text}")
            lines.append("")
        lines.pop()
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mtr.sh", add_help=False)
    sub = parser.add_subparsers(dest="command")
    for command in COMMANDS:
        item = sub.add_parser(command.name, add_help=False, usage=command.synopsis)
        for arg in command.args:
            if arg.flag:
                kwargs: dict = {"help": arg.text}
                if arg.kind is not None:
                    kwargs["type"] = arg.kind
                item.add_argument(arg.flag, **kwargs)
            else:
                kwargs = {"metavar": arg.metavar or arg.dest}
                if arg.nargs is not None:
                    kwargs["nargs"] = arg.nargs
                item.add_argument(arg.dest, **kwargs)
        item.set_defaults(func=command.run)
    return parser


def _wants_page(argv: list[str]) -> str | None:
    """Return a command name when the user asked for its manual page."""
    if not argv:
        return ""
    if argv[0] in {"-h", "--help"}:
        return ""
    if argv[0] == "help":
        if len(argv) == 1:
            return ""
        if len(argv) == 2:
            return argv[1]
        print("usage: mtr.sh help <command>", file=sys.stderr)
        raise SystemExit(2)
    if argv[0] in BY_NAME and any(token in {"-h", "--help"} for token in argv[1:]):
        return argv[0]
    return None


def _emit(result: dict) -> None:
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    page = _wants_page(argv)
    if page == "":
        sys.stdout.write(index_page())
        return 0
    if page is not None:
        text = command_page(page)
        if text is None:
            print(f"no such command: {page}", file=sys.stderr)
            print("command list: mtr.sh help", file=sys.stderr)
            return 2
        sys.stdout.write(text)
        return 0
    args = _parser().parse_args(argv)
    _emit(args.func(args))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except MtrError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
PY