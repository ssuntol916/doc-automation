"""Historical quotations prove source bytes/ownership, never a new event."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from zipfile import ZipFile

from lxml import etree as ET
from PIL import Image
import pytest

from doc_automation.business import validate_project
from doc_automation.hwpx import NS, own_text
from doc_automation import quotations as Q
from doc_automation.renderers import generate_project, _supported_inputs


ROOT = Path(__file__).resolve().parents[1]


def _profile(quote):
    return {**{key: quote[key] for key in Q._PROFILE_KEYS},
            "historical_owner_sha256": Q.canonical_digest(quote["historical_owner"]),
            "document_role": quote["historical_owner"]["document_role"]}


@pytest.fixture
def quotation(tmp_path, monkeypatch):
    data = json.loads((ROOT / "examples/demo-suite.project.json").read_text())
    for domain in ("sources", "attachments"):
        for entry in data[domain]:
            entry["path"] = str((ROOT / "examples" / entry["path"]).resolve())
    image_path = tmp_path / "historical-synthetic.bmp"
    Image.new("RGB", (64, 16), "#276fa2").save(image_path)
    raw = image_path.read_bytes()
    root = ET.Element(f"{{{NS['hs']}}}sec", nsmap={key: NS[key] for key in ("hs", "hp", "hc")})
    paragraph = ET.SubElement(root, f"{{{NS['hp']}}}p")
    table = ET.SubElement(ET.SubElement(paragraph, f"{{{NS['hp']}}}run"), f"{{{NS['hp']}}}tbl")
    cells = []
    literals = ["SYNTHETIC-GROUP", "합성 원문 그룹", "1) 합성 케이스"]
    for index, text in enumerate(literals):
        row = ET.SubElement(table, f"{{{NS['hp']}}}tr")
        cell = ET.SubElement(row, f"{{{NS['hp']}}}tc")
        ET.SubElement(cell, f"{{{NS['hp']}}}cellAddr", rowAddr=str(index), colAddr="0")
        p = ET.SubElement(ET.SubElement(cell, f"{{{NS['hp']}}}subList"), f"{{{NS['hp']}}}p")
        t = ET.SubElement(ET.SubElement(p, f"{{{NS['hp']}}}run"), f"{{{NS['hp']}}}t")
        t.text = text
        if index == 2:
            ET.SubElement(t, f"{{{NS['hp']}}}tab").tail = "꼬리 텍스트"
        cells.append(cell)
    pic = ET.SubElement(cells[-1].find("hp:subList/hp:p/hp:run", NS), f"{{{NS['hp']}}}pic")
    ET.SubElement(pic, f"{{{NS['hc']}}}img", binaryItemIDRef="source-image")
    opf = ET.Element(f"{{{NS['opf']}}}package", nsmap={"opf": NS["opf"]})
    manifest = ET.SubElement(opf, f"{{{NS['opf']}}}manifest")
    ET.SubElement(manifest, f"{{{NS['opf']}}}item", id="section", href="section0.xml")
    ET.SubElement(manifest, f"{{{NS['opf']}}}item", id="source-image", href="BinData/source.bmp")
    ET.SubElement(ET.SubElement(opf, f"{{{NS['opf']}}}spine"), f"{{{NS['opf']}}}itemref", idref="section")
    source_path = tmp_path / "historical-synthetic.hwpx"
    with ZipFile(source_path, "w") as package:
        package.writestr("Contents/content.hpf", ET.tostring(opf))
        package.writestr("Contents/section0.xml", ET.tostring(root))
        package.writestr("BinData/source.bmp", raw)
    identity = []
    for cell in cells:
        texts = [own_text(p) for p in cell.findall("hp:subList/hp:p", NS)]
        identity.append({"xml_member": "Contents/section0.xml", "xpath": root.getroottree().getpath(cell),
                         "cell_address": dict(cell.find("hp:cellAddr", NS).attrib),
                         "paragraph_owned_texts": texts, "text_verbatim": "\n".join(texts)})
    quote = {"attachment_id": "SYNTHETIC-HISTORICAL-QUOTE",
             "quotation_kind": "historical_test_result", "scope": "historical_reference_only",
             "source_document_id": "SYNTHETIC-HISTORICAL-SOURCE",
             "source_document_sha256": sha256(source_path.read_bytes()).hexdigest(),
             "source_xml": "Contents/section0.xml", "source_picture_xpath": root.getroottree().getpath(pic),
             "source_binary_item_id": "source-image", "source_binary_member": "BinData/source.bmp",
             "source_binary_sha256": sha256(raw).hexdigest(), "source_pixel_sha256": Q.pixel_digest(raw)[0],
             "historical_owner": {"document_role": "SF-TI1", "owner_kind": "test_case_result_cell",
                                  "group_id_literal": literals[0], "group_name_literal": literals[1],
                                  "case_number": 1, "case_label_literal": literals[2], "identity_refs": identity}}
    data["sources"].append({"id": quote["source_document_id"], "title": "합성 역사적 원문",
                            "kind": "reference_document", "path": str(source_path),
                            "sha256": quote["source_document_sha256"], "verification_status": "provided",
                            "document_role": "SF-TI1"})
    data["attachments"].append({"id": quote["attachment_id"], "name": "합성 원문 인용",
                                "status": "provided", "verification_status": "provided", "source_refs": [],
                                "path": str(image_path), "sha256": quote["source_binary_sha256"],
                                "source_id": quote["source_document_id"], "media_type": "image/bmp",
                                "purpose": "historical_reference_quotation_only", "caption": "긴 원문 캡션 " * 30})
    parent = next(item for item in data["test_cases"] if item["stage"] == "integration")
    parent["reference_result_quotations"] = [quote]
    profile = _profile(quote)
    monkeypatch.setattr(Q, "_profiles", lambda: [profile])
    return data, parent, quote, profile


def _errors(data):
    return validate_project(data)["errors"]


def test_quotation_verifies_exact_source_owner_inline_tail_and_pixels(quotation):
    data, parent, quote, _ = quotation
    before = deepcopy(parent)
    report = validate_project(data)
    assert report["errors"] == []
    checked = report["summary"]["reference_quotation_checks"][0]
    assert checked["pixels"] == (64, 16)
    assert checked["source_owned_paragraphs_read"] == 4
    assert "\t꼬리 텍스트" in quote["historical_owner"]["identity_refs"][-1]["text_verbatim"]
    assert parent == before and report["submission_ready"] is False


@pytest.mark.parametrize("change", ["unknown-key", "wrong-kind", "wrong-scope", "owner-literal", "owner-role", "pixel-sha", "source-xpath"])
def test_closed_slot_contract_rejects_incorrect_or_relabelled_provenance(quotation, change):
    data, _, quote, _ = quotation
    if change == "unknown-key": quote["executed"] = True
    elif change == "wrong-kind": quote["quotation_kind"] = "historical_installation_photo"
    elif change == "wrong-scope": quote["scope"] = "new_execution"
    elif change == "owner-literal": quote["historical_owner"]["group_name_literal"] = "변경한 원문"
    elif change == "owner-role": quote["historical_owner"]["document_role"] = "SF-TI4"
    elif change == "pixel-sha": quote["source_pixel_sha256"] = "0" * 64
    else: quote["source_picture_xpath"] += "[2]"
    assert _errors(data)


def test_original_source_and_asset_bytes_are_required(quotation):
    data, _, quote, _ = quotation
    source = data["sources"][-1]
    Path(source["path"]).write_bytes(b"changed supplied package")
    assert any(e["code"] == "REFERENCE_QUOTATION_INVALID" for e in _errors(data))
    assert quote["source_document_sha256"] != sha256(Path(source["path"]).read_bytes()).hexdigest()


@pytest.mark.parametrize("change", ["opf-id", "opf-member", "identity-address", "identity-tail"])
def test_source_internals_are_checked_in_addition_to_digest_allowlist(quotation, change):
    data, _, quote, profile = quotation
    source = data["sources"][-1]
    path = Path(source["path"])
    with ZipFile(path) as package:
        members = {name: package.read(name) for name in package.namelist()}
    if change.startswith("opf"):
        opf = ET.fromstring(members["Contents/content.hpf"])
        item = opf.findall("opf:manifest/opf:item", NS)[1]
        item.set("id" if change == "opf-id" else "href", "wrong")
        members["Contents/content.hpf"] = ET.tostring(opf)
    else:
        section = ET.fromstring(members["Contents/section0.xml"])
        cell = section.xpath(quote["historical_owner"]["identity_refs"][-1]["xpath"], namespaces=NS)[0]
        if change == "identity-address": cell.find("hp:cellAddr", NS).set("rowAddr", "10")
        else: cell.find("hp:subList/hp:p/hp:run/hp:t/hp:tab", NS).tail = "다른 tail"
        members["Contents/section0.xml"] = ET.tostring(section)
    with ZipFile(path, "w") as package:
        for name, raw in members.items(): package.writestr(name, raw)
    # A newly declared synthetic package hash alone cannot replace internal checks.
    source["sha256"] = quote["source_document_sha256"] = sha256(path.read_bytes()).hexdigest()
    profile["source_document_sha256"] = source["sha256"]
    assert any(e["code"] == "REFERENCE_QUOTATION_INVALID" for e in _errors(data))


@pytest.mark.parametrize("reuse", ["same-id-evidence", "same-id-flow", "same-sha-copy", "reencoded-pixels", "deliverable-role", "tiff-pixels", "gif-pixels", "octet-stream-pixels"])
def test_quotation_payload_cannot_be_reused_as_current_evidence_or_flow(quotation, tmp_path, reuse):
    data, parent, quote, _ = quotation
    field = "flow_attachment_ids" if reuse == "same-id-flow" else "evidence_ids"
    if reuse.startswith("same-id"):
        parent[field] = [quote["attachment_id"]]
    else:
        duplicate = deepcopy(data["attachments"][-1])
        duplicate.update(id="NEW-EVIDENCE-LABEL", purpose="new execution evidence")
        if reuse == "deliverable-role":
            duplicate["document_role"] = "SF-TI1"
        if reuse in {"reencoded-pixels", "tiff-pixels", "gif-pixels", "octet-stream-pixels"}:
            fmt, mime = {"tiff-pixels": ("TIFF", "image/tiff"),
                         "gif-pixels": ("GIF", "image/gif"),
                         "octet-stream-pixels": ("PNG", "application/octet-stream")}.get(reuse, ("PNG", "image/png"))
            path = tmp_path / ("same-pixels." + fmt.lower())
            with Image.open(duplicate["path"]) as image: image.save(path, format=fmt)
            duplicate.update(path=str(path), media_type=mime, sha256=sha256(path.read_bytes()).hexdigest())
        data["attachments"].append(duplicate)
        if reuse != "deliverable-role":
            parent[field] = [duplicate["id"]]
    assert any(e["code"] == "REFERENCE_QUOTATION_INVALID" for e in _errors(data))


def test_raw_test_data_homonyms_are_not_quotation_or_evidence_slots(quotation):
    data, parent, quote, _ = quotation
    parent["data"] = {"reference_result_quotations": [{"not": "a slot"}], "evidence_ids": [quote["attachment_id"]]}
    assert _errors(data) == []
    assert len(list(Q.entries(data))) == 1


def test_detail_regions_require_source_pixel_bounds_and_local_provenance(quotation):
    data, _, quote, _ = quotation
    quote["detail_regions"] = [{"label": "원본 경계 밖", "box_pixels": [0, 0, 65, 10]}]
    errors = _errors(data)
    assert any("detail_regions" in str(error) for error in errors)
    quote["detail_regions"] = [{"label": "합성 원문의 부분 보기", "box_pixels": [0, 0, 20, 10]}]
    checked = validate_project(data)
    assert checked["errors"] == []
    assert checked["summary"]["reference_quotation_checks"][0]["detail_regions"] == quote["detail_regions"]
    quote["detail_regions"] = []
    assert _errors(data) == []
    assert validate_project(data, verify_files=False)["errors"]


@pytest.mark.parametrize("region", [
    {"label": "", "box_pixels": [0, 0, 20, 10]},
    {"label": " ", "box_pixels": [0, 0, 20, 10]},
    {"label": "전체를 다시 요청", "box_pixels": [0, 0, 64, 16]},
    {"label": "빈 폭", "box_pixels": [3, 2, 3, 10]},
    {"label": "역전", "box_pixels": [20, 10, 3, 2]},
    {"label": "음수", "box_pixels": [-1, 0, 20, 10]},
    {"label": "bool 좌표", "box_pixels": [False, 0, 20, 10]},
    {"label": "추정 보정 금지", "box_pixels": [0, 0, 20, 10], "enhance": True},
])
def test_detail_regions_reject_ambiguous_or_nonpixel_declarations(quotation, region):
    data, parent, quote, _ = quotation
    quote["detail_regions"] = [region]
    pointer = next(Q.entries(data))[0]
    with pytest.raises(ValueError, match="detail_regions"):
        Q.verify_quotation(data, pointer, parent, quote, ROOT)


def test_detail_regions_do_not_duplicate_rectangles_or_mutate_supplied_values(quotation):
    data, parent, quote, _ = quotation
    quote["detail_regions"] = [{"label": "두 끝 경계 포함", "box_pixels": [32, 8, 64, 16]}]
    before = deepcopy(data)
    pointer = next(Q.entries(data))[0]
    checked = Q.verify_quotation(data, pointer, parent, quote, ROOT)
    assert checked["detail_regions"] == quote["detail_regions"] and data == before
    quote["detail_regions"].append({"label": "동일 영역의 다른 이름", "box_pixels": [32, 8, 64, 16]})
    with pytest.raises(ValueError, match="duplicate"):
        Q.verify_quotation(data, pointer, parent, quote, ROOT)


def test_detail_register_keeps_whole_first_exact_owners_and_unmodified_source_payload(quotation, tmp_path):
    from doc_automation.compose import TemplateDocument, HANCOM_MAC_12_30_PNG_METADATA
    from doc_automation.renderers import _materialize_images
    data, parent, quote, _ = quotation
    quote["detail_regions"] = [{"label": "합성 부분 보기", "box_pixels": [32, 4, 64, 16]}]
    original_data = deepcopy(data)
    fixture_root = ROOT / "tests/fixtures/synthetic"
    host = tmp_path / "host.hwpx"
    with ZipFile(host, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        for name in ("header.xml", "section0.xml", "content.hpf"):
            payload = (fixture_root / name).read_bytes()
            if name == "header.xml":
                header = ET.fromstring(payload)
                for para in header.findall(".//hh:paraPr", NS):
                    ET.SubElement(para, f"{{{NS['hh']}}}align", horizontal="LEFT", vertical="BASELINE")
                    ET.SubElement(para, f"{{{NS['hh']}}}breakSetting", breakLatinWord="BREAK_WORD",
                                  breakNonLatinWord="BREAK_WORD", keepLines="0", keepWithNext="0")
                payload = ET.tostring(header)
            archive.writestr("Contents/" + name, payload)
    host_bytes = host.read_bytes()
    doc = TemplateDocument(host)
    original_paragraphs = [ET.tostring(p, method="c14n") for p in list(doc.root())]
    for name in ("heading", "caption", "picture", "body"):
        setattr(doc, "_editorial_" + name + "_paragraphs", set())
    ctx = {"input_dir": ROOT, "editorial": True,
           "raster_metadata_profile": HANCOM_MAC_12_30_PNG_METADATA}
    Q.append_reference_quotations(doc, "SF-TI1", data, ctx)
    bindings = ctx["image_bindings"]
    assert len(bindings) == 2 and bindings[0]["crop"] == "none"
    assert bindings[1]["viewport_pixels_ltrb"] == [32, 4, 64, 16]
    assert bindings[1]["quotation_parent_key"] == "Q1"
    assert bindings[1]["quotation_detail_key"] == "Q1.D1"
    assert bindings[1]["whole_original_view_retained"] is True
    assert bindings[0]["embedded_sha256"] == bindings[1]["embedded_sha256"]
    assert all(parent["id"] in binding["caption"] and Q.DISCLOSURE in binding["caption"] for binding in bindings)
    fields = ctx["meaning_map"][0]["fields"]
    detail_label = next(field for field in fields if field["input_pointer"].endswith("/detail_regions/0/label"))
    detail_box = next(field for field in fields if field["input_pointer"].endswith("/detail_regions/0/box_pixels"))
    assert detail_label["input_value"] == "합성 부분 보기"
    assert detail_box["input_value"] == [32, 4, 64, 16]
    assert "[32, 4, 64, 16]" in own_text(detail_box["_primary_paragraphs"][0])
    _materialize_images(doc, ctx)
    owners = Q.finalize_quotation_owners(doc, ctx)
    assert [owner["key"] for owner in owners] == ["Q1", "Q1.D1"]
    for owner in owners:
        for kind in ("picture", "caption"):
            record = owner["owners"][kind]
            node = doc.xml(record["section"]).xpath(record["xpath"], namespaces=NS)[0]
            assert node is not None
    assert original_paragraphs == [ET.tostring(p, method="c14n") for p in list(doc.root())[:len(original_paragraphs)]]
    assert data == original_data and host.read_bytes() == host_bytes
    result = doc.save(tmp_path / "detail.hwpx")
    assert result["package_validation"]["valid"]
    with ZipFile(result["output_path"]) as archive:
        opf = ET.fromstring(archive.read("Contents/content.hpf"))
        for pending in ctx["_pending_images"]:
            picture = pending["paragraph"].find("hp:run/hp:pic", NS)
            bid = picture.find("hc:img", NS).get("binaryItemIDRef")
            item = next(item for item in opf.iter()
                        if item.tag.rsplit("}", 1)[-1] == "item" and item.get("id") == bid)
            assert Q.pixel_digest(archive.read(item.get("href")))[0] == quote["source_pixel_sha256"]


def test_generation_requires_viewport_profile_before_creating_output(quotation, tmp_path):
    data, _, quote, _ = quotation
    quote["detail_regions"] = [{"label": "합성 부분 보기", "box_pixels": [0, 0, 32, 8]}]
    source = tmp_path / "input-with-detail.json"
    source.write_text(json.dumps(data, ensure_ascii=False))
    output = tmp_path / "not-created"
    with pytest.raises(ValueError, match="detail_regions"):
        generate_project(source, output, roles=["SF-TI1"])
    assert not output.exists()


def test_explicit_role_selection_cannot_silently_omit_quote(quotation):
    data, _, _, _ = quotation
    _supported_inputs(data, ["SF-TI1"])
    with pytest.raises(ValueError, match="historical quotations require"):
        _supported_inputs(data, ["SF-TI2"])


def test_empty_quotation_fields_do_not_touch_document():
    class NoMutation:
        def __getattr__(self, name):
            raise AssertionError("Empty quotation path must not touch document: " + name)
    data = {"test_cases": [{"stage": "integration", "reference_result_quotations": []}], "deployment_items": []}
    Q.append_reference_quotations(NoMutation(), "SF-TI1", data, {})
    Q.assert_quotation_files_stable({})
    Q.reject_quotation_output_collisions(data, Path("."), [])


@pytest.mark.parametrize("alias", ["lexical", "symlink", "hardlink"])
def test_collision_preflight_covers_aliases_without_touching_inputs(quotation, tmp_path, alias):
    data, _, _, _ = quotation
    source = Path(data["sources"][-1]["path"])
    before = source.read_bytes()
    target = tmp_path / "output.hwpx"
    if alias == "lexical": target = source
    elif alias == "symlink": target.symlink_to(source)
    else: target.hardlink_to(source)
    with pytest.raises(ValueError, match="aliases a planned output"):
        Q.reject_quotation_output_collisions(data, tmp_path, [target])
    assert source.read_bytes() == before


@pytest.mark.corpus
@pytest.mark.parametrize("collision", ["hwpx", "manifest", "profile", "meaning", "sources"])
def test_generation_rejects_planned_write_collisions_before_mutation(quotation, tmp_path, collision):
    data, _, _, _ = quotation
    output = tmp_path / "generated"
    target = output / "SF-TI1_통합테스트결과서_검증용.hwpx"
    path = {"hwpx": target, "manifest": output / "manifest.json",
            "profile": output / "profiles/SF-TI1.json", "meaning": target.with_suffix(".meaning.json"),
            "sources": target.with_suffix(".sources.json")}[collision]
    record = data["sources"][-1] if collision != "manifest" else data["attachments"][-1]
    original = Path(record["path"]).read_bytes()
    path.parent.mkdir(parents=True)
    path.write_bytes(original)
    record["path"] = str(path)
    input_path = tmp_path / "project.json"
    input_path.write_text(json.dumps(data, ensure_ascii=False))
    before = {str(p): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="aliases a planned output"):
        generate_project(input_path, output, roles=["SF-TI1"], style_profile="reference-v1")
    assert {str(p): p.read_bytes() for p in output.rglob("*") if p.is_file()} == before


@pytest.mark.corpus
def test_owned_stale_companion_cleanup_cannot_delete_quotation_input(quotation, tmp_path):
    data, _, _, _ = quotation
    output = tmp_path / "generated"
    output.mkdir()
    attachment = data["attachments"][-1]
    retained = output / "previous-owned-companion.bmp"
    retained.write_bytes(Path(attachment["path"]).read_bytes())
    attachment["path"] = str(retained)
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps({"companions": [{"path": str(retained), "sha256": attachment["sha256"]}]}))
    input_path = tmp_path / "project.json"
    input_path.write_text(json.dumps(data, ensure_ascii=False))
    before = {str(p): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="aliases a planned output"):
        generate_project(input_path, output, roles=["SF-TI1", "SF-TD5"])
    assert {str(p): p.read_bytes() for p in output.rglob("*") if p.is_file()} == before


@pytest.mark.corpus
@pytest.mark.parametrize("changed", ["source", "bitmap"])
@pytest.mark.parametrize("boundary", ["save", "manifest"])
def test_save_boundary_source_drift_fails_without_publishing_output(quotation, tmp_path, monkeypatch, changed, boundary):
    from doc_automation.compose import TemplateDocument
    data, _, _, _ = quotation
    input_path = tmp_path / "project.json"
    input_path.write_text(json.dumps(data, ensure_ascii=False))
    save = TemplateDocument.save
    watched = Path(data["sources"][-1]["path"] if changed == "source" else data["attachments"][-1]["path"])

    def drift_then_save(doc, target):
        watched.write_bytes(watched.read_bytes() + b"synthetic save-boundary drift")
        return save(doc, target)

    output = tmp_path / "generated"
    if boundary == "save":
        monkeypatch.setattr(TemplateDocument, "save", drift_then_save)
    else:
        write_text = Path.write_text

        def drift_at_manifest(path, text, *args, **kwargs):
            result = write_text(path, text, *args, **kwargs)
            if path == output / "manifest.json":
                watched.write_bytes(watched.read_bytes() + b"synthetic manifest-boundary drift")
            return result

        monkeypatch.setattr(Path, "write_text", drift_at_manifest)
    with pytest.raises(ValueError, match="Quotation source/bitmap changed before commit"):
        generate_project(input_path, output, roles=["SF-TI1"])
    assert list(output.glob("*.hwpx")) == []
    assert not (output / "manifest.json").exists()


def test_committed_registry_contains_hashes_and_locators_without_source_literals():
    rows = json.loads((ROOT / "src/doc_automation/quotation_sources.json").read_text())["entries"]
    assert len(rows) == 6
    allowed = {*Q._PROFILE_KEYS, "historical_owner_sha256", "document_role"}
    assert all(set(row) == allowed for row in rows)
    assert len({row["source_binary_sha256"] for row in rows}) == 4


@pytest.mark.corpus
@pytest.mark.parametrize("role", ["SF-TI1", "SF-TI2", "SF-TI4"])
@pytest.mark.parametrize("style", [None, "reference-v1"])
def test_six_real_source_instances_keep_pixels_disclosure_parent_and_unknowns(tmp_path, role, style):
    private_location = os.environ.get("DOC_AUTOMATION_PRIVATE_FIXTURE_ROOT")
    if not private_location:
        pytest.fail("Selected private corpus cases require DOC_AUTOMATION_PRIVATE_FIXTURE_ROOT; missing private input is not a skip")
    private_root = Path(private_location).expanduser().resolve()
    additions_path = private_root / "outputs/quality-loop/r08/reference-quotation-proposal/proposed-input-additions.json"
    if not additions_path.is_file():
        pytest.fail("The explicitly selected private quotation fixture is unavailable")
    additions = json.loads(additions_path.read_text())["roles"][role]
    base = Path(additions["base_input"]["path"])
    original_bytes = base.read_bytes()
    assert sha256(original_bytes).hexdigest() == additions["base_input"]["sha256"]
    data = json.loads(original_bytes)
    data["attachments"].extend(additions["attachments_to_append"])
    # A long supplied caption must not take the generic >88-character fallback
    # that would silently omit supplied text or the historical disclosure.
    data["attachments"][-1]["caption"] += " · 긴 제공 캡션 보존 검증" * 15
    for addition in additions["entity_field_additions"]:
        domain, index = addition["entity_pointer"].strip("/").split("/")
        data[domain][int(index)].setdefault(addition["field"], []).append(addition["quotation_to_append"])
    input_path = tmp_path / "quotation-variant.json"
    input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    output = generate_project(input_path, tmp_path / "generated", roles=[role], style_profile=style,
                              raster_metadata_profile="hancom-mac-12.30.0-png")["documents"][0]
    quotes = [binding for binding in output["image_bindings"] if binding.get("historical_reference_only")]
    assert len(quotes) == len(output["reference_quotations"]) == 2
    with ZipFile(output["path"]) as package:
        roots = {name: ET.fromstring(package.read(name)) for name in package.namelist()
                 if name.startswith("Contents/section") and name.endswith(".xml")}
        for binding in quotes:
            assert Q.DISCLOSURE in binding["caption"]
            assert binding["entity_id"] in binding["caption"] and binding["quotation_key"] in binding["caption"]
            picture_owner = binding["owners"]["picture"]
            p = roots[picture_owner["section"]].xpath(picture_owner["xpath"], namespaces=NS)[0]
            pic = p.find("hp:run/hp:pic", NS)
            assert pic is not None
            # Canonical pixels remain exact after BMP->PNG encoding. Input
            # result/installation fields and source files remain unchanged.
            assert binding["pixel_sha256"] in {q["source_pixel_sha256"] for _, _, q in Q.entries(data)}
            width, height = binding["width_hwp"], binding["height_hwp"]
            q = next(q for ptr, _, q in Q.entries(data) if ptr == binding["quotation_input_pointer"])
            check = Q.verify_quotation(data, binding["quotation_input_pointer"],
                                      next(parent for ptr, parent, _ in Q.entries(data) if ptr == binding["quotation_input_pointer"]), q, tmp_path)
            assert abs(width / height - check["pixels"][0] / check["pixels"][1]) < .002
            binary_id = pic.find("hc:img", NS).get("binaryItemIDRef")
            opf = ET.fromstring(package.read("Contents/content.hpf"))
            manifest_item = next(item for item in opf.findall("opf:manifest/opf:item", NS)
                                 if item.get("id") == binary_id)
            member = Q._member(manifest_item.get("href"), package.namelist())
            embedded = package.read(member)
            assert sha256(embedded).hexdigest() == binding["embedded_sha256"]
            with Image.open(BytesIO(embedded)) as result, Image.open(BytesIO(check["bytes"])) as source:
                assert result.size == source.size
                assert result.convert("RGBA").tobytes() == source.convert("RGBA").tobytes()
            caption_owner = binding["owners"]["caption"]
            caption_p = roots[caption_owner["section"]].xpath(caption_owner["xpath"], namespaces=NS)[0]
            assert own_text(caption_p) == binding["caption"]
        all_owned = [own_text(p) for section in roots.values() for p in section.iter(f"{{{NS['hp']}}}p")]
        assert any(data["attachments"][-1]["caption"] in text for text in all_owned)
    assert input_path.read_text() == json.dumps(data, ensure_ascii=False)
    assert base.read_bytes() == original_bytes
    assert output["submission_ready"] is False and output["native_review_status"] == "pending"
