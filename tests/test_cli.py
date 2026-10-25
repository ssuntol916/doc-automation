import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_submission_gate_is_enforced_from_another_working_directory(tmp_path):
    report = tmp_path / "quality.json"
    command = [sys.executable, "-m", "doc_automation.cli", "validate-project", str(ROOT/"examples/demo.project.json"), "--report", str(report), "--require-submission-ready"]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2, result.stderr
    data = json.loads(report.read_text())
    assert data["draft_ready"] is True
    assert data["submission_ready"] is False
    assert data["errors"] == []


@pytest.mark.parametrize("value", [None, {"project": None}])
def test_invalid_project_shape_produces_a_report_instead_of_crashing(tmp_path, value):
    source, report = tmp_path/"invalid.json", tmp_path/"report.json"
    source.write_text(json.dumps(value))
    result = subprocess.run([sys.executable, "-m", "doc_automation.cli", "validate-project", str(source), "--report", str(report)], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert json.loads(report.read_text())["errors"]


def test_binary_hwp_is_reported_as_unanalyzed_input(tmp_path):
    source = tmp_path/"source"
    source.mkdir()
    (source/"input.hwp").write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    destination = tmp_path/"analysis"
    result = subprocess.run([sys.executable, "-m", "doc_automation.cli", "analyze", str(source), str(destination), "--kind", "template"], capture_output=True, text=True)
    assert result.returncode == 1
    inventory = json.loads((destination/"inventory.json").read_text())
    assert inventory["documents"] == []
    assert len(inventory["unsupported_inputs"]) == 1
