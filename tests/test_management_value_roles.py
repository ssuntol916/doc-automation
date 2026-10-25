"""Source-specific management value typography, without changing business facts."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree as ET
from corpus_sources import pinned_source_path
import pytest

from doc_automation.compose import ComposeError, TemplateDocument
from doc_automation.hwpx import NS, own_text
from doc_automation.management_roles import load_contract, prepare_overrides, source_paragraph, split_meeting_value
from doc_automation.renderers import generate_project

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "examples/style-upgrade/illustrated-extended-v2/illustrated.project.json"


def _relocated_input():
    data = json.loads(INPUT.read_text())
    for collection in ("sources", "attachments"):
        for record in data.get(collection, []):
            if record.get("path"):
                path = Path(record["path"]).expanduser()
                record["path"] = str((INPUT.parent / path if not path.is_absolute() else path).resolve())
    return data


def chars(doc, paragraph):
    props = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
    return [props[run.get("charPrIDRef")] for run in paragraph.findall("hp:run", NS)
            if run.find("hp:t", NS) is not None]


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    result = generate_project(INPUT, tmp_path_factory.mktemp("management-value-roles"),
        roles=["SF-PM2", "SF-PM3"], style_profile="reference-v1")
    return {item["role"]: (TemplateDocument(item["path"]), item) for item in result["documents"]}


@pytest.mark.corpus
@pytest.mark.parametrize("role,count", [("SF-PM2", 8), ("SF-PM3", 1)])
def test_source_role_evidence_and_actual_registry_targets_are_exact(generated, role, count):
    doc, report = generated[role]
    profile = json.loads((ROOT / "resources/style-upgrade/profiles" / (role + ".json")).read_text())
    original = TemplateDocument(pinned_source_path(profile))
    source_bytes = Path(pinned_source_path(profile)).read_bytes()
    for selection in profile["management_character_role_sources"].values():
        for key in ["source"] + (["regular_reference"] if "regular_reference" in selection else []):
            p = source_paragraph(original, selection[key])
            assert own_text(p) == selection[key]["text_before_generation_verbatim"]
    roles = report["editorial_profile"]["management_character_roles"]
    assert len(roles) == count
    for record in roles:
        current = doc.root(1).getroottree().xpath(record["xpath"], namespaces=NS)
        assert len(current) == 1 and own_text(current[0]) == record["text"]
        for prop in chars(doc, current[0]):
            for flag, expected in record["target"].items():
                assert (prop.find("hh:" + flag, NS) is not None) is expected
    assert Path(pinned_source_path(profile)).read_bytes() == source_bytes


@pytest.mark.corpus
def test_pm2_four_span_cells_have_distinct_bold_labels_and_regular_values(generated):
    doc, _ = generated["SF-PM2"]
    data = json.loads(INPUT.read_text())
    table = doc.tables(1)[0]
    labels = ["5. 회의내용", "6. 회의결과(합의사항)", "7. 특이사항", "8. 참석자"]
    for row, label in zip(range(4, 8), labels):
        cell = doc.cell(table, row, 0)
        ps = cell.findall("hp:subList/hp:p", NS)
        assert len(ps) == 2 and own_text(ps[0]) == label
        assert cell.find("hp:cellSpan", NS).get("colSpan") == "2"
        assert all(p.find("hh:bold", NS) is not None for p in chars(doc, ps[0]))
        assert all(p.find("hh:bold", NS) is None for p in chars(doc, ps[1]))
    note = own_text(doc.cell(table, 6, 0).findall("hp:subList/hp:p", NS)[1])
    assert data["meetings"][0]["special_notes"] in note
    for row in range(4):
        p = doc.cell(table, row, 0).find("hp:subList/hp:p", NS)
        assert all(prop.find("hh:bold", NS) is not None for prop in chars(doc, p))
    meaning = json.loads(Path(generated["SF-PM2"][1]["meaning_map"]["path"]).read_text())
    field = next(f for item in meaning["entities"] for f in item["fields"]
                 if f["input_pointer"] == "/meetings/0/special_notes")
    assert field["input_value"] == data["meetings"][0]["special_notes"]
    assert field["input_type"] == "str" and field["owners"]


@pytest.mark.corpus
def test_pm3_only_generated_request_number_values_lose_guide_italics(generated):
    doc, report = generated["SF-PM3"]
    table = doc.tables(1)[0]
    p = doc.cell(table, 1, 2).find("hp:subList/hp:p", NS)
    assert own_text(p) == "미제공"
    assert all(prop.find("hh:italic", NS) is None for prop in chars(doc, p))
    # The original guide is a source instruction, never a new document number.
    assert not any("발송된 공문번호를 기록" in own_text(p) for p in doc.root(1).iter("{" + NS["hp"] + "}p"))
    assert len(report["editorial_profile"]["management_character_roles"]) == 1
    assert report["editorial_profile"]["management_character_roles"][0]["input_pointer"] == "/changes/0/request_number"
    for header in table.findall("hp:tr", NS)[0].iter("{" + NS["hp"] + "}p"):
        assert all(prop.find("hh:bold", NS) is not None for prop in chars(doc, header))


@pytest.mark.corpus
def test_pm3_request_title_keeps_source18pt_bold_alignment_and_spacing(generated):
    doc, report = generated["SF-PM3"]
    roles = report["editorial_profile"]["management_preserved_titles"]
    assert len(roles) == 1 and roles[0]["name"] == "change_request_title"
    title = doc.root(1).getroottree().xpath(roles[0]["xpath"], namespaces=NS)[0]
    assert own_text(title) == "변경요청서"
    assert all(prop.get("height") == "1800" and prop.find("hh:bold", NS) is not None
               for prop in chars(doc, title))
    assert title.get("pageBreak") == "1"
    props = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:paraPr", NS)}
    para = props[title.get("paraPrIDRef")]
    assert para.find("hh:align", NS).get("horizontal") == "CENTER"
    assert [dict(node.attrib) for node in para.findall(".//hh:lineSpacing", NS)] == [
        {"type": "BETWEEN_LINES", "value": "96", "unit": "HWPUNIT"},
        {"type": "BETWEEN_LINES", "value": "192", "unit": "HWPUNIT"}]
    breaks = para.find("hh:breakSetting", NS)
    assert breaks.get("keepWithNext") == breaks.get("keepLines") == "1"


@pytest.mark.corpus
@pytest.mark.parametrize("bad", ["label", "protected", "profile"])
def test_missing_source_role_or_changed_runtime_boundary_fails_closed(bad):
    spec = json.loads((ROOT / "resources/style-upgrade/profiles/SF-PM2.json").read_text())
    doc = TemplateDocument(pinned_source_path(spec))
    contract = load_contract(doc, "SF-PM2")
    table = doc.tables()[1]
    if bad == "label":
        p = doc.cell(table, 6, 0).find("hp:subList/hp:p", NS)
        doc.set_paragraph_text(p, "unexpected source row")
    elif bad == "protected":
        p = doc.cell(table, 6, 0).find("hp:subList/hp:p", NS)
        ET.SubElement(p.find("hp:run", NS), "{" + NS["hp"] + "}ole")
    if bad != "profile":
        before = ET.tostring(table)
        with pytest.raises(ComposeError, match="PM2 source label/value"):
            split_meeting_value(doc, table, 6, "special_notes", "7. 특이사항", "value", contract,
                                entity_id="TEST", input_pointer="/meetings/0/special_notes")
        assert ET.tostring(table) == before
    else:
        split_meeting_value(doc, table, 6, "special_notes", "7. 특이사항", "value", contract,
                            entity_id="TEST", input_pointer="/meetings/0/special_notes")
        changed = deepcopy(spec)
        changed["targets"]["management_character_roles"]["meeting_special_notes_value"]["bold"] = True
        with pytest.raises(ComposeError, match="profile changed"):
            prepare_overrides(doc, changed)


@pytest.mark.corpus
def test_pm2_typed_labels_do_not_rewrite_raw_special_note_json_keys(tmp_path):
    data = _relocated_input()
    literal = '원문 그대로: {"attendees":["가상 인물"],"organizer":"미정"}'
    data["meetings"][0]["special_notes"] = literal
    path = tmp_path / "project.json"
    path.write_text(json.dumps(data, ensure_ascii=False))
    output = generate_project(path, tmp_path / "generated", roles=["SF-PM2"], style_profile="reference-v1")["documents"][0]
    doc = TemplateDocument(output["path"])
    texts = [own_text(p) for p in doc.root(1).iter("{" + NS["hp"] + "}p")]
    assert any(literal in text for text in texts)
    assert any("주최자 세부" in text for text in texts)
    assert any("참석자 명단" in text for text in texts)
    assert path.read_text() == json.dumps(data, ensure_ascii=False)
