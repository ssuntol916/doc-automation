"""Declared cover-program wrapping, exact no-ops and source-bound scope."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree as ET
from corpus_sources import pinned_source_path
import pytest

from doc_automation import layout
from doc_automation.compose import ComposeError, TemplateDocument
from doc_automation.hwpx import NS, own_text, parse_xml
from doc_automation.renderers import ROLES, generate_project

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "examples/style-upgrade/illustrated-extended-v2/illustrated.project.json"
NOOP = {"SF-AD1", "SF-AD2"}


def c14n(node):
    return ET.tostring(node, method="c14n", exclusive=True)


def entries(path):
    with ZipFile(path) as archive:
        return {i.filename: archive.read(i.filename) for i in archive.infolist()}


def profile_for(role):
    return json.loads((ROOT / f"resources/style-upgrade/profiles/{role}.json").read_text())


def direct_doc(role="SF-AD3"):
    profile = profile_for(role)
    doc = TemplateDocument(pinned_source_path(profile))
    doc._editorial_cover_paragraphs = {
        key: doc.xml(s["template"]["xml"]).xpath(s["template"]["xpath"], namespaces=NS)[0]
        for key, s in profile["cover_selectors"].items()
    }
    return doc, profile


@pytest.fixture(scope="module")
def paired_generation(tmp_path_factory):
    """Compare the isolated optional target, not two mirrored implementations."""
    from unittest.mock import patch
    out = tmp_path_factory.mktemp("cover-program-only")
    input_before = INPUT.read_bytes()
    with patch.object(layout, "_prepare_cover_program_paragraph", return_value=None):
        old_reference = generate_project(INPUT, out / "before-reference", style_profile="reference-v1")
    # Default generation must never invoke the editorial target at all.
    with patch.object(layout, "_prepare_cover_program_paragraph", side_effect=AssertionError("default invoked editorial target")):
        old_default = generate_project(INPUT, out / "before-default")
    new_reference = generate_project(INPUT, out / "after-reference", style_profile="reference-v1")
    new_default = generate_project(INPUT, out / "after-default")
    assert INPUT.read_bytes() == input_before
    return {key: {d["role"]: d for d in manifest["documents"]} for key, manifest in
            [("old_reference", old_reference), ("new_reference", new_reference),
             ("old_default", old_default), ("new_default", new_default)]}


@pytest.mark.corpus
@pytest.mark.parametrize("role", ROLES)
def test_default_none_preserves_every_whole_document_and_source_policy(paired_generation, role):
    before, after = paired_generation["old_default"][role], paired_generation["new_default"][role]
    assert Path(before["path"]).read_bytes() == Path(after["path"]).read_bytes()
    doc = TemplateDocument(after["path"])
    selector = profile_for(role)["cover_selectors"]["program"]["template"]
    owner, = doc.xml(selector["xml"]).xpath(selector["xpath"], namespaces=NS)
    definition, = doc.xml("Contents/header.xml").xpath(".//hh:paraPr[@id=$i]", namespaces=NS, i=owner.get("paraPrIDRef"))
    assert definition.find("hh:breakSetting", NS).get("breakNonLatinWord") == ("BREAK_WORD" if role in NOOP else "KEEP_WORD")


@pytest.mark.corpus
@pytest.mark.parametrize("role", ROLES)
def test_reference_change_is_one_program_property_and_noop_owners_keep_raw_bytes(paired_generation, role):
    old, new = paired_generation["old_reference"][role], paired_generation["new_reference"][role]
    before, after = entries(old["path"]), entries(new["path"])
    report = new["editorial_profile"]["cover_program_paragraph"]
    assert report["changed_paragraphs"] == int(role not in NOOP)
    assert report["already_matching_owner_skipped_without_derivation"] is (role in NOOP)
    assert report["all_other_paragraph_properties_preserved"]
    assert report["actual_break_non_latin"] == "BREAK_WORD"
    if role in NOOP:
        assert Path(old["path"]).read_bytes() == Path(new["path"]).read_bytes()
        return
    assert list(before) == list(after)
    member, xpath = report["member"], report["current_xpath"]
    assert {n for n in before if before[n] != after[n]} <= {member, "Contents/header.xml"}
    bsec, asec = parse_xml(before[member]), parse_xml(after[member])
    bp, = bsec.xpath(xpath, namespaces=NS)
    ap, = asec.xpath(xpath, namespaces=NS)
    assert own_text(bp) == own_text(ap) == "2026년도 검증용 스마트공장 문서 자동화 예제"
    before_id, after_id = bp.get("paraPrIDRef"), ap.get("paraPrIDRef")
    bh, ah = parse_xml(before["Contents/header.xml"]), parse_xml(after["Contents/header.xml"])
    old_pr, = bh.xpath(".//hh:paraPr[@id=$i]", namespaces=NS, i=before_id)
    new_pr, = ah.xpath(".//hh:paraPr[@id=$i]", namespaces=NS, i=after_id)
    assert old_pr.find("hh:breakSetting", NS).get("breakNonLatinWord") == "KEEP_WORD"
    assert new_pr.find("hh:breakSetting", NS).get("breakNonLatinWord") == "BREAK_WORD"
    restored = deepcopy(new_pr)
    restored.set("id", before_id)
    restored.find("hh:breakSetting", NS).set("breakNonLatinWord", "KEEP_WORD")
    assert c14n(restored) == c14n(old_pr)
    ap.set("paraPrIDRef", before_id)
    # This compares every other cover/body text, direct format, owner, object,
    # table/paragraph geometry and control, including all five other roles.
    assert c14n(asec) == c14n(bsec)
    if after_id not in {p.get("id") for p in bh.findall(".//hh:paraPr", NS)}:
        props = new_pr.getparent()
        props.remove(new_pr)
        props.set("itemCnt", str(len(props)))
    assert c14n(ah) == c14n(bh)


@pytest.mark.corpus
@pytest.mark.parametrize("failure", ["guard_type", "sha", "xpath", "owner_hash", "definition_hash", "expected_property",
                                     "extra_guard", "extra_target", "current_definition", "object", "registry"])
def test_program_guard_rejects_drift_before_any_editorial_mutation(failure):
    doc, profile = direct_doc()
    guard = profile["cover_program_paragraph_source"]
    owner = doc._editorial_cover_paragraphs["program"]
    if failure == "guard_type":
        profile["cover_program_paragraph_source"] = None
    elif failure == "sha":
        guard["source_sha256"] = "0" * 64
    elif failure == "xpath":
        guard["xpath"] = profile["cover_selectors"]["title"]["template"]["xpath"]
    elif failure == "owner_hash":
        guard["paragraph_c14n_sha256"] = "0" * 64
    elif failure == "definition_hash":
        guard["paragraph_definition_c14n_sha256"] = "0" * 64
    elif failure == "expected_property":
        guard["break_non_latin"] = "BREAK_WORD"
    elif failure == "extra_guard":
        guard["any_owner"] = True
    elif failure == "extra_target":
        profile["targets"]["cover_program_paragraph"]["align"] = "LEFT"
    elif failure == "current_definition":
        pr, = doc.xml("Contents/header.xml").xpath(".//hh:paraPr[@id=$i]", namespaces=NS, i=owner.get("paraPrIDRef"))
        pr.find("hh:align", NS).set("horizontal", "RIGHT")
    elif failure == "object":
        ET.SubElement(owner.find("hp:run", NS), "{" + NS["hp"] + "}pic")
    else:
        doc._editorial_cover_paragraphs["program"] = deepcopy(owner)
    before = {name: c14n(doc.xml(name)) for name in ["Contents/header.xml", *doc.sections]}
    with pytest.raises(ComposeError, match="Cover"):
        layout.apply_editorial_profile(doc, "SF-AD3", profile)
    assert before == {name: c14n(doc.xml(name)) for name in before}


@pytest.mark.corpus
@pytest.mark.parametrize("role", sorted(NOOP))
def test_already_matching_program_does_not_even_call_derivation_or_invalidation(role, monkeypatch):
    doc, profile = direct_doc(role)
    owners = layout._prepare_cover_roles(doc, profile)
    prepared = layout._prepare_cover_program_paragraph(doc, profile, owners)
    before = {name: c14n(doc.xml(name)) for name in ["Contents/header.xml", *doc.sections]}
    monkeypatch.setattr(doc, "use_paragraph_style", lambda *a, **k: pytest.fail("no-op derived a paragraph"))
    monkeypatch.setattr(doc, "invalidate_layout", lambda *a, **k: pytest.fail("no-op invalidated layout"))
    result = layout._apply_cover_program_paragraph(doc, prepared)
    assert result["changed_paragraphs"] == 0
    assert before == {name: c14n(doc.xml(name)) for name in before}
