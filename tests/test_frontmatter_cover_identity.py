"""Prospective initial-chapter typography and provided cover identity."""
from copy import deepcopy
import json
from pathlib import Path

from lxml import etree as ET
from corpus_sources import pinned_source_path
import pytest

from doc_automation.compose import ComposeError, TemplateDocument
from doc_automation.hwpx import NS, own_text, parse_xml
from doc_automation.layout import register_td3_initial_chapters, _prepare_td3_initial_typography
from doc_automation.renderers import _cover_program_identity, _prepare, generate_project

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "examples/style-upgrade/illustrated-extended-v2/illustrated.project.json"
PROFILE = ROOT / "resources/style-upgrade/profiles/SF-TD3.json"


def _relocated_input():
    data = json.loads(INPUT.read_text())
    for collection in ("sources", "attachments"):
        for record in data.get(collection, []):
            if record.get("path"):
                path = Path(record["path"]).expanduser()
                record["path"] = str((INPUT.parent / path if not path.is_absolute() else path).resolve())
    return data


@pytest.mark.parametrize("year,name,shown,expressed", [
    (2026, "합성 사업명", "2026년도 합성 사업명", True),
    (2026, "2026년도 합성 사업명", "2026년도 합성 사업명", False),
    (2026, "2024년 합성 사업명", "2024년 합성 사업명", False),
    (2026, " 2024년도 합성 사업명", " 2024년도 합성 사업명", False),
    (None, "합성 사업명", "합성 사업명", False),
    (None, "2024년도 합성 사업명", "2024년도 합성 사업명", False),
    (2026, None, "2026년도 미확인(자료 미제공)", True),
])
def test_cover_identity_preserves_provided_name_year_and_unknowns(year, name, shown, expressed):
    data = {"program_year": year, "program_name": name}
    before = deepcopy(data)
    result = _cover_program_identity(data)
    assert result["text"] == shown and data == before
    assert result["program_year_input"] is year and result["program_name_input"] == name
    assert result["program_year_field_expressed_by_composition"] is expressed
    assert ("/project/program_year" in result["expressed_input_pointers"]) is expressed


@pytest.mark.parametrize("year", [True, "2026", 2026.0])
def test_cover_identity_rejects_untyped_years(year):
    with pytest.raises(ValueError, match="provided integer"):
        _cover_program_identity({"program_year": year, "program_name": "합성 회귀"})


def definitions(doc):
    h = doc.xml("Contents/header.xml")
    return ({p.get("id"): p for p in h.findall(".//hh:charPr", NS)},
            {p.get("id"): p for p in h.findall(".//hh:paraPr", NS)},
            {f.get("lang").lower(): {font.get("id"): font.get("face") for font in f}
             for f in h.findall(".//hh:fontface", NS)})


@pytest.fixture(scope="module")
def td3_candidate(tmp_path_factory):
    item = generate_project(INPUT, tmp_path_factory.mktemp("td3-initial-roles"), roles=["SF-TD3"],
                            style_profile="reference-v1")["documents"][0]
    return TemplateDocument(item["path"]), item


@pytest.mark.corpus
def test_td3_initial_seven_owners_get_declared_metrics_without_geometry_scope_growth(td3_candidate):
    doc, item = td3_candidate
    profile = json.loads(PROFILE.read_text())
    source = TemplateDocument(pinned_source_path(profile))
    chars, paras, fonts = definitions(doc)
    records = item["editorial_profile"]["td3_initial_chapter_typography"]
    assert len(records) == 7 and sum(r["role"] == "heading" for r in records) == 2
    assert ET.tostring(doc.root(0).find("./hp:p/hp:run/hp:secPr/hp:pagePr", NS), method="c14n") == ET.tostring(source.root(0).find("./hp:p/hp:run/hp:secPr/hp:pagePr", NS), method="c14n")
    for record in records:
        p = doc.root(0).xpath(record["xpath"], namespaces=NS)[0]
        assert own_text(p) == record["text"] and p.getparent() is doc.root(0)
        heading = record["role"] == "heading"
        for run in p.findall("hp:run", NS):
            if not any(t.text or len(t) for t in run.findall("hp:t", NS)):
                continue
            c = chars[run.get("charPrIDRef")]
            assert int(c.get("height")) == (1200 if heading else 1100)
            assert (c.find("hh:bold", NS) is not None) is heading
            assert all(fonts[k][v] == "함초롬바탕" for k, v in c.find("hh:fontRef", NS).attrib.items())
            assert set(c.find("hh:spacing", NS).attrib.values()) == {"0"}
            assert set(c.find("hh:ratio", NS).attrib.values()) == {"100"}
        pp = paras[p.get("paraPrIDRef")]
        assert {x.get("value") for x in pp.findall(".//hh:lineSpacing", NS)} == {"150" if heading else "130"}
        if heading:
            selector = profile["td3_initial_chapter_sources"][record["chapter"]]
            original = source.root(0).xpath(selector["xpath"], namespaces=NS)[0]
            assert {k: v for k, v in p.attrib.items() if k != "paraPrIDRef"} == {k: v for k, v in original.attrib.items() if k != "paraPrIDRef"}
            assert [x.get("value") for x in pp.findall(".//hc:intent", NS)] == ["-1830", "-3660"]
        else:
            assert pp.find("hh:align", NS).get("horizontal") == "LEFT"
            for name in ["left", "intent"]:
                assert [x.get("value") for x in pp.findall(".//hc:" + name, NS)] == ["0", "0"]
    assert item["editorial_profile"]["selector"]["body_section_boundary"]["source_heading"]["xpath"] == "/hs:sec/hp:p[54]"
    assert doc.root(1).find("./hp:p/hp:run/hp:secPr/hp:pagePr", NS).get("landscape") == "NARROWLY"


@pytest.mark.corpus
@pytest.mark.parametrize("failure", ["sha", "xpath", "text", "node", "page", "paragraph_style"])
def test_td3_initial_source_guard_rejects_wrong_source_owner_or_geometry(failure):
    profile = json.loads(PROFILE.read_text())
    doc = TemplateDocument(pinned_source_path(profile))
    selector = profile["td3_initial_chapter_sources"]["standards"]
    p = doc.root(0).xpath(selector["xpath"], namespaces=NS)[0]
    if failure == "sha":
        selector["source_sha256"] = "0" * 64
    elif failure == "xpath":
        selector["xpath"] = "/hs:sec/hp:p[999]"
    elif failure == "text":
        doc.set_paragraph_text(p, "새 값과 비슷한 제목")
    elif failure == "node":
        p.getparent().replace(p, deepcopy(p))
    elif failure == "page":
        doc.root(0).find("./hp:p/hp:run/hp:secPr/hp:pagePr", NS).set("width", "60000")
    else:
        header = parse_xml(doc._entries["Contents/header.xml"])
        para = header.xpath(".//hh:paraPr[@id=$id]", namespaces=NS, id=p.get("paraPrIDRef"))[0]
        para.find("hh:align", NS).set("horizontal", "RIGHT")
        doc._entries["Contents/header.xml"] = ET.tostring(header)
    with pytest.raises(ComposeError, match="TD3 initial"):
        register_td3_initial_chapters(doc, profile)


@pytest.mark.corpus
@pytest.mark.parametrize("failure", ["body_text", "body_order", "body_control", "body_count", "profile", "missing_registry"])
def test_td3_generated_prose_registry_cannot_silently_lose_owner_or_scope(failure):
    profile = json.loads(PROFILE.read_text())
    doc = TemplateDocument(pinned_source_path(profile))
    registry = register_td3_initial_chapters(doc, profile)
    rec = registry["standards"]
    doc.set_paragraph_text(rec["heading"], "1. 화면 표준(합성 소유자 시험)")
    rec["expected_heading_text"] = own_text(rec["heading"])
    p = doc.new_paragraph("합성 산문 소유자", prototype=rec["heading"])
    rec["heading"].addnext(p)
    rec["body"] = [p]
    rec["expected_body_texts"] = [own_text(p)]
    doc._editorial_body_paragraphs = {p}
    _prepare_td3_initial_typography(doc, profile)
    if failure == "body_text":
        doc.set_paragraph_text(p, "소유자 문자열 변경")
    elif failure == "body_order":
        p.getparent().append(p)
    elif failure == "body_control":
        ET.SubElement(p.find("hp:run", NS), "{" + NS["hp"] + "}ctrl")
    elif failure == "body_count":
        rec["body"].clear()
    elif failure == "profile":
        profile["targets"]["body_height_hwp"] = 900
    else:
        del doc._editorial_td3_initial_chapters
    with pytest.raises(ComposeError, match="TD3 initial"):
        _prepare_td3_initial_typography(doc, profile)


@pytest.mark.corpus
@pytest.mark.parametrize("prefix", ["2026년도", "2024년"])
def test_existing_cover_year_does_not_falsely_bind_structural_year_to_cover(tmp_path, prefix):
    data = _relocated_input()
    data["project"]["program_name"] = prefix + " 합성 사업명"
    data["project"]["program_year"] = 2026
    source = tmp_path / "input.json"
    source.write_text(json.dumps(data, ensure_ascii=False))
    item = generate_project(source, tmp_path / "generated", roles=["SF-AD2"], style_profile="reference-v1")["documents"][0]
    identity = item["editorial_profile"]["cover_program_identity"]
    assert identity["text"] == data["project"]["program_name"]
    assert identity["expressed_input_pointers"] == ["/project/program_name"]
    assert identity["program_year_field_expressed_by_composition"] is False
    doc = TemplateDocument(item["path"])
    p = doc.xml(identity["owner"]["section"]).xpath(identity["owner"]["xpath"], namespaces=NS)[0]
    assert own_text(p) == identity["text"]
    meaning = json.loads(Path(item["meaning_map"]["path"]).read_text())
    field = next(f for e in meaning["entities"] for f in e["fields"] if f["input_pointer"] == "/project/program_year")
    assert field["input_value"] == 2026 and field["input_type"] == "int"
    assert all(o["xpath"] != identity["owner"]["xpath"] for o in field["owners"])


@pytest.mark.corpus
def test_default_prepare_does_not_change_cover_program_or_invent_date():
    profile = json.loads(PROFILE.read_text())
    doc = TemplateDocument(pinned_source_path(profile))
    data = json.loads(INPUT.read_text())
    selector = profile["cover_selectors"]["program"]["template"]
    p = doc.root(0).xpath(selector["xpath"], namespaces=NS)[0]
    before = ET.tostring(p, method="c14n")
    _prepare(doc, "SF-TD3", data, editorial=False)
    assert ET.tostring(p, method="c14n") == before
    assert not hasattr(doc, "_editorial_cover_program_identity")
