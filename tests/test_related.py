"""Actual owner/relationship checks for the role-specific reference register."""
from copy import deepcopy
import json
from pathlib import Path

from corpus_sources import pinned_source_path
import pytest

from doc_automation.compose import ComposeError, TemplateDocument
from doc_automation.hwpx import own_text
from doc_automation.narrative import SourceNotes, source_note_scope
from doc_automation.related import append_reference_register
from doc_automation.renderers import _finalize_meaning_map


ROOT = Path(__file__).resolve().parents[1]
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"


def source_document(role):
    inventory = json.loads((ROOT / "resources/stage1/inventory.json").read_text())
    source = next(x for x in inventory["documents"] if x["id"] == "template-" + role.lower())
    if not pinned_source_path(source).is_file():
        pytest.fail("Selected corpus test requires original read-only template: " + str(pinned_source_path(source)))
    doc = TemplateDocument(str(pinned_source_path(source)), expected_sha256=source["sha256"])
    parent = doc.root(len(doc.sections) - 1)
    prototype = next(p for p in reversed(list(parent)) if p.tag == f"{{{HP}}}p")
    doc._editorial_heading_paragraphs = set()
    return doc, parent, prototype


def field(records, pointer):
    return next(f for e in records for f in e["fields"] if f["input_pointer"] == pointer)


def actual_owners(doc, item):
    assert item["content_review_status"] == "pending"
    assert item["owner_basis"] == "explicit_writer_owners; independent semantic review required"
    texts = []
    for location in item["owners"]:
        nodes = doc.xml(location["section"]).xpath(location["xpath"], namespaces={"hp": HP, "hs": "http://www.hancom.co.kr/hwpml/2011/section"})
        assert len(nodes) == 1 and own_text(nodes[0]) == location["rendered_text"]
        texts.append(own_text(nodes[0]))
    return texts


def flags(doc, paragraph):
    definitions = doc.xml("Contents/header.xml").findall(f".//{{{HH}}}paraPr")
    definition = next(x for x in definitions if x.get("id") == paragraph.get("paraPrIDRef"))
    return definition.find(f"{{{HH}}}breakSetting")


@pytest.mark.corpus
def test_td3_register_pairs_names_and_direct_requirement_lists_and_preserves_old_owner(tmp_path):
    data = json.loads((ROOT / "examples/demo-suite.project.json").read_text())
    data["features"][0]["requirement_ids"] = []
    data["features"][1]["requirement_ids"] = [data["requirements"][1]["id"]]
    original = deepcopy(data)
    doc, parent, prototype = source_document("SF-TD3")
    previous = doc.new_paragraph("기존 명칭: " + data["features"][0]["name"], prototype=prototype)
    parent.append(previous)
    ctx = {"editorial": True, "meaning_map": [{"input_pointer": "/features/0", "entity_id": data["features"][0]["id"],
           "entity_name": data["features"][0]["name"], "fields": [{"input_pointer": "/features/0/name",
           "input_value": data["features"][0]["name"], "input_type": "str", "_paragraph": previous,
           "rendered_text": own_text(previous)}]}]}
    with source_note_scope(SourceNotes()):
        rows = append_reference_register(doc, "SF-TD3", data, ctx, parent=parent, prototype=prototype)
    assert len(rows) == len(data["features"]) + len(data["programs"])
    finalized = _finalize_meaning_map(doc, ctx["meaning_map"])
    output = tmp_path / "related.hwpx"
    doc.save(output)
    saved = TemplateDocument(output)
    for domain in ("features", "programs"):
        for index, item in enumerate(data[domain]):
            for key in ("id", "name"):
                owners = actual_owners(saved, field(finalized, f"/{domain}/{index}/{key}"))
                assert any(item["id"] in text and item["name"] in text for text in owners)
    first = actual_owners(saved, field(finalized, "/features/0/requirement_ids"))
    second = actual_owners(saved, field(finalized, "/features/1/requirement_ids"))
    assert any("연결 입력 0개" in text for text in first)
    assert all(requirement["id"] not in "\n".join(first) for requirement in data["requirements"])
    assert data["requirements"][1]["id"] in "\n".join(second)
    assert data["requirements"][0]["id"] not in "\n".join(second)
    old = actual_owners(saved, field(finalized, "/features/0/name"))
    assert old[0] == "기존 명칭: " + data["features"][0]["name"]
    program_header = next(p for p in parent if p not in doc._editorial_heading_paragraphs
                          and own_text(p).startswith("[L") and data["programs"][0]["id"] in own_text(p))
    assert flags(doc, program_header).get("keepWithNext") == "0"
    assert data == original


@pytest.mark.corpus
def test_pm4_register_keeps_all_17_names_and_explicit_test_stage_group_without_test_data(tmp_path):
    data = json.loads((ROOT / "examples/demo-suite.project.json").read_text())
    data["test_cases"][0]["group_id"] = None
    data["test_cases"][1]["group_id"] = "0"
    data["test_cases"][0]["data"] = {"marker": "TEST-DATA-IS-NOT-PM4-REGISTER-CONTENT"}
    original = deepcopy(data)
    doc, parent, prototype = source_document("SF-PM4")
    before = len(parent)
    ctx = {"editorial": True}
    with source_note_scope(SourceNotes()) as _:
        rows = append_reference_register(doc, "SF-PM4", data, ctx, parent=parent, prototype=prototype)
    assert len(rows) == 17 + len(data["changes"])
    finalized = _finalize_meaning_map(doc, ctx["meaning_map"])
    path = tmp_path / "trace-register.hwpx"
    doc.save(path)
    saved = TemplateDocument(path)
    for domain in ("features", "screens", "programs", "database_tables", "test_cases"):
        for index, item in enumerate(data[domain]):
            names = actual_owners(saved, field(finalized, f"/{domain}/{index}/name"))
            assert any(item["id"] in text and item["name"] in text for text in names)
    assert any("미확인(null)" in t for t in actual_owners(saved, field(finalized, "/test_cases/0/group_id")))
    assert any("0 (문자열)" in t for t in actual_owners(saved, field(finalized, "/test_cases/1/group_id")))
    acceptance = next(i for i, case in enumerate(data["test_cases"]) if case["stage"] == "acceptance")
    assert any("사용자시험" in t for t in actual_owners(saved, field(finalized, f"/test_cases/{acceptance}/stage")))
    contents = "\n".join(own_text(p) for p in list(parent)[before:])
    assert "TEST-DATA-IS-NOT-PM4-REGISTER-CONTENT" not in contents
    assert all(not f["input_pointer"].endswith(("/data", "/expected", "/actual", "/executor"))
               for e in finalized for f in e["fields"])
    values = [p for p in list(parent)[before:] if own_text(p).startswith("[L") and p not in doc._editorial_heading_paragraphs]
    assert values and all(flags(doc, p).get("keepWithNext") == "0" for p in values)
    assert data == original


@pytest.mark.parametrize("role", ["SF-AD2", "SF-PM4"])
@pytest.mark.corpus
def test_direct_change_register_preserves_before_after_reason_without_unrelated_claims(tmp_path, role):
    data = json.loads((ROOT / "examples/demo-suite.project.json").read_text())
    change = data["changes"][0]
    change.update(before="기존 입력 내용 — 변경 전", after="새 입력 내용 — 변경 후",
                  reason="제공된 변경 사유", approval_status=None)
    unrelated = deepcopy(change)
    unrelated.update(id="UNRELATED-CHANGE", name="연결 없는 변경", affected_refs=[])
    data["changes"].append(unrelated)
    modified = next(item for item in data["features"] if item["requirement_ids"])
    modified.update(change_type="modified", before="기존 기능 설명", after="변경 기능 설명")
    original = deepcopy(data)
    doc, parent, prototype = source_document(role)
    start = len(parent)
    ctx = {"editorial": True}
    with source_note_scope(SourceNotes()):
        append_reference_register(doc, role, data, ctx, parent=parent, prototype=prototype)
    records = _finalize_meaning_map(doc, ctx["meaning_map"])
    output = tmp_path / f"{role}.hwpx"
    doc.save(output)
    saved = TemplateDocument(output)
    for key in ("before", "after", "reason", "approval_status", "affected_refs"):
        owners = actual_owners(saved, field(records, "/changes/0/" + key))
        assert owners and all(text.startswith("[L") for text in owners)
        if key in {"before", "after", "reason"}:
            assert change[key] in "\n".join(owners)
        elif key == "approval_status":
            assert "미확인" in "\n".join(owners)
        else:
            assert change["affected_refs"][0]["id"] in "\n".join(owners)
    contents = "\n".join(own_text(p) for p in list(parent)[start:])
    assert "UNRELATED-CHANGE" not in contents
    assert not any(e["input_pointer"] == "/changes/1" for e in records)
    if role == "SF-AD2":
        index = data["features"].index(modified)
        for key in ("before", "after", "change_type", "requirement_ids"):
            assert actual_owners(saved, field(records, f"/features/{index}/{key}"))
    assert data == original


@pytest.mark.corpus
def test_register_refuses_false_zero_meaning_merge_and_unselected_role_does_not_edit():
    from doc_automation.related import _field_record
    doc, parent, prototype = source_document("SF-TD3")
    paragraph = doc.new_paragraph("소유 문단", prototype=prototype)
    parent.append(paragraph)
    entity = {"input_pointer": "/test_cases/0", "fields": [{"input_pointer": "/test_cases/0/group_id", "input_value": False, "input_type": "bool"}]}
    with pytest.raises(ComposeError, match="conflicts with supplied meaning"):
        _field_record(entity, "group_id", 0, [paragraph], "L1")
    before = len(parent)
    assert append_reference_register(doc, "SF-AD2", {"requirements": []}, {"editorial": True}, parent=parent, prototype=prototype) == []
    assert len(parent) == before
