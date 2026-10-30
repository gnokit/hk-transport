#!/usr/bin/env bash
# Call the journey function and print its JSON envelope.
#
#   bash ./journey.sh                         # introduction and one line per command
#   bash ./journey.sh help                    # same page
#   bash ./journey.sh help <command>          # manual page for that command
#   bash ./journey.sh <command> [args...]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
    echo "journey.sh: uv is not on PATH" >&2
    exit 1
fi

exec uv run --project "$ROOT" python - "$@" <<'PY'
import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
import json

from hk_transport.journey import journey
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
        parts = ["journey.sh", self.name, *(arg.synopsis_piece for arg in self.args)]
        return " ".join(parts)


def _commands() -> tuple[Command, ...]:
    return (
        Command(
            "journey",
            "Any journey across rail, buses and green minibuses",
            (
                "One search over MTR, KMB/LWB and green minibus together.",
                "Each option lists its walk legs and its ride legs, in order.",
                "Ranking is transfers, then stops, then walking; one transfer counts as 100 stops and one stop as 100 metres of walking.",
                "Walking metres and minutes come from the Lands Department pedestrian network; when a walk has no route there, it is marked estimated.",
                "No riding time is published, so a total duration is never given. No fares are included.",
                "Citybus, NLB, tram and ferry are not in the graph yet.",
            ),
            lambda ns: journey(
                _required(ns.origin),
                _required(ns.destination),
                options=ns.options,
                walk=ns.walk,
            ),
            (
                Arg("origin", "Origin place, stop name, station name, or id.", metavar="origin"),
                Arg("destination", "Destination place, stop name, station name, or id.", metavar="destination"),
                Arg(
                    "options",
                    "How many distinct journeys to return. Default 3.",
                    flag="--options",
                    metavar="count",
                    kind=int,
                    default=3,
                ),
                Arg(
                    "walk",
                    "Walking radius at each end. Default 800.",
                    flag="--walk",
                    metavar="metres",
                    kind=int,
                    default=800,
                ),
            ),
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
        "     journey.sh — one journey across every network",
        "",
        "SYNOPSIS",
        "     journey.sh <command> [arguments...]",
        "     journey.sh help [<command>]",
        "",
        "DESCRIPTION",
        *_indent(
            (
                "Run the combined journey search and print its JSON on stdout.",
                "This page is the feature list. Pick a command below, run",
                "journey.sh help <command> for its arguments, then run the command.",
                "Every result has dataset_id, endpoint, retrieved_at, data_at,",
                "update_frequency, data and note. Read note and data first.",
                "Covers MTR, KMB/LWB and green minibuses.",
            )
        ),
        "",
        "COMMANDS",
    ]
    for command in COMMANDS:
        lines.append(f"     {command.name:<{width}}  {command.summary}")
    lines.extend(["", "     Arguments and description of one command: journey.sh help <command>"])
    return "\n".join(lines) + "\n"


def command_page(name: str) -> str | None:
    command = BY_NAME.get(name)
    if command is None:
        return None
    lines = [
        "NAME",
        f"     journey.sh {command.name} — {command.summary}",
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
    parser = argparse.ArgumentParser(prog="journey.sh", add_help=False)
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
        print("usage: journey.sh help <command>", file=sys.stderr)
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
            print("command list: journey.sh help", file=sys.stderr)
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
