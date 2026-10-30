import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "journey.sh"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )


def test_script_names_no_endpoints():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "http://" not in text
    assert "https://" not in text


def test_index_lists_the_one_command():
    result = _run()
    assert result.returncode == 0, result.stderr
    assert "journey" in result.stdout


def test_help_page_explains_the_weights_and_scope():
    result = _run("help", "journey")
    assert result.returncode == 0, result.stderr
    assert "journey.sh journey" in result.stdout
    assert "transfers" in result.stdout
    assert "Peak Tram" in result.stdout


def test_missing_argument_exits_two():
    result = _run("journey", "only-one")
    assert result.returncode == 2
    assert result.stdout == ""


def test_script_is_executable():
    assert SCRIPT.stat().st_mode & 0o111
