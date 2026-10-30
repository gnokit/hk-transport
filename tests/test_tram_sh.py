import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tram.sh"

COMMANDS = (
    "tram_route",
    "tram_stops_near",
    "tram_fare",
    "peak_tram",
    "tram_disruption",
    "tram_service_hours",
    "tram_eta",
)


def _run(*args):
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT, text=True, capture_output=True, timeout=120, check=False)


def test_no_endpoints_in_the_script():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "http://" not in text and "https://" not in text


def test_index_lists_every_command():
    result = _run()
    assert result.returncode == 0, result.stderr
    for name in COMMANDS:
        assert name in result.stdout


def test_a_no_data_command_still_prints_an_envelope():
    result = _run("tram_eta")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"] is None
    assert "實時" in payload["note"]


def test_script_is_executable():
    assert SCRIPT.stat().st_mode & 0o111
