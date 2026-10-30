import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bus.sh"

COMMANDS = (
    "bus_journey",
    "bus_route",
    "bus_stops_near",
    "bus_direct",
    "bus_fare",
    "bus_service_hours",
    "bus_frequency",
    "bus_eta",
    "bus_disruption",
    "bus_accessibility",
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def test_script_names_no_endpoints():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "http://" not in text
    assert "https://" not in text


def test_index_lists_every_command():
    result = _run()
    assert result.returncode == 0, result.stderr
    for name in COMMANDS:
        assert name in result.stdout


def test_help_page_describes_one_command():
    result = _run("help", "bus_fare")
    assert result.returncode == 0, result.stderr
    assert "bus.sh bus_fare" in result.stdout
    assert "SYNOPSIS" in result.stdout


def test_unknown_command_exits_two():
    result = _run("nope")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "invalid choice" in result.stderr


def test_missing_argument_exits_two():
    result = _run("bus_fare")
    assert result.returncode == 2
    assert result.stdout == ""


def test_a_command_without_data_prints_the_envelope():
    result = _run("bus_service_hours", "45")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"] is None
    assert "服務時間" in payload["note"]


def test_script_is_executable():
    mode = SCRIPT.stat().st_mode
    assert mode & 0o111
