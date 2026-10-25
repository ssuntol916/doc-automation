"""Source-bound regression for the observed defect heading/grid inversion."""
from hashlib import sha256
import json
from pathlib import Path

from corpus_sources import pinned_source_path
import pytest
from lxml import etree as ET

from doc_automation.compose import TemplateDocument
from doc_automation.hwpx import NS, own_text
from doc_automation.renderers import generate_project

ROOT = Path(__file__).resolve().parents[1]
ROLES = {"SF-CD1": "unit", "SF-TI1": "integration", "SF-TI4": "acceptance"}


@pytest.fixture(scope="module")
def defect_candidates(tmp_path_factory):
    source = ROOT / "examples/style-upgrade/illustrated-extended-v2/illustrated.project.json"
    result = generate_project(source, tmp_path_factory.mktemp("defect-title-flow"),
        roles=list(ROLES), style_profile="reference-v1")
    return {item["role"]: item for item in result["documents"]}


@pytest.mark.corpus
@pytest.mark.parametrize("role", ROLES)
def test_defect_grid_keeps_its_exact_source_title_owner_and_floating_offset(defect_candidates, role):
    output = defect_candidates[role]
    doc = TemplateDocument(output["path"])
    table = doc.tables(len(doc.sections) - 1)[-1]
    owner = table.getparent().getparent()
    assert own_text(owner) == "2. 결함관리 내역"
    assert [child.tag.rsplit("}", 1)[-1] for child in table.getparent()] == ["tbl", "t"]
    assert table.get("pageBreak") == "TABLE"
    position = table.find("hp:pos", NS)
    assert {key: position.get(key) for key in ("treatAsChar", "vertOffset", "horzOffset")} == {
        "treatAsChar": "0", "vertOffset": "1800", "horzOffset": "0"}
    body_tables = doc.tables(len(doc.sections) - 1)
    if role == "SF-CD1":
        assert body_tables[0].find("hp:pos", NS).get("treatAsChar") == "1"
    else:
        source = json.loads((ROOT / "examples/style-upgrade/illustrated-extended-v2/illustrated.project.json").read_text())
        cases = [case for case in source["test_cases"] if case["stage"] == ROLES[role]]
        main_cards = [card for card in body_tables if card.get("colCnt") == "7"
                      and len(card.find("hp:tr", NS).findall("hp:tc", NS)) < 7]
        assert len(main_cards) == len(cases)
        for card, case in zip(main_cards, cases):
            assert card.find("hp:pos", NS).get("treatAsChar") == "0"
            assert card.get("pageBreak") == "CELL" and card.get("repeatHeader") == "1"
            identity = doc.cell(card, 1 if role == "SF-TI1" else 0, 1)
            lines = "\n".join(own_text(p) for p in identity.findall("hp:subList/hp:p", NS)).splitlines()
            assert "케이스 ID: " + case["id"] in lines
    profile_path = ROOT / "resources/style-upgrade/profiles" / (role + ".json")
    profile = json.loads(profile_path.read_text())
    evidence = profile["defect_title_flow_evidence"]
    assert profile["version"] == (10 if role == "SF-CD1" else 11)
    assert profile["cover_program_wordbreak_refinement"]["previous_profile_version"] == profile["version"] - 1
    assert profile["targets"]["cover_program_paragraph"] == {"break_non_latin": "BREAK_WORD"}
    guard = profile["cover_program_paragraph_source"]
    selector = profile["cover_selectors"]["program"]["template"]
    assert (guard["source_sha256"], guard["xml"], guard["xpath"]) == (
        output["source_template"]["sha256"], selector["xml"], selector["xpath"])
    original = TemplateDocument(output["source_template"]["path"])
    source_owner, = original.xml(guard["xml"]).xpath(guard["xpath"], namespaces=NS)
    source_definition, = original.xml("Contents/header.xml").xpath(
        ".//hh:paraPr[@id=$i]", namespaces=NS, i=source_owner.get("paraPrIDRef"))
    assert own_text(source_owner) == selector["text_before_generation_verbatim"]
    assert sha256(ET.tostring(source_owner, method="c14n", exclusive=True)).hexdigest() == guard["paragraph_c14n_sha256"]
    assert sha256(ET.tostring(source_definition, method="c14n", exclusive=True)).hexdigest() == guard["paragraph_definition_c14n_sha256"]
    assert guard["break_non_latin"] == source_definition.find("hh:breakSetting", NS).get("breakNonLatinWord") == "KEEP_WORD"
    paragraph_policy = output["editorial_profile"]["cover_program_paragraph"]
    assert paragraph_policy["changed_paragraphs"] == 1 and paragraph_policy["all_other_paragraph_properties_preserved"]
    assert paragraph_policy["current_xpath"] == guard["xpath"] and paragraph_policy["actual_break_non_latin"] == "BREAK_WORD"
    wrapping_evidence = profile["cover_program_wordbreak_evidence"]
    assert sha256((ROOT / wrapping_evidence["path"]).read_bytes()).hexdigest() == wrapping_evidence["sha256"]
    assert profile["assessment"]["score_percent"] is None
    if role != "SF-CD1":
        assert profile["targets"]["testing_case_cards"] == {"per_case": True, "inline": False,
            "page_break": "CELL", "repeat_header_rows": 4 if role == "SF-TI1" else 3}
        case_evidence = profile["case_and_appendix_flow_evidence"]
        assert sha256((ROOT / case_evidence["path"]).read_bytes()).hexdigest() == case_evidence["sha256"]
    assert profile["defect_grid_title_owner"]["source_sha256"] == output["source_template"]["sha256"]
    assert sha256((ROOT / evidence["path"]).read_bytes()).hexdigest() == evidence["sha256"]


@pytest.mark.corpus
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("failure", ["source_sha", "source_xpath", "source_own_text", "wrong_table"])
def test_defect_title_flow_rejects_a_different_source_owner(role, failure):
    from doc_automation.renderers import _all_tables, _paragraph, _testing_defect_details
    profile = json.loads((ROOT / "resources/style-upgrade/profiles" / (role + ".json")).read_text())
    doc = TemplateDocument(pinned_source_path(profile))
    tables = _all_tables(doc)
    table = tables[-1]
    owner = _paragraph(table)
    if failure == "source_sha":
        doc.source_sha256 = "0" * 64
    elif failure == "source_xpath":
        doc._source_paragraph_locations[owner] = ("Contents/section1.xml", "/hs:sec/hp:p[999]")
    elif failure == "source_own_text":
        doc._source_paragraph_text[owner] = "Business text with the same-looking table is not the source owner"
    else:
        table = tables[-2]
    with pytest.raises(ValueError, match="Testing defect title/table source owner"):
        _testing_defect_details(doc, table, {"test_cases": [], "defects": []}, ROLES[role], {"warnings": []})
