"""Read-only diagram audit behavior using independent synthetic image assets."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest


SCRIPT = (Path(__file__).resolve().parents[1] / ".agents/skills/"
          "document-diagram-quality/scripts/audit_picture.py")


@pytest.fixture(scope="module")
def auditor():
    spec = importlib.util.spec_from_file_location("diagram_quality_audit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_image(path, size=(20, 30), *, dpi=(300, 300)):
    Image.new("RGB", size, "#f0f0f0").save(path, dpi=dpi)
    return path.read_bytes()


def test_cli_refuses_report_hardlink_without_changing_source(tmp_path):
    source, report = tmp_path / "source.png", tmp_path / "report.json"
    original = make_image(source)
    try:
        os.link(source, report)
    except OSError as error:
        pytest.skip(f"Hard links unavailable: {error}")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--report", str(report)],
        capture_output=True, text=True,
    )

    assert result.returncode == 2
    assert "different from the input" in result.stderr
    assert source.read_bytes() == report.read_bytes() == original
    with Image.open(source) as image:
        assert image.size == (20, 30)


def test_unknown_mapping_leaves_ppi_and_distortion_unresolved(auditor, tmp_path):
    source = tmp_path / "source.png"
    original = make_image(source)

    result = auditor.audit(source, width_mm=160, height_mm=60)

    assert result["placement"]["mapping"] == "unknown"
    assert result["placement"]["effective_ppi"] is None
    assert result["placement"]["relative_x_to_y_scale"] is None
    assert result["raster"]["stored_pixels"] == [20, 30]
    assert source.read_bytes() == original


def test_contain_reports_actual_image_extent_and_unused_slot(auditor, tmp_path):
    source = tmp_path / "portrait.png"
    original = make_image(source)

    result = auditor.audit(source, width_mm=160, height_mm=60, mapping="contain")

    placed = result["placement"]
    assert placed["mapped_image_mm"] == pytest.approx([40, 60])
    assert placed["relative_x_to_y_scale"] == 1
    assert placed["effective_ppi"] == pytest.approx({"x": 12.7, "y": 12.7})
    assert placed["unused_box_extent_mm"] == pytest.approx(
        {"horizontal_total": 120, "vertical_total": 0}
    )
    assert source.read_bytes() == original


def test_effective_ppi_uses_pixels_and_placement_instead_of_metadata(auditor, tmp_path):
    first, second = tmp_path / "low-dpi.png", tmp_path / "high-dpi.png"
    before = {p: make_image(p, (200, 100), dpi=(dpi, dpi))
              for p, dpi in [(first, 72), (second, 600)]}

    results = [auditor.audit(p, width_mm=50.8, height_mm=25.4, mapping="stretch")
               for p in (first, second)]

    assert (results[0]["raster"]["metadata_dpi_not_effective_ppi"]
            != results[1]["raster"]["metadata_dpi_not_effective_ppi"])
    for path, result in zip((first, second), results):
        assert result["placement"]["effective_ppi"] == pytest.approx({"x": 100, "y": 100})
        assert result["placement"]["relative_x_to_y_scale"] == pytest.approx(1)
        assert path.read_bytes() == before[path]
