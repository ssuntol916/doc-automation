"""Source-specific case continuation and neutral generated-appendix regressions."""
from copy import deepcopy
import json
from pathlib import Path

from lxml import etree as ET
from corpus_sources import pinned_source_path
import pytest

from doc_automation import renderers
from doc_automation.compose import ComposeError, TemplateDocument
from doc_automation.hwpx import NS, own_text, parse_xml
from doc_automation.management_roles import load_contract
from doc_automation.testing_roles import prepare_case_cards, stale_guide_restart

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "examples/style-upgrade/illustrated-extended-v2/illustrated.project.json"
HP = "{" + NS["hp"] + "}"


def profile(role):
    return json.loads((ROOT / "resources/style-upgrade/profiles" / (role + ".json")).read_text())


def paragraph_style(doc, paragraph):
    return doc.xml("Contents/header.xml").xpath(".//hh:paraPr[@id=$id]", namespaces=NS,
                                               id=paragraph.get("paraPrIDRef"))[0]


@pytest.fixture(scope="module")
def case_outputs(tmp_path_factory):
    folder = tmp_path_factory.mktemp("case-card-flow")
    data = json.loads(INPUT.read_text())
    # The copied JSON resolves its inputs from the temporary directory, so
    # preserve each provided source/attachment location before relocation.
    for collection in ("sources", "attachments"):
        for record in data[collection]:
            if record.get("path"):
                path = Path(record["path"]).expanduser()
                record["path"] = str(path.resolve() if path.is_absolute()
                                     else (INPUT.parent / path).resolve())
    first = next(case for case in data["test_cases"] if case["stage"] == "integration")
    second = deepcopy(first)
    second.update(id="SYNTHETIC-INTEGRATION-CASE02", name="합성 장문 계속 페이지 검증",
                  scenario="합성 보존 회귀용 장문. " * 180)
    data["test_cases"].append(second)
    for stage in ("integration", "acceptance"):
        for case in (c for c in data["test_cases"] if c["stage"] == stage):
            case["group_id"] = "SYNTHETIC-SHARED-" + stage
            case.pop("case_number", None)
    # One explicitly owned flow image must not be copied to the second case.
    first["flow_attachment_ids"] = [data["attachments"][1]["id"]]
    data["test_cases"][-1]["flow_attachment_ids"] = []
    source = folder / "input.json"
    source.write_text(json.dumps(data, ensure_ascii=False))
    output = renderers.generate_project(source, folder / "generated", roles=["SF-TI1", "SF-TI4"],
        style_profile="reference-v1", raster_metadata_profile="hancom-mac-12.30.0-png")
    return data, {row["role"]: row for row in output["documents"]}


@pytest.mark.corpus
@pytest.mark.parametrize("role,stage,start", [("SF-TI1", "integration", 4), ("SF-TI4", "acceptance", 3)])
def test_each_case_has_source_card_and_full_identity_in_repeated_header(case_outputs, role, stage, start):
    data, outputs = case_outputs
    item = outputs[role]
    doc = TemplateDocument(item["path"])
    cases = [case for case in data["test_cases"] if case["stage"] == stage]
    cards = [t for t in doc.tables(1) if t.get("colCnt") == "7"
             and len(t.find("hp:tr", NS).findall("hp:tc", NS)) < 7]
    assert len(cards) == len(cases)
    for number, (card, case) in enumerate(zip(cards, cases), 1):
        assert card.get("pageBreak") == "CELL" and card.find("hp:pos", NS).get("treatAsChar") == "0"
        header_rows = card.findall("hp:tr", NS)[:start]
        assert len(header_rows) == start
        assert all(cell.get("header") == "1" for row in header_rows for cell in row.findall("hp:tc", NS))
        identity = "\n".join(own_text(p) for p in doc.cell(card, 1 if stage == "integration" else 0, 1).iter(HP + "p"))
        assert case["group_id"] in identity and case["id"] in identity
        body = "\n".join(own_text(p) for p in doc.cell(card, start, 0).iter(HP + "p"))
        assert body.startswith(f"{number}. {case['id']} ") and case["scenario"] in body
    meaning = json.loads(Path(item["meaning_map"]["path"]).read_text())
    for entity in meaning["entities"]:
        if entity.get("entity_id") not in {case["id"] for case in cases}:
            continue
        for field in entity["fields"]:
            pointer = field["input_pointer"].split("/")
            value = data[pointer[1]][int(pointer[2])][pointer[3]]
            assert field["input_value"] == value and field["input_type"] == type(value).__name__
            if pointer[3] in {"id", "name", "scenario", "data", "expected"}:
                assert field["owners"]
                for owner in field["owners"]:
                    found = doc.xml(owner["section"]).xpath(owner["xpath"], namespaces=meaning["xml_namespaces"])
                    assert len(found) == 1 and any(found[0] in card.iter() for card in cards)
    if role == "SF-TI1":
        assert len(item["image_bindings"]) == 1 and item["image_bindings"][0]["entity_id"] == cases[0]["id"]


@pytest.mark.corpus
@pytest.mark.parametrize("role", ["SF-TI1", "SF-TI4"])
@pytest.mark.parametrize("drift", ["source", "owner", "table"])
def test_case_card_source_guard_rejects_fingerprint_owner_and_shape_drift(role, drift):
    spec = profile(role)
    doc = TemplateDocument(pinned_source_path(spec))
    table = doc.tables(1)[0]
    prepare_case_cards(doc, role, table)
    if drift == "source":
        doc.source_sha256 = "0" * 64
    elif drift == "owner":
        table = doc.clone_paragraph(table.getparent().getparent()).find(".//hp:tbl", NS)
    else:
        table.find("hp:pos", NS).set("treatAsChar", "1")
    with pytest.raises(ComposeError, match="Testing case-card"):
        prepare_case_cards(doc, role, table)


@pytest.mark.corpus
def test_ti1_exact_trailing_guide_restart_removed_while_body_start_survives(case_outputs):
    spec = profile("SF-TI1")
    doc = TemplateDocument(pinned_source_path(spec))
    source_path = Path(pinned_source_path(spec))
    source_bytes = source_path.read_bytes()
    source = doc.root(1)
    start, trailing = source.xpath("./hp:p[1] | ./hp:p[18]", namespaces=NS)
    assert not stale_guide_restart(doc, "SF-TI1", start)
    assert stale_guide_restart(doc, "SF-TI1", trailing)
    output = TemplateDocument(case_outputs[1]["SF-TI1"]["path"])
    numbers = output.root(1).findall(".//hp:newNum[@numType='PAGE']", NS)
    assert len(numbers) == 1 and numbers[0].get("num") == "1"
    assert source_path.read_bytes() == source_bytes
    trailing.find(".//hp:newNum", NS).set("num", "2")
    with pytest.raises(ComposeError, match="Testing guide restart"):
        stale_guide_restart(doc, "SF-TI1", trailing)


@pytest.mark.corpus
def test_registered_after_picture_caption_is_atomic_and_does_not_bind_next_figure(case_outputs):
    item = case_outputs[1]["SF-TI1"]
    doc = TemplateDocument(item["path"])
    binding = item["image_bindings"][0]
    caption = next(p for p in doc.root(1).iter(HP + "p") if own_text(p) == binding["caption"])
    assert caption.getprevious().find("hp:run/hp:pic", NS) is not None
    policy = paragraph_style(doc, caption).find("hh:breakSetting", NS)
    assert policy.get("keepLines") == "1" and policy.get("keepWithNext") == "0"
    assert paragraph_style(doc, caption.getprevious()).find("hh:breakSetting", NS).get("keepWithNext") == "1"


@pytest.mark.corpus
def test_pm2_source_attendee_indent_is_not_the_generated_appendix_prototype(tmp_path):
    source_spec = profile("SF-PM2")
    source = TemplateDocument(pinned_source_path(source_spec))
    load_contract(source, "SF-PM2")
    prototype = source._editorial_appendix_prototype
    assert own_text(prototype) == "" and prototype.get("paraPrIDRef") != source.tables(0)[-1].findall(".//hp:p", NS)[-1].get("paraPrIDRef")
    item = renderers.generate_project(INPUT, tmp_path / "generated", roles=["SF-PM2"], style_profile="reference-v1")["documents"][0]
    output = TemplateDocument(item["path"])
    attendee = output.cell(output.tables(1)[0], 7, 0).findall("hp:subList/hp:p", NS)[1]
    margins = paragraph_style(output, attendee)
    assert [p.get("value") for p in margins.findall(".//hc:left", NS)] == ["2276", "4552"]
    assert [p.get("value") for p in margins.findall(".//hc:intent", NS)] == ["-1948", "-3896"]
    table_owner = next(p for p in output.root(1) if p.find(".//hp:tbl", NS) is not None)
    appendix = list(output.root(1))[list(output.root(1)).index(table_owner) + 1:]
    assert len(appendix) >= 30
    for p in appendix:
        style = paragraph_style(output, p)
        assert [v.get("value") for v in style.findall(".//hc:left", NS)] == ["0", "0"]
        assert [v.get("value") for v in style.findall(".//hc:intent", NS)] == ["0", "0"]


@pytest.mark.corpus
def test_pm2_optional_appendix_constructors_also_use_neutral_source_prototype():
    from doc_automation.narrative import SourceNotes
    data = json.loads(INPUT.read_text())
    doc = TemplateDocument(pinned_source_path(profile("SF-PM2")))
    load_contract(doc, "SF-PM2")
    doc._editorial_heading_paragraphs = set()
    root = doc.root(0)
    original_children = set(root)
    review = data["reviews"][0]
    attachment = data["attachments"][1]
    ctx = {"editorial": True, "additional_review_bindings": [("SYNTHETIC-CHECK", [review["id"]])],
           "attachment_notes": {attachment["id"]: {"key": "A1", "attachment": attachment,
              "usages": [{"entity_id": "SYNTHETIC-CHECK", "entity_name": "합성 회귀", "slot_label": "검토 그림"}]}}}
    renderers._append_attachment_notes(doc, ctx)
    renderers._append_linked_review_notes(doc, data, ctx)
    added = [p for p in root if p not in original_children]
    assert any("[A1]" in own_text(p) for p in added) and any("[RV1]" in own_text(p) for p in added)
    for paragraph in added:
        style = paragraph_style(doc, paragraph)
        assert [v.get("value") for v in style.findall(".//hc:left", NS)] == ["0", "0"]
        assert [v.get("value") for v in style.findall(".//hc:intent", NS)] == ["0", "0"]


@pytest.mark.corpus
@pytest.mark.parametrize("kind", ["left", "intent", "protected"])
def test_pm2_neutral_prototype_rejects_source_margin_or_object_drift(kind):
    spec = profile("SF-PM2")
    doc = TemplateDocument(pinned_source_path(spec))
    selector = spec["management_character_role_sources"]["meeting_special_notes_value"]["source"]
    if kind == "protected":
        root = parse_xml(doc._entries[selector["xml"]])
        p = root.xpath(selector["xpath"], namespaces=NS)[0]
        ET.SubElement(p.find("hp:run", NS), HP + "ctrl")
        doc._entries[selector["xml"]] = ET.tostring(root)
    else:
        root = parse_xml(doc._entries["Contents/header.xml"])
        p = parse_xml(doc._entries[selector["xml"]]).xpath(selector["xpath"], namespaces=NS)[0]
        definition = root.xpath(".//hh:paraPr[@id=$id]", namespaces=NS, id=p.get("paraPrIDRef"))[0]
        definition.find(".//hc:" + kind, NS).set("value", "1")
        doc._entries["Contents/header.xml"] = ET.tostring(root)
    with pytest.raises(ComposeError, match="Management appendix"):
        load_contract(doc, "SF-PM2")


def test_detail_view_profile_requirement_precedes_any_output_mutation(tmp_path, monkeypatch):
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"dataset_kind": "synthetic", "project": {}, "test_cases": [{
        "reference_result_quotations": [{"detail_regions": [{"label": "synthetic", "box_pixels": [1, 1, 2, 2]}]}]}]}))
    monkeypatch.setattr(renderers, "validate_project", lambda *args, **kwargs: {"errors": []})
    target = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="detail_regions requires.*before output generation"):
        renderers.generate_project(source, target, roles=["SF-TI1"])
    assert not target.exists()


@pytest.mark.parametrize("viewport", [None, [1, 2, 17, 23]])
def test_pending_picture_viewport_is_passed_without_reinterpreting_coordinates(viewport):
    root = ET.Element("{" + NS["hs"] + "}sec")
    p = ET.SubElement(root, HP + "p")
    sec = ET.SubElement(ET.SubElement(p, HP + "run"), HP + "secPr")
    page = ET.SubElement(sec, HP + "pagePr", width="59528", height="84188", landscape="WIDELY")
    ET.SubElement(page, HP + "margin", left="5102", right="5102", top="4252", bottom="4252", gutter="0")
    target = ET.SubElement(root, HP + "p")
    calls = []
    class Doc:
        sections = ["Contents/section0.xml"]
        def root(self, index):
            return root
        def insert_picture(self, paragraph, data, **kwargs):
            calls.append(kwargs)
            picture = ET.Element(HP + "pic")
            ET.SubElement(picture, HP + "curSz", width="1000", height="500")
            return picture
    ctx = {"editorial": True, "raster_metadata_profile": "hancom-mac-12.30.0-png", "_pending_images": [{
        "paragraph": target, "bytes": b"synthetic-call-fixture", "media_type": "image/png", "pixels": (32, 32),
        "binding": {"caption": "synthetic fixture"}, "viewport_pixels": viewport}]}
    renderers._materialize_images(Doc(), ctx)
    assert calls[0]["viewport_pixels"] is viewport
