"""Run the same native-lock and Unicode smoke tests on Windows, macOS and Linux."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from brandprobe.config import load_config
from brandprobe.exceptions import BrandProbeError
from brandprobe.worker import lease


def test_lock_excludes_another_process_and_releases_after_exit(tmp_path):
    folder = tmp_path / "workspace with spaces"
    script = """
import sys
from pathlib import Path
from brandprobe.worker import lease
with lease(Path(sys.argv[1])):
    print('acquired', flush=True)
    sys.stdin.read()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(folder)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert child.stdout.readline().strip() == "acquired"
        with pytest.raises(BrandProbeError, match="Another BrandProbe worker"):
            with lease(folder):
                pytest.fail("Two processes acquired the worker lease")
    finally:
        child.terminate()
        child.communicate(timeout=10)
    # Native OS locks are released even when the holder cannot run its finally block.
    with lease(folder):
        assert (folder / ".brandprobe/worker.lock").exists()


def test_lock_releases_after_python_exception(tmp_path):
    with pytest.raises(RuntimeError):
        with lease(tmp_path):
            raise RuntimeError("test")
    with lease(tmp_path):
        pass


def test_cli_demo_exports_utf8_in_workspace_with_spaces(tmp_path):
    folder = tmp_path / "Example workspace"
    folder.mkdir()
    settings = Path("examples/sots-pilot.toml").read_text(encoding="utf-8")
    settings = settings.replace(
        "Society of Teen Scientists", "Société des jeunes scientifiques 科学"
    )
    settings = settings.replace("repetitions = 3", "repetitions = 1")
    config_file = folder / "audit.toml"
    config_file.write_text(settings, encoding="utf-8")
    assert "科学" in load_config(config_file).brand.name
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "brandprobe",
            "--root",
            str(folder),
            "demo",
            "--config",
            "audit.toml",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stderr
    reports = folder / ".brandprobe/reports"
    html = next(reports.glob("*.html")).read_text(encoding="utf-8")
    data = json.loads(next(reports.glob("*.json")).read_text(encoding="utf-8"))
    assert "科学" in html
    assert data["audit"]["status"] == "complete"
    assert data["audit"]["plan"]["mode"] == "demo"
    assert len(data["audit"]["observations"]) == 15


def test_multimodel_walkthrough_is_unambiguous():
    config = load_config(Path("examples/sots-pilot.toml"))
    assert len(config.models) == 3
    assert len(config.prompts) == 5 and config.repetitions == 3
    assert config.evaluator_model == "anthropic/claude-sonnet-5"
    assert config.competitors[0].name == "Lumiere Education"
    assert all(
        config.brand.name in p.text for p in config.prompts if p.kind == "recognition"
    )
    assert sum(p.kind == "discovery" for p in config.prompts) == 3
