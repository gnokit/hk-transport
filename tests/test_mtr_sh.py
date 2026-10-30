import json
import subprocess
from pathlib import Path

from hk_transport import __all__ as PUBLIC

# bus.sh owns the bus commands; this script owns the rest.
OTHER_SCRIPTS = ("bus.sh", "minibus.sh")
MTR_PUBLIC = tuple(
    name
    for name in PUBLIC
    if not name.startswith("bus_")
    and not name.startswith("minibus_")
    and name != "red_minibus"
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mtr.sh"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def test_script_does_not_name_endpoints():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "http://" not in text
    assert "https://" not in text


def _command_lines(page: str) -> dict[str, str]:
    found = {}
    for line in page.splitlines():
        for name in MTR_PUBLIC:
            if line.strip().startswith(name + " "):
                found[name] = line
    return found


def test_help_lists_every_public_function_on_its_own_line():
    result = _run()
    assert result.returncode == 0
    assert result.stderr == ""
    assert "mtr.sh help <command>" in result.stdout
    lines = _command_lines(result.stdout)
    assert set(lines) == set(MTR_PUBLIC)
    for name, line in lines.items():
        summary = line.strip()[len(name) :].strip()
        assert summary
        assert not any(other in summary for other in MTR_PUBLIC)


def test_help_without_a_command_matches_no_arguments():
    assert _run("help").stdout == _run().stdout


def test_help_command_is_a_manual_page():
    result = _run("help", "mtr_journey")
    assert result.returncode == 0
    assert result.stderr == ""
    text = result.stdout
    assert "NAME\n" in text
    assert "SYNOPSIS\n" in text
    assert "DESCRIPTION\n" in text
    assert "ARGUMENTS\n" in text
    assert "mtr.sh mtr_journey origin destination" in text
    assert "mtr_fare" not in text


def test_unknown_help_command_fails():
    result = _run("help", "mtr_ferry")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "mtr.sh help" in result.stderr


def test_missing_argument_is_usage():
    result = _run("mtr_journey", "長沙灣")
    assert result.returncode == 2
    assert result.stdout == ""


def test_mtr_exits_prints_the_envelope():
    result = _run("mtr_exits", "--station", "金鐘")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["update_frequency"] == "yearly"
    assert payload["data"]
    assert {row["station_zh"] for row in payload["data"]} == {"金鐘"}
    assert payload["data"][0]["latitude"]
    assert payload["data"][0]["longitude"]


def test_mtr_exits_requires_a_station():
    result = _run("mtr_exits")
    assert result.returncode == 2
    assert result.stdout == ""


def test_mtr_exits_can_target_one_station():
    result = _run("mtr_exits", "--station", "金鐘")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert {row["station_zh"] for row in payload["data"]} == {"金鐘"}
    assert "只列出「金鐘」" in payload["note"]
