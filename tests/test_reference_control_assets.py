"""Selected source-picture extraction using tiny authored ZIP/BMP fixtures."""
from hashlib import sha256
import importlib.util
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_reference_quality_controls.py"
SPEC = importlib.util.spec_from_file_location("reference_controls", SCRIPT)
controls = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controls)


@pytest.fixture
def selected_picture(tmp_path, monkeypatch):
    stream = BytesIO()
    Image.new("RGB", (2, 1), (10, 20, 30)).save(stream, format="BMP")
    blob = stream.getvalue()
    original = tmp_path / "read-only-corpus" / "synthetic-reference.hwpx"
    original.parent.mkdir()
    member = "BinData/picture.bmp"
    with ZipFile(original, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr(member, blob)
    source_sha = sha256(original.read_bytes()).hexdigest()
    picture_sha = sha256(blob).hexdigest()
    selection = {
        "source": {"path": str(original), "sha256": source_sha},
        "table_locator": "Contents/section0.xml:synthetic-table",
        "cells": [{"address": {"rowAddr": str(r), "colAddr": str(c)}, "text_verbatim": value}
                  for r, c, value in [(0, 1, "SYNTHETIC-SCREEN"), (0, 3, "합성 화면"),
                                      (1, 1, "검증 > 화면"), (3, 1, "합성 처리순서"), (4, 1, "합성 확인항목")]],
        "figures": [{"binary_sha256": picture_sha, "zip_member": member}],
    }
    catalog = {"document_id": "reference-sf-td3", "sha256": picture_sha,
               "source_sha256": source_sha, "package_path": member,
               "asset_path": "/missing/historical-analysis/picture.bmp"}
    root = tmp_path / "repository"
    assets = root / "resources/stage2/assets-manifest.json"
    assets.parent.mkdir(parents=True)
    monkeypatch.setattr(controls, "ROOT", root)

    def write_catalog(records):
        assets.write_text(json.dumps({"records": records}, ensure_ascii=False))

    write_catalog([catalog])
    return selection, catalog, write_catalog, blob, original, tmp_path / "new-output"


def test_selected_picture_is_extracted_from_exact_source_without_historical_asset_file(selected_picture):
    selection, _, _, blob, original, output = selected_picture
    before = original.read_bytes()
    data = controls.td3(selection, output_dir=output, asset_manifest=controls.ROOT / "resources/stage2/assets-manifest.json")
    assert original.read_bytes() == before
    attachment, = data["attachments"]
    path = Path(attachment["path"])
    assert path.is_relative_to(output / "assets")
    assert path.read_bytes() == blob
    assert attachment["sha256"] == sha256(blob).hexdigest()
    assert data["screens"][0]["after_attachment_ids"] == [attachment["id"]]
    source_copy = Path(data["sources"][0]["path"])
    assert source_copy.read_bytes() == before
    assert data["dataset_kind"] == "reference_extraction" and data["submission_ready"] is False
    assert data["project"]["status"] == "unverified"


@pytest.mark.parametrize("mutation", ["missing_member", "wrong_binary_sha", "wrong_source_sha", "missing_selector", "wrong_member_binding"])
def test_incomplete_or_misbound_picture_selection_cannot_create_an_attachment(selected_picture, mutation):
    selection, catalog, write_catalog, _, original, output = selected_picture
    if mutation == "missing_member":
        selection["figures"][0]["zip_member"] = catalog["package_path"] = "BinData/missing.bmp"
    elif mutation == "wrong_binary_sha":
        selection["figures"][0]["binary_sha256"] = catalog["sha256"] = "0" * 64
    elif mutation == "wrong_source_sha":
        catalog["source_sha256"] = "0" * 64
    elif mutation == "wrong_member_binding":
        selection["figures"][0]["zip_member"] = "BinData/different.bmp"
    write_catalog([] if mutation == "missing_selector" else [catalog])
    before = original.read_bytes()
    with pytest.raises((ValueError, KeyError)):
        controls.td3(selection, output_dir=output, asset_manifest=controls.ROOT / "resources/stage2/assets-manifest.json")
    assert original.read_bytes() == before
    assert not (output / "assets").exists()


def test_reference_picture_requires_explicit_private_catalog(selected_picture):
    selection, _, _, _, original, output = selected_picture
    before = original.read_bytes()
    with pytest.raises(ValueError, match="explicit private"):
        controls.td3(selection, output_dir=output)
    assert original.read_bytes() == before
    assert not (output / "assets").exists()
