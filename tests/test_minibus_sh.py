import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "minibus.sh"

COMMANDS = (
    "minibus_journey",
    "minibus_route",
    "minibus_stops_near",
    "minibus_direct",
    "minibus_fare",
    "minibus_service_hours",
    "minibus_frequency",
    "minibus_eta",
    "minibus_disruption",
    "minibus_accessibility",
    "red_minibus",
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
    result = _run("help", "minibus_fare")
    assert result.returncode == 0, result.stderr
    assert "minibus.sh minibus_fare" in result.stdout
    assert "SYNOPSIS" in result.stdout


def test_unknown_command_exits_two():
    result = _run("nope")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "invalid choice" in result.stderr


def test_missing_argument_exits_two():
    result = _run("minibus_fare")
    assert result.returncode == 2
    assert result.stdout == ""


def test_a_command_without_data_prints_the_envelope():
    result = _run("minibus_service_hours", "37")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"] is None
    assert "服務時間" in payload["note"]


def test_numeric_options_have_defaults_in_the_manual():
    result = _run("help", "minibus_journey")
    assert "Default 3" in result.stdout
    assert "Default 400" in result.stdout


def test_script_is_executable():
    assert SCRIPT.stat().st_mode & 0o111
