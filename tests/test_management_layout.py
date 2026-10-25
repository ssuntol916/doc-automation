"""Source-owned management boundaries and typed value presentation, not native QA."""
from copy import deepcopy
from pathlib import Path
import json

from lxml import etree as ET
from corpus_sources import pinned_source_path
import pytest

from doc_automation.compose import ComposeError, TemplateDocument
from doc_automation.hwpx import NS, own_text, parse_xml
from doc_automation.layout import apply_editorial_profile
from doc_automation.renderers import generate_project

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "examples/style-upgrade/illustrated-extended-v2/illustrated.project.json"
ROLES = ["SF-OS2", "SF-PM1", "SF-PM2", "SF-PM3"]


def definitions(doc, name):
    return {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:" + name, NS)}


def paragraph_shape(doc, paragraph):
    prop = definitions(doc, "paraPr")[paragraph.get("paraPrIDRef")]
    return prop.find("hh:align", NS).get("horizontal"), prop.find("hh:breakSetting", NS)


def characters(doc, paragraph):
    chars = definitions(doc, "charPr")
    return [chars[r.get("charPrIDRef")] for r in paragraph.findall("hp:run", NS)
            if r.find("hp:t", NS) is not None]


@pytest.fixture(scope="module")
def outputs(tmp_path_factory):
    manifest = generate_project(INPUT, tmp_path_factory.mktemp("management"), roles=ROLES,
                                style_profile="reference-v1")
    return {d["role"]: (TemplateDocument(d["path"]), d) for d in manifest["documents"]}


@pytest.mark.corpus
@pytest.mark.parametrize("role", ROLES[1:])
def test_management_title_and_source_summary_start_the_body_with_controls_and_size_preserved(outputs, role):
    doc, report = outputs[role]
    profile = json.loads((ROOT / "resources/style-upgrade/profiles" / (role + ".json")).read_text())
    start = profile["body_section_start"]
    original = TemplateDocument(pinned_source_path(profile))
    original_paragraph = original.xml(start["xml"]).xpath(start["xpath"], namespaces=NS)[0]
    selector = report["editorial_profile"]["selector"]
    assert selector["body_section_boundary"]["selection"] == "exact_management_source_start_with_registered_generated_text"
    assert len(doc.sections) == 2
    first = doc.root(1)[0]
    assert own_text(first) == ("주간 계획자료 검토본(월간 양식 사용)" if role == "SF-PM1" else start["text_before_generation_verbatim"])
    assert not any(own_text(p) == own_text(first) for p in doc.root(0))
    source_controls = [ET.tostring(n, method="c14n", exclusive=True) for n in original_paragraph.findall("./hp:run/hp:ctrl", NS)]
    current_controls = first.findall("./hp:run/hp:ctrl", NS)
    for source_control in source_controls:
        matches = [n for n in current_controls if ET.tostring(n, method="c14n", exclusive=True) == source_control]
        assert len(matches) == 1
        current_controls.remove(matches[0])
    # split_section explicitly brings the source column/header controls into
    # the new section; they supplement rather than replace pageHiding.
    assert all(all(ET.QName(c).localname in {"colPr", "header", "footer"} for c in n) for n in current_controls)
    assert [c.get("height") for c in characters(doc, first)] == [c.get("height") for c in characters(original, original_paragraph)]
    _, keep = paragraph_shape(doc, first)
    assert keep.get("keepWithNext") == "1"
    assert doc.tables(1)[0].getparent().getparent().getparent() is doc.root(1)
    if role == "SF-PM1":
        values = [own_text(p) for p in doc.root(1)]
        assert any(v.startswith("과제명 :") for v in values)
        assert any(v.startswith("기간 :") and "주간 입력·월간 실적 아님" in v for v in values)
        assert any(v.startswith("입력 진도:") and "계획 20%" in v for v in values)
        for spec in start["source_bridge"]:
            source_p = original.xml(spec["xml"]).xpath(spec["xpath"], namespaces=NS)[0]
            if spec["text_before_generation_verbatim"].startswith(("과제명", "기  간", "진척율")):
                prefix = {"과제명": "과제명", "기  간": "기간", "진척율": "입력 진도"}[spec["text_before_generation_verbatim"].split(":")[0].strip()]
                target = next(p for p in doc.root(1) if own_text(p).startswith(prefix))
                assert [c.get("height") for c in characters(doc, target)] == [c.get("height") for c in characters(original, source_p)]


@pytest.mark.corpus
def test_os2_notice_regular_body_and_decimal_precision_are_owned_by_the_frame(outputs):
    doc, _ = outputs["SF-OS2"]
    frame = doc.tables(1)[0]
    assert frame.get("pageBreak") == "CELL"
    assert frame.find("hp:pos", NS).get("treatAsChar") == "0"
    paragraphs = list(frame.iter("{" + NS["hp"] + "}p"))
    assert own_text(paragraphs[0]).startswith("검증용 합성 자료")
    assert "과제:" in own_text(paragraphs[0])
    assert not any(own_text(p).startswith("검증용 합성 자료") for p in doc.root(1))
    note = json.loads(INPUT.read_text())["kpis"][0]["notes"]
    original_note = next(p for p in paragraphs if own_text(p) == "비고 원문: " + note)
    display = next(p for p in paragraphs if own_text(p).startswith("[K1.1] 비고 소수 표시:"))
    assert "66.67" in own_text(display) and "66.66666666666667" in own_text(display)
    assert "소수 2자리 반올림 참고값" in own_text(display)
    assert "새 측정·실적·성공 판정이 아니다" in own_text(display)
    assert any("numerator / denominator * 100" in own_text(p) and "분자 18 / 분모 20" in own_text(p) for p in paragraphs)
    assert any("입력 실적 소수 자릿수: 2" in own_text(p) for p in paragraphs)
    for paragraph in [original_note, display]:
        align, breaks = paragraph_shape(doc, paragraph)
        assert align == "LEFT" and breaks.get("breakLatinWord") == "KEEP_WORD"
        assert all(c.find("hh:bold", NS) is None for c in characters(doc, paragraph))


@pytest.mark.corpus
def test_pm1_risk_identity_and_values_have_readable_declared_geometry(outputs):
    doc, _ = outputs["SF-PM1"]
    work, risk = doc.tables(1)[:2]
    row = risk.findall("hp:tr", NS)[1]
    cells = row.findall("hp:tc", NS)
    assert own_text(cells[0].find("hp:subList/hp:p", NS)) == "DEMO-RISK-001"
    assert int(cells[0].find("hp:cellSz", NS).get("width")) == 10000
    assert sum(int(c.find("hp:cellSz", NS).get("width")) for c in cells) == 48500
    for paragraph in work.findall("hp:tr", NS)[1].iter("{" + NS["hp"] + "}p"):
        assert paragraph_shape(doc, paragraph)[0] == "LEFT"
        assert all(c.find("hh:bold", NS) is None for c in characters(doc, paragraph))


@pytest.mark.corpus
def test_pm3_long_prose_and_following_appendices_do_not_inherit_example_italics_or_center(outputs):
    doc, _ = outputs["SF-PM3"]
    card = doc.tables(1)[1]
    for row in [3, 4, 5, 6]:
        for paragraph in doc.cell(card, row, 1).iter("{" + NS["hp"] + "}p"):
            assert paragraph_shape(doc, paragraph)[0] == "LEFT"
            assert all(c.find("hh:italic", NS) is None and c.find("hh:bold", NS) is None for c in characters(doc, paragraph))
    notes = own_text(doc.cell(card, 6, 1).find("hp:subList/hp:p", NS))
    assert "승인 증거 연결: 입력0개(빈 목록; 실제 증거 부재 여부 미판정)" in notes
    assert "승인 증거: 없음" not in notes
    assert "요청/승인 상태: 미요청" in notes and "변경 요청·승인·적용은 미수행" in notes
    appendix = next(p for p in doc.root(1) if own_text(p).startswith("[B1] 사유:"))
    assert paragraph_shape(doc, appendix)[0] == "LEFT"


@pytest.mark.corpus
def test_declared_management_start_rejects_wrong_source_bridge_registry_and_controls(monkeypatch, tmp_path):
    import doc_automation.layout as layout
    original_apply = layout.apply_editorial_profile
    checked = []
    def guarded(doc, role, profile):
        if role != "SF-PM1":
            return original_apply(doc, role, profile)
        before = [ET.tostring(doc.xml(member)) for member in doc._roots]
        for mutation in ["sha", "xpath", "bridge", "registry", "control", "notice"]:
            bad = deepcopy(profile)
            selected = doc._editorial_body_start_paragraph
            control = selected.find("./hp:run/hp:ctrl/hp:pageHiding", NS)
            control_before = dict(control.attrib)
            registered = set(doc._editorial_body_paragraphs)
            if mutation == "sha": bad["body_section_start"]["source_sha256"] = "0" * 64
            elif mutation == "xpath": bad["body_section_start"]["xpath"] = "/hs:sec/hp:p[22]"
            elif mutation == "bridge": bad["body_section_start"]["source_bridge"] = list(reversed(bad["body_section_start"]["source_bridge"]))
            elif mutation == "registry": doc._editorial_body_start_paragraph = doc.root()[0]
            elif mutation == "control": control.set("hideHeader", "0")
            else: doc._editorial_body_paragraphs = set()
            try:
                with pytest.raises(ComposeError, match="Management body"):
                    original_apply(doc, role, bad)
            finally:
                doc._editorial_body_start_paragraph = selected
                control.attrib.clear()
                control.attrib.update(control_before)
                doc._editorial_body_paragraphs = registered
            assert [ET.tostring(doc.xml(member)) for member in doc._roots] == before
            checked.append(mutation)
        return original_apply(doc, role, profile)
    monkeypatch.setattr(layout, "apply_editorial_profile", guarded)
    generate_project(INPUT, tmp_path / "guarded", roles=["SF-PM1"], style_profile="reference-v1")
    assert checked == ["sha", "xpath", "bridge", "registry", "control", "notice"]


@pytest.mark.corpus
def test_pm3_supplied_approval_links_remain_exact_and_are_not_reclassified(tmp_path):
    data = json.loads(INPUT.read_text())
    base = INPUT.parent
    for collection in ["sources", "attachments"]:
        for item in data[collection]:
            if item.get("path") and not Path(item["path"]).is_absolute():
                item["path"] = str((base / item["path"]).resolve())
    evidence = data["attachments"][0]["id"]
    data["changes"][0]["approval_evidence_ids"] = [evidence]
    data["changes"][0]["approval_status"] = "approved"
    source = tmp_path / "project.json"
    source.write_text(json.dumps(data, ensure_ascii=False))
    manifest = generate_project(source, tmp_path / "approved", roles=["SF-PM3"], style_profile="reference-v1")
    doc = TemplateDocument(manifest["documents"][0]["path"])
    card = doc.tables(1)[1]
    notes = own_text(doc.cell(card, 6, 1).find("hp:subList/hp:p", NS))
    assert "승인 증거 연결: " + evidence in notes
    assert "입력0개" not in notes
    assert "요청/승인 상태: 승인" in notes


@pytest.mark.corpus
@pytest.mark.parametrize("precision,display", [(0, "-12"), (2, "-12.35"), (None, None)])
def test_kpi_note_display_preserves_negative_literal_zero_and_unknown_precision(tmp_path, precision, display):
    data = json.loads(INPUT.read_text())
    for collection in ["sources", "attachments"]:
        for item in data[collection]:
            if item.get("path") and not Path(item["path"]).is_absolute():
                item["path"] = str((INPUT.parent / item["path"]).resolve())
    kpi = data["kpis"][0]
    literal = "-12.345678901234567"
    kpi["notes"] = "검증용 소수 원문 " + literal + "; 수행 자료 아님"
    kpi["actual_precision"] = precision
    source = tmp_path / "precision.json"
    source.write_text(json.dumps(data, ensure_ascii=False))
    manifest = generate_project(source, tmp_path / "precision", roles=["SF-OS2"], style_profile="reference-v1")
    doc = TemplateDocument(manifest["documents"][0]["path"])
    paragraphs = list(doc.tables(1)[0].iter("{" + NS["hp"] + "}p"))
    assert any(own_text(p) == "비고 원문: " + kpi["notes"] for p in paragraphs)
    assert any(own_text(p).startswith("입력 실적 90%") for p in paragraphs)
    notes = [own_text(p) for p in paragraphs if own_text(p).startswith("[K1.1]")]
    if precision is None:
        assert not notes
        assert any("입력 실적 소수 자릿수: 미확인(null)" in own_text(p) for p in paragraphs)
    else:
        assert len(notes) == 1
        assert "비고 소수 표시: " + display in notes[0]
        assert "원문 수치: " + literal in notes[0]
        assert f"소수 {precision}자리 반올림 참고값" in notes[0]
