#!/usr/bin/env bash
# Call one bus function and print its JSON envelope.
#
#   bash ./bus.sh                         # introduction and one line per command
#   bash ./bus.sh help                    # same page
#   bash ./bus.sh help <command>          # manual page for that command
#   bash ./bus.sh <command> [args...]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
    echo "bus.sh: uv is not on PATH" >&2
    exit 1
fi

exec uv run --project "$ROOT" python - "$@" <<'PY'
import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
import json

from hk_transport.bus import (
    bus_accessibility,
    bus_direct,
    bus_disruption,
    bus_eta,
    bus_fare,
    bus_frequency,
    bus_journey,
    bus_route,
    bus_service_hours,
    bus_stops_near,
)
from hk_transport._result import MtrError
from hk_transport._values import blank


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
    required: bool = False
    default: object | None = None

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
            return self.label if self.required else f"[{self.label}]"
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
        parts = ["bus.sh", self.name, *(arg.synopsis_piece for arg in self.args)]
        return " ".join(parts)


def _commands() -> tuple[Command, ...]:
    return (
        Command(
            "bus_journey",
            "Routes between two places, with transfers",
            (
                "Several ways to travel, each with its legs, transfers and walking.",
                "Cost is transfers then stops, never minutes. Options are not ranked.",
                "Fare is not included in a journey; use bus_fare for the route fare.",
                "KMB and LWB only. A transfer between operators cannot be found.",
                "Every stop within the walking radius is tried, not just the nearest.",
            ),
            lambda ns: bus_journey(
                _required(ns.origin),
                _required(ns.destination),
                options=ns.options,
                walk=ns.walk,
            ),
            (
                Arg("origin", "Origin place, stop name, or stop id.", metavar="origin"),
                Arg("destination", "Destination place, stop name, or stop id.", metavar="destination"),
                Arg(
                    "options",
                    "How many distinct routes to return. Default 3.",
                    flag="--options",
                    metavar="count",
                    kind=int,
                    default=3,
                ),
                Arg(
                    "walk",
                    "Walking radius in metres. Default 400.",
                    flag="--walk",
                    metavar="metres",
                    kind=int,
                    default=400,
                ),
            ),
        ),
        Command(
            "bus_route",
            "Stop order of one route, or whether it serves a place",
            (
                "Every direction and service type of that route, up to four.",
                "With --place, each variant says whether it serves that place.",
                "KMB and LWB only.",
            ),
            lambda ns: bus_route(_required(ns.route), place=blank(ns.place)),
            (
                Arg("route", "Route number, for example 45.", metavar="route"),
                Arg("place", "Optional place to test the route against.", flag="--place", metavar="place"),
            ),
        ),
        Command(
            "bus_stops_near",
            "Bus stops near a place",
            (
                "Stops within the walking radius, nearest first, with straight-line distance.",
                "KMB and LWB only. Straight-line is not walking distance.",
            ),
            lambda ns: bus_stops_near(_required(ns.place), limit=ns.limit),
            (
                Arg("place", "Place name, or a stop name or id.", metavar="place"),
                Arg(
                    "limit",
                    "How many stops to return. Default 8.",
                    flag="--limit",
                    metavar="count",
                    kind=int,
                    default=8,
                ),
            ),
        ),
        Command(
            "bus_direct",
            "One-ride routes between two stops",
            (
                "Routes that serve both stops in the same direction, on the same trip.",
                "No path search: this is a membership and order check.",
                "Empty data means no single KMB or LWB route does it.",
            ),
            lambda ns: bus_direct(_required(ns.origin), _required(ns.destination)),
            (
                Arg("origin", "Origin stop name, place, or id.", metavar="origin"),
                Arg("destination", "Destination stop name, place, or id.", metavar="destination"),
            ),
        ),
        Command(
            "bus_fare",
            "Adult route fare and published whole-route time",
            (
                "Adult full fare for boarding the route, per service variant.",
                "Not a section fare. Compass and transfer discounts are not included.",
                "journey_time_minutes is the whole route, not the segment you ride.",
            ),
            lambda ns: bus_fare(_required(ns.route), company=blank(ns.company)),
            (
                Arg("route", "Route number, for example B1.", metavar="route"),
                Arg("company", "Optional operator code such as KMB.", flag="--company", metavar="code"),
            ),
        ),
        Command(
            "bus_service_hours",
            "First and last bus (no data)",
            (
                "This skill has no service hours or first/last bus data.",
                "It answers with data null and says so. Do not estimate.",
            ),
            lambda ns: bus_service_hours(_required(ns.route)),
            (Arg("route", "Route number.", metavar="route"),),
        ),
        Command(
            "bus_frequency",
            "Headway, circular, express (no data)",
            (
                "This skill has no timetable, headway, or circular/express flags.",
                "It answers with data null and says so. Do not estimate.",
            ),
            lambda ns: bus_frequency(_required(ns.route)),
            (Arg("route", "Route number.", metavar="route"),),
        ),
        Command(
            "bus_eta",
            "Next buses for a route, or at a stop",
            (
                "Give a route, or a stop, or both.",
                "A stop without a route only checks its first five routes.",
                "KMB and LWB only.",
            ),
            lambda ns: bus_eta(route=blank(ns.route), stop=blank(ns.stop)),
            (
                Arg("route", "Route number.", flag="--route", metavar="route"),
                Arg("stop", "Stop name, place, or id.", flag="--stop", metavar="stop"),
            ),
        ),
        Command(
            "bus_disruption",
            "Transport Department notices that mention a route",
            (
                "Keyword match across live incidents and published arrangements.",
                "Not an operator route alert. Notices do not always list routes, so no match is not no disruption.",
                "Numeric-only routes are noisy; check by hand.",
            ),
            lambda ns: bus_disruption(_required(ns.route), limit=ns.limit),
            (
                Arg("route", "Route number, for example K66.", metavar="route"),
                Arg(
                    "limit",
                    "Maximum notices to return. Default 5.",
                    flag="--limit",
                    metavar="count",
                    kind=int,
                    default=5,
                ),
            ),
        ),
        Command(
            "bus_accessibility",
            "Low-floor and wheelchair access (no data)",
            (
                "This skill has no low-floor or accessible-bus data.",
                "It answers with data null and says so. Do not estimate.",
            ),
            lambda ns: bus_accessibility(_required(ns.route)),
            (Arg("route", "Route number.", metavar="route"),),
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
        "     bus.sh — Hong Kong franchised bus tools",
        "",
        "SYNOPSIS",
        "     bus.sh <command> [arguments...]",
        "     bus.sh help [<command>]",
        "",
        "DESCRIPTION",
        *_indent(
            (
                "Run one hk_transport bus function and print its JSON on stdout.",
                "This page is the feature list. Pick a command below, run",
                "bus.sh help <command> for its arguments, then run the command.",
                "Every result has dataset_id, endpoint, retrieved_at, data_at,",
                "update_frequency, data and note. Read note and data first.",
                "Covers KMB and LWB. Fares come from the Transport Department.",
            )
        ),
        "",
        "COMMANDS",
    ]
    for command in COMMANDS:
        lines.append(f"     {command.name:<{width}}  {command.summary}")
    lines.extend(["", "     Arguments and description of one command: bus.sh help <command>"])
    return "\n".join(lines) + "\n"


def command_page(name: str) -> str | None:
    command = BY_NAME.get(name)
    if command is None:
        return None
    lines = [
        "NAME",
        f"     bus.sh {command.name} — {command.summary}",
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
    parser = argparse.ArgumentParser(prog="bus.sh", add_help=False)
    sub = parser.add_subparsers(dest="command")
    for command in COMMANDS:
        item = sub.add_parser(command.name, add_help=False, usage=command.synopsis)
        for arg in command.args:
            if arg.flag:
                kwargs: dict = {
                    "help": arg.text,
                    "required": arg.required,
                    "default": arg.default,
                }
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


def _page_request(argv: list[str]) -> tuple[bool, str | None]:
    """Whether a manual page was asked for, and which command it describes.

    The command is None for the index page, which every command shares.
    """
    if not argv or argv[0] in {"-h", "--help"}:
        return True, None
    if argv[0] == "help":
        if len(argv) == 1:
            return True, None
        if len(argv) == 2:
            return True, argv[1]
        print("usage: bus.sh help <command>", file=sys.stderr)
        raise SystemExit(2)
    if argv[0] in BY_NAME and any(token in {"-h", "--help"} for token in argv[1:]):
        return True, argv[0]
    return False, None


def _emit(result: dict) -> None:
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    wants_page, page = _page_request(argv)
    if wants_page and page is None:
        sys.stdout.write(index_page())
        return 0
    if wants_page:
        text = command_page(page)
        if text is None:
            print(f"no such command: {page}", file=sys.stderr)
            print("command list: bus.sh help", file=sys.stderr)
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
