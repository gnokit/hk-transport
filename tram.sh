#!/usr/bin/env bash
# Call one tram function and print its JSON envelope.
#
#   bash ./tram.sh                         # introduction and one line per command
#   bash ./tram.sh help                    # same page
#   bash ./tram.sh help <command>          # manual page for that command
#   bash ./tram.sh <command> [args...]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
    echo "tram.sh: uv is not on PATH" >&2
    exit 1
fi

exec uv run --project "$ROOT" python - "$@" <<'PY'
import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
import json

from hk_transport.tram import (
    peak_tram,
    tram_disruption,
    tram_eta,
    tram_fare,
    tram_route,
    tram_service_hours,
    tram_stops_near,
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
        parts = ["tram.sh", self.name, *(arg.synopsis_piece for arg in self.args)]
        return " ".join(parts)


def _commands() -> tuple[Command, ...]:
    return (
        Command(
            "tram_route",
            "Stop order of one tram line, or whether it serves a place",
            (
                "Tram lines have Chinese names, not numbers, for example 跑馬地.",
                "Eastbound and westbound are separate variants and are listed separately.",
                "With --place, each variant says whether it serves that place.",
            ),
            lambda ns: tram_route(blank(ns.route), place=blank(ns.place)),
            (
                Arg("route", "Line name or a word from it, for example 跑馬地.", metavar="route"),
                Arg("place", "Optional place to test the line against.", flag="--place", metavar="place"),
            ),
        ),
        Command(
            "tram_stops_near",
            "Tram stops near a place",
            (
                "Stops within the walking radius, nearest first, straight-line distance.",
                "Eastbound and westbound stops appear separately.",
            ),
            lambda ns: tram_stops_near(_required(ns.place), limit=ns.limit),
            (
                Arg("place", "Place name, or a stop name.", metavar="place"),
                Arg("limit", "How many stops. Default 8.", flag="--limit", metavar="count", kind=int, default=8),
            ),
        ),
        Command(
            "tram_fare",
            "Adult tram fare",
            (
                "Hong Kong Tramways charges a flat adult fare, not a section fare.",
                "Boarding again after alighting costs another fare.",
            ),
            lambda ns: tram_fare(blank(ns.route)),
            (Arg("route", "Optional line name or word.", flag="--route", metavar="route"),),
        ),
        Command(
            "peak_tram",
            "Peak Tram stops and fare",
            (
                "Six stops, two directions, one fare.",
                "No headway or arrival data.",
            ),
            lambda ns: peak_tram(),
            (),
        ),
        Command(
            "tram_disruption",
            "Transport Department notices that mention a line",
            (
                "Keyword match on the line name, because tram lines have no numbers.",
                "No match does not mean no disruption.",
            ),
            lambda ns: tram_disruption(_required(ns.route)),
            (Arg("route", "Line name or a word from it.", metavar="route"),),
        ),
        Command(
            "tram_service_hours",
            "First and last tram (no data)",
            ("This skill has no tram service hours.", "It answers data null and says so."),
            lambda ns: tram_service_hours(blank(ns.route)),
            (Arg("route", "Optional line name.", flag="--route", metavar="route"),),
        ),
        Command(
            "tram_eta",
            "Next tram (no data)",
            ("This skill has no tram real-time arrivals.", "It answers data null and says so."),
            lambda ns: tram_eta(blank(ns.stop)),
            (Arg("stop", "Optional stop name.", flag="--stop", metavar="stop"),),
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
        "     tram.sh — Hong Kong tram and Peak Tram tools",
        "",
        "SYNOPSIS",
        "     tram.sh <command> [arguments...]",
        "     tram.sh help [<command>]",
        "",
        "DESCRIPTION",
        *_indent(
            (
                "Run one hk_transport tram function and print its JSON on stdout.",
                "This page is the feature list. Pick a command below, run",
                "tram.sh help <command> for its arguments, then run the command.",
                "Every result has dataset_id, endpoint, retrieved_at, data_at,",
                "update_frequency, data and note. Read note and data first.",
                "Covers Hong Kong Tramways and the Peak Tram. Fares come from the Transport Department.",
            )
        ),
        "",
        "COMMANDS",
    ]
    for command in COMMANDS:
        lines.append(f"     {command.name:<{width}}  {command.summary}")
    lines.extend(["", "     Arguments and description of one command: tram.sh help <command>"])
    return "\n".join(lines) + "\n"


def command_page(name: str) -> str | None:
    command = BY_NAME.get(name)
    if command is None:
        return None
    lines = [
        "NAME",
        f"     tram.sh {command.name} — {command.summary}",
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
    parser = argparse.ArgumentParser(prog="tram.sh", add_help=False)
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
        print("usage: tram.sh help <command>", file=sys.stderr)
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
            print("command list: tram.sh help", file=sys.stderr)
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
