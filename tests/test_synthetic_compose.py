"""Portable mechanics fixtures authored here; no source corpus or native export."""
from copy import deepcopy
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from lxml import etree as ET
import pytest

from doc_automation.compose import ComposeError, TemplateDocument, validate_package
from doc_automation.hwpx import NS, inline_text, own_text

FIXTURES = Path(__file__).parent / "fixtures/synthetic"


@pytest.fixture
def synthetic(tmp_path):
    path = tmp_path / "synthetic-source.hwpx"
    with ZipFile(path, "w", compression=ZIP_STORED) as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        for name in ("header.xml", "section0.xml", "content.hpf"):
            archive.writestr("Contents/" + name, (FIXTURES / name).read_bytes())
    assert validate_package(path)["valid"]
    return path, TemplateDocument(path)


def payload(node):
    return ET.tostring(node, method="c14n")


def test_portable_source_roundtrip_keeps_every_package_member(synthetic, tmp_path):
    source, doc = synthetic
    before = source.read_bytes()
    output = tmp_path / "roundtrip.hwpx"
    result = doc.save(output)
    assert result["modified_entries"] == result["removed_entries"] == []
    assert source.read_bytes() == before
    with ZipFile(source) as left, ZipFile(output) as right:
        assert right.infolist()[0].filename == "mimetype"
        assert right.infolist()[0].compress_type == ZIP_STORED
        assert {n: left.read(n) for n in left.namelist()} == {n: right.read(n) for n in right.namelist()}


def test_parent_owned_text_edit_keeps_nested_table_and_scope_control(synthetic, tmp_path):
    _, doc = synthetic
    table = doc.tables()[0]
    before = payload(table)
    control = payload(doc.root().find(".//hp:secPr", NS))
    parent = table.getparent().getparent()
    doc.set_paragraph_text(parent, "새 부모\n둘째 줄")
    assert own_text(parent) == "새 부모\n둘째 줄"
    assert payload(table) == before
    assert payload(doc.root().find(".//hp:secPr", NS)) == control
    assert [own_text(p) for p in table.findall(".//hp:p", NS)] == ["왼쪽\n꼬리", "오른쪽"]
    output = tmp_path / "parent.hwpx"
    assert doc.save(output)["package_validation"]["valid"]


def test_cell_inline_edit_keeps_geometry_and_character_properties(synthetic, tmp_path):
    _, doc = synthetic
    cell = doc.cell(doc.tables()[0], 0, 0)
    geometry = [payload(cell.find("hp:" + name, NS)) for name in ("cellAddr", "cellSpan", "cellSz")]
    header = payload(doc.xml("Contents/header.xml"))
    run = cell.find(".//hp:run", NS)
    doc.set_text_node(run.find("hp:t", NS), "새 값\n꼬리\t탭 뒤")
    assert inline_text(run.find("hp:t", NS)) == "새 값\n꼬리\t탭 뒤"
    assert run.get("charPrIDRef") == "1"
    assert geometry == [payload(cell.find("hp:" + name, NS)) for name in ("cellAddr", "cellSpan", "cellSz")]
    assert payload(doc.xml("Contents/header.xml")) == header
    assert doc.save(tmp_path / "cell.hwpx")["package_validation"]["valid"]


def test_table_font_derivation_preserves_bold_size_text_and_original_definitions(synthetic, tmp_path):
    _, doc = synthetic
    table = doc.tables()[0]
    definitions = {p.get("id"): deepcopy(p) for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
    before = [(r, inline_text(r.find("hp:t", NS)), deepcopy(definitions[r.get("charPrIDRef")]))
              for r in table.findall(".//hp:run", NS)]
    doc.use_character_style(table, font="맑은 고딕")
    current = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
    faces = {f.get("lang").lower(): {n.get("id"): n.get("face") for n in f}
             for f in doc.xml("Contents/header.xml").findall(".//hh:fontface", NS)}
    for run, text, old in before:
        new = deepcopy(current[run.get("charPrIDRef")])
        assert inline_text(run.find("hp:t", NS)) == text
        assert all(faces[k][v] == "맑은 고딕" for k, v in new.find("hh:fontRef", NS).attrib.items())
        for definition in (old, new):
            definition.attrib.pop("id")
            definition.remove(definition.find("hh:fontRef", NS))
        assert payload(old) == payload(new)
    assert all(payload(current[k]) == payload(value) for k, value in definitions.items())
    assert doc.save(tmp_path / "font.hwpx")["package_validation"]["valid"]


def test_wrong_source_hash_and_source_overwrite_are_refused(synthetic):
    path, doc = synthetic
    before = path.read_bytes()
    with pytest.raises(ComposeError):
        TemplateDocument(path, expected_sha256="0" * 64)
    with pytest.raises(ComposeError):
        doc.save(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("mutation", ["unresolved_style", "overlapping_cell"])
def test_invalid_current_structure_cannot_replace_existing_output(synthetic, tmp_path, mutation):
    _, doc = synthetic
    if mutation == "unresolved_style":
        doc.root().find("hp:p", NS).set("paraPrIDRef", "missing")
    else:
        doc.cell(doc.tables()[0], 0, 1).find("hp:cellAddr", NS).set("colAddr", "0")
    output = tmp_path / "existing.hwpx"
    output.write_bytes(b"keep the existing artifact")
    with pytest.raises(ComposeError):
        doc.save(output)
    assert output.read_bytes() == b"keep the existing artifact"
