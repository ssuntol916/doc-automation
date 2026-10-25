"""A source-owned organization chart belongs to the AD1 customer overview."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image
import pytest

from doc_automation.business import validate_project
from doc_automation.compose import TemplateDocument, HANCOM_MAC_12_30_PNG_METADATA
from doc_automation.hwpx import NS, own_text
from doc_automation.renderers import _image_groups, _supported_inputs, generate_project


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def org_input(tmp_path):
    data = json.loads((ROOT / "examples/demo-suite.project.json").read_text())
    for collection in ("sources", "attachments"):
        for entry in data[collection]:
            entry["path"] = str((ROOT / "examples" / entry["path"]).resolve())
    ids = []
    for number, color in enumerate(("#4d7892", "#83a46d"), 1):
        path = tmp_path / f"synthetic-org-{number}.png"
        Image.new("RGB", (320, 160), color).save(path)
        attachment = deepcopy(data["attachments"][0])
        aid = f"SYNTHETIC-ORG-{number}"
        attachment.update(id=aid, name=f"조직 역할 합성 시안 {number}", path=str(path),
            sha256=sha256(path.read_bytes()).hexdigest(), media_type="image/png",
            caption=f"조직 역할 합성 설계 {number} · 실제 회사 조직/임명 확인 아님",
            purpose="사업 입력의 가상 조직 역할도; 실제 조직·임명·승인 증거가 아님")
        data["attachments"].append(attachment)
        ids.append(aid)
    data["project"]["organization_chart_attachment_ids"] = ids
    path = tmp_path / "project.json"

    def write():
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    return data, write


def test_organization_chart_ids_are_typed_unique_attachment_references(org_input):
    data, _ = org_input
    assert validate_project(data)["errors"] == []
    for bad in (("missing-id",), ("SYNTHETIC-ORG-1", "SYNTHETIC-ORG-1"), (None,)):
        changed = deepcopy(data)
        changed["project"]["organization_chart_attachment_ids"] = list(bad)
        assert validate_project(changed)["errors"]


def test_organization_chart_has_only_the_explicit_ad1_role_and_project_pointer(org_input):
    data, _ = org_input
    project_group = _image_groups(data, "SF-AD1")[0]
    assert project_group == ("project", [data["project"]],
                             (("organization_chart_attachment_ids", "도입기업 조직도"),))
    _supported_inputs(data, ["SF-AD1"])
    for role in ("SF-AD2", "SF-TD1", "SF-TD2", "SF-TI3"):
        assert not any("organization_chart_attachment_ids" in dict(slots)
                       for _, _, slots in _image_groups(data, role))
        with pytest.raises(ValueError, match="/project/organization_chart_attachment_ids.*only for SF-AD1"):
            _supported_inputs(data, [role])


@pytest.mark.parametrize("mode", ["mime", "sha", "missing"])
def test_invalid_org_artifact_stops_before_output_mutation(org_input, tmp_path, mode):
    data, write = org_input
    attachment = data["attachments"][-1]
    if mode == "mime":
        attachment["media_type"] = "image/jpeg"
    elif mode == "sha":
        attachment["sha256"] = "0" * 64
    else:
        data["project"]["organization_chart_attachment_ids"] = ["missing-org"]
    output = tmp_path / "not-created"
    with pytest.raises(ValueError, match="MIME|HASH_MISMATCH|REFERENCE_MISSING"):
        generate_project(write(), output, roles=["SF-AD1"], style_profile="reference-v1")
    assert not output.exists()


@pytest.mark.corpus
@pytest.mark.parametrize("style", [None, "reference-v1"])
def test_org_pictures_keep_bytes_and_own_customer_overview(org_input, tmp_path, style):
    data, write = org_input
    source = write()
    input_bytes = source.read_bytes()
    result = generate_project(source, tmp_path / "generated", roles=["SF-AD1"],
        style_profile=style, raster_metadata_profile=HANCOM_MAC_12_30_PNG_METADATA)
    output = result["documents"][0]
    doc = TemplateDocument(output["path"])
    body = doc.root(len(doc.sections) - 1)
    table = doc.tables(len(doc.sections) - 1)[0]
    paragraphs = doc.cell(table, 0, 0).findall("hp:subList/hp:p", NS)
    values = [own_text(p) for p in paragraphs]
    overview = values.index("1) 도입기업 소개")
    workflow = values.index("2) 전체 업무 흐름도")
    chart = [i for i, p in enumerate(paragraphs) if p.find(".//hp:pic", NS) is not None]
    assert len(chart) == 2 and all(overview < i < workflow for i in chart)
    assert data["project"]["customer"]["name"] in "\n".join(values[overview:workflow])
    assert "합성 조직도 설계자료·실제 회사 조직/임명 확인 아님" in "\n".join(values)
    assert body[0].find(".//hp:secPr", NS) is not None
    bindings = output["image_bindings"]
    assert [b["attachment_id"] for b in bindings] == data["project"]["organization_chart_attachment_ids"]
    for index, binding in enumerate(bindings):
        assert binding["entity_id"] == data["project"]["id"]
        assert binding["entity_input_pointer"] == "/project"
        assert binding["slot_input_pointer"] == "/project/organization_chart_attachment_ids"
        assert binding["attachment_value_input_pointer"] == f"/project/organization_chart_attachment_ids/{index}"
        assert binding["placement"] == "after_exact_customer_overview_before_overall_workflow"
        assert binding["sha256"] == binding["embedded_sha256"]
        assert binding["raster_metadata_profile"] == HANCOM_MAC_12_30_PNG_METADATA
        assert binding["attachment_id"] in "\n".join(values[overview:workflow])
        assert binding["sha256"] in "\n".join(values[overview:workflow])
    with ZipFile(output["path"]) as archive:
        for metadata in output["inserted_picture_metadata"]:
            member = next(n.get("href") for n in doc.xml("Contents/content.hpf").iter()
                          if n.tag.endswith("}item") and n.get("id") == metadata["binary_id"])
            assert sha256(archive.read(member)).hexdigest() == metadata["raster_sha256"]
    if style:
        meaning = json.loads(Path(output["meaning_map"]["path"]).read_text())
        entity = next(e for e in meaning["entities"] if e["input_pointer"] == "/project/organization_chart_attachment_ids")
        field = entity["fields"][0]
        assert field["input_value"] == data["project"]["organization_chart_attachment_ids"]
        assert field["input_type"] == "list" and len(field["input_leaves"]) == 2
        assert all(doc.xml(o["section"]).xpath(o["xpath"], namespaces=meaning["xml_namespaces"])
                   for o in field["owners"])
        context = next(e for e in meaning["entities"] if e["input_pointer"] == "/project")
        assert "/project/id" in {f["input_pointer"] for f in context["fields"]}
    assert source.read_bytes() == input_bytes
    assert result["native_review_status"] == "pending" and not result["submission_ready"]


@pytest.mark.corpus
def test_explicit_empty_org_list_is_printed_without_claiming_real_absence(org_input, tmp_path):
    data, write = org_input
    data["project"]["organization_chart_attachment_ids"] = []
    result = generate_project(write(), tmp_path / "empty", roles=["SF-AD1"], style_profile="reference-v1")
    output = result["documents"][0]
    assert output["image_bindings"] == []
    meaning = json.loads(Path(output["meaning_map"]["path"]).read_text())
    entity = next(e for e in meaning["entities"] if e["input_pointer"] == "/project/organization_chart_attachment_ids")
    field = entity["fields"][0]
    assert field["input_value"] == [] and field["input_type"] == "list"
    assert field["input_leaves"] == [{"input_pointer": "/project/organization_chart_attachment_ids", "value": [], "type": "list"}]
    assert any("0개" in o["rendered_text"] and "부재 여부 미판정" in o["rendered_text"] for o in field["owners"])


@pytest.mark.corpus
def test_absent_org_field_keeps_existing_generated_xml(org_input, tmp_path, monkeypatch):
    import doc_automation.renderers as renderers
    data, write = org_input
    data["project"].pop("organization_chart_attachment_ids")
    source = write()
    before = generate_project(source, tmp_path / "before", roles=["SF-AD1"], style_profile="reference-v1")
    original = renderers._image_groups
    monkeypatch.setattr(renderers, "_image_groups", lambda d, role: [g for g in original(d, role) if g[0] != "project"])
    after = generate_project(source, tmp_path / "after", roles=["SF-AD1"], style_profile="reference-v1")
    with ZipFile(before["documents"][0]["path"]) as left, ZipFile(after["documents"][0]["path"]) as right:
        assert left.namelist() == right.namelist()
        assert {name: left.read(name) for name in left.namelist()} == {name: right.read(name) for name in right.namelist()}
