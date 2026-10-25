"""Mechanics integration against the fingerprinted corpus; no native-layout claims."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from lxml import etree as ET
from corpus_sources import pinned_source_path
import pytest

from doc_automation.compose import ComposeError, HP, TemplateDocument, validate_package
from doc_automation.hwpx import NS, local, own_text, inline_text

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = json.loads((ROOT / "resources/stage1/inventory.json").read_text())["documents"]
DEVELOPMENT = [item for item in INVENTORY if item["id"].startswith("template-sf-")]


def source(code):
    item = next(item for item in INVENTORY if item["id"] == "template-" + code.lower())
    path = pinned_source_path(item)
    if not path.exists():
        pytest.fail("Selected corpus test requires the read-only source corpus: " + str(path))
    return path


def document(code="SF-AD2"):
    return TemplateDocument(source(code))


def editorial_spec(doc, role):
    profile = json.loads((ROOT / f"resources/style-upgrade/profiles/{role}.json").read_text())
    if profile["targets"].get("cover_roles"):
        # Direct compose tests have no domain renderer. Register the exact
        # source owners the renderer is required to retain across substitutions.
        doc._editorial_cover_paragraphs = {key: doc.xml(value["template"]["xml"]).xpath(
            value["template"]["xpath"], namespaces=NS)[0] for key, value in profile["cover_selectors"].items()}
    if profile["targets"].get("toc_roles"):
        doc._editorial_toc_paragraphs = {key: doc.xml(value["template"]["xml"]).xpath(
            value["template"]["xpath"], namespaces=NS)[0] for key, value in profile["toc_selectors"].items()}
    if profile.get("body_section_start"):
        # Direct compose fixtures explicitly register the same exact source
        # boundary as the domain renderer. The runtime must still reject a
        # missing registry/notice; the cover assertions below are unchanged.
        start = profile["body_section_start"]
        doc._editorial_body_start_paragraph = doc.xml(start["xml"]).xpath(start["xpath"], namespaces=NS)[0]
        carrier = start["first_table_carrier"]
        anchor = doc.xml(carrier["xml"]).xpath(carrier["xpath"], namespaces=NS)[0]
        notice = doc.new_paragraph("검토용 초안·표지 보존 기계검사(사업 수행 증거 아님)",
                                   prototype=anchor.find(".//hp:tc/hp:subList/hp:p", NS))
        anchor.addprevious(notice)
        doc._editorial_body_paragraphs = {notice}
    return profile


def xml(node):
    return ET.tostring(node)


def entries(path):
    with ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.mark.parametrize("item", INVENTORY, ids=lambda x: x["id"])
@pytest.mark.corpus
def test_all_21_profile_roundtrips_preserve_each_member_byte(item, tmp_path):
    path = pinned_source_path(item)
    if not path.exists():
        pytest.fail("Selected corpus test requires the read-only source corpus: " + str(path))
    before = path.read_bytes()
    doc = TemplateDocument(path, expected_sha256=item["sha256"])
    report = doc.save(tmp_path / (item["id"] + ".hwpx"))
    assert doc.source_profile_id == item["id"]
    assert report["modified_entries"] == report["removed_entries"] == []
    assert report["package_validation"]["valid"] and report["source_unchanged"]
    assert not report["native_verified"]
    assert entries(path) == entries(report["output_path"])
    assert path.read_bytes() == before
    with ZipFile(report["output_path"]) as archive:
        assert archive.infolist()[0].filename == "mimetype"
        assert archive.infolist()[0].compress_type == ZIP_STORED


@pytest.mark.parametrize("item", DEVELOPMENT, ids=lambda x: x["id"])
@pytest.mark.corpus
def test_all_19_plain_text_edits_preserve_header_and_table_geometry(item, tmp_path):
    path = pinned_source_path(item)
    if not path.exists():
        pytest.fail("Selected corpus test requires the read-only source corpus: " + str(path))
    doc = TemplateDocument(path)
    header = xml(doc.xml("Contents/header.xml"))
    geometry = [[dict(table.attrib), [xml(child) for child in table if local(child) != "tr"]]
                for section in range(len(doc.sections)) for table in doc.tables(section)]
    p = next(p for p in doc.paragraphs(-1) if own_text(p) and not any(
        local(child) in {"fieldBegin", "fieldEnd"} for child in p.iter()))
    doc.set_paragraph_text(p, "검증용 합성 자료(제출용 아님)\n긴 내용\t이어지는 값")
    report = doc.save(tmp_path / (item["id"] + ".hwpx"))
    assert xml(doc.xml("Contents/header.xml")) == header
    assert [[dict(table.attrib), [xml(child) for child in table if local(child) != "tr"]]
            for section in range(len(doc.sections)) for table in doc.tables(section)] == geometry
    assert own_text(p) == "검증용 합성 자료(제출용 아님)\n긴 내용\t이어지는 값"
    assert report["package_validation"]["valid"]
    assert report["removed_entries"] == ["Preview/PrvImage.png"]
    output = entries(report["output_path"])
    assert "검증용 합성 자료(제출용 아님)" in output["Preview/PrvText.txt"].decode()


@pytest.mark.corpus
def test_own_paragraph_replacement_keeps_section_controls_and_nested_table():
    doc = document()
    p = doc.root(1)[0]
    table = next(p.iter(HP + "tbl"))
    before_table = xml(table)
    before_controls = [xml(child) for child in p.iter() if local(child) in {"secPr", "colPr", "pageNum", "newNum"}]
    doc.set_paragraph_text(p, "검증용 제목")
    assert own_text(p) == "검증용 제목"
    assert xml(table) == before_table
    assert [xml(child) for child in p.iter() if local(child) in {"secPr", "colPr", "pageNum", "newNum"}] == before_controls


@pytest.mark.corpus
def test_multiline_inline_tails_and_character_run_properties_survive():
    doc = document()
    p = next(p for p in doc.paragraphs(1) if own_text(p) == "시스템명")
    attrs = [dict(run.attrib) for run in p.findall("hp:run", NS)]
    doc.set_paragraph_text(p, "첫째\n둘째\t셋째\u3000넷째\u00a0다섯째")
    assert own_text(p) == "첫째\n둘째\t셋째\u3000넷째\u00a0다섯째"
    assert [dict(run.attrib) for run in p.findall("hp:run", NS)] == attrs
    assert p.find("hp:run/hp:t/hp:tab", NS).get("width") == "0"


@pytest.mark.corpus
def test_text_colour_adds_local_definition_without_mutating_source_styles(tmp_path):
    doc = document()
    definitions = doc.xml("Contents/header.xml").find(".//hh:charProperties", NS)
    original = {node.get("id"): xml(node) for node in definitions}
    p = next(p for p in doc.paragraphs(1) if any(
        doc.xml("Contents/header.xml").xpath(
            ".//hh:charPr[@id=$identifier]/@textColor", namespaces=NS,
            identifier=run.get("charPrIDRef"))[0] != "#000000"
        for run in p.findall("hp:run", NS)) and own_text(p))
    doc.set_paragraph_text(p, "검증용 입력 본문")
    changed = doc.blacken_text_runs(p)
    assert changed > 0
    assert {node.get("id"): xml(node) for node in definitions if node.get("id") in original} == original
    assert int(definitions.get("itemCnt")) == len(definitions)
    def style_payload(node):
        copy = deepcopy(node)
        copy.attrib.pop("id", None)
        copy.attrib.pop("textColor", None)
        return ET.tostring(copy, method="c14n", exclusive=True)
    original_payloads = {style_payload(ET.fromstring(before)) for before in original.values()}
    for run in p.findall("hp:run", NS):
        if any(t.text for t in run.findall("hp:t", NS)):
            current = next(node for node in definitions if node.get("id") == run.get("charPrIDRef"))
            assert current.get("textColor") == "#000000"
            assert style_payload(current) in original_payloads
    count = len(definitions)
    assert doc.blacken_text_runs(p) == 0 and len(definitions) == count
    assert doc.save(tmp_path / "black-input.hwpx")["package_validation"]["valid"]


@pytest.mark.corpus
def test_duplicate_local_character_definition_is_rejected(tmp_path):
    doc = document()
    definitions = doc.xml("Contents/header.xml").find(".//hh:charProperties", NS)
    definitions.append(deepcopy(definitions[0]))
    with pytest.raises(ComposeError, match="Duplicate local charPr"):
        doc.save(tmp_path / "duplicate-style.hwpx")


@pytest.mark.corpus
def test_cell_text_keeps_geometry_and_clears_only_plain_paragraphs():
    doc = document()
    cell = doc.cell(doc.tables(1)[0], 3, 1)
    properties = [xml(child) for child in cell if local(child) != "subList"]
    sublist = cell.find("hp:subList", NS)
    sublist.append(doc.new_paragraph("旧第二段", prototype=sublist[0]))
    doc.set_cell_text(cell, "구체 요건\n제약과 조건")
    assert [xml(child) for child in cell if local(child) != "subList"] == properties
    assert len(sublist.findall("hp:p", NS)) == 1
    assert own_text(sublist[0]) == "구체 요건\n제약과 조건"


@pytest.mark.corpus
def test_cell_edit_refuses_semantic_object_without_mutation():
    doc = document("SF-PM4")
    cell = doc.cell(doc.tables()[1], 1, 0)
    run = next(cell.iter(HP + "run"))
    ET.SubElement(run, HP + "equation", id="123456")
    before = xml(cell)
    with pytest.raises(ComposeError, match="semantic objects"):
        doc.set_cell_text(cell, "지우면 안 됨")
    assert xml(cell) == before


@pytest.mark.corpus
def test_merged_coordinates_require_explicit_covered_lookup():
    doc = document()
    table = doc.tables(1)[0]
    with pytest.raises(ComposeError, match="covered=True"):
        doc.cell(table, 3, 3)
    assert doc.cell(table, 3, 3, covered=True) is doc.cell(table, 3, 1)


@pytest.mark.corpus
def test_clone_card_preserves_original_scope_but_does_not_repeat_it(tmp_path):
    doc = document()
    p = doc.root(1)[0]
    original_controls = [xml(node) for node in p.iter() if local(node) in {"secPr", "colPr", "pageNum", "newNum"}]
    clone = doc.clone_paragraph(p, insert_after=True)
    assert not any(local(node) in {"secPr", "colPr", "pageNum", "newNum"} for node in clone.iter())
    assert not any(not len(node) for node in clone.iter(HP + "ctrl"))
    assert [xml(node) for node in p.iter() if local(node) in {"secPr", "colPr", "pageNum", "newNum"}] == original_controls
    clone_ids = [node.get("id") for node in clone.iter() if node.get("id")]
    assert len(clone_ids) == len(set(clone_ids))
    original_ids = {node.get("id") for section in doc.sections for node in doc.xml(section).iter()
                    if node not in set(clone.iter()) and node.get("id")}
    assert not set(clone_ids) & original_ids
    assert doc.save(tmp_path / "cloned.hwpx")["package_validation"]["valid"]


@pytest.mark.corpus
def test_clone_fields_remaps_both_begin_reference_and_fieldid(tmp_path):
    doc = TemplateDocument(source("forms-2025"))
    field = next(doc.root(1).iter(HP + "fieldBegin"))
    p = next(ancestor for ancestor in field.iterancestors() if ancestor.tag == HP + "p")
    clone = doc.clone_paragraph(p, insert_after=True)
    original_begin = p.find(".//hp:fieldBegin", NS)
    begin, end = clone.find(".//hp:fieldBegin", NS), clone.find(".//hp:fieldEnd", NS)
    assert begin.get("id") != original_begin.get("id")
    assert begin.get("fieldid") != original_begin.get("fieldid")
    assert end.get("beginIDRef") == begin.get("id") and end.get("fieldid") == begin.get("fieldid")
    assert doc.save(tmp_path / "paired.hwpx")["package_validation"]["valid"]
    with pytest.raises(ComposeError, match="field result"):
        doc.set_paragraph_text(p, "수식 손실 금지")
    with pytest.raises(ComposeError, match="splits a field"):
        doc._clone(begin)


@pytest.mark.corpus
def test_repeat_feature_rows_removes_sample_vertical_merge_groups(tmp_path):
    doc = document("SF-AD3")
    table = doc.tables()[1]
    prototype = table.findall("hp:tr", NS)[8]
    widths = [cell.find("hp:cellSz", NS).get("width") for cell in prototype]
    rows = doc.replace_body_rows(table, prototype_row_index=8, rows_count=17, header_rows=1)
    doc.repeat_header_rows(table)
    assert table.get("rowCnt") == "18"
    for index, row in enumerate(rows, 1):
        assert [cell.find("hp:cellSz", NS).get("width") for cell in row] == widths
        assert all(cell.find("hp:cellAddr", NS).get("rowAddr") == str(index) for cell in row)
        assert all(cell.find("hp:cellSpan", NS).get("rowSpan") == "1" for cell in row)
    assert all(cell.get("header") == "1" for cell in table.findall("hp:tr", NS)[0])
    assert doc.save(tmp_path / "features.hwpx")["package_validation"]["valid"]


@pytest.mark.corpus
def test_repeat_integration_cases_retains_horizontal_merges(tmp_path):
    doc = document("SF-TI1")
    table = doc.tables(1)[0]
    prefix = [xml(row) for row in table.findall("hp:tr", NS)[:4]]
    rows = doc.replace_body_rows(table, 4, 9, header_rows=4)
    assert [xml(row) for row in table.findall("hp:tr", NS)[:4]] == prefix
    assert table.get("rowCnt") == "13"
    assert [cell.find("hp:cellSpan", NS).get("colSpan") for cell in rows[0]] == ["2", "1", "2", "2"]
    assert doc.save(tmp_path / "integration.hwpx")["package_validation"]["valid"]


@pytest.mark.corpus
def test_zero_body_rows_does_not_fabricate_one_case():
    doc = document("SF-CD1")
    table = doc.tables(1)[0]
    assert doc.replace_body_rows(table, 1, 0) == []
    assert table.get("rowCnt") == "1" and doc.validate()["valid"]


@pytest.mark.corpus
def test_vertical_merge_boundary_rejection_is_non_destructive():
    doc = document("SF-AD3")
    table = doc.tables()[1]
    before = xml(table)
    with pytest.raises(ComposeError, match="vertical merged"):
        doc.replace_body_rows(table, 1, 3)
    with pytest.raises(ComposeError, match="boundary"):
        doc.replace_body_rows(table, 8, 3, header_rows=2)
    assert xml(table) == before


@pytest.mark.corpus
def test_raw_root_edit_invalidates_only_changed_paragraph_caches(tmp_path):
    doc = document()
    table = doc.tables(1)[0]
    changed = next(doc.cell(table, 0, 0).iter(HP + "p"))
    untouched = next(doc.cell(table, 0, 2).iter(HP + "p"))
    before = xml(untouched)
    assert changed.find("hp:linesegarray", NS) is not None
    changed.find("hp:run/hp:t", NS).text = "직접 변경"
    doc.save(tmp_path / "raw-edit.hwpx")
    assert changed.find("hp:linesegarray", NS) is None
    assert xml(untouched) == before


@pytest.mark.corpus
def test_image_resource_manifest_and_geometry_survive(tmp_path):
    doc = document("SF-PM4")
    picture = next(doc.root().iter(HP + "pic"))
    before = [xml(node) for node in picture if local(node) != "img"]
    raw = entries(source("SF-PM4"))["BinData/image1.png"]
    binary_id = doc.set_picture_image(picture, raw, "image/png", "png")
    assert [xml(node) for node in picture if local(node) != "img"] == before
    report = doc.save(tmp_path / "image.hwpx")
    output = entries(report["output_path"])
    assert output[f"BinData/{binary_id}.png"] == raw
    assert report["package_validation"]["valid"]


@pytest.mark.corpus
def test_stale_preview_declarations_are_removed_together(tmp_path):
    source_entries = entries(source("SF-AD2"))
    package = ET.fromstring(source_entries["Contents/content.hpf"])
    manifest = package.find("opf:manifest", NS)
    ET.SubElement(manifest, "{" + NS["opf"] + "}item", id="preview-image",
                  href="Preview/PrvImage.png", attrib={"media-type": "image/png"})
    source_entries["Contents/content.hpf"] = ET.tostring(package, encoding="UTF-8", xml_declaration=True)
    container = ET.fromstring(source_entries["META-INF/container.xml"])
    rootfiles = container[0]
    ET.SubElement(rootfiles, rootfiles[0].tag, attrib={"full-path": "Preview/PrvImage.png", "media-type": "image/png"})
    source_entries["META-INF/container.xml"] = ET.tostring(container, encoding="UTF-8", xml_declaration=True)
    copy = tmp_path / "preview-declared.hwpx"
    with ZipFile(copy, "w") as archive:
        for name, data in source_entries.items():
            archive.writestr(name, data)
    doc = TemplateDocument(copy)
    p = next(p for p in doc.paragraphs(1) if own_text(p) == "시스템명")
    doc.set_paragraph_text(p, "검증명칭")
    report = doc.save(tmp_path / "preview-clean.hwpx")
    result = entries(report["output_path"])
    assert "Preview/PrvImage.png" not in result
    assert b"Preview/PrvImage.png" not in result["Contents/content.hpf"]
    assert b"Preview/PrvImage.png" not in result["META-INF/container.xml"]


@pytest.mark.corpus
def test_preview_shared_as_body_image_requires_explicit_resolution():
    doc = document("SF-PM4")
    manifest = doc.xml("Contents/content.hpf").find("opf:manifest", NS)
    ET.SubElement(manifest, "{" + NS["opf"] + "}item", id="preview-image",
                  href="Preview/PrvImage.png", attrib={"media-type": "image/png"})
    picture = next(doc.root().iter(HP + "pic"))
    next(picture.iter("{" + NS["hc"] + "}img")).set("binaryItemIDRef", "preview-image")
    with pytest.raises(ComposeError, match="also document content"):
        doc.validate()


@pytest.mark.corpus
def test_metadata_clear_removes_legacy_subject_and_author():
    doc = document()
    doc.set_metadata(title="검증용 요구사항정의서", clear_legacy=True)
    package = ET.tostring(doc.xml("Contents/content.hpf"), encoding="unicode")
    assert "유스케이스다이어그램" not in package
    assert "클라우드컴퓨팅" not in package
    assert "검증용 요구사항정의서" in package


@pytest.mark.corpus
def test_new_duplicate_instance_or_dangling_style_cannot_replace_output(tmp_path):
    doc = document()
    doc.root(1).append(deepcopy(doc.root(1)[0]))
    destination = tmp_path / "keep.hwpx"
    destination.write_bytes(b"untouched existing output")
    with pytest.raises(ComposeError, match="duplicate"):
        doc.save(destination)
    assert destination.read_bytes() == b"untouched existing output"
    assert not list(tmp_path.glob(".*.tmp"))
    doc = document()
    next(doc.root().iter(HP + "run")).set("charPrIDRef", "9999999999")
    with pytest.raises(ComposeError, match="Unresolved charPrIDRef"):
        doc.save(destination)
    assert destination.read_bytes() == b"untouched existing output"


@pytest.mark.corpus
def test_source_overwrite_hardlinks_and_source_tree_are_refused(tmp_path):
    doc = document()
    with pytest.raises(ComposeError, match="source template"):
        doc.save(doc.template_path)
    hardlink = tmp_path / "hardlink.hwpx"
    hardlink.hardlink_to(doc.template_path)
    with pytest.raises(ComposeError, match="source template"):
        doc.save(hardlink)
    with pytest.raises(ComposeError, match="read-only"):
        doc.save(tmp_path / "_references" / "output.hwpx")


@pytest.mark.corpus
def test_fingerprint_and_concurrent_source_change_are_detected(tmp_path):
    with pytest.raises(ComposeError, match="fingerprint"):
        TemplateDocument(source("SF-AD2"), expected_sha256="0" * 64)
    copy = tmp_path / "local.hwpx"
    copy.write_bytes(source("SF-AD2").read_bytes())
    doc = TemplateDocument(copy)
    copy.write_bytes(copy.read_bytes() + b"changed")
    with pytest.raises(ComposeError, match="changed during"):
        doc.save(tmp_path / "output.hwpx")


@pytest.mark.corpus
def test_source_page_controls_cannot_be_removed_implicitly():
    doc = document()
    with pytest.raises(ComposeError, match="section/page/header"):
        doc.remove(doc.root(1)[0])


@pytest.mark.corpus
def test_notice_cannot_precede_the_section_properties_carrier(tmp_path):
    doc = document()
    notice = doc.new_paragraph("검증용 합성 자료(제출용 아님)")
    doc.root(1).insert(0, notice)
    with pytest.raises(ComposeError, match="secPr must remain"):
        doc.save(tmp_path / "invalid-order.hwpx")
    doc.root(1).remove(notice)
    doc.root(1)[0].addnext(notice)
    assert doc.save(tmp_path / "valid-order.hwpx")["package_validation"]["valid"]


@pytest.mark.corpus
def test_empty_control_wrapper_is_rejected(tmp_path):
    doc = document()
    ET.SubElement(next(doc.root(1).iter(HP + "run")), HP + "ctrl")
    with pytest.raises(ComposeError, match="Empty hp:ctrl"):
        doc.save(tmp_path / "empty-control.hwpx")


@pytest.mark.corpus
def test_invalid_text_type_or_xml_characters_are_not_silently_inserted():
    doc = document()
    p = next(p for p in doc.paragraphs(1) if own_text(p) == "시스템명")
    before = xml(p)
    with pytest.raises(TypeError):
        doc.set_paragraph_text(p, None)
    with pytest.raises(ComposeError, match="XML 1.0"):
        doc.set_paragraph_text(p, "금지\x00문자")
    assert xml(p) == before


def test_bad_zip_is_a_validation_failure(tmp_path):
    path = tmp_path / "bad.hwpx"
    path.write_bytes(b"not a zip")
    assert not validate_package(path)["valid"]


@pytest.mark.corpus
def test_paragraph_keep_derivation_preserves_source_spacing_and_other_break_flags(tmp_path):
    doc = document("SF-AD1")
    table = doc.tables(1)[0]
    prototype = doc.cell(table, 0, 0).find("hp:subList/hp:p", NS)
    body = doc.new_paragraph("짧은 본문 문단", prototype=prototype)
    properties = doc.xml("Contents/header.xml").find(".//hh:paraProperties", NS)
    original = {p.get("id"): xml(p) for p in properties}
    old_id = body.get("paraPrIDRef")
    source_definition = next(p for p in properties if p.get("id") == old_id)
    old_break = source_definition.find("hh:breakSetting", NS)
    assert old_break.get("keepLines") == old_break.get("keepWithNext") == "0"
    table_geometry = [xml(c) for c in table if local(c) != "tr"]
    doc.use_paragraph_keep(body, keep_lines=True)
    derived = next(p for p in properties if p.get("id") == body.get("paraPrIDRef"))
    expected = deepcopy(source_definition)
    expected.set("id", derived.get("id"))
    expected.find("hh:breakSetting", NS).set("keepLines", "1")
    def payload(node):
        return node.tag, dict(node.attrib), node.text, node.tail, [payload(child) for child in node]
    assert payload(derived) == payload(expected)
    assert derived.find("hh:breakSetting", NS).get("keepWithNext") == "0"
    assert all(xml(next(p for p in properties if p.get("id") == identifier)) == value for identifier, value in original.items())
    assert [xml(c) for c in table if local(c) != "tr"] == table_geometry
    doc.cell(table, 0, 0).find("hp:subList", NS).append(body)
    assert doc.save(tmp_path / "paragraph-keep.hwpx")["package_validation"]["valid"]


@pytest.mark.corpus
def test_paragraph_keep_is_explicit_deduplicated_and_preserves_unspecified_values():
    doc = document("SF-AD1")
    prototype = doc.cell(doc.tables(1)[0], 0, 0).find("hp:subList/hp:p", NS)
    properties = doc.xml("Contents/header.xml").find(".//hh:paraProperties", NS)
    first, second = (doc.new_paragraph(text, prototype=prototype) for text in ("첫 본문", "둘째 본문"))
    size = len(properties)
    doc.use_paragraph_keep(first, keep_lines=True)
    doc.use_paragraph_keep(second, keep_lines=True)
    doc.use_paragraph_keep(first, keep_lines=True)
    assert len(properties) == size + 1
    assert first.get("paraPrIDRef") == second.get("paraPrIDRef")
    heading = doc.new_paragraph("제목", prototype=prototype)
    doc.use_paragraph_keep(heading, keep_with_next=True)
    inherited = doc.new_paragraph("명시적으로 해당 제목 서식을 상속한 문단", prototype=heading)
    doc.use_paragraph_keep(inherited, keep_lines=True)
    definition = next(p for p in properties if p.get("id") == inherited.get("paraPrIDRef"))
    assert definition.find("hh:breakSetting", NS).get("keepWithNext") == "1"
    assert definition.find("hh:breakSetting", NS).get("keepLines") == "1"
    before = xml(properties)
    with pytest.raises(ComposeError, match="bool or None"):
        doc.use_paragraph_keep(second, keep_lines="1")
    assert xml(properties) == before


@pytest.mark.corpus
def test_table_pagination_changes_only_explicit_flow_flags(tmp_path):
    doc = document("SF-TD3")
    table = doc.tables()[1]
    source = deepcopy(table)
    header = xml(doc.xml("Contents/header.xml"))
    assert table.get("pageBreak") == "NONE"
    assert table.find("hp:pos", NS).get("treatAsChar") == "0"
    doc.use_table_pagination(table, break_mode="CELL", inline=True)
    source.set("pageBreak", "CELL")
    source.find("hp:pos", NS).set("treatAsChar", "1")
    def payload(node):
        return node.tag, dict(node.attrib), node.text, node.tail, [payload(child) for child in node]
    assert payload(table) == payload(source)
    assert xml(doc.xml("Contents/header.xml")) == header
    assert doc.save(tmp_path / "flowing-card.hwpx")["package_validation"]["valid"]
    before = xml(table)
    with pytest.raises(ComposeError, match="page break mode"):
        doc.use_table_pagination(table, break_mode="AUTO")
    with pytest.raises(ComposeError, match="bool or None"):
        doc.use_table_pagination(table, inline="1")
    assert xml(table) == before


@pytest.mark.corpus
def test_page_numbering_move_preserves_text_geometry_and_section_controls(tmp_path):
    doc = document("SF-OS1")
    root = doc.root()
    sources = [p for p in root if p.findall("./hp:run/hp:ctrl/hp:newNum[@numType='PAGE']", NS)]
    assert len(sources) == 2
    target = next(p for p in root if doc.tables()[1] in p.iter())
    assert target.get("pageBreak") == "1"
    own_before = {p: own_text(p) for p in root}
    section_before = xml(root.find(".//hp:secPr", NS))
    table_before = xml(doc.tables()[1])
    page_before = dict(sources[-1].find("./hp:run/hp:ctrl/hp:pageNum", NS).attrib)
    assert doc.move_page_numbering(sources, target) == {"moved_pairs": 1, "consolidated_duplicate_pairs": 1}
    assert all(own_text(p) == text for p, text in own_before.items())
    assert xml(root.find(".//hp:secPr", NS)) == section_before
    assert xml(doc.tables()[1]) == table_before
    assert len(root.findall(".//hp:newNum[@numType='PAGE']", NS)) == 1
    assert dict(target.find("./hp:run/hp:ctrl/hp:pageNum", NS).attrib) == page_before
    assert all(not p.findall("./hp:run/hp:ctrl/hp:newNum", NS) for p in sources)
    assert doc.save(tmp_path / "body-numbering.hwpx")["package_validation"]["valid"]


@pytest.mark.corpus
def test_conflicting_page_numbering_is_rejected_before_mutation():
    doc = document("SF-OS1")
    root = doc.root()
    sources = [p for p in root if p.findall("./hp:run/hp:ctrl/hp:newNum[@numType='PAGE']", NS)]
    target = next(p for p in root if doc.tables()[1] in p.iter())
    sources[0].find("./hp:run/hp:ctrl/hp:newNum", NS).set("num", "5")
    before = xml(root)
    with pytest.raises(ComposeError, match="Conflicting"):
        doc.move_page_numbering(sources, target)
    assert xml(root) == before


@pytest.mark.corpus
def test_editorial_character_style_preserves_definitions_inline_tails_and_nested_ownership(tmp_path):
    doc = document("SF-AD3")
    paragraph = next(p for p in doc.root() if own_text(p).startswith("1. 000"))
    table = next(paragraph.iter(HP + "tbl"))
    nested_before = xml(table)
    doc.set_paragraph_text(paragraph, "대상\n제목\t값")
    old_definitions = {p.get("id"): xml(p) for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
    assert doc.use_character_style(paragraph, font="함초롬바탕", size_pt=11, bold=True, spacing_percent=0, ratio_percent=100) > 0
    assert own_text(paragraph) == "대상\n제목\t값"
    assert xml(table) == nested_before
    definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
    assert all(xml(definitions[key]) == payload for key, payload in old_definitions.items())
    run = next(r for r in paragraph.findall("hp:run", NS) if r.findall("hp:t", NS))
    style = definitions[run.get("charPrIDRef")]
    assert style.get("height") == "1100" and style.find("hh:bold", NS) is not None
    assert set(style.find("hh:spacing", NS).attrib.values()) == {"0"}
    assert set(style.find("hh:ratio", NS).attrib.values()) == {"100"}
    for script, identifier in style.find("hh:fontRef", NS).attrib.items():
        family = doc.xml("Contents/header.xml").find(f".//hh:fontface[@lang='{script.upper()}']", NS)
        assert next(f for f in family if f.get("id") == identifier).get("face") == "함초롬바탕"
    definition_count = len(definitions)
    assert doc.use_character_style(paragraph, font="함초롬바탕", size_pt=11, bold=True, spacing_percent=0, ratio_percent=100) == 0
    assert len(doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)) == definition_count
    assert doc.save(tmp_path / "editorial-char.hwpx")["package_validation"]["valid"]


@pytest.mark.corpus
def test_editorial_paragraph_style_updates_both_branches_without_touching_nested_cells(tmp_path):
    doc = document("SF-AD3")
    paragraph = next(p for p in doc.root() if own_text(p).startswith("1. 000"))
    table = next(paragraph.iter(HP + "tbl"))
    before_table = xml(table)
    source_properties = {p.get("id"): xml(p) for p in doc.xml("Contents/header.xml").findall(".//hh:paraPr", NS)}
    assert doc.use_paragraph_style(paragraph, line_spacing_percent=135, align="LEFT", break_non_latin="KEEP_WORD", keep_with_next=True) == 1
    assert xml(table) == before_table
    properties = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:paraPr", NS)}
    current = properties[paragraph.get("paraPrIDRef")]
    assert all(p.get("value") == "135" and p.get("type") == "PERCENT" for p in current.findall(".//hh:lineSpacing", NS))
    assert current.find("hh:breakSetting", NS).get("keepWithNext") == "1"
    assert all(xml(properties[key]) == value for key, value in source_properties.items())
    assert doc.save(tmp_path / "editorial-para.hwpx")["package_validation"]["valid"]


@pytest.mark.corpus
def test_new_landscape_section_roundtrips_preserving_cover_geometry_and_body_objects(tmp_path):
    doc = document("SF-TD5")
    table = doc.tables()[1]
    paragraph = next(p for p in doc.root() if table in p.iter())
    original_page = xml(doc.root().find(".//hp:pagePr", NS))
    def semantic_payload(node):
        copy = deepcopy(node)
        for cache in copy.findall(".//hp:linesegarray", NS):
            cache.getparent().remove(cache)
        return ET.tostring(copy, method="c14n", exclusive=True)
    original_table = semantic_payload(table)
    original_texts = [own_text(p) for p in doc.paragraphs() if own_text(p)]
    new_index = doc.split_section(paragraph, landscape=True, margins_mm={"left": 15, "right": 15, "top": 12, "bottom": 12})
    assert new_index == 1
    assert doc.root(1)[0] is paragraph  # No extra native blank line before the table.
    assert xml(doc.root().find(".//hp:pagePr", NS)) == original_page
    assert semantic_payload(table) == original_table
    assert [own_text(p) for s in range(len(doc.sections)) for p in doc.paragraphs(s) if own_text(p)] == original_texts
    assert doc.root(1).find("hp:p/hp:run/hp:secPr/hp:pagePr", NS).get("landscape") == "NARROWLY"
    assert table in doc.root(1).iter() and paragraph.get("pageBreak") == "0"
    path = tmp_path / "landscape.hwpx"
    doc.save(path)
    reopened = TemplateDocument(path)
    assert len(reopened.sections) == 2 and reopened.validate()["valid"]
    assert reopened.xml("Contents/header.xml").get("secCnt") == "2"
    assert xml(reopened.root().find(".//hp:pagePr", NS)) == original_page


@pytest.mark.corpus
def test_logical_table_widths_resize_merged_cells_without_losing_content(tmp_path):
    doc = document("SF-AD2")
    table = doc.tables(1)[0]
    before_text = [own_text(p) for p in table.iter(HP + "p")]
    before_ids = [dict(n.attrib) for n in table.iter() if local(n) in {"cellAddr", "cellSpan"}]
    widths = [6000, 15000, 6000, 15000]
    doc.set_table_layout(table, column_widths_hwp=widths, cell_margins_mm={"left": 1, "right": 1, "top": 0.7, "bottom": 0.7})
    assert int(table.find("hp:sz", NS).get("width")) == sum(widths)
    for cell in table.findall("hp:tr/hp:tc", NS):
        start = int(cell.find("hp:cellAddr", NS).get("colAddr"))
        count = int(cell.find("hp:cellSpan", NS).get("colSpan"))
        assert int(cell.find("hp:cellSz", NS).get("width")) == sum(widths[start:start + count])
        assert cell.get("hasMargin") == "1"
    assert [own_text(p) for p in table.iter(HP + "p")] == before_text
    assert [dict(n.attrib) for n in table.iter() if local(n) in {"cellAddr", "cellSpan"}] == before_ids
    assert doc.save(tmp_path / "table-width.hwpx")["package_validation"]["valid"]


@pytest.mark.corpus
def test_invalid_table_padding_and_page_margins_are_non_destructive():
    doc = document("SF-AD2")
    table = doc.tables(1)[0]
    before_table = xml(table)
    before_root = xml(doc.root(1))
    with pytest.raises(ComposeError, match="padding"):
        doc.set_table_layout(table, column_widths_mm=[1, 1, 1, 1], cell_margins_mm={"left": 1, "right": 1})
    assert xml(table) == before_table
    with pytest.raises(ComposeError, match="consume"):
        doc.set_page_layout(1, margins_mm={"left": 200, "right": 200})
    assert xml(doc.root(1)) == before_root


@pytest.mark.corpus
def test_header_footer_frame_sync_is_explicit_and_preserves_owned_payload(tmp_path):
    doc = document("SF-TD5")
    header = doc.root().find("hp:p/hp:run/hp:ctrl/hp:header", NS)
    header_paragraph = header.find("hp:subList/hp:p", NS)
    doc.set_paragraph_text(header_paragraph, "머리말 소유 텍스트")
    doc.use_character_style(header_paragraph, bold=True, italic=True, include_headers=True)
    doc.use_paragraph_style(header_paragraph, align="RIGHT", include_headers=True)
    footer = doc._clone(header)
    footer.tag = HP + "footer"
    header.getparent().append(footer)
    table = doc.tables()[1]
    carrier = next(p for p in doc.root() if table in p.iter())
    doc.split_section(carrier, landscape=True, margins_hwp={"left": 4252, "right": 4252,
        "top": 4252, "bottom": 4252, "header": 2268, "footer": 1984, "gutter": 0})
    cover_controls = [xml(node) for node in doc.root().xpath(".//hp:header | .//hp:footer", namespaces=NS)]
    body_controls = doc.root(1).xpath(".//hp:header | .//hp:footer", namespaces=NS)
    frames = [control.find("hp:subList", NS) for control in body_controls]
    old_extents = [(frame.get("textWidth"), frame.get("textHeight")) for frame in frames]

    def payload(control):
        copy = deepcopy(control)
        for cache in copy.findall(".//hp:linesegarray", NS):
            cache.getparent().remove(cache)
        frame = copy.find("hp:subList", NS)
        for key in ("textWidth", "textHeight"):
            frame.attrib.pop(key)
        return ET.tostring(copy, method="c14n", exclusive=True)

    before_payload = [payload(control) for control in body_controls]
    definitions = xml(doc.xml("Contents/header.xml"))
    # Existing callers preserve frame extents, even when geometry changed.
    assert doc.set_page_layout(1)["header_footer_frames"] == []
    assert [(f.get("textWidth"), f.get("textHeight")) for f in frames] == old_extents
    report = doc.set_page_layout(1, sync_header_footer_frames=True)
    assert [(f.get("textWidth"), f.get("textHeight")) for f in frames] == [("75684", "2268"), ("75684", "1984")]
    assert [payload(control) for control in body_controls] == before_payload
    assert xml(doc.xml("Contents/header.xml")) == definitions
    assert [xml(node) for node in doc.root().xpath(".//hp:header | .//hp:footer", namespaces=NS)] == cover_controls
    assert [r["kind"] for r in report["header_footer_frames"]] == ["header", "footer"]
    output = tmp_path / "coherent-header-frames.hwpx"
    assert doc.save(output)["package_validation"]["valid"]
    reopened = TemplateDocument(output)
    assert reopened.root(1).find(".//hp:header/hp:subList", NS).get("textWidth") == "75684"


@pytest.mark.corpus
def test_invalid_frame_sync_is_rejected_before_geometry_mutation():
    doc = document("SF-TD5")
    frame = doc.root().find(".//hp:header/hp:subList", NS)
    del frame.attrib["textWidth"]
    before = xml(doc.root())
    with pytest.raises(ComposeError, match="textWidth/textHeight"):
        doc.set_page_layout(landscape=True, sync_header_footer_frames=True)
    assert xml(doc.root()) == before
    with pytest.raises(ComposeError, match="must be bool"):
        doc.set_page_layout(sync_header_footer_frames=1)
    assert xml(doc.root()) == before


@pytest.mark.corpus
def test_declared_empty_section_boundary_suffix_is_removed_without_text_or_control_loss():
    from doc_automation.layout import apply_editorial_profile
    doc = document("SF-PM4")
    profile = editorial_spec(doc, "SF-PM4")
    selectors = profile["section_boundary_spacer_selectors"]
    spacers = [doc.xml(s["xml"]).xpath(s["xpath"], namespaces=NS)[0] for s in selectors]
    assert len(spacers) == 3
    original_texts = {p: own_text(p) for p in doc.paragraphs() if own_text(p)}
    def semantic_control(node):
        copy = deepcopy(node)
        for cache in copy.findall(".//hp:linesegarray", NS):
            cache.getparent().remove(cache)
        return ET.tostring(copy, method="c14n", exclusive=True)
    controls = {node: semantic_control(node) for node in doc.root().iter()
                if local(node) in {"pageNum", "newNum", "header", "footer", "pageHiding"}}
    report = apply_editorial_profile(doc, "SF-PM4", profile)
    assert all(p.getparent() is None for p in spacers)
    assert all(own_text(p) == text for p, text in original_texts.items())
    assert all(semantic_control(node) == payload for node, payload in controls.items())
    assert own_text(doc.root(0)[-1]) == "공급기업명"
    assert len(report["section_boundary_spacers"]) == 3
    assert all(item["status"] == "discarded_at_new_section_boundary" for item in report["section_boundary_spacers"])


@pytest.mark.parametrize("failure", ["control", "text", "break", "noncontiguous"])
@pytest.mark.corpus
def test_explicit_section_boundary_discard_rejects_semantic_or_nonadjacent_paragraphs(failure):
    doc = document("SF-PM4")
    first = next(p for p in doc.root() if own_text(p) == "1. 기능 요구사항")
    spacers = list(doc.root())[doc.root().index(first)-3:doc.root().index(first)]
    if failure == "control":
        ET.SubElement(spacers[-1].find("hp:run", NS), HP + "ctrl").append(ET.Element(HP + "newNum", num="1", numType="PAGE"))
    elif failure == "text":
        doc.set_paragraph_text(spacers[-1], "의미 있는 입력")
    elif failure == "break":
        spacers[-1].set("pageBreak", "1")
    else:
        spacers = spacers[:1]
    before = xml(doc.root()), xml(doc.xml("Contents/header.xml")), list(doc.sections)
    with pytest.raises(ComposeError, match="Boundary spacer"):
        doc.split_section(first, landscape=True, discard_boundary_spacers=spacers)
    assert (xml(doc.root()), xml(doc.xml("Contents/header.xml")), list(doc.sections)) == before


@pytest.mark.corpus
def test_trace_table_widths_use_semantic_registry_without_changing_normal_repeated_grid():
    from doc_automation.layout import apply_editorial_profile
    doc = document("SF-PM4")
    normal = doc.tables()[2]
    carrier = next(p for p in doc.root() if normal in p.iter())
    trace_carrier = doc.clone_paragraph(carrier)
    repeated_carrier = doc.clone_paragraph(carrier)
    doc.root().extend([trace_carrier, repeated_carrier])
    trace = trace_carrier.find(".//hp:tbl", NS)
    repeated = repeated_carrier.find(".//hp:tbl", NS)
    doc._editorial_trace_tables = {trace}
    profile = editorial_spec(doc, "SF-PM4")
    report = apply_editorial_profile(doc, "SF-PM4", profile)
    reports = {item["instance_id"]: item for item in report["tables"]}
    assert reports[normal.get("id")]["column_widths_hwp"] == profile["targets"]["table_column_widths_hwp"]["1"]
    assert reports[repeated.get("id")]["column_widths_hwp"] == profile["targets"]["table_column_widths_hwp"]["1"]
    assert reports[trace.get("id")]["column_widths_hwp"] == profile["targets"]["trace_table_column_widths_hwp"]
    assert reports[trace.get("id")]["selection"] == "renderer_trace_table_role"


@pytest.mark.corpus
def test_insert_picture_retains_semantic_content_and_fits_whole_raster(tmp_path):
    from io import BytesIO
    from PIL import Image
    doc = document()
    paragraph = next(p for p in doc.paragraphs(1) if own_text(p) == "시스템명")
    stream = BytesIO()
    Image.new("RGB", (400, 200), "white").save(stream, format="PNG")
    raw = stream.getvalue()
    picture = doc.insert_picture(paragraph, raw, "image/png", "png", width_mm=80, height_mm=80,
                                 description="합성 시안·실제 실행화면 아님")
    size = picture.find("hp:sz", NS)
    assert abs(int(size.get("width")) / int(size.get("height")) - 2) < 0.001
    assert own_text(paragraph) == "시스템명"
    assert picture.find("hp:shapeComment", NS).text == "합성 시안·실제 실행화면 아님"
    identifier = picture.find("hc:img", NS).get("binaryItemIDRef")
    output = tmp_path / "new-raster.hwpx"
    doc.save(output)
    reopened = TemplateDocument(output)
    item = next(i for i in reopened.xml("Contents/content.hpf").find("opf:manifest", NS) if i.get("id") == identifier)
    assert entries(output)[item.get("href")] == raw
    assert reopened.validate()["picture_count"] == 1
    assert reopened.validate()["valid"]


@pytest.mark.corpus
def test_invalid_raster_does_not_add_a_resource_or_change_the_target():
    doc = document()
    paragraph = next(p for p in doc.paragraphs(1) if own_text(p) == "시스템명")
    before = xml(paragraph), xml(doc.xml("Contents/content.hpf")), dict(doc._new_entries)
    with pytest.raises(ComposeError, match="decoded"):
        doc.insert_picture(paragraph, b"not an image", "image/png", "png", width_mm=80)
    assert (xml(paragraph), xml(doc.xml("Contents/content.hpf")), dict(doc._new_entries)) == before


@pytest.mark.corpus
def test_new_picture_matrix_uses_observed_native_precision_without_changing_raster_or_extents():
    from io import BytesIO
    from PIL import Image
    doc = document()
    paragraph = next(p for p in doc.paragraphs(1) if own_text(p) == "시스템명")
    stream = BytesIO()
    Image.new("RGB", (1000, 760), "white").save(stream, format="PNG")
    raw = stream.getvalue()
    picture = doc.insert_picture(paragraph, raw, "image/png", "png", width_mm=38396 * 25.4 / 7200)
    matrix = picture.find("hp:renderingInfo/hc:scaMatrix", NS)
    # Historical TD3 SaveAs changed this rational value to0.511947; generate
    # those bytes initially rather than weakening the strict object comparison.
    assert matrix.get("e5") == "0.511947"
    assert picture.find("hp:curSz", NS).get("height") == "29181"
    assert picture.find("hp:orgSz", NS).get("height") == "57000"
    binary_id = picture.find("hc:img", NS).get("binaryItemIDRef")
    item = next(item for item in doc.xml("Contents/content.hpf").find("opf:manifest", NS) if item.get("id") == binary_id)
    assert doc._new_entries[item.get("href")] == raw


@pytest.mark.corpus
def test_body_style_does_not_change_header_footer_or_note_paragraphs():
    doc = document()
    controls = [node for root in [doc.root(i) for i in range(len(doc.sections))] for node in root.iter()
                if local(node) in {"header", "footer", "footNote", "endNote"}]
    assert controls
    original = [xml(node) for node in controls]
    for section in range(len(doc.sections)):
        doc.use_character_style(doc.root(section), font="함초롬바탕", size_pt=11, spacing_percent=0, ratio_percent=100)
        doc.use_paragraph_style(doc.root(section), line_spacing_percent=130)
    assert [xml(node) for node in controls] == original


@pytest.mark.corpus
def test_editorial_profile_uses_marked_nested_heading_and_repeat_card_widths(tmp_path):
    from doc_automation.layout import apply_editorial_profile
    doc = document()
    table = doc.tables(1)[0]
    carrier = next(p for p in doc.root(1) if table in p.iter())
    copy = doc.clone_paragraph(carrier)
    doc.root(1).append(copy)
    heading = doc.new_paragraph("선택한 의미 제목", prototype=doc.cell(table, 0, 1).find("hp:subList/hp:p", NS))
    doc.cell(table, 2, 1).find("hp:subList", NS).append(heading)
    doc._editorial_heading_paragraphs = {heading}
    profile = editorial_spec(doc, "SF-AD2")
    report = apply_editorial_profile(doc, "SF-AD2", profile)
    body_tables = doc.tables(1)
    assert len(body_tables) == 2
    assert report["tables"][0]["column_widths_hwp"] == report["tables"][1]["column_widths_hwp"]
    assert any(s["selection"] == "renderer_semantic_role" for s in report["selector"]["heading_selections"])
    current = next(p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)
                   if p.get("id") == heading.find("hp:run", NS).get("charPrIDRef"))
    assert current.get("height") == str(profile["targets"]["heading_height_hwp"])
    assert current.find("hh:bold", NS) is not None
    # Value slots remain body-size and do not acquire label/header bold.
    value = doc.cell(table, 0, 1)
    doc.set_cell_text(value, "입력값")
    doc.use_character_style(value, bold=False)
    apply_editorial_profile(doc, "SF-AD2", profile)
    value_style = next(p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)
                       if p.get("id") == value.find("hp:subList/hp:p/hp:run", NS).get("charPrIDRef"))
    assert value_style.find("hh:bold", NS) is None
    assert doc.save(tmp_path / "profile-cards.hwpx")["package_validation"]["valid"]


@pytest.mark.corpus
def test_narrative_frame_is_not_mistaken_for_a_column_header():
    from doc_automation.layout import apply_editorial_profile
    doc = document("SF-AD1")
    table = doc.tables(1)[0]
    cell = doc.cell(table, 0, 0)
    prototype = cell.find("hp:subList/hp:p", NS)
    body = doc.new_paragraph("업무 설명 본문", prototype=prototype)
    heading = doc.new_paragraph("의미가 지정된 절 제목", prototype=prototype)
    cell.find("hp:subList", NS).extend([heading, body])
    doc.use_character_style(body, bold=False)
    doc._editorial_heading_paragraphs = {heading}
    profile = editorial_spec(doc, "SF-AD1")
    report = apply_editorial_profile(doc, "SF-AD1", profile)
    definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
    body_style = definitions[body.find("hp:run", NS).get("charPrIDRef")]
    heading_style = definitions[heading.find("hp:run", NS).get("charPrIDRef")]
    assert body_style.get("height") == str(profile["targets"]["body_height_hwp"])
    assert body_style.find("hh:bold", NS) is None
    assert heading_style.get("height") == str(profile["targets"]["heading_height_hwp"])
    assert heading_style.find("hh:bold", NS) is not None
    assert report["changes"]["header_cells"] == 0


@pytest.mark.corpus
def test_semantic_caption_role_overrides_header_cell_style_and_preserves_picture():
    from io import BytesIO
    from PIL import Image
    from doc_automation.layout import apply_editorial_profile
    doc = document("SF-AD2")
    table = doc.tables(1)[0]
    sublist = doc.cell(table, 0, 0).find("hp:subList", NS)
    prototype = sublist.find("hp:p", NS)
    picture_paragraph = doc.new_paragraph("", prototype=prototype)
    caption = doc.new_paragraph("변경 화면 — 제공 이미지의 의미 캡션", prototype=prototype)
    sublist.extend([picture_paragraph, caption])
    value_sublist = doc.cell(table, 0, 1).find("hp:subList", NS)
    instruction = doc.new_paragraph("화면 구성: 아래 제공 이미지 참조", prototype=prototype)
    source_note = doc.new_paragraph("출처: 제공 첨부 자료", prototype=prototype)
    value_sublist.extend([instruction, source_note])
    stream = BytesIO()
    Image.new("RGB", (20, 10), "white").save(stream, format="PNG")
    picture = doc.insert_picture(picture_paragraph, stream.getvalue(), "image/png", "png", width_mm=20,
                                 description="합성 이미지·실제 실행화면 아님")
    original_picture = xml(picture)
    doc._editorial_caption_paragraphs = {caption}
    doc._editorial_picture_paragraphs = {picture_paragraph}
    profile = editorial_spec(doc, "SF-AD2")
    report = apply_editorial_profile(doc, "SF-AD2", profile)
    definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
    style = definitions[caption.find("hp:run", NS).get("charPrIDRef")]
    assert style.get("height") == str(profile["targets"]["caption_height_hwp"])
    for body_paragraph in (instruction, source_note):
        assert definitions[body_paragraph.find("hp:run", NS).get("charPrIDRef")].get("height") == str(profile["targets"]["body_height_hwp"])
        assert all(s["text"] != own_text(body_paragraph) for s in report["selector"]["caption_selections"])
    paragraph_definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:paraPr", NS)}
    for paragraph in (caption, picture_paragraph):
        definition = paragraph_definitions[paragraph.get("paraPrIDRef")]
        assert definition.find("hh:breakSetting", NS).get("keepWithNext") == "1"
    assert own_text(caption) == "변경 화면 — 제공 이미지의 의미 캡션"
    assert xml(picture) == original_picture
    assert any(s["selection"] == "renderer_semantic_role" and s["text"] == own_text(caption)
               for s in report["selector"]["caption_selections"])


@pytest.mark.corpus
def test_rewritten_toc_entry_cannot_become_the_body_section_boundary():
    from doc_automation.layout import apply_editorial_profile
    doc = document("SF-TD5")
    toc = next(p for p in doc.root() if own_text(p).lstrip().startswith("1.") and "\t" in own_text(p))
    table = doc.tables()[1]
    doc.set_paragraph_text(toc, "1. DEMO_PRODUCTION_RESULT ........ 쪽수 확인 예정")
    profile = editorial_spec(doc, "SF-TD5")
    report = apply_editorial_profile(doc, "SF-TD5", profile)
    assert toc.getparent() is doc.root(0)
    assert table in doc.root(1).iter()
    assert report["selector"]["new_body_section"]


@pytest.mark.corpus
def test_td3_exact_chapter_and_finite_intro_move_with_first_landscape_card():
    from doc_automation.layout import apply_editorial_profile
    doc = document("SF-TD3")
    profile = editorial_spec(doc, "SF-TD3")
    selector = profile["body_section_selector"]
    heading = doc.root().xpath(selector["source_heading"]["xpath"], namespaces=NS)[0]
    carrier = doc.root().xpath(selector["first_table_carrier"]["xpath"], namespaces=NS)[0]
    standard = next(p for p in doc.root() if own_text(p) == "1. 화면 표준")
    menu = next(p for p in doc.root() if own_text(p) == "2. 메뉴구조도")
    intro = doc.new_paragraph("과제: 검증용 제공 프로젝트", prototype=carrier)
    carrier.addprevious(intro)
    doc._editorial_body_paragraphs = {intro}
    doc._editorial_heading_paragraphs = {heading}
    doc.use_paragraph_keep(intro, keep_with_next=True)
    heading.set("pageBreak", "1")
    table = carrier.find(".//hp:tbl", NS)
    table_id = table.get("id")
    before_texts = {p: own_text(p) for p in doc.paragraphs()}
    original_page = xml(doc.root().find(".//hp:pagePr", NS))
    report = apply_editorial_profile(doc, "SF-TD3", profile)
    assert standard.getparent() is menu.getparent() is doc.root(0)
    assert list(doc.root(1))[:3] == [heading, intro, carrier]
    assert heading.get("pageBreak") == "0"
    assert table.get("id") == table_id and table in carrier.iter()
    assert all(own_text(p) == text for p, text in before_texts.items())
    assert xml(doc.root(0).find(".//hp:pagePr", NS)) == original_page
    definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:paraPr", NS)}
    assert definitions[carrier.get("paraPrIDRef")].find("hh:breakSetting", NS).get("keepWithNext") == "0"
    boundary = report["selector"]["body_section_boundary"]
    assert boundary["source_heading"]["xpath"] == "/hs:sec/hp:p[54]"
    assert boundary["generated_intro"][0]["text"] == "과제: 검증용 제공 프로젝트"


@pytest.mark.parametrize("failure", ["wrong_source_heading", "unregistered_intro", "extra_intro", "intro_control"])
@pytest.mark.corpus
def test_td3_declared_section_boundary_rejects_unowned_content_before_any_style_change(failure):
    from doc_automation.layout import apply_editorial_profile
    doc = document("SF-TD3")
    profile = editorial_spec(doc, "SF-TD3")
    carrier = doc.root().xpath(profile["body_section_selector"]["first_table_carrier"]["xpath"], namespaces=NS)[0]
    intro = doc.new_paragraph("과제: 검증용 제공 프로젝트", prototype=carrier)
    carrier.addprevious(intro)
    doc._editorial_body_paragraphs = {intro}
    if failure == "wrong_source_heading":
        profile["body_section_selector"]["source_heading"]["xpath"] = "/hs:sec/hp:p[52]"
    elif failure == "unregistered_intro":
        doc._editorial_body_paragraphs = set()
    elif failure == "extra_intro":
        extra = doc.new_paragraph("과제: 등록되지 않은 추가 문단", prototype=carrier)
        carrier.addprevious(extra)
        doc._editorial_body_paragraphs.add(extra)
    else:
        ET.SubElement(intro.find("hp:run", NS), HP + "ctrl").append(ET.Element(HP + "pageNum", pos="BOTTOM_CENTER", formatType="DIGIT", sideChar="-"))
    before = {name: xml(doc.xml(name)) for name in ["Contents/header.xml", *doc.sections]}
    with pytest.raises(ComposeError, match="Body section"):
        apply_editorial_profile(doc, "SF-TD3", profile)
    assert {name: xml(doc.xml(name)) for name in ["Contents/header.xml", *doc.sections]} == before


@pytest.mark.corpus
def test_context_keys_do_not_turn_body_values_into_bold_headings_or_keep_chains():
    from doc_automation.layout import apply_editorial_profile
    doc = document("SF-PM4")
    profile = editorial_spec(doc, "SF-PM4")
    prototype = doc.cell(doc.tables()[1], 1, 3).find("hp:subList/hp:p", NS)
    title = doc.new_paragraph("[T1] REQ-001 제공 요구사항 제목", prototype=prototype)
    values = [doc.new_paragraph(value, prototype=prototype) for value in
              ("[T1] 분류: 제공 분류 원문", "[T1] 출처: [S1]", "[C1] 비고: 제공 원문", "[F1] 검토: 미확인", "1. 제공 단계별 처리 본문")]
    doc.root().extend([title, *values])
    for paragraph in [title, *values]:
        doc.use_character_style(paragraph, bold=False)
        doc.use_paragraph_keep(paragraph, keep_with_next=False)
    doc._editorial_heading_paragraphs = {title}
    report = apply_editorial_profile(doc, "SF-PM4", profile)
    chars = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
    paras = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:paraPr", NS)}
    assert chars[title.find("hp:run", NS).get("charPrIDRef")].find("hh:bold", NS) is not None
    for paragraph in values:
        char = chars[paragraph.find("hp:run", NS).get("charPrIDRef")]
        assert char.find("hh:bold", NS) is None and char.get("height") == str(profile["targets"]["body_height_hwp"])
        assert paras[paragraph.get("paraPrIDRef")].find("hh:breakSetting", NS).get("keepWithNext") == "0"
        assert all(item["text"] != own_text(paragraph) for item in report["selector"]["heading_selections"])


@pytest.mark.parametrize("item", DEVELOPMENT, ids=lambda item: item["id"])
@pytest.mark.corpus
def test_five_cover_roles_preserve_text_paragraph_format_geometry_and_unselected_runs(item):
    from doc_automation.layout import apply_editorial_profile
    role = item["id"].removeprefix("template-").upper()
    doc = document(role)
    profile = editorial_spec(doc, role)
    owners = doc._editorial_cover_paragraphs
    for name, paragraph in owners.items():
        doc.set_paragraph_text(paragraph, "제공 입력 " + name)
    texts = {name: own_text(p) for name, p in owners.items()}
    paragraph_formats = {name: dict(p.attrib) for name, p in owners.items()}
    original_paras = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:paraPr", NS)}
    paragraph_definitions = {name: deepcopy(original_paras[p.get("paraPrIDRef")]) for name, p in owners.items()}
    selected_runs = {run for paragraph in owners.values() for run in paragraph.findall("hp:run", NS)
                     if any(t.text or len(t) for t in run.findall("hp:t", NS))}
    # A selected TOC font-only target is independent of the five cover roles.
    selected_runs.update(run for paragraph in getattr(doc, "_editorial_toc_paragraphs", {}).values()
                         for run in paragraph.findall("hp:run", NS)
                         if any(inline_text(t) for t in run.findall("hp:t", NS)))
    if role == "SF-TD3":
        # Initial chapter typography now has a separate exact source scope;
        # this cover test must still protect every other retained cover run.
        selectors = profile["td3_initial_chapter_sources"]
        titles = [paragraph for paragraph, location in doc._source_paragraph_locations.items()
                  if location in {(s["xml"], s["xpath"]) for s in selectors.values()}]
        assert len(titles) == 2
        selected_runs.update(run for paragraph in titles for run in paragraph.findall("hp:run", NS)
                             if any(inline_text(t) for t in run.findall("hp:t", NS)))
    unselected = {run: dict(run.attrib) for run in doc.root(0).iter(HP + "run") if run not in selected_runs}
    cover_table = doc.tables()[0]
    geometry = [(node, dict(node.attrib)) for node in cover_table.iter()
                if local(node) in {"tbl", "sz", "pos", "outMargin", "inMargin", "cellAddr", "cellSpan", "cellSz", "cellMargin"}]
    cover_page = xml(doc.root(0).find(".//hp:pagePr", NS))
    report = apply_editorial_profile(doc, role, profile)
    assert {name: own_text(p) for name, p in owners.items()} == texts
    actual_paras = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:paraPr", NS)}
    for name, paragraph in owners.items():
        expected_attrs = dict(paragraph_formats[name])
        actual_attrs = dict(paragraph.attrib)
        actual_definition = deepcopy(actual_paras[paragraph.get("paraPrIDRef")])
        expected_definition = paragraph_definitions[name]
        if name == "program":
            assert actual_definition.find("hh:breakSetting", NS).get("breakNonLatinWord") == "BREAK_WORD"
            assert report["cover_program_paragraph"]["current_xpath"] == paragraph.getroottree().getpath(paragraph)
            actual_attrs["paraPrIDRef"] = expected_attrs["paraPrIDRef"]
            actual_definition.set("id", expected_definition.get("id"))
            actual_definition.find("hh:breakSetting", NS).set("breakNonLatinWord", expected_definition.find("hh:breakSetting", NS).get("breakNonLatinWord"))
        assert actual_attrs == expected_attrs
        assert ET.tostring(actual_definition, method="c14n", exclusive=True) == ET.tostring(expected_definition, method="c14n", exclusive=True)
    assert all(dict(node.attrib) == attrs for node, attrs in geometry)
    assert xml(doc.root(0).find(".//hp:pagePr", NS)) == cover_page
    # Scope this check to the retained cover suffix/prefix: body runs are allowed
    # separate editorial changes after the section split.
    assert all(dict(run.attrib) == attrs for run, attrs in unselected.items()
               if run.getroottree().getroot() is doc.root(0))
    assert {r["role"] for r in report["cover_roles"]} == set(owners)
    for result in report["cover_roles"]:
        target = profile["targets"]["cover_roles"][result["role"]]
        assert result["actual_ids"]
        assert all(actual["height_hwp"] == target["height_hwp"] and actual["bold"] == target["bold"]
                   and set(actual["fonts"].values()) == {target["font_face"]} for actual in result["actual_ids"])


@pytest.mark.parametrize("failure", ["registry", "xpath", "verbatim", "source_sha", "extra_target"])
@pytest.mark.corpus
def test_cover_misidentification_is_rejected_before_any_edit(failure):
    from doc_automation.layout import apply_editorial_profile
    doc = document()
    profile = editorial_spec(doc, "SF-AD2")
    if failure == "registry":
        doc._editorial_cover_paragraphs["program"] = doc._editorial_cover_paragraphs["title"]
    elif failure == "xpath":
        profile["cover_selectors"]["program"]["template"]["xpath"] = profile["cover_selectors"]["title"]["template"]["xpath"]
    elif failure == "verbatim":
        profile["cover_selectors"]["program"]["template"]["text_before_generation_verbatim"] = "틀린 원문"
    elif failure == "source_sha":
        profile["cover_selectors"]["program"]["template"]["source_sha256"] = "0" * 64
    else:
        profile["targets"]["cover_roles"]["program"]["spacing_percent"] = 0
    before = {name: xml(doc.xml(name)) for name in ["Contents/header.xml", *doc.sections]}
    with pytest.raises(ComposeError, match="Cover"):
        apply_editorial_profile(doc, "SF-AD2", profile)
    assert {name: xml(doc.xml(name)) for name in ["Contents/header.xml", *doc.sections]} == before


@pytest.mark.parametrize("role", ["SF-AD1", "SF-AD2", "SF-TD1", "SF-TD2", "SF-TD3", "SF-TD4", "SF-TD5",
                                 "SF-CD1", "SF-TI1", "SF-TI2", "SF-TI3", "SF-TI4", "SF-OS1", "SF-OS2"])
@pytest.mark.corpus
def test_toc_font_only_roles_preserve_owner_text_direct_formatting_geometry_and_controls(role):
    from doc_automation.layout import apply_editorial_profile
    doc = document(role)
    profile = editorial_spec(doc, role)
    owners = doc._editorial_toc_paragraphs
    doc.set_paragraph_text(owners["entries"], "1. 제공된 ID ........ 쪽수 확인 예정\n2. 추가 항목 ........ 쪽수 확인 예정")
    # Explicit source-owner formatting survives the font-only target.
    doc.use_character_style(owners["entries"], italic=True)
    definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
    before = {run: deepcopy(definitions[run.get("charPrIDRef")]) for paragraph in owners.values()
              for run in paragraph.findall("hp:run", NS) if any(inline_text(t) for t in run.findall("hp:t", NS))}
    texts = {key: own_text(p) for key, p in owners.items()}
    paragraph_attributes = {key: dict(p.attrib) for key, p in owners.items()}
    evidence = json.loads((ROOT / profile["toc_observed_evidence"]["path"]).read_text())
    controls = [doc.xml(item["xml"]).xpath(item["xpath"], namespaces=NS)[0]
                for item in evidence["template_source"]["protected_region_controls"]]
    control_bytes = {node: xml(node) for node in controls}
    report = apply_editorial_profile(doc, role, profile)
    definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
    families = {f.get("lang").lower(): {font.get("id"): font.get("face") for font in f}
                for f in doc.xml("Contents/header.xml").findall(".//hh:fontface", NS)}
    for run, old in before.items():
        new = deepcopy(definitions[run.get("charPrIDRef")])
        assert all(families[script][identifier] == "함초롬바탕" for script, identifier in new.find("hh:fontRef", NS).attrib.items())
        for definition in (old, new):
            definition.attrib.pop("id")
            definition.remove(definition.find("hh:fontRef", NS))
        assert ET.tostring(old, method="c14n", exclusive=True) == ET.tostring(new, method="c14n", exclusive=True)
    assert {key: own_text(p) for key, p in owners.items()} == texts
    assert {key: dict(p.attrib) for key, p in owners.items()} == paragraph_attributes
    assert all(xml(node) == payload for node, payload in control_bytes.items())
    assert {r["role"] for r in report["toc_roles"]} == {"title", "entries"}


@pytest.mark.parametrize("failure", ["registry", "xpath", "verbatim", "source_sha", "extra_target"])
@pytest.mark.corpus
def test_toc_misidentification_is_rejected_before_cover_or_body_edits(failure):
    from doc_automation.layout import apply_editorial_profile
    doc = document()
    profile = editorial_spec(doc, "SF-AD2")
    if failure == "registry":
        doc._editorial_toc_paragraphs["entries"] = doc._editorial_toc_paragraphs["title"]
    elif failure == "xpath":
        profile["toc_selectors"]["entries"]["template"]["xpath"] = profile["toc_selectors"]["title"]["template"]["xpath"]
    elif failure == "verbatim":
        profile["toc_selectors"]["entries"]["template"]["text_before_generation_verbatim"] = "다른 원문"
    elif failure == "source_sha":
        profile["toc_selectors"]["title"]["template"]["source_sha256"] = "0" * 64
    else:
        profile["targets"]["toc_roles"]["entries"]["height_hwp"] = 1000
    before = {name: xml(doc.xml(name)) for name in ["Contents/header.xml", *doc.sections]}
    with pytest.raises(ComposeError, match="TOC"):
        apply_editorial_profile(doc, "SF-AD2", profile)
    assert {name: xml(doc.xml(name)) for name in ["Contents/header.xml", *doc.sections]} == before
