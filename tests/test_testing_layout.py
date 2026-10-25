"""Role-local regressions for observed testing and narrative-frame defects."""
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from doc_automation.compose import TemplateDocument, validate_package
from doc_automation.hwpx import own_text
from doc_automation.renderers import NOTICE, generate_project

ROOT = Path(__file__).resolve().parents[1]
NS = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph", "hh": "http://www.hancom.co.kr/hwpml/2011/head"}
ROLES = ["SF-CD1", "SF-TI1", "SF-TI2", "SF-TI3", "SF-TI4", "SF-OS1"]


@pytest.fixture(scope="module")
def candidates(tmp_path_factory):
    source = ROOT / "examples/style-upgrade/illustrated-extended-v2/illustrated.project.json"
    result = generate_project(source, tmp_path_factory.mktemp("testing-layout"), roles=ROLES, style_profile="reference-v1")
    return json.loads(source.read_text()), {d["role"]: d for d in result["documents"]}


def bold(doc, paragraph):
    definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
    return [definitions[run.get("charPrIDRef")].find("hh:bold", NS) is not None for run in paragraph.findall("hp:run", NS)]


@pytest.mark.corpus
@pytest.mark.parametrize("role", ROLES)
def test_testing_candidates_keep_valid_packages_sources_and_sizes(candidates, role):
    _, outputs = candidates
    output = outputs[role]
    doc = TemplateDocument(output["path"])
    report = validate_package(output["path"])
    assert report["valid"], report
    profile = json.loads((ROOT / "resources/style-upgrade/profiles" / (role + ".json")).read_text())
    assert profile["source_template"]["sha256"] == output["source_template"]["sha256"]
    assert profile["targets"]["body_height_hwp"] == (1100 if role in {"SF-TI2", "SF-TI3", "SF-OS1"} else 1000)
    assert profile["assessment"]["score_percent"] is None
    index = json.loads((ROOT / "resources/style-upgrade/profiles/index.json").read_text())
    indexed = next(p for p in index["profiles"] if p["role"] == role)
    assert indexed["sha256"] == sha256((ROOT / indexed["path"]).read_bytes()).hexdigest()
    assert sha256((ROOT / profile["testing_layout_evidence"]["path"]).read_bytes()).hexdigest() == profile["testing_layout_evidence"]["sha256"]


@pytest.mark.corpus
@pytest.mark.parametrize("role,stage", [("SF-CD1", "unit"), ("SF-TI1", "integration"), ("SF-TI4", "acceptance")])
def test_test_data_width_and_case_field_owners_survive_reflow(candidates, role, stage):
    data, outputs = candidates
    output = outputs[role]
    doc = TemplateDocument(output["path"])
    tables = doc.tables(len(doc.sections) - 1)
    cases = [(index, case) for index, case in enumerate(data["test_cases"]) if case["stage"] == stage]
    if role == "SF-CD1":
        cards = [tables[0]]
        case_rows = [(index, case, cards[0], row) for row, (index, case) in enumerate(cases, 1)]
    else:
        cards = [table for table in tables if table.get("colCnt") == "7"
                 and len(table.find("hp:tr", NS).findall("hp:tc", NS)) < 7]
        assert len(cards) == len(cases)
        start = 4 if role == "SF-TI1" else 3
        case_rows = [(index, case, card, start) for (index, case), card in zip(cases, cards)]
    column = 3 if role == "SF-CD1" else 2
    definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:paraPr", NS)}
    meaning = json.loads(Path(output["meaning_map"]["path"]).read_text())
    entities = {e["input_pointer"]: e for e in meaning["entities"]}
    required = {"id", "name", "scenario", "data", "expected", "actual", "result", "execution_date", "executor", "evidence_ids", "status", "source_refs"}
    profile = json.loads((ROOT / "resources/style-upgrade/profiles" / (role + ".json")).read_text())
    for index, case, table, row in case_rows:
        assert int(doc.cell(table, row, column).find("hp:cellSz", NS).get("width")) >= 10500
        assert table.find("hp:pos", NS).get("treatAsChar") == ("1" if role == "SF-CD1" else "0")
        assert table.get("pageBreak") == "CELL"
        if role != "SF-CD1":
            assert table.get("repeatHeader") == "1"
            header = table.findall("hp:tr", NS)[:row]
            assert len(header) == row and all(c.get("header") == "1" for r in header for c in r.findall("hp:tc", NS))
            identity = "\n".join(own_text(p) for p in doc.cell(table, 1 if role == "SF-TI1" else 0, 1).findall("hp:subList/hp:p", NS))
            assert "케이스 ID: " + case["id"] in identity.splitlines()
        expected_column = 4 if role == "SF-CD1" else 3
        widths = profile["targets"]["table_column_widths_hwp"]["0"]
        for value_column in (column, expected_column):
            cell = doc.cell(table, row, value_column)
            address, span = cell.find("hp:cellAddr", NS), cell.find("hp:cellSpan", NS)
            start, count = int(address.get("colAddr")), int(span.get("colSpan"))
            assert int(cell.find("hp:cellSz", NS).get("width")) == sum(widths[start:start + count])
            for paragraph in cell.findall("hp:subList/hp:p", NS):
                assert definitions[paragraph.get("paraPrIDRef")].find("hh:breakSetting", NS).get("breakLatinWord") == "KEEP_WORD"
        fields = {field["input_pointer"].rsplit("/", 1)[1]: field for field in entities[f"/test_cases/{index}"]["fields"]}
        assert required <= set(fields) and set(fields) == set(case)
        for key in case:
            field = fields[key]
            assert field["input_value"] == case[key]
            assert field["input_type"] == type(case[key]).__name__
            assert field["owners"], (role, case["id"], key)
            for owner in field["owners"]:
                found = doc.xml(owner["section"]).xpath(owner["xpath"], namespaces=meaning["xml_namespaces"])
                assert len(found) == 1 and own_text(found[0]) == owner["rendered_text"]
                main_fields = {"id", "name", "scenario", "requirement_ids", "data", "expected"}
                if key in main_fields or (role != "SF-CD1" and field["representation"] == "role_main_specification"):
                    assert any(node is table for node in found[0].iterancestors()), (case["id"], key)
        assert not any(any(bold(doc, p)) for p in doc.cell(table, row, 0).findall("hp:subList/hp:p", NS))


@pytest.mark.corpus
def test_cd1_result_and_defect_details_have_keys_and_full_typed_values(candidates):
    data, outputs = candidates
    output = outputs["SF-CD1"]
    doc = TemplateDocument(output["path"])
    tables = doc.tables(len(doc.sections) - 1)
    assert "[U1]" in "".join(doc.cell(tables[0], 1, 5).itertext())
    assert "실행일 입력" not in "".join(doc.cell(tables[0], 1, 5).itertext())
    body = "\n".join(own_text(p) for p in doc.root(len(doc.sections) - 1) if not p.findall(".//hp:tbl", NS))
    assert "[U1] 실제 결과: 미확인(null)" in body
    assert "[U1] 실행 상태: 미수행" in body
    defect = tables[-1]
    assert defect.get("pageBreak") == "TABLE" and defect.find("hp:pos", NS).get("treatAsChar") == "0"
    assert "출처" not in "".join(defect.itertext())
    assert "[D1]" in body and data["defects"][0]["description"] in body
    meaning = json.loads(Path(output["meaning_map"]["path"]).read_text())
    record = next(e for e in meaning["entities"] if e["input_pointer"] == "/defects/0")
    for field in record["fields"]:
        assert field["owners"]
        if field["representation"] == "role_main_specification":
            assert all("[D1]" in p["rendered_text"] for p in field["owners"])


@pytest.mark.corpus
@pytest.mark.parametrize("role", ["SF-TI2", "SF-TI3", "SF-OS1"])
def test_frame_notice_and_body_share_original_anchor_and_bold_roles(candidates, role):
    _, outputs = candidates
    doc = TemplateDocument(outputs[role]["path"])
    table = doc.tables(len(doc.sections) - 1)[0]
    paragraphs = doc.cell(table, 0, 0).findall("hp:subList/hp:p", NS)
    assert own_text(paragraphs[0]).startswith(NOTICE)
    assert table.get("pageBreak") == "CELL" and table.find("hp:pos", NS).get("treatAsChar") == "0"
    assert not any(own_text(p).startswith(NOTICE) for p in doc.root(len(doc.sections) - 1))
    headings = {r["text"] for r in outputs[role]["editorial_profile"]["selector"]["heading_selections"]}
    for paragraph in paragraphs:
        value = own_text(paragraph)
        if value in headings:
            assert all(bold(doc, paragraph))
        elif value and paragraph.find(".//hp:pic", NS) is None:
            assert not any(bold(doc, paragraph)), value


@pytest.mark.corpus
def test_manual_pictures_follow_each_screen_description_not_emergency_contacts(candidates):
    data, outputs = candidates
    output = outputs["SF-TI3"]
    doc = TemplateDocument(output["path"])
    paragraphs = doc.cell(doc.tables(len(doc.sections) - 1)[0], 0, 0).findall("hp:subList/hp:p", NS)
    text = [own_text(p) for p in paragraphs]
    emergency = next(i for i, value in enumerate(text) if value == "(6) 비상 연락망")
    for binding in output["image_bindings"]:
        assert binding["placement"] == "after_exact_manual_or_screen_description"
        screen = next(s for s in data["screens"] if s["id"] == binding["entity_id"])
        start = text.index(screen["id"] + " " + screen["name"])
        caption = text.index(binding["caption"])
        assert start < caption < emergency
        assert paragraphs[caption - 1].find(".//hp:pic", NS) is not None
        later = [text.index(s["id"] + " " + s["name"]) for s in data["screens"] if text.index(s["id"] + " " + s["name"]) > start]
        if later:
            assert caption < min(later)


def test_manual_and_support_business_labels_preserve_original_code_correspondence():
    from doc_automation.narrative import LABELS, SourceNotes, code_label, source_note_scope
    assert all(key in LABELS for key in ("field_definitions", "buttons", "permissions", "before_attachment_ids", "after_attachment_ids", "standard_attachment_ids"))
    notes = SourceNotes()
    with source_note_scope(notes):
        assert code_label("pilot") == "시범운영"
        assert code_label("training") == "교육"
    assert notes.code_mappings == {"pilot": "시범운영", "training": "교육"}


@pytest.mark.corpus
def test_ti2_migration_rows_keep_parent_and_each_nested_source_link(candidates):
    data, outputs = candidates
    output = outputs['SF-TI2']
    doc = TemplateDocument(output['path'])
    notes = json.loads(Path(output['source_notes']['path']).read_text())
    paragraphs = [own_text(p) for member in doc.sections for p in doc.xml(member).iter('{http://www.hancom.co.kr/hwpml/2011/paragraph}p')]
    for item in data['deployment_items']:
        for row in item.get('migration_counts', []):
            for reference in row['source_refs']:
                record = next(record for record in notes['references'] if record['source_ref'] == reference)
                visible = [text for text in paragraphs if '적재 입력:' in text and item['id'] in text and row['data_type'] in text]
                assert visible and any(f"[{record['key']}]" in text for text in visible)
                owner = record['owner']
                node = doc.xml(owner['section']).xpath(owner['xpath'], namespaces=notes['xml_namespaces'])[0]
                assert reference['locator'] in own_text(node)
                assert row['actual_count'] is None
                assert all('실제 미확인' in text for text in visible)


@pytest.mark.corpus
def test_ti3_system_context_keeps_exact_values_states_diagram_links_and_owners(candidates):
    data, outputs = candidates
    output = outputs['SF-TI3']
    doc = TemplateDocument(output['path'])
    meaning = json.loads(Path(output['meaning_map']['path']).read_text())
    notes = json.loads(Path(output['source_notes']['path']).read_text())
    for index, system in enumerate(data['project']['systems']):
        entity = next(row for row in meaning['entities'] if row['input_pointer'] == f'/project/systems/{index}')
        fields = {row['input_pointer'].rsplit('/', 1)[1]: row for row in entity['fields']}
        for key in ('id', 'name', 'status', 'lifecycle', 'configuration', 'as_is_description', 'to_be_description', 'network_method', 'as_is_diagram_ids', 'to_be_diagram_ids', 'source_refs'):
            if key not in system:
                continue
            field = fields[key]
            assert field['input_value'] == system[key] and field['input_type'] == type(system[key]).__name__
            assert field['owners']
            for owner in field['owners']:
                node = doc.xml(owner['section']).xpath(owner['xpath'], namespaces=meaning['xml_namespaces'])[0]
                assert own_text(node) == owner['rendered_text']
                assert own_text(node).startswith(f'[구성{index + 1}] ')
        for key in ('as_is_diagram_ids', 'to_be_diagram_ids'):
            for attachment_id in system.get(key, []):
                assert attachment_id in '\n'.join(owner['rendered_text'] for owner in fields[key]['owners'])
        for ref in system['source_refs']:
            record = next(row for row in notes['references'] if row['source_ref'] == ref)
            assert f"[{record['key']}]" in '\n'.join(owner['rendered_text'] for owner in fields['source_refs']['owners'])
        text = '\n'.join(own_text(p) for member in doc.sections for p in doc.xml(member).iter('{http://www.hancom.co.kr/hwpml/2011/paragraph}p'))
        assert f"SF-TD2 아키텍처설계서의 동일 시스템 ID {system['id']} 참조" in text
        assert '실제 설치·운영 검증과 구분' in text
