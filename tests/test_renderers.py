"""Content-preserving generation against the supplied nineteen source forms."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

from lxml import etree as ET
from corpus_sources import pinned_source_path
import pytest

from doc_automation.compose import validate_package
from doc_automation.renderers import NOTICE, ROLES, generate_project


REPOSITORY = Path(__file__).resolve().parents[1]
EXAMPLES = REPOSITORY / "examples"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS = {"hp": HP}


def test_editorial_value_descriptions_keep_null_empty_false_zero_and_types():
    from doc_automation.narrative import typed_value, readable_value
    cases = [None, "", False, 0, "0", [], {}, [False, 0, "0", None, ""]]
    values = [typed_value(value) for value in cases]
    assert len(set(values)) == len(cases)
    assert "미확인(null)" in values[0]
    assert "빈 문자열" in values[1]
    assert "false" in values[2] and "논리값" in values[2]
    assert values[3] == "0 (정수)" and values[4] == "0 (문자열)"
    assert "0개" in values[5] and "부재 여부 미판정" in values[5]
    nested = readable_value({"notes": "", "field_states": {"/required": {"reason": "NEEDS-REVIEW", "source_refs": []}}})
    assert "NEEDS-REVIEW" in nested and "/required" in nested and "빈 문자열" in nested
    assert '{"' not in nested


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sections(path):
    with ZipFile(path) as archive:
        return [ET.fromstring(archive.read(n)) for n in sorted(archive.namelist()) if n.startswith("Contents/section") and n.endswith(".xml")]


def text(path):
    return "\n".join("".join(root.itertext()) for root in sections(path))


@pytest.fixture(scope="module")
def inputs():
    inventory = REPOSITORY / "resources/stage1/inventory.json"
    if not inventory.is_file():
        pytest.fail("Selected corpus tests require resources/stage1/inventory.json")
    documents = {d["id"].removeprefix("template-").upper(): d for d in json.loads(inventory.read_text())["documents"] if d["id"].startswith("template-sf-")}
    for record in documents.values():
        record["source_path"] = str(pinned_source_path(record))
    if not all(Path(d["source_path"]).is_file() for d in documents.values()):
        pytest.fail("Selected corpus tests require the original read-only v2 forms; see docs/GIT_RETENTION.md")
    return documents


@pytest.fixture(scope="module")
def generated(inputs, tmp_path_factory):
    output = tmp_path_factory.mktemp("render-all-19")
    manifest = generate_project(EXAMPLES / "demo-suite.project.json", output)
    return {d["role"]: d for d in manifest["documents"]}, manifest


def dataset(tmp_path, data, name="input.json"):
    data = deepcopy(data)
    for collection in ("sources", "attachments"):
        for item in data[collection]:
            if item.get("path") and not Path(item["path"]).is_absolute():
                item["path"] = str((EXAMPLES / item["path"]).resolve())
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def image_attachment(tmp_path, data, *, kind="PNG", declared_media=None):
    """Clearly synthetic byte fixture for insertion, never an execution capture."""
    from PIL import Image
    path = tmp_path / f"synthetic-layout-fixture.{kind.lower()}"
    Image.new("RGB", (320, 160), "white").save(path, format=kind)
    attachment = deepcopy(data["attachments"][0])
    attachment.update(id="SYNTHETIC-IMAGE-FIXTURE", name="합성 그림 삽입 시험", path=str(path),
        sha256=sha(path), media_type=declared_media or {"PNG": "image/png", "JPEG": "image/jpeg", "BMP": "image/bmp"}[kind],
        caption="합성 시안·실제 실행화면 아님", purpose="그림·캡션·출처 연결 시험", notes="SYNTHETIC-IMAGE-NOTES")
    data["attachments"].append(attachment)
    return attachment


@pytest.mark.corpus
def test_all_roles_keep_source_hashes_styles_and_section_properties(inputs, generated):
    documents, manifest = generated
    assert set(documents) == set(ROLES)
    assert not manifest["submission_ready"] and manifest["native_review_status"] == "pending"
    for role, output in documents.items():
        source = inputs[role]
        assert sha(source["source_path"]) == source["sha256"]
        assert output["sha256"] == sha(output["path"])
        assert validate_package(output["path"])["valid"]
        with ZipFile(source["source_path"]) as old, ZipFile(output["path"]) as new:
            old_header = ET.fromstring(old.read("Contents/header.xml"))
            new_header = ET.fromstring(new.read("Contents/header.xml"))
            hh = {"hh": "http://www.hancom.co.kr/hwpml/2011/head"}
            original_styles = {p.get("id"): ET.tostring(p) for p in old_header.findall(".//hh:charPr", hh)}
            current_styles = {p.get("id"): ET.tostring(p) for p in new_header.findall(".//hh:charPr", hh)}
            assert all(current_styles[key] == value for key, value in original_styles.items())
            assert len(current_styles) >= len(original_styles)
        for old, new in zip(sections(source["source_path"]), sections(output["path"])):
            original = old.find(".//hp:secPr", NS)
            current = new.find(".//hp:secPr", NS)
            assert ET.tostring(original) == ET.tostring(current)
            assert new[0].find(".//hp:secPr", NS) is not None


@pytest.mark.corpus
def test_all_covers_are_labelled_and_sample_instructions_removed(generated):
    documents, _ = generated
    for output in documents.values():
        roots = sections(output["path"])
        assert NOTICE in "".join(roots[0].itertext())
        body = text(output["path"])
        assert "※ 작성 방법" not in body
        assert "MES-CD2-001" not in body and "MES-TI5-001" not in body
        assert "요구사항명n" not in body and "테이블IDn" not in body
        assert "2019년" not in body and "2020년" not in body


@pytest.mark.corpus
def test_all_repeated_entities_and_explicit_constraints_are_kept(generated):
    documents, _ = generated
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    for role, domain in (("SF-AD2", "requirements"), ("SF-AD3", "features"), ("SF-TD3", "screens"), ("SF-TD4", "programs")):
        body = text(documents[role]["path"])
        for item in data[domain]:
            assert item["id"] in body and item["name"] in body
    body = text(documents["SF-TD5"]["path"])
    for table in data["database_tables"]:
        assert table["id"] in body
        for column in table["columns"]:
            assert column["id"] in body and column["name"] in body
    screen_body = text(documents["SF-TD3"]["path"])
    for requirement in data["requirements"]:
        for rule in requirement["details"] + requirement["constraints"]:
            assert rule in screen_body
    assert "1. 화면 표준" in screen_body and "2. 메뉴구조도" in screen_body and "4. 화면 검토 결과" in screen_body


@pytest.mark.corpus
def test_plans_are_not_reclassified_as_execution_or_monthly_results(generated):
    documents, _ = generated
    for role in ("SF-CD1", "SF-TI1", "SF-TI4"):
        body = text(documents[role]["path"])
        assert "미수행 (not_run)" in body
        assert "입력 판정: passed" not in body
    body = text(documents["SF-PM1"]["path"])
    assert "주간 계획자료" in body and "월간 실적으로 재분류하지 않음" in body
    assert "개최·참석·합의·서명은 미수행" in text(documents["SF-PM2"]["path"])
    assert "unrequested" in text(documents["SF-PM3"]["path"])
    assert "actual_physical_database_export" not in text(documents["SF-TD5"]["path"])


@pytest.mark.corpus
def test_only_selected_template_files_are_required(inputs, tmp_path):
    templates = tmp_path / "two-templates"
    templates.mkdir()
    roles = ["SF-AD2", "SF-TD3"]
    for role in roles:
        original = Path(inputs[role]["source_path"])
        shutil.copyfile(original, templates / original.name)
    manifest = generate_project(EXAMPLES / "demo-suite.project.json", tmp_path / "output", roles=roles, template_root=templates)
    assert [d["role"] for d in manifest["documents"]] == roles


@pytest.mark.parametrize("literal_format", [False, True])
@pytest.mark.corpus
def test_td3_reports_template_id_literal_discrepancy_without_rewriting_supplied_ids(inputs, tmp_path, literal_format):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    if literal_format:
        replacements = {s["id"]: f"MES-TD3-{i:03}" for i, s in enumerate(data["screens"], 1)}
        def replace(value):
            if isinstance(value, dict):
                return {k: replace(v) for k, v in value.items()}
            if isinstance(value, list):
                return [replace(v) for v in value]
            return replacements.get(value, value) if isinstance(value, str) else value
        data = replace(data)
    result = generate_project(dataset(tmp_path, data), tmp_path / "id-guidance", roles=["SF-TD3"])["documents"][0]
    doc = TemplateDocument(result["path"])
    assert [own_text(doc.cell(card, 0, 1).find("hp:subList/hp:p", NS)) for card in doc.tables()[1:]] == [s["id"] for s in data["screens"]]
    discrepancies = [w for w in result["warnings"] if "원본 작성 지침(시스템명 3자리" in w]
    assert bool(discrepancies) is not literal_format
    if discrepancies:
        assert all(s["id"] in discrepancies[0] for s in data["screens"])
        assert "제공 ID를 보존" in discrepancies[0] and "실제 사업의 명명 규칙은 추가 확인" in discrepancies[0]
    assert any("필드/버튼/권한의 개별 source_refs" in w for w in result["warnings"])


@pytest.mark.corpus
def test_invalid_data_and_unsupported_images_fail_before_output(inputs, tmp_path):
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["requirements"].append(deepcopy(data["requirements"][0]))
    source = dataset(tmp_path, data)
    with pytest.raises(ValueError, match="DUPLICATE_ID"):
        generate_project(source, tmp_path / "invalid", roles=["SF-AD2"])
    assert not (tmp_path / "invalid").exists()
    data["requirements"].pop()
    data["screens"][0]["before_attachment_ids"] = [data["attachments"][0]["id"]]
    source = dataset(tmp_path, data)
    with pytest.raises(ValueError, match="/screens/0/before_attachment_ids"):
        generate_project(source, tmp_path / "unsupported", roles=["SF-TD3"])
    assert not (tmp_path / "unsupported").exists()


@pytest.mark.corpus
def test_project_execution_and_approval_values_are_preserved(inputs, tmp_path):
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["dataset_kind"] = "project"
    data["project"]["name"] = "일반 프로젝트 입력 보존 시험"
    case = data["test_cases"][0]
    case.update(result="passed", actual="OBSERVED-RESULT-ONLY-IN-INPUT", execution_date="2026-11-02",
        executor={"name": "INPUT-TESTER", "review_status": "provided"}, evidence_ids=[data["attachments"][0]["id"]])
    change = data["changes"][0]
    change.update(approval_status="approved", approval_evidence_ids=[data["attachments"][0]["id"]],
        response_content="INPUT-APPROVAL-RESPONSE", response_number="INPUT-RESPONSE-001", response_date="2026-11-03")
    meeting = data["meetings"][0]
    meeting.update(date="2026-11-02", discussions=["INPUT-ACTUAL-DISCUSSION"], decisions=["INPUT-ACTUAL-DECISION"])
    source = dataset(tmp_path, data)
    manifest = generate_project(source, tmp_path / "project", roles=["SF-CD1", "SF-PM2", "SF-PM3"])
    docs = {d["role"]: d for d in manifest["documents"]}
    case_text = text(docs["SF-CD1"]["path"])
    assert "OBSERVED-RESULT-ONLY-IN-INPUT" in case_text and "INPUT-TESTER" in case_text
    assert "입력 판정: passed" in case_text and "미수행 (not_run)" in case_text  # The other case remains planned.
    assert "INPUT-ACTUAL-DISCUSSION" in text(docs["SF-PM2"]["path"])
    assert "INPUT-ACTUAL-DECISION" in text(docs["SF-PM2"]["path"])
    assert "INPUT-APPROVAL-RESPONSE" in text(docs["SF-PM3"]["path"])
    assert "미요청 검토안" not in text(docs["SF-PM3"]["path"])
    assert manifest["notice"] != NOTICE and not manifest["submission_ready"]


@pytest.mark.corpus
def test_stress_does_not_truncate_or_reuse_mismatched_workbook(inputs, tmp_path):
    source = EXAMPLES / "stress.project.json"
    data = json.loads(source.read_text())
    manifest = generate_project(source, tmp_path / "stress", roles=["SF-AD2", "SF-TD5"])
    docs = {d["role"]: d for d in manifest["documents"]}
    requirements = text(docs["SF-AD2"]["path"])
    for requirement in data["requirements"]:
        for detail in requirement["details"]:
            assert detail in requirements
    database = text(docs["SF-TD5"]["path"])
    for table in data["database_tables"]:
        for column in table["columns"]:
            assert column["id"] in database
    assert manifest["companions"] == []
    assert "현재 DB 입력과 일치 확인된 부속 Excel 미제공" in database


@pytest.mark.corpus
def test_original_template_directory_cannot_be_output(inputs):
    source = Path(inputs["SF-AD2"]["source_path"])
    with pytest.raises(ValueError, match="outside the original"):
        generate_project(EXAMPLES / "demo-suite.project.json", source.parent, roles=["SF-AD2"])


@pytest.mark.corpus
def test_not_run_with_supplied_actual_is_reported_as_conflict_not_erased(inputs, tmp_path):
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["test_cases"][0]["actual"] = "UNRESOLVED-ACTUAL-INPUT"
    source = dataset(tmp_path, data)
    manifest = generate_project(source, tmp_path / "conflict", roles=["SF-CD1"])
    body = text(manifest["documents"][0]["path"])
    assert "UNRESOLVED-ACTUAL-INPUT" in body and "정합 검토 필요" in body
    assert any(w["code"] == "TEST_UNEXECUTED_HAS_ACTUAL" for w in manifest["validation"]["warnings"])


@pytest.mark.corpus
def test_all_displayed_runs_are_black_without_removing_original_styles(generated):
    documents, _ = generated
    hh = {"hh": "http://www.hancom.co.kr/hwpml/2011/head"}
    for output in documents.values():
        with ZipFile(output["path"]) as archive:
            header = ET.fromstring(archive.read("Contents/header.xml"))
        styles = {p.get("id"): p for p in header.findall(".//hh:charPr", hh)}
        for root in sections(output["path"]):
            for run in root.iter(f"{{{HP}}}run"):
                if "".join(run.xpath("./hp:t//text()", namespaces=NS)).strip():
                    assert styles[run.get("charPrIDRef")].get("textColor") == "#000000"


@pytest.mark.corpus
def test_regeneration_removes_only_owned_unchanged_stale_companion(inputs, tmp_path):
    output = tmp_path / "regenerate"
    # Contract fixture for copying/ownership, not a spreadsheet content review.
    workbook = tmp_path / "synthetic-companion.xlsx"
    with ZipFile(workbook, "w") as archive:
        archive.writestr("fixture.txt", "Synthetic companion ownership fixture; not a reviewed workbook")
    baseline = EXAMPLES / "demo-suite.project.json"
    verification = tmp_path / "synthetic-companion-verification.json"
    verification.write_text(json.dumps({"input": str(baseline), "input_sha256": sha(baseline),
        "output": str(workbook), "output_sha256": sha(workbook)}))
    manifest = generate_project(baseline, output, roles=["SF-TD5"], companion_verification=verification)
    assert len(manifest["companions"]) == 1
    old = Path(manifest["companions"][0]["path"])
    assert old.is_file()
    current = generate_project(EXAMPLES / "stress.project.json", output, roles=["SF-TD5"], companion_verification=verification)
    assert current["companions"] == [] and not old.exists()
    assert str(old) in current["removed_owned_stale_companions"]


@pytest.mark.corpus
def test_header_role_and_company_field_labels_are_not_cover_placeholders(generated):
    documents, _ = generated
    from doc_automation.compose import TemplateDocument
    for role, title in (("SF-PM2", "회의록"), ("SF-PM3", "변경관리내역서"), ("SF-PM4", "요구사항추적표")):
        root = sections(documents[role]["path"])[0]
        headings = root.findall(".//hp:header//hp:p", NS)
        assert any(title in "".join(p.itertext()) for p in headings)
        assert all("일정계획서" not in "".join(p.itertext()) for p in headings)
    doc = TemplateDocument(documents["SF-PM3"]["path"])
    table = doc.tables()[2]
    assert "".join(doc.cell(table, 0, 2).itertext()) == "도입기업명"
    assert "".join(doc.cell(table, 1, 2).itertext()) == "공급기업명"
    assert "검증용 도입기업 A" in "".join(doc.cell(table, 0, 3).itertext())
    assert "검증용 공급기업 B" in "".join(doc.cell(table, 1, 3).itertext())


@pytest.mark.corpus
def test_database_table_notes_and_trace_change_basis_survive(generated):
    documents, _ = generated
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    body = text(documents["SF-TD5"]["path"])
    for table in data["database_tables"]:
        assert table["description"] in body
        if table.get("notes"):
            assert table["notes"] in body
    assert "복합 UNIQUE" in body
    trace = text(documents["SF-PM4"]["path"])
    assert "구분: 변경" in trace and "구분: 추가" in trace
    assert "SOURCE-DEMO-FACTS /requirement_notes/0" in trace
    assert "DEMO-PM3-001 (unrequested)" in trace


@pytest.mark.corpus
def test_executed_tests_without_defect_rows_do_not_become_unexecuted(inputs, tmp_path):
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["dataset_kind"] = "project"
    data["defects"] = []
    for case in data["test_cases"]:
        if case["stage"] == "unit":
            case.update(result="passed", actual="RECORDED-RESULT", execution_date="2026-11-02",
                executor={"name": "INPUT-TESTER", "review_status": "provided"}, evidence_ids=[data["attachments"][0]["id"]])
    source = dataset(tmp_path, data)
    manifest = generate_project(source, tmp_path / "executed", roles=["SF-CD1"])
    body = text(manifest["documents"][0]["path"])
    assert "결함 원장 미제공/확인 필요" in body
    assert "시험 미수행" not in body


@pytest.mark.corpus
def test_defect_verification_state_and_evidence_are_retained(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["dataset_kind"] = "project"
    case = next(t for t in data["test_cases"] if t["stage"] == "acceptance")
    aid = data["attachments"][0]["id"]
    case.update(result="passed", actual="RECORDED-RESULT", execution_date="2026-11-03",
        executor={"name": "INPUT-TESTER", "review_status": "provided"}, evidence_ids=[aid])
    data["defects"][0].update(test_case_id=case["id"], detected_date="2026-11-02", resolved_date="2026-11-03",
        description="PROVIDED-DEFECT", resolution_status="verified", resolution="PROVIDED-RESOLUTION",
        evidence_ids=[aid], verification_evidence_ids=[aid])
    source = dataset(tmp_path, data)
    manifest = generate_project(source, tmp_path / "verified-defect", roles=["SF-TI4"])
    doc = TemplateDocument(manifest["documents"][0]["path"])
    table = doc.tables(1)[-1]
    confirmation = "".join(doc.cell(table, 1, 6).itertext())
    assert "verified" in confirmation and aid in confirmation
    assert "확인 미수행" not in confirmation
    assert "PROVIDED-RESOLUTION" in "".join(doc.cell(table, 1, 4).itertext())


@pytest.mark.corpus
def test_cover_notice_reuses_small_blank_slot_without_adding_customer_line(inputs, generated):
    documents, _ = generated
    from doc_automation.renderers import _own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    for role, output in documents.items():
        old, new = sections(inputs[role]["source_path"])[0], sections(output["path"])[0]
        customer_index = next(i for i, p in enumerate(old) if _own_text(p).strip() == "도입기업명")
        supplier_index = next(i for i, p in enumerate(old) if _own_text(p).strip() == "공급기업명")
        assert _own_text(new[customer_index]).strip() == data["project"]["customer"]["name"]
        assert _own_text(new[supplier_index]).strip() == data["project"]["supplier"]["name"]
        assert new[customer_index].find("./hp:run/hp:t/hp:lineBreak", NS) is None
        notice_index = next(i for i, p in enumerate(list(new)[:customer_index]) if _own_text(p).strip() == NOTICE)
        assert not _own_text(old[notice_index]).strip()
        assert new[notice_index].attrib == old[notice_index].attrib
        with ZipFile(output["path"]) as archive:
            header = ET.fromstring(archive.read("Contents/header.xml"))
        heights = {c.get("id"): int(c.get("height")) for c in header.findall(".//{http://www.hancom.co.kr/hwpml/2011/head}charPr")}
        assert all(900 <= heights[r.get("charPrIDRef")] <= 1100 for r in new[notice_index].findall("hp:run", NS))


@pytest.mark.corpus
def test_ad3_narrow_columns_use_short_labels_and_full_evidence_moves_to_page_width(generated):
    from doc_automation.compose import TemplateDocument
    documents, _ = generated
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    doc = TemplateDocument(documents["SF-AD3"]["path"])
    table = doc.tables()[-1]
    wide_text = "\n".join("".join(p.itertext()) for p in doc.root() if p.find(".//hp:tbl", NS) is None)
    assert "2. 기능별 근거·검토상태" in wide_text
    for i, feature in enumerate(data["features"], 1):
        remark = "".join(doc.cell(table, i, 5).itertext())
        change = "".join(doc.cell(table, i, 3).itertext())
        assert change in {"기존", "추가", "변경", "삭제"}
        assert f"[F{i}]" in remark and f"[F{i}]" in wide_text
        assert "SOURCE-DEMO-FACTS" not in remark and "/feature_inventory" not in remark
        assert feature["notes"] not in remark
        assert feature["notes"] in wide_text
        for ref in feature["source_refs"]:
            assert ref["source_id"] in wide_text and ref["locator"] in wide_text


@pytest.mark.corpus
def test_narrative_keep_policy_targets_only_short_single_plain_paragraphs(inputs):
    from doc_automation.compose import TemplateDocument
    from doc_automation.renderers import NARRATIVE_KEEP_MAX_CHARS, _narrative, _own_text
    doc = TemplateDocument(inputs["SF-AD1"]["source_path"])
    table = doc.tables(1)[0]
    long = "장문" * (NARRATIVE_KEEP_MAX_CHARS + 1)
    source_definitions = {p.get("id"): ET.tostring(p) for p in doc.xml("Contents/header.xml").findall(".//{http://www.hancom.co.kr/hwpml/2011/head}paraPr")}
    _narrative(doc, table, [("1. 제목", ["짧은 본문", long, "여러줄 블록 첫째\n여러줄 블록 둘째"]), ("2. 다음 제목", ["다음 본문"])])
    definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//{http://www.hancom.co.kr/hwpml/2011/head}paraPr")}
    assert all(ET.tostring(definitions[key]) == value for key, value in source_definitions.items())
    paragraphs = doc.cell(table, 0, 0).findall("hp:subList/hp:p", NS)
    observed = {_own_text(p): definitions[p.get("paraPrIDRef")].find("{http://www.hancom.co.kr/hwpml/2011/head}breakSetting").attrib for p in paragraphs}
    for heading in ("1. 제목", "2. 다음 제목"):
        assert observed[heading]["keepWithNext"] == "1" and observed[heading]["keepLines"] == "0"
    for body in ("짧은 본문", "다음 본문", "여러줄 블록 첫째", "여러줄 블록 둘째"):
        assert observed[body]["keepLines"] == "1" and observed[body]["keepWithNext"] == "0"
    for untouched in (long,):
        assert observed[untouched]["keepLines"] == "0" and observed[untouched]["keepWithNext"] == "0"


@pytest.mark.parametrize("dataset_kind", ["synthetic", "project"])
@pytest.mark.corpus
def test_td5_table_metadata_and_common_notice_follow_all_lists_before_column_details(inputs, tmp_path, dataset_kind):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    from doc_automation.renderers import _notice
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["dataset_kind"] = dataset_kind
    result = generate_project(dataset(tmp_path, data), tmp_path / "td5-metadata", roles=["SF-TD5"])
    doc = TemplateDocument(result["documents"][0]["path"])
    root = doc.root()
    paragraphs = list(root)
    owned = [own_text(p) for p in paragraphs]
    lists = doc.tables()[1:]
    assert len(lists) == len(data["database_tables"])
    last_list = max(paragraphs.index(next(p for p in table.iterancestors() if p.tag == f"{{{HP}}}p")) for table in lists)
    first_list = min(paragraphs.index(next(p for p in table.iterancestors() if p.tag == f"{{{HP}}}p")) for table in lists)
    notices = [i for i, value in enumerate(owned) if value.startswith(_notice(data) + "\n과제: ")]
    assert len(notices) == 1 and notices[0] > last_list
    notice = owned[notices[0]]
    assert data["project"]["name"] in notice
    assert "전체 테이블: " + ", ".join(t["id"] for t in data["database_tables"]) in notice
    assert "부속: " in notice and "실제 물리DB 추출·구축 결과로 승인할 수 없다." in notice
    metadata_start = owned.index("2. 테이블별 설명·제약·근거")
    columns_start = owned.index("3. 컬럼별 제약·암호화·기본값·근거")
    assert last_list < notices[0] < metadata_start < columns_start
    for i, item in enumerate(data["database_tables"], 1):
        marker = f"[T{i}] {item['id']} — {item['name']}"
        start = next(j for j, value in enumerate(owned) if value.startswith(marker))
        end = next((j for j in range(start + 1, columns_start) if owned[j].startswith("[T")), columns_start)
        block = owned[start:end]
        assert metadata_start < start < end <= columns_start
        for value in ["설계 설명: " + item["description"], "테이블 제약/비고: " + item["notes"]]:
            assert value in block
            assert value not in "\n".join(owned[:first_list])
        assert "출처: " + "; ".join(f"{r['source_id']} {r['locator']}" for r in item["source_refs"]) in block
    markers = [value for value in owned[columns_start + 1:] if value.startswith("[C")]
    expected = [(item, column) for item in data["database_tables"] for column in item["columns"]]
    assert len(markers) == len(expected) == 19
    for i, (marker, (item, column)) in enumerate(zip(markers, expected), 1):
        assert marker.startswith(f"[C{i}] {item['id']}.{column['id']} — {column['name']}")
    definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//{http://www.hancom.co.kr/hwpml/2011/head}paraPr")}
    for p in paragraphs[last_list + 1:]:
        value = own_text(p)
        if not value:
            continue
        flags = definitions[p.get("paraPrIDRef")].find("{http://www.hancom.co.kr/hwpml/2011/head}breakSetting")
        assert (flags.get("keepLines") == "1") is (len(value) <= 240)
        is_heading = value in {"2. 테이블별 설명·제약·근거", "3. 컬럼별 제약·암호화·기본값·근거"} or value.startswith(("[T", "[C"))
        if is_heading:
            assert flags.get("keepWithNext") == "1"
    assert sha(inputs["SF-TD5"]["source_path"]) == inputs["SF-TD5"]["sha256"]


@pytest.mark.parametrize("boundary", ["short", "per_paragraph", "paragraph_count", "total_characters"])
@pytest.mark.corpus
def test_td5_entry_keep_groups_stop_at_one_entry_and_enforce_every_bound(inputs, tmp_path, boundary):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    table = data["database_tables"][1] if boundary in {"paragraph_count", "total_characters"} else data["database_tables"][0]
    column = table["columns"][1] if boundary in {"paragraph_count", "total_characters"} else table["columns"][0]
    if boundary == "per_paragraph":
        column["notes"] = "LONG-PARAGRAPH-" * 30
    elif boundary == "paragraph_count":
        column["field_states"] = {"/nullable": {"status": "unverified", "reason": "BOUNDED-ENTRY-STATE", "source_refs": []}}
        column.update(expected_id=column["id"], expected_name=column["name"], definition_source_refs=column["source_refs"])
    elif boundary == "total_characters":
        column["name"] += "이름" * 60
        column["notes"] = "비고" * 80
        column["field_states"] = {"/nullable": {"status": "unverified", "reason": "검토" * 40, "source_refs": []}}
    output = generate_project(dataset(tmp_path, data), tmp_path / "td5-bounded", roles=["SF-TD5"])["documents"][0]
    doc = TemplateDocument(output["path"])
    paragraphs = list(doc.root())
    start = next(i for i, p in enumerate(paragraphs) if own_text(p).startswith("[C") and f"] {table['id']}.{column['id']} —" in own_text(p))
    end = next(i for i in range(start + 1, len(paragraphs)) if own_text(paragraphs[i]).startswith("[C"))
    entry = paragraphs[start:end]
    values = [own_text(p) for p in entry]
    properties = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//{http://www.hancom.co.kr/hwpml/2011/head}paraPr")}
    flags = [properties[p.get("paraPrIDRef")].find("{http://www.hancom.co.kr/hwpml/2011/head}breakSetting").get("keepWithNext") for p in entry]
    if boundary == "short":
        assert len(values) == 4 and flags == ["1", "1", "1", "0"]
    else:
        assert flags == ["1"] + ["0"] * (len(values) - 1)
        if boundary == "per_paragraph": assert max(map(len, values)) > 240
        if boundary == "paragraph_count": assert len(values) == 7
        if boundary == "total_characters": assert len(values) == 6 and max(map(len, values)) <= 240 and sum(map(len, values)) > 720
    assert flags[-1] == "0"  # Never chain this entry into the next column.
    if column.get("notes"):
        assert json.dumps(column["notes"], ensure_ascii=False) in "\n".join(values)
    assert sha(inputs["SF-TD5"]["source_path"]) == inputs["SF-TD5"]["sha256"]


@pytest.mark.corpus
def test_td5_narrow_remarks_only_reference_complete_wide_column_details(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.renderers import _own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    first, second, third = data["database_tables"][0]["columns"][:3]
    first.update(key=None, default_value=0, notes="FULL-COLUMN-NOTE")
    first["encryption"].update(applied=True, algorithm="AES-256-GCM", notes="FULL-ENCRYPTION-POLICY")
    second.update(nullable=True, default_value=False)
    second["encryption"].update(applied=False, notes="FALSE-IS-NOT-NULL")
    third["field_states"] = {"/default_value": {"status": "unverified", "reason": "DEFAULT-UNKNOWN", "source_refs": []}}
    source = dataset(tmp_path, data)
    manifest = generate_project(source, tmp_path / "td5-wide", roles=["SF-TD5"])
    doc = TemplateDocument(manifest["documents"][0]["path"])
    wide = "\n".join(_own_text(p) for p in doc.root() if p.find(".//hp:tbl", NS) is None)
    assert "3. 컬럼별 제약·암호화·기본값·근거" in wide
    assert "기본값=0" in wide and "기본값=false" in wide and "기본값=null" in wide
    assert "AES-256-GCM" in wide and "FULL-ENCRYPTION-POLICY" in wide and "FULL-COLUMN-NOTE" in wide
    assert "암호화 적용=false" in wide and "DEFAULT-UNKNOWN" in wide
    counter = 0
    for table, item in zip(doc.tables()[1:], data["database_tables"]):
        for row, column in enumerate(item["columns"], 1):
            counter += 1
            marker = f"[C{counter}]"
            assert "".join(doc.cell(table, row, 8).itertext()) == f"C{counter}"
            assert f"{marker} {item['id']}.{column['id']}" in wide
            for ref in column["source_refs"] + column["encryption"]["source_refs"]:
                assert ref["source_id"] in wide and ref["locator"] in wide
    assert counter == 19
    assert "C10 → [C10]" in wide
    assert "".join(doc.cell(doc.tables()[1], 1, 5).itertext()) == "미확인"
    assert "".join(doc.cell(doc.tables()[1], 1, 6).itertext()) == "미확인"


@pytest.mark.corpus
def test_td5_stress_all_74_column_keys_and_details_are_preserved(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.renderers import _own_text
    source = EXAMPLES / "stress.project.json"
    data = json.loads(source.read_text())
    manifest = generate_project(source, tmp_path / "td5-stress-wide", roles=["SF-TD5"])
    doc = TemplateDocument(manifest["documents"][0]["path"])
    wide = "\n".join(_own_text(p) for p in doc.root() if p.find(".//hp:tbl", NS) is None)
    counter = 0
    for table, item in zip(doc.tables()[1:], data["database_tables"]):
        assert len(table.findall("hp:tr", NS)) == len(item["columns"]) + 1
        for row, column in enumerate(item["columns"], 1):
            counter += 1
            assert "".join(doc.cell(table, row, 8).itertext()) == f"C{counter}"
            assert f"[C{counter}] {item['id']}.{column['id']}" in wide
            assert column["name"] in wide
    assert counter == 74 and manifest["companions"] == []


@pytest.mark.corpus
def test_ad2_stress_cards_allow_continuation_and_repeat_identity_without_losing_tails(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    from doc_automation.renderers import _text
    data = json.loads((EXAMPLES / "stress.project.json").read_text())
    output = generate_project(EXAMPLES / "stress.project.json", tmp_path / "ad2-stress", roles=["SF-AD2"])["documents"][0]
    doc = TemplateDocument(output["path"])
    cards = doc.tables(1)
    assert len(cards) == len(data["requirements"]) == 5
    requirements = {r["id"]: r for r in data["requirements"]}
    for card in cards:
        requirement = requirements[own_text(doc.cell(card, 1, 1).find("hp:subList/hp:p", NS))]
        assert card.get("pageBreak") == "CELL" and card.get("repeatHeader") == "1"
        assert card.find("hp:pos", NS).get("treatAsChar") == "0"
        for i, row in enumerate(card.findall("hp:tr", NS)):
            assert all(c.get("header") == ("1" if i < 2 else "0") for c in row.findall("hp:tc", NS))
        for row, field in [(2, "description"), (3, "details"), (4, "constraints")]:
            assert "\n".join(own_text(p) for p in doc.cell(card, row, 1).findall("hp:subList/hp:p", NS)) == _text(requirement.get(field))
        assert requirement["notes"] in "\n".join(own_text(p) for p in card.iter(f"{{{HP}}}p"))
        for ref in requirement["source_refs"]:
            assert f"{ref['source_id']} {ref['locator']}" in own_text(doc.cell(card, 6, 1).find("hp:subList/hp:p", NS))
    for si in range(len(doc.sections)):
        assert doc.root(si)[0].find(".//hp:secPr", NS) is not None
    assert sha(inputs["SF-AD2"]["source_path"]) == inputs["SF-AD2"]["sha256"]


@pytest.mark.parametrize("kinds,order,headings", [
    (["nonfunctional", "functional", None, "functional", "nonfunctional", None],
     [1, 3, 0, 4, 2, 5], ["1. 기능 요구사항(SW)", "2. 비기능 요구사항(HW 등)", "3. 유형 미확인 요구사항"]),
    (["nonfunctional", "functional", "functional"], [1, 2, 0],
     ["1. 기능 요구사항(SW)", "2. 비기능 요구사항(HW 등)"]),
    (["nonfunctional"] * 3, [0, 1, 2], ["1. 비기능 요구사항(HW 등)"]),
    ([None] * 3, [0, 1, 2], ["1. 유형 미확인 요구사항"]),
])
@pytest.mark.corpus
def test_ad2_groups_toc_and_whole_cards_stably_without_reclassifying_or_reformatting(inputs, tmp_path, kinds, order, headings):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    original = deepcopy(data["requirements"])
    data["requirements"] = [deepcopy(original[i % 3]) for i in range(len(kinds))]
    for i, (r, kind) in enumerate(zip(data["requirements"], kinds)):
        if i >= 3:
            r.update(id=f"DEMO-AD2-{i + 1:03}", name=f"합성 분류 안정성 검증 {i + 1}")
        r["kind"] = kind
    facts = dataset(tmp_path, data)
    facts_before = facts.read_bytes()
    source = TemplateDocument(inputs["SF-AD2"]["source_path"])
    template = source.tables(1)[0]
    result = generate_project(facts, tmp_path / "grouped-ad2", roles=["SF-AD2"])
    doc = TemplateDocument(result["documents"][0]["path"])
    cards = doc.tables(1)
    cell_text = lambda document, table, row, col: "\n".join(own_text(p) for p in document.cell(table, row, col).findall("hp:subList/hp:p", NS))
    assert [cell_text(doc, c, 1, 1) for c in cards] == [data["requirements"][i]["id"] for i in order]
    toc = next(own_text(p) for p in doc.root() if "쪽수: 네이티브 출력 후 확인 예정" in own_text(p))
    assert [line for line in toc.splitlines() if line and not line.startswith("  ")][:-1] == headings
    positions = [toc.index(data["requirements"][i]["id"]) for i in order]
    assert positions == sorted(positions)
    for card, i in zip(cards, order):
        r = data["requirements"][i]
        expected = {(0, 1): r["system_name"], (0, 3): r["business_area"], (1, 1): r["id"],
                    (1, 3): r["name"], (2, 1): r["description"],
                    (3, 1): "\n".join(f"{j}. {s}" for j, s in enumerate(r["details"], 1)),
                    (4, 1): "\n".join(f"{j}. {s}" for j, s in enumerate(r["constraints"], 1)),
                    (5, 1): {"functional": "기능", "nonfunctional": "비기능"}.get(r["kind"], "구분 미확인"),
                    (5, 3): "담당자 미지정·확인/서명 자료 미제공", (6, 1): "SOURCE-DEMO-FACTS " + r["source_refs"][0]["locator"]}
        for (row, col), value in expected.items():
            assert cell_text(doc, card, row, col) == value
        assert r["notes"] in cell_text(doc, card, 7, 1)
        for tag in ("hp:sz", "hp:pos", "hp:outMargin"):
            assert card.find(tag, NS).attrib == template.find(tag, NS).attrib
        for old, new in zip(template.findall("hp:tr/hp:tc", NS), card.findall("hp:tr/hp:tc", NS)):
            for tag in ("hp:cellAddr", "hp:cellSpan", "hp:cellSz", "hp:cellMargin"):
                assert old.find(tag, NS).attrib == new.find(tag, NS).attrib
            assert old.get("borderFillIDRef") == new.get("borderFillIDRef")
        # Resolve every fixed label's direct character format within its file.
        hh = {"hh": "http://www.hancom.co.kr/hwpml/2011/head"}
        for row, col in [(0, 0), (0, 2), (1, 0), (1, 2), (2, 0), (3, 0), (4, 0), (5, 0), (5, 2), (6, 0), (7, 0)]:
            old = source.cell(template, row, col).find("hp:subList/hp:p", NS)
            new = doc.cell(card, row, col).find("hp:subList/hp:p", NS)
            assert own_text(old) == own_text(new)
            assert (old.get("paraPrIDRef"), old.get("styleIDRef")) == (new.get("paraPrIDRef"), new.get("styleIDRef"))
            old_id = old.find("hp:run", NS).get("charPrIDRef")
            new_id = new.find("hp:run", NS).get("charPrIDRef")
            assert ET.tostring(source.xml("Contents/header.xml").find(f".//hh:charPr[@id='{old_id}']", hh)) == ET.tostring(doc.xml("Contents/header.xml").find(f".//hh:charPr[@id='{new_id}']", hh))
    assert facts.read_bytes() == facts_before
    assert sha(inputs["SF-AD2"]["source_path"]) == inputs["SF-AD2"]["sha256"]
    assert all(doc.root(si)[0].find(".//hp:secPr", NS) is not None for si in range(len(doc.sections)))


@pytest.mark.corpus
def test_td3_finite_intro_and_cell_keeps_use_actual_linked_requirement_titles(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    from doc_automation.renderers import NARRATIVE_KEEP_MAX_CHARS, _notice
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    old_id, new_id = data["requirements"][0]["id"], "REQ-SECURITY-ALPHA-777"
    def remap(value):
        if isinstance(value, dict): return {key: remap(item) for key, item in value.items()}
        if isinstance(value, list): return [remap(item) for item in value]
        return new_id if value == old_id else value
    data = remap(data)
    data["requirements"][0]["name"] = "입력 이름으로 연결한 권한 검토 제목"
    data["screens"][0]["checks"].append("긴 단일 검토 문장 " * 80)
    output = generate_project(dataset(tmp_path, data), tmp_path / "td3-keeps", roles=["SF-TD3"])["documents"][0]
    doc = TemplateDocument(output["path"])
    definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//{http://www.hancom.co.kr/hwpml/2011/head}paraPr")}
    def keep(p): return definitions[p.get("paraPrIDRef")].find("{http://www.hancom.co.kr/hwpml/2011/head}breakSetting")
    requirements = {r["id"]: r for r in data["requirements"]}
    cards = doc.tables()[1:]
    for table, screen in zip(cards, data["screens"]):
        linked = {f"{rid} {requirements[rid]['name']}" for rid in screen["requirement_ids"]}
        for row in (3, 4):
            paragraphs = doc.cell(table, row, 1).findall("hp:subList/hp:p", NS)
            assert len(paragraphs) > 1
            for p in paragraphs:
                value = own_text(p)
                assert (keep(p).get("keepLines") == "1") is bool(value.strip() and len(value) <= NARRATIVE_KEEP_MAX_CHARS)
                assert (keep(p).get("keepWithNext") == "1") is (value.rstrip().endswith(":") or value in linked)
            if row == 4:
                assert linked <= {own_text(p) for p in paragraphs}
        anchor = next(p for p in table.iterancestors() if p.tag == f"{{{HP}}}p")
        assert keep(anchor).get("keepLines") == keep(anchor).get("keepWithNext") == "0"
    root = doc.root()
    heading = next(p for p in root if own_text(p) == "3. 화면(보고서) 설계")
    index = list(root).index(heading)
    assert heading.get("pageBreak") == "1" and keep(heading).get("keepWithNext") == "1"
    intro = list(root)[index + 1:index + 4]
    assert [own_text(p) for p in intro] == [_notice(data), f"과제: {data['project']['name']}", "협의·수행·승인·서명 사실과 근거는 별도 확인이 필요하다."]
    assert all(keep(p).get("keepWithNext") == "1" for p in intro)
    assert list(root)[index + 4].find(".//hp:tbl", NS) is cards[0]
    assert sha(inputs["SF-TD3"]["source_path"]) == inputs["SF-TD3"]["sha256"]


@pytest.mark.corpus
def test_td3_long_cards_allow_cell_continuation_and_precede_review_section(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.renderers import _own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    sentinel = "LONG-SCREEN-CHECK-END"
    data["screens"][0]["checks"].append("검토 내용 " * 500 + sentinel)
    source = dataset(tmp_path, data)
    output = generate_project(source, tmp_path / "td3-long", roles=["SF-TD3"])["documents"][0]
    doc = TemplateDocument(output["path"])
    cards = doc.tables()[1:]
    assert len(cards) == len(data["screens"])
    for card, screen in zip(cards, data["screens"]):
        assert card.get("pageBreak") == "CELL"
        assert card.find("hp:pos", NS).get("treatAsChar") == "0"
        assert all(cell.get("header") == "1" for cell in card.findall("hp:tr", NS)[0].findall("hp:tc", NS))
        body = "".join(card.itertext())
        for program in screen["program_ids"]:
            assert program in body
        for permission in screen["permissions"]:
            assert permission["role"] in body and permission["permission"] in body
        for ref in screen["source_refs"]:
            assert ref["source_id"] in body and ref["locator"] in body
    assert sentinel in "".join(cards[0].itertext())
    root = doc.root()
    review = next(p for p in root if _own_text(p).startswith("4. 화면 검토 결과"))
    last_card = next(p for p in root if cards[-1] in p.iter())
    assert list(root).index(review) == list(root).index(last_card) + 1
    assert review.get("pageBreak") == "1"


@pytest.mark.parametrize("role,body_section,first_table", [("SF-TD4", 0, 1), ("SF-CD1", 1, 0), ("SF-TI4", 1, 0)])
@pytest.mark.corpus
def test_guide_restart_is_discarded_and_body_start_number_is_kept(inputs, generated, role, body_section, first_table):
    from doc_automation.compose import TemplateDocument
    source = TemplateDocument(inputs[role]["source_path"])
    source_restarts = source.root(body_section).findall(".//hp:newNum[@numType='PAGE']", NS)
    assert len(source_restarts) == 2
    output = TemplateDocument(generated[0][role]["path"])
    restarts = output.root(body_section).findall(".//hp:newNum[@numType='PAGE']", NS)
    assert len(restarts) == 1 and dict(restarts[0].attrib) == dict(source_restarts[0].attrib)
    root = output.root(body_section)
    restart_paragraph = next(p for p in root if restarts[0] in p.iter())
    first_card = next(p for p in root if output.tables(body_section)[first_table] in p.iter())
    assert list(root).index(restart_paragraph) <= list(root).index(first_card)
    assert all(not card.findall(".//hp:newNum", NS) for card in output.tables(body_section)[first_table:])
    assert ET.tostring(source.root(body_section).find(".//hp:secPr", NS)) == ET.tostring(output.root(body_section).find(".//hp:secPr", NS))


@pytest.mark.parametrize("resolved_date", [None, "2026-11-03"])
@pytest.mark.corpus
def test_cd1_completion_cell_is_only_date_and_full_verification_remains_at_page_width(inputs, tmp_path, resolved_date):
    from doc_automation.compose import TemplateDocument
    from doc_automation.renderers import _own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    defect = data["defects"][0]
    aid = data["attachments"][0]["id"]
    defect.update(resolved_date=resolved_date, resolution_status="verified" if resolved_date else "unverified",
        verification_evidence_ids=[aid], notes="COMPLETE-DEFECT-NOTES",
        owner={"name": "INPUT-DEFECT-OWNER", "review_status": "provided"})
    source = dataset(tmp_path, data)
    output = generate_project(source, tmp_path / "cd1-wide", roles=["SF-CD1"])["documents"][0]
    doc = TemplateDocument(output["path"])
    table = doc.tables(1)[-1]
    date_cell = "".join(doc.cell(table, 1, 5).itertext())
    assert date_cell == (resolved_date or "미확인")
    assert "검증 상세 참조" in "".join(doc.cell(table, 1, 4).itertext())
    wide = "\n".join(_own_text(p) for p in doc.root(1) if p.find(".//hp:tbl", NS) is None)
    assert f"[D1] {defect['id']}" in wide
    assert defect["resolution_status"] in wide and aid in wide
    assert "확인자 실명 자료 미제공" in wide
    assert "INPUT-DEFECT-OWNER" in wide and "COMPLETE-DEFECT-NOTES" in wide
    for ref in defect["source_refs"]:
        assert ref["source_id"] in wide and ref["locator"] in wide
    source_doc = TemplateDocument(inputs["SF-CD1"]["source_path"])
    assert doc.cell(table, 1, 5).find("hp:cellSz", NS).get("width") == source_doc.cell(source_doc.tables(1)[-1], 1, 5).find("hp:cellSz", NS).get("width")


@pytest.mark.parametrize("role", ["SF-OS1", "SF-TD3", "SF-TD4", "SF-TD5"])
@pytest.mark.corpus
def test_body_numbering_is_anchored_at_the_actual_first_body_page(generated, role):
    from doc_automation.compose import TemplateDocument
    from doc_automation.renderers import _own_text
    doc = TemplateDocument(generated[0][role]["path"])
    root = doc.root()
    numbering = [p for p in root if p.findall("./hp:run/hp:ctrl/hp:newNum[@numType='PAGE']", NS)]
    assert len(numbering) == 1
    target = numbering[0]
    assert target.get("pageBreak") == "1"
    if role == "SF-TD3":
        assert _own_text(target).startswith("1. 화면 표준(검토안)")
    else:
        assert doc.tables()[1] in target.iter()
    assert dict(target.find("./hp:run/hp:ctrl/hp:newNum", NS).attrib) == {"num": "1", "numType": "PAGE"}
    assert target.find("./hp:run/hp:ctrl/hp:pageNum", NS).get("pos") == "BOTTOM_CENTER"


@pytest.mark.corpus
def test_pm4_narrow_remarks_reference_full_trace_details_without_losing_ids(inputs, generated):
    from doc_automation.compose import TemplateDocument
    from doc_automation.renderers import _own_text
    doc = TemplateDocument(generated[0]["SF-PM4"]["path"])
    source = TemplateDocument(inputs["SF-PM4"]["source_path"])
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    wide = "\n".join(_own_text(p) for p in doc.root() if p.find(".//hp:tbl", NS) is None)
    rows = {"functional": 0, "nonfunctional": 0}
    for index, requirement in enumerate(data["requirements"], 1):
        kind = requirement["kind"]
        table_index, last_column = (1, 9) if kind == "functional" else (2, 6)
        rows[kind] += 1
        cell = doc.cell(doc.tables()[table_index], rows[kind], last_column)
        assert "".join(cell.itertext()) == f"T{index}"
        assert cell.find("hp:cellSz", NS).get("width") == source.cell(source.tables()[table_index], 1, last_column).find("hp:cellSz", NS).get("width")
        assert f"[T{index}] {requirement['id']} {requirement['name']}" in wide
        assert requirement["notes"] in wide
        for ref in requirement["source_refs"]:
            assert ref["source_id"] in wide and ref["locator"] in wide
        for feature in data["features"]:
            if requirement["id"] in feature["requirement_ids"]:
                assert feature["id"] in wide
        for change in data["changes"]:
            if any(ref.get("kind") == "requirements" and ref.get("id") == requirement["id"] for ref in change["affected_refs"]):
                assert f"{change['id']} ({change['approval_status']})" in wide
        if kind == "nonfunctional" and requirement.get("original_classification"):
            assert requirement["original_classification"] in wide


def _pm4_requirement_detail(doc, rid):
    from doc_automation.renderers import _own_text
    paragraphs = [_own_text(p) for p in doc.root() if p.find(".//hp:tbl", NS) is None]
    start = next(i for i, value in enumerate(paragraphs) if value.startswith("[T") and f"] {rid} " in value)
    end = next((i for i in range(start + 1, len(paragraphs)) if paragraphs[i].startswith("[T")), len(paragraphs))
    return "\n".join(paragraphs[start:end])


@pytest.mark.corpus
def test_pm4_nonfunctional_detail_preserves_all_demo_screen_program_trace_links(generated):
    from doc_automation.compose import TemplateDocument
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    rid = "DEMO-AD2-003"
    detail = _pm4_requirement_detail(TemplateDocument(generated[0]["SF-PM4"]["path"]), rid)
    assert "화면: DEMO-TD3-001, DEMO-TD3-002; 프로그램: DEMO-TD4-001, DEMO-TD4-002" in detail
    for trace in data["trace_links"]:
        if trace["target_kind"] == "requirements" and trace["target_id"] == rid:
            assert json.dumps(trace, ensure_ascii=False, sort_keys=True) in detail


@pytest.mark.parametrize("large_trace", [False, True])
@pytest.mark.corpus
def test_pm4_wide_keeps_short_titles_and_single_bounded_trace_without_chaining_records(inputs, tmp_path, large_trace):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    if large_trace:
        data["trace_links"][0]["notes"] = "LARGE-TRACE-NOTES-" * 100
    result = generate_project(dataset(tmp_path, data), tmp_path / "pm4-keeps", roles=["SF-PM4"])
    doc = TemplateDocument(result["documents"][0]["path"])
    properties = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//{http://www.hancom.co.kr/hwpml/2011/head}paraPr")}
    paragraphs = list(doc.root())
    start = next(i for i, p in enumerate(paragraphs) if own_text(p) == "3. 요구사항별 추적 근거·검토상태")
    observed_traces = []
    for p in paragraphs[start:]:
        value = own_text(p)
        if not value:
            continue
        flags = properties[p.get("paraPrIDRef")].find("{http://www.hancom.co.kr/hwpml/2011/head}breakSetting")
        title = value.startswith("[T") or value in {"3. 요구사항별 추적 근거·검토상태", "4. 구분 미확인 요구사항과 추적 근거"}
        if title:
            assert flags.get("keepLines") == flags.get("keepWithNext") == "1"
        elif value.startswith("명시 추적 연결 원문: {"):
            observed_traces.append(value.removeprefix("명시 추적 연결 원문: "))
            assert (flags.get("keepLines") == "1") is (len(value) <= 720)
            assert flags.get("keepWithNext") == "0"
        else:
            assert flags.get("keepWithNext") == "0"
            assert (flags.get("keepLines") == "1") is (len(value) <= 240)
    expected = [json.dumps(t, ensure_ascii=False, sort_keys=True) for t in data["trace_links"]]
    assert sorted(observed_traces) == sorted(expected)
    if large_trace:
        assert any(len(value) > 720 for value in observed_traces)
    assert sha(inputs["SF-PM4"]["source_path"]) == inputs["SF-PM4"]["sha256"]


@pytest.mark.parametrize("kind", ["functional", "nonfunctional", None])
@pytest.mark.corpus
def test_pm4_all_classifications_keep_direct_and_bidirectional_cross_domain_trace(inputs, tmp_path, kind):
    from doc_automation.compose import TemplateDocument
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    requirement = data["requirements"][0]
    rid = requirement["id"]
    requirement.update(kind=kind, original_classification=f"RAW-PM4-CLASS-{kind}", notes="REQUIREMENT-TRACE-NOTES-" + "원문 " * 100)
    # Direct links remain available where the source domain has requirement_ids.
    for domain in ("screens", "programs", "test_cases"):
        for item in data[domain]:
            item["requirement_ids"] = [value for value in item.get("requirement_ids", []) if value != rid]
        data[domain][0]["requirement_ids"].append(rid)
    raw = []
    endpoints = [
        ("screens", "DEMO-TD3-002", False), ("screens", "DEMO-TD3-002", True),
        ("programs", "DEMO-TD4-002", True),
        ("database_tables", "DEMO_PRODUCTION_RESULT", False), ("database_tables", "DEMO_QUALITY_INSPECTION", True),
        ("test_cases", "DEMO-TEST-002", False), ("test_cases", "DEMO-TEST-003", True),
        ("test_cases", "DEMO-TEST-004", False), ("test_cases", "DEMO-TEST-005", True),
        ("features", "DEMO-AD3-006", False), ("defects", "DEMO-DEFECT-001", True),
    ]
    for i, (domain, ident, outgoing) in enumerate(endpoints):
        trace = deepcopy(data["trace_links"][0])
        trace.update(id=f"PM4-EXPLICIT-{i}", name=f"TRACE-NAME-{i}",
                     source_kind="requirements" if outgoing else domain, source_id=rid if outgoing else ident,
                     target_kind=domain if outgoing else "requirements", target_id=ident if outgoing else rid,
                     relation="related_to" if outgoing else "depends_on", rationale=f"TRACE-RATIONALE-{i}",
                     notes=f"TRACE-NOTES-{i}-" + "충실한 원문 " * 80, content_review_status="needs_changes",
                     source_refs=deepcopy(data["trace_links"][i]["source_refs"]))
        raw.append(trace)
    unrelated = deepcopy(data["trace_links"][0])
    unrelated.update(id="PM4-UNRELATED-TRACE", target_id=data["requirements"][1]["id"], notes="UNRELATED-NOTES-MUST-NOT-LEAK")
    data["trace_links"] = raw + [unrelated]
    output = generate_project(dataset(tmp_path, data), tmp_path / "pm4-trace", roles=["SF-PM4"])["documents"][0]
    doc = TemplateDocument(output["path"])
    detail = _pm4_requirement_detail(doc, rid)
    assert "화면: DEMO-TD3-001, DEMO-TD3-002; 프로그램: DEMO-TD4-001, DEMO-TD4-002; DB: DEMO_PRODUCTION_RESULT, DEMO_QUALITY_INSPECTION" in detail
    assert "단위시험: DEMO-TEST-001, DEMO-TEST-002; 통합시험: DEMO-TEST-003; 사용자시험: DEMO-TEST-004, DEMO-TEST-005" in detail
    assert requirement["original_classification"] in detail and requirement["notes"] in detail
    for trace in raw:
        # Whole raw objects catch lost direction/domain/relation, notes, status,
        # content-review judgment or source refs rather than mere ID presence.
        assert json.dumps(trace, ensure_ascii=False, sort_keys=True) in detail
    assert "PM4-UNRELATED-TRACE" not in detail and "UNRELATED-NOTES-MUST-NOT-LEAK" not in detail
    functional = "".join(doc.tables()[1].itertext())
    nonfunctional = "".join(doc.tables()[2].itertext())
    assert (rid in functional) is (kind == "functional")
    assert (rid in nonfunctional) is (kind == "nonfunctional")
    assert sha(inputs["SF-PM4"]["source_path"]) == inputs["SF-PM4"]["sha256"]


@pytest.mark.parametrize("requester_name", [None, "PROVIDED-REQUESTER-NAME"])
@pytest.mark.corpus
def test_pm3_short_unknown_cells_preserve_supplied_requester_and_approval_details(inputs, tmp_path, requester_name):
    from doc_automation.compose import TemplateDocument
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["dataset_kind"] = "project"
    change = data["changes"][0]
    change.update(approval_status="pending", request_date=None, response_date=None,
        requester={"name": requester_name, "review_status": "provided", "organization_role": "customer", "organization_name": "PROVIDED-ORGANIZATION", "title": "PROVIDED-TITLE", "contact": "PROVIDED-CONTACT", "source_refs": change["source_refs"]})
    path = dataset(tmp_path, data)
    output = generate_project(path, tmp_path / "pm3-short", roles=["SF-PM3"])["documents"][0]
    doc = TemplateDocument(output["path"])
    assert "".join(doc.cell(doc.tables()[1], 1, 4).itertext()) == (requester_name or "미지정")
    assert "".join(doc.cell(doc.tables()[1], 1, 3).itertext()) == "미확인"
    assert "".join(doc.cell(doc.tables()[-1], 2, 3).itertext()) == "미확인"
    detail = "".join(doc.cell(doc.tables()[-1], 6, 1).itertext())
    for value in ["pending", "PROVIDED-ORGANIZATION", "PROVIDED-TITLE", "PROVIDED-CONTACT", "provided", "요청일 미제공", "회신일 미제공"]:
        assert value in detail
    if requester_name:
        assert requester_name in detail
    assert "미요청" not in "".join(doc.cell(doc.tables()[-1], 2, 3).itertext())


@pytest.mark.parametrize("changes_count", [1, 2])
@pytest.mark.corpus
def test_pm3_request_title_starts_detail_page_without_keeping_the_table(inputs, tmp_path, changes_count):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    if changes_count == 2:
        extra = deepcopy(data["changes"][0])
        extra.update(id="SECOND-CHANGE-REQUEST", name="추가 입력 변경요청", notes="SECOND-CHANGE-NOTES")
        data["changes"].append(extra)
    output = generate_project(dataset(tmp_path, data), tmp_path / "pm3-title", roles=["SF-PM3"])["documents"][0]
    doc = TemplateDocument(output["path"])
    properties = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//{http://www.hancom.co.kr/hwpml/2011/head}paraPr")}
    titles = [p for p in doc.root() if own_text(p).strip() == "변경요청서"]
    assert len(titles) == 1
    title = titles[0]
    assert title.get("pageBreak") == "1"
    flags = properties[title.get("paraPrIDRef")].find("{http://www.hancom.co.kr/hwpml/2011/head}breakSetting")
    assert flags.get("keepLines") == flags.get("keepWithNext") == "1"
    cards = doc.tables()[2:]
    assert len(cards) == changes_count and title.getnext().find(".//hp:tbl", NS) is cards[0]
    for table, change in zip(cards, data["changes"]):
        assert table.get("pageBreak") == "NONE" and table.find("hp:pos", NS).get("treatAsChar") == "0"
        anchor = next(p for p in table.iterancestors() if p.tag == f"{{{HP}}}p")
        flags = properties[anchor.get("paraPrIDRef")].find("{http://www.hancom.co.kr/hwpml/2011/head}breakSetting")
        assert flags.get("keepLines") == flags.get("keepWithNext") == "0"
        detail = "\n".join(own_text(p) for p in table.iter(f"{{{HP}}}p"))
        assert change["id"] in detail and change["notes"] in detail
    assert doc.root()[0].find(".//hp:secPr", NS) is not None
    assert sha(inputs["SF-PM3"]["source_path"]) == inputs["SF-PM3"]["sha256"]


@pytest.mark.corpus
def test_pm3_provided_dates_numbers_and_long_name_are_not_shortened(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["dataset_kind"] = "project"
    change = data["changes"][0]
    name = "미확인이라는문자가포함돼도실제입력된긴요청자명전체를유지"
    change.update(approval_status="pending", request_date="2026-11-01", response_date="2026-11-02",
        request_number="PROVIDED-REQUEST-NO-001", response_number="PROVIDED-RESPONSE-NO-002",
        response_content="PROVIDED-RESPONSE-CONTENT", requester={"name": name, "review_status": "provided"})
    output = generate_project(dataset(tmp_path, data), tmp_path / "pm3-provided", roles=["SF-PM3"])["documents"][0]
    doc = TemplateDocument(output["path"])
    register, card = doc.tables()[1], doc.tables()[-1]
    for column, value in [(2, change["request_number"]), (3, change["request_date"]), (4, name), (5, change["response_number"]), (6, change["response_content"]), (7, change["response_date"])]:
        assert "".join(doc.cell(register, 1, column).itertext()) == value
    assert "".join(doc.cell(card, 2, 3).itertext()) == change["request_date"]
    detail = "".join(doc.cell(card, 6, 1).itertext())
    for value in [change["id"], change["request_number"], change["request_date"], name, change["response_number"], change["response_content"], change["response_date"], "pending"]:
        assert value in detail


@pytest.mark.corpus
def test_td3_unknown_required_and_typed_defaults_are_not_conflated(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    screen = data["screens"][0]
    prototype = deepcopy(screen["fields"][0])
    cases = [("UNKNOWN-ZERO", None, 0), ("OPTIONAL-FALSE", False, False), ("REQUIRED-TEXT", True, "NONNULL-DEFAULT"),
        ("UNKNOWN-NULL", None, None), ("OPTIONAL-EMPTY-TEXT", False, ""), ("REQUIRED-EMPTY-OBJECT", True, {}),
        ("UNKNOWN-ARRAY", None, ["one", False, 0])]
    screen["fields"] = []
    for name, required, default in cases:
        field = deepcopy(prototype)
        field.update(name=name, required=required, default_value=default)
        screen["fields"].append(field)
    screen["notes"] = "FULL-SCREEN-NOTES: 제공된 화면 비고 전체를 보존한다."
    output = generate_project(dataset(tmp_path, data), tmp_path / "td3-metadata", roles=["SF-TD3"])
    doc = TemplateDocument(output["documents"][0]["path"])
    card = doc.tables()[1]
    fields = "".join(doc.cell(card, 3, 1).itertext())
    for name, required, default in cases:
        line = fields[fields.index(name):].split("]: ", 1)[0]
        label = "필수" if required is True else "선택" if required is False else "필수 여부 미확인"
        assert f" / {label} / " in line
        if default is None:
            assert "기본값 미확인(null)" in line
        else:
            assert "기본값=" + json.dumps(default, ensure_ascii=False, sort_keys=True) in line
        if required is None:
            assert " / 선택 / " not in line
    detail = "".join(doc.cell(card, 4, 1).itertext())
    assert screen["notes"] in detail
    assert "기능 연결:" in detail
    for feature_id in screen["feature_ids"]:
        assert feature_id in detail
    assert card.get("pageBreak") == "CELL" and card.find("hp:pos", NS).get("treatAsChar") == "0"
    numbering = [p for p in doc.root() if p.findall("./hp:run/hp:ctrl/hp:newNum[@numType='PAGE']", NS)]
    assert len(numbering) == 1 and numbering[0].get("pageBreak") == "1"
    assert any("필드/버튼/권한의 개별 source_refs" in warning for warning in output["documents"][0]["warnings"])


@pytest.mark.parametrize("all_unknown", [False, True])
@pytest.mark.corpus
def test_unclassified_requirements_are_preserved_without_becoming_nonfunctional(inputs, tmp_path, all_unknown):
    from doc_automation.compose import TemplateDocument
    from doc_automation.renderers import _own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    for i, requirement in enumerate(data["requirements"]):
        requirement["kind"] = None if all_unknown or i == 0 else "functional" if i == 1 else "nonfunctional"
    first = data["requirements"][0]
    first.update(original_id="RAW-UNCLASSIFIED-ID", original_classification="RAW-CLASSIFICATION-UNCONFIRMED", notes="UNKNOWN-REQUIREMENT-NOTES")
    first["field_states"] = {"/kind": {"status": "unverified", "reason": "CLASSIFICATION-NEEDS-REVIEW", "source_refs": first["source_refs"]}}
    output = generate_project(dataset(tmp_path, data), tmp_path / "unknown-requirement", roles=["SF-AD2", "SF-PM4"])
    documents = {d["role"]: TemplateDocument(d["path"]) for d in output["documents"]}
    ad2, pm4 = documents["SF-AD2"], documents["SF-PM4"]
    by_id = {r["id"]: r for r in data["requirements"]}
    for card in ad2.tables(1):
        requirement = by_id["".join(ad2.cell(card, 1, 1).itertext())]
        assert "".join(ad2.cell(card, 5, 1).itertext()) == {"functional": "기능", "nonfunctional": "비기능"}.get(requirement["kind"], "구분 미확인")
    known_tables = "\n".join("".join(table.itertext()) for table in pm4.tables()[1:])
    wide = "\n".join(_own_text(p) for p in pm4.root() if p.find(".//hp:tbl", NS) is None)
    assert "4. 구분 미확인 요구사항과 추적 근거" in wide
    for requirement in data["requirements"]:
        if requirement["kind"] is not None:
            assert requirement["id"] in known_tables
            continue
        assert requirement["id"] not in known_tables
        for value in [requirement["id"], requirement["name"], requirement["description"], *requirement["details"], *requirement["constraints"], requirement["notes"]]:
            assert value in wide
        for ref in requirement["source_refs"]:
            assert ref["source_id"] in wide and ref["locator"] in wide
        for trace in data["trace_links"]:
            if (trace["source_kind"] == "requirements" and trace["source_id"] == requirement["id"]) or (trace["target_kind"] == "requirements" and trace["target_id"] == requirement["id"]):
                assert json.dumps(trace, ensure_ascii=False, sort_keys=True) in wide
    for value in ["RAW-UNCLASSIFIED-ID", "RAW-CLASSIFICATION-UNCONFIRMED", "CLASSIFICATION-NEEDS-REVIEW"]:
        assert value in wide
    if all_unknown:
        assert "요구사항ID1" not in known_tables and "요구사항명1" not in known_tables


@pytest.mark.parametrize("kind", ["monthly", "weekly", "interim", "completion", "other", None])
@pytest.mark.corpus
def test_pm1_report_types_and_unknown_risk_are_not_reclassified(inputs, tmp_path, kind):
    from doc_automation.compose import TemplateDocument
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    report = data["progress_reports"][0]
    report["report_kind"] = kind
    prototype = deepcopy(report["risks"][0])
    report["risks"] = []
    for i, risk_kind in enumerate(["risk", "issue", None]):
        risk = deepcopy(prototype)
        risk.update(number=f"MIXED-RISK-{i}", kind=risk_kind)
        report["risks"].append(risk)
    output = generate_project(dataset(tmp_path, data), tmp_path / "report-types", roles=["SF-PM1"])["documents"][0]
    doc = TemplateDocument(output["path"])
    body = text(output["path"])
    table = doc.tables()[2]
    assert ["".join(doc.cell(table, i, 1).itertext()) for i in range(1, 4)] == ["위험", "이슈", "미확인"]
    if kind == "weekly":
        assert "주간 계획자료 검토본(월간 양식 사용)" in body
        assert "월간보고서 검토본" not in body
    elif kind == "monthly":
        assert "월간보고서 검토본" in body
    else:
        assert "월간보고서 검토본" not in body
        assert "월간 양식 사용" in body
        assert f"입력 보고 유형: {json.dumps(kind, ensure_ascii=False)}" in body
        assert "보고 유형만으로 실제 완료·수행을 판정하지 않는다" in body
        assert "".join(doc.cell(doc.tables()[1], 0, 0).itertext()) == "해당기간 입력 내용"


@pytest.mark.corpus
def test_td5_unknown_scale_is_not_defaulted_to_zero(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    columns = data["database_tables"][0]["columns"]
    for column, scale in zip(columns, [None, 0, 3]):
        column.update(type="DECIMAL", length=None, precision=12, scale=scale)
    output = generate_project(dataset(tmp_path, data), tmp_path / "unknown-scale", roles=["SF-TD5"])["documents"][0]
    doc = TemplateDocument(output["path"])
    assert ["".join(doc.cell(doc.tables()[1], i, 4).itertext()) for i in range(1, 4)] == ["DECIMAL(12,미확인)", "DECIMAL(12,0)", "DECIMAL(12,3)"]
    body = text(output["path"])
    assert "scale=null" in body and "scale=0" in body and "scale=3" in body


@pytest.mark.parametrize("provided", [False, True])
@pytest.mark.corpus
def test_project_missing_execution_is_unknown_and_provided_installation_meeting_inputs_survive(inputs, tmp_path, provided):
    from doc_automation.compose import TemplateDocument
    from doc_automation.renderers import _own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["dataset_kind"] = "project"
    data["project"]["name"] = "TEST-ONLY 검증용 합성 실제입력 반례(실제 사실 아님)"
    data["test_cases"] = []
    data["trace_links"] = [trace for trace in data["trace_links"] if trace["source_kind"] != "test_cases" and trace["target_kind"] != "test_cases"]
    for defect in data["defects"]:
        defect.update(test_case_id=None, resolution=None)
    for support in data["project"]["support_activities"]:
        support["actual_result"] = None
    item = data["deployment_items"][0]
    item.update(installation_status="verified" if provided else "unverified", actual_specification="PROVIDED-ACTUAL-SPEC" if provided else None,
        installed_quantity=1 if provided else None, installation_date="2026-11-01" if provided else None,
        verification_result="PROVIDED-VERIFICATION-RESULT" if provided else None,
        evidence_ids=[data["attachments"][0]["id"]] if provided else [])
    meeting = data["meetings"][0]
    meeting.update(date=None, discussions=["PROVIDED-DISCUSSION"] if provided else [], decisions=["PROVIDED-DECISION"] if provided else [],
        attendees=[{"name": "PROVIDED-ATTENDEE", "organization_role": "customer", "status": "provided", "source_refs": []}] if provided else [])
    roles = ["SF-TD2", "SF-TI1", "SF-TI4", "SF-OS2", "SF-PM2", "SF-TI2", "SF-OS1"]
    result = generate_project(dataset(tmp_path, data), tmp_path / "execution-state", roles=roles)
    docs = {output["role"]: TemplateDocument(output["path"]) for output in result["documents"]}
    td2 = "\n".join("".join(root.itertext()) for root in [docs["SF-TD2"].root(i) for i in range(len(docs["SF-TD2"].sections))])
    assert "실제 설치: 미수행" not in td2
    assert "실제 설치 입력 상태: " + item["installation_status"] in td2
    if provided:
        for value in [item["actual_specification"], item["installation_date"], item["verification_result"], item["evidence_ids"][0]]:
            assert value in td2
    else:
        assert "실제 수행 자료 미제공·미확인" in td2
    for role in ["SF-TI1", "SF-TI4"]:
        content = "".join(docs[role].tables(1)[0].itertext())
        assert "시험 계획 자료 미제공·실행 여부 미확인" in content
        assert "실행 미수행" not in content
    os2 = "\n".join("".join(docs["SF-OS2"].root(i).itertext()) for i in range(len(docs["SF-OS2"].sections)))
    assert "조치 실제 수행 자료 미제공·미확인" in os2
    assert "지원 결과 입력: 실제 수행 자료 미제공·미확인" in os2
    assert "등록 로그가 없어" not in os2 and "원시자료와 집계 근거의 제공 범위" in os2
    assert "합성 운영집계 검토(실제 운영 아님)" not in os2
    meeting_card = docs["SF-PM2"].tables()[-1]
    assert "".join(docs["SF-PM2"].cell(meeting_card, 0, 1).itertext()) == "개최일 미확인"
    if provided:
        for value in ["PROVIDED-DISCUSSION", "PROVIDED-DECISION", "PROVIDED-ATTENDEE"]:
            assert value in "".join(meeting_card.itertext())
    for role, denied in [("SF-TI2", ["계획/미설치", "계획/미수행"]), ("SF-OS1", ["지원 계획/실제 미수행", "실인원 미확인"])]:
        toc = "\n".join(_own_text(p) for p in docs[role].root())
        assert all(label not in toc for label in denied)


@pytest.mark.corpus
def test_td3_project_approval_is_retained_without_claiming_approval_absent(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["dataset_kind"] = "project"
    data["project"]["name"] = "TEST-ONLY 검증용 합성 승인입력(실제 사실 아님)"
    data["reviews"].append({"id": "PROVIDED-APPROVAL", "name": "TEST-ONLY 합성 승인입력", "status": "provided", "source_refs": [],
        "review_type": "approval", "outcome": "approved", "artifact_id": None, "artifact_sha256": None,
        "reviewer": "PROVIDED-REVIEWER", "reviewed_at": "2026-11-03T10:00:00+09:00", "evidence_ids": [data["attachments"][0]["id"]]})
    data["screens"][0]["review_ids"] = ["PROVIDED-APPROVAL"]
    output = generate_project(dataset(tmp_path, data), tmp_path / "approved-screen", roles=["SF-TD3"])["documents"][0]
    doc = TemplateDocument(output["path"])
    body = "".join(doc.root().itertext())
    assert "공통 표준의 실제 승인은 미수행이다" not in body
    assert "캡처·승인 없음" not in body
    assert "캡처 이미지 미삽입" in body and "실제 승인 범위·상태" in body
    for value in ["PROVIDED-APPROVAL", "approved", "PROVIDED-REVIEWER", "2026-11-03T10:00:00+09:00"]:
        assert value in body


def test_editorial_trace_prose_preserves_direction_and_every_supplied_field():
    from doc_automation.narrative import trace_paragraphs
    trace = {"id": "LINK-1", "name": "검증 연결", "source_kind": "screens", "source_id": "SCREEN-A",
        "target_kind": "requirements", "target_id": "REQ-B", "relation": "depends_on", "rationale": "SUPPLIED-RATIONALE",
        "notes": "", "status": "unverified", "content_review_status": "needs_changes",
        "source_refs": [{"source_id": "SOURCE-C", "locator": "/trace/0"}], "extra_supplied_field": False}
    paragraphs = trace_paragraphs(trace)
    body = "\n".join(paragraphs)
    assert "연결 방향: 화면 SCREEN-A → 요구사항 REQ-B" in body
    for value in ("LINK-1", "depends_on", "SUPPLIED-RATIONALE", "unverified", "needs_changes", "SOURCE-C", "/trace/0", "extra_supplied_field", "false", "빈 문자열"):
        assert value in body
    assert '{"' not in body and '"source_kind"' not in body


@pytest.mark.parametrize("kind", ["PNG", "JPEG", "BMP"])
@pytest.mark.corpus
def test_td3_supplied_images_keep_slot_ratio_bytes_and_caption(inputs, tmp_path, kind):
    from doc_automation.compose import TemplateDocument
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    attachment = image_attachment(tmp_path, data, kind=kind)
    for slot in ("standard_attachment_ids", "before_attachment_ids", "after_attachment_ids"):
        data["screens"][0][slot] = [attachment["id"]]
    source_bytes = Path(attachment["path"]).read_bytes()
    result = generate_project(dataset(tmp_path, data), tmp_path / "images", roles=["SF-TD3"])["documents"][0]
    bindings = result["image_bindings"]
    assert {binding["slot"] for binding in bindings} == {"standard_attachment_ids", "before_attachment_ids", "after_attachment_ids"}
    assert all(binding["sha256"] == attachment["sha256"] and binding["crop"] == "none" for binding in bindings)
    assert all(binding["width_mm"] / binding["height_mm"] == pytest.approx(2, abs=0.001) for binding in bindings)
    assert all(binding["conversion"] == ("bmp_to_png_lossless" if kind == "BMP" else "none") for binding in bindings)
    assert Path(attachment["path"]).read_bytes() == source_bytes
    doc = TemplateDocument(result["path"])
    card = doc.tables()[1]
    assert len(card.findall(".//hp:pic", NS)) == 3
    for picture, binding in zip(card.findall(".//hp:pic", NS), bindings):
        actual = picture.find("hp:curSz", NS)
        assert int(actual.get("width")) == binding["width_hwp"]
        assert int(actual.get("height")) == binding["height_hwp"]
    body = "".join(card.itertext())
    for value in (attachment["id"], "합성 시안·실제 실행화면 아님", "SYNTHETIC-IMAGE-NOTES", attachment["source_id"], "그림·캡션·출처 연결 시험"):
        assert value in body
    assert "캡처 이미지 미삽입" not in body
    assert validate_package(result["path"])["picture_count"] == 3
    with ZipFile(result["path"]) as archive:
        embedded = [archive.read(name) for name in archive.namelist() if name.startswith("BinData/")]
    assert any(hashlib.sha256(raw).hexdigest() == bindings[0]["embedded_sha256"] for raw in embedded)
    if kind != "BMP":
        assert source_bytes in embedded


@pytest.mark.corpus
def test_image_mime_mismatch_stops_before_output(inputs, tmp_path):
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    attachment = image_attachment(tmp_path, data, kind="PNG", declared_media="image/jpeg")
    data["screens"][0]["after_attachment_ids"] = [attachment["id"]]
    output = tmp_path / "bad-mime"
    with pytest.raises(ValueError, match="differ from declared MIME"):
        generate_project(dataset(tmp_path, data), output, roles=["SF-TD3"])
    assert not output.exists()


@pytest.mark.corpus
def test_editorial_cover_slots_keep_actual_owners_and_supplied_program(inputs):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    from doc_automation.renderers import _prepare
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["project"]["program_name"] = "제공한 사업명 그대로 보존"
    doc = TemplateDocument(inputs["SF-AD2"]["source_path"])
    _prepare(doc, "SF-AD2", data, editorial=True)
    roles = doc._editorial_cover_paragraphs
    assert set(roles) == {"program", "title", "customer", "date", "supplier", "notice"}
    assert all(paragraph in doc.root().iter() for paragraph in roles.values())
    assert own_text(roles["program"]) == f"{data['project']['program_year']}년도 {data['project']['program_name']}"
    assert doc._editorial_cover_program_identity["expressed_input_pointers"] == ["/project/program_year", "/project/program_name"]
    assert own_text(roles["title"]) == "요구사항정의서"
    assert own_text(roles["notice"]) == NOTICE


@pytest.mark.parametrize("role,domain,field", [
    ("SF-AD1", "business_processes", "as_is_attachment_ids"),
    ("SF-TD1", "business_processes", "to_be_attachment_ids"),
    ("SF-TD2", "systems", "to_be_diagram_ids"),
    ("SF-TD4", "programs", "module_flow_attachment_ids"),
    ("SF-CD1", "test_cases", "flow_attachment_ids"),
    ("SF-TI1", "test_cases", "flow_attachment_ids"),
    ("SF-TI4", "test_cases", "flow_attachment_ids"),
    ("SF-TI3", "manual_sections", "attachment_ids"),
    ("SF-TI3", "screens", "after_attachment_ids"),
])
@pytest.mark.corpus
def test_role_images_preserve_entity_slot_and_evidence(inputs, tmp_path, role, domain, field):
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    attachment = image_attachment(tmp_path, data)
    collection = data["project"][domain] if domain in {"business_processes", "systems", "manual_sections"} else data[domain]
    stage = {"SF-CD1": "unit", "SF-TI1": "integration", "SF-TI4": "acceptance"}.get(role)
    item = next(item for item in collection if stage is None or item.get("stage") == stage)
    item[field] = [attachment["id"]]
    result = generate_project(dataset(tmp_path, data), tmp_path / role, roles=[role])["documents"][0]
    assert len(result["image_bindings"]) == 1
    binding = result["image_bindings"][0]
    assert binding["slot"] == field and binding["entity_id"] == item.get("id")
    assert attachment["id"] in text(result["path"])
    assert "그림·캡션·출처 연결 시험" in text(result["path"])
    assert validate_package(result["path"])["picture_count"] == 1


@pytest.mark.corpus
def test_reference_profile_pilots_keep_meanings_without_raw_json(inputs, tmp_path):
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    fields = data["screens"][0]["fields"]
    for field, default in zip(fields, [0, False, "", "0", None, {}]):
        field["default_value"] = default
    data["trace_links"][0]["notes"] = "FULL-TRACE-REASON"
    result = generate_project(dataset(tmp_path, data), tmp_path / "reference-pilots", roles=["SF-AD2", "SF-TD5", "SF-TD3", "SF-PM4"], style_profile="reference-v1")
    docs = {document["role"]: document for document in result["documents"]}
    for document in docs.values():
        assert document["editorial_profile"] and document["native_review_status"] == "pending"
        profile_source = document["editorial_profile"]["profile_source"]
        assert sha(profile_source["path"]) == profile_source["sha256"]
        correspondence = document["source_notes"]
        assert sha(correspondence["path"]) == correspondence["sha256"]
        source_notes = json.loads(Path(correspondence["path"]).read_text())
        assert source_notes["document_sha256"] == document["sha256"]
        assert source_notes["input_sha256"] == result["input"]["sha256"]
        assert len(source_notes["references"]) == correspondence["reference_count"]
        before_appendix = text(document["path"]).split("부록. 출처 대응표", 1)[0]
        assert "/screen_plan/" not in before_appendix and "/requirement_notes/" not in before_appendix
        assert validate_package(document["path"])["valid"]
    screen = text(docs["SF-TD3"]["path"])
    for value in ("0 (정수)", "아니오 (false·논리값)", "빈 문자열(문자열)", "0 (문자열)", "미확인(null)", "빈 객체(0개 항목)"):
        assert value in screen
    for field in fields:
        for ref in field["source_refs"]:
            assert ref["source_id"] in screen and ref["locator"] in screen
    trace = text(docs["SF-PM4"]["path"])
    assert "FULL-TRACE-REASON" in trace and "시작 종류 / ID" in trace and "대상 종류 / ID" in trace
    assert "명시 추적 연결 원문: {" not in trace
    assert '"source_kind"' not in trace and '"source_refs"' not in trace
    from doc_automation.compose import TemplateDocument
    database = TemplateDocument(docs["SF-TD5"]["path"])
    grids = [table for index in range(len(database.sections)) for table in database.tables(index) if table.get("colCnt") == "9"]
    assert len(grids) == 1
    grid = grids[0]
    assert len(grid.findall("hp:tr", NS)) == 20
    assert "NOT NULL" not in "".join(grid.itertext()) and "불가" in "".join(grid.itertext())
    assert "NULL 허용: 아니오 (false·논리값)" in text(docs["SF-TD5"]["path"])
    for table in data["database_tables"]:
        for column in table["columns"]:
            assert column["id"] in "".join(grid.itertext())
    # One document-level warning plus cover; no identical notice in each card.
    ad2 = text(docs["SF-AD2"]["path"])
    assert ad2.count(NOTICE) <= 2
    ad2_body = ad2.split("부록. 출처 대응표", 1)[0]
    assert "확인 상태: 합성 자료" in ad2_body and "확인 상태: synthetic" not in ad2_body
    assert "원문 분류: 기능" in ad2_body


@pytest.mark.corpus
def test_reference_unknown_execution_stays_unknown_in_synthetic_data(inputs, tmp_path):
    """Synthetic provenance supplies no evidence about real-world execution."""
    from doc_automation.compose import TemplateDocument
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["project"]["program_name"] = "합성 입력 사업명 — 표지 검증"
    for activity in data["project"]["support_activities"]:
        activity.update(plan="검토 예정", actual_result=None)
    for work in data["progress_reports"][0]["work_items"]:
        work.update(actual=None, next_plan="다음 계획")
    meeting = data["meetings"][0]
    meeting.update(date=None, discussions=[], decisions=[])
    roles = ["SF-TD2", "SF-OS1", "SF-OS2", "SF-PM1", "SF-PM2"]
    result = generate_project(dataset(tmp_path, data), tmp_path / "synthetic-unknown", roles=roles, style_profile="reference-v1")
    docs = {item["role"]: TemplateDocument(item["path"]) for item in result["documents"]}
    td2 = text(next(item["path"] for item in result["documents"] if item["role"] == "SF-TD2"))
    assert "실제 설치: 미수행" not in td2 and "실제 수행 자료 미제공·미확인" in td2
    for role in ("SF-OS1", "SF-OS2"):
        content = text(next(item["path"] for item in result["documents"] if item["role"] == role))
        assert "합성 입력 사업명 — 표지 검증" in content
        assert "스마트공장구축및고도화사업" not in content
        assert "실제 수행 자료 미제공·미확인" in content
        assert "지원 계획/실제 미수행" not in content
    pm1 = docs["SF-PM1"]
    work_table = next(table for i in range(len(pm1.sections)) for table in pm1.tables(i) if table.get("colCnt") == "2")
    assert "실제 결과: 실제 수행 자료 미제공·미확인" in "".join(pm1.cell(work_table, 1, 0).itertext())
    pm2 = docs["SF-PM2"]
    meeting_card = [table for i in range(len(pm2.sections)) for table in pm2.tables(i)][-1]
    date = "".join(pm2.cell(meeting_card, 0, 1).itertext())
    assert date == "개최일 미확인" and "미개최" not in date


@pytest.mark.corpus
def test_reference_conditions_manual_unknown_audience_and_nested_report_values_have_owners(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    program = data["programs"][0]
    program.update(query_conditions=["QUERY-CONDITION-V5"], registration_conditions=["REGISTER-CONDITION-V5"], calculation_rules=["CALCULATION-RULE-V5"])
    manual = data["project"]["manual_sections"][0]
    manual.update(audience=None, content="UNKNOWN-AUDIENCE-CONTENT-V5", version="MANUAL-VERSION-V5")
    work = data["progress_reports"][0]["work_items"][0]
    work.update(planned_progress=0, actual_progress=0)
    column = data["database_tables"][0]["columns"][0]
    column.update(original_id="COLUMN-ORIGINAL-V5", original_classification="COLUMN-CLASS-V5", expected_id=None, expected_name=None, definition_source_refs=[])
    result = generate_project(dataset(tmp_path, data), tmp_path / "semantic-owners", roles=["SF-TD4", "SF-TI3", "SF-PM1", "SF-TD5"], style_profile="reference-v1")
    docs = {item["role"]: item for item in result["documents"]}
    program_doc = TemplateDocument(docs["SF-TD4"]["path"])
    card = next(table for i in range(len(program_doc.sections)) for table in program_doc.tables(i) if table.get("colCnt") == "4" and program["id"] in "".join(table.itertext()))
    owner = "".join(program_doc.cell(card, 3, 1).itertext())
    for marker in ("QUERY-CONDITION-V5", "REGISTER-CONDITION-V5", "CALCULATION-RULE-V5"):
        assert marker in owner
    manual_content = text(docs["SF-TI3"]["path"])
    unknown_section = manual_content.split("3. 대상 사용자 미확인 설명", 1)[1].split("부록.", 1)[0]
    assert "UNKNOWN-AUDIENCE-CONTENT-V5" in unknown_section and "문서 버전: MANUAL-VERSION-V5" in unknown_section
    report_content = text(docs["SF-PM1"]["path"])
    assert "계획 진도: 0 (정수)" in report_content and "입력 실적 진도: 0 (정수)" in report_content
    column_content = text(docs["SF-TD5"]["path"])
    assert "원문 식별자: COLUMN-ORIGINAL-V5 (문자열)" in column_content
    assert "기준 ID=미확인(null); 기준명=미확인(null)" in column_content
    for output in docs.values():
        meaning = json.loads(Path(output["meaning_map"]["path"]).read_text())
        assert meaning["document_sha256"] == sha(output["path"])
        assert meaning["semantic_review_status"] == "pending"
        document = TemplateDocument(output["path"])
        for entity in meaning["entities"]:
            for field in entity["fields"]:
                assert field["content_review_status"] == "pending"
                if field["representation"] == "readable_supplement":
                    nodes = document.xml(field["owner"]["section"]).xpath(field["owner"]["xpath"], namespaces=meaning["xml_namespaces"])
                    assert len(nodes) == 1 and own_text(nodes[0]) == field["rendered_text"]


@pytest.mark.corpus
def test_reference_source_appendix_uses_source_contract_title_status_and_metadata(inputs, tmp_path):
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    source = data["sources"][0]
    source.update(title="SOURCE-TITLE-V5", verification_status="provided", notes="SOURCE-NOTES-V5")
    result = generate_project(dataset(tmp_path, data), tmp_path / "source-contract", roles=["SF-AD2"], style_profile="reference-v1")
    output = result["documents"][0]
    appendix = text(output["path"]).split("부록. 출처 대응표", 1)[1]
    for marker in ("SOURCE-TITLE-V5", "확인 상태 원문: provided", "SOURCE-NOTES-V5", source["sha256"], source["path"]):
        assert marker in appendix
    notes = json.loads(Path(output["source_notes"]["path"]).read_text())
    assert all(record["source"]["title"] == source["title"] and record["source"]["verification_status"] == "provided" for record in notes["references"])
    assert notes["document_sha256"] == sha(output["path"])
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    doc = TemplateDocument(output["path"])
    paragraphs = [p for i in range(len(doc.sections)) for p in doc.root(i).iter(f"{{{HP}}}p") if own_text(p)]
    title = next(i for i, p in enumerate(paragraphs) if own_text(p) == "부록. 출처 대응표")
    intro = paragraphs[title + 1]
    assert own_text(intro).startswith("표시값 원문 대응: ")
    for original, label in notes["code_mappings"].items():
        assert f"{label} ← {original}" in own_text(intro)
    assert own_text(paragraphs[title + 2]).startswith("자료: SOURCE-TITLE-V5")
    assert "확인 상태·분류·관계의 원문 값 대응" not in text(output["path"])
    hh = {"hh": "http://www.hancom.co.kr/hwpml/2011/head"}
    pp = doc.xml("Contents/header.xml").find(f".//hh:paraPr[@id='{intro.get('paraPrIDRef')}']", hh)
    flags = pp.find("hh:breakSetting", hh)
    assert flags.get("keepWithNext") == "1" and flags.get("keepLines") == "0" and flags.get("pageBreakBefore") == "0"
    # The bounded source introduction ends at its first citation paragraph;
    # later citations must not become a document-wide keep chain.
    owner = notes["references"][0]["owner"]
    first_citation = doc.xml(owner["section"]).xpath(owner["xpath"], namespaces=notes["xml_namespaces"])[0]
    assert own_text(first_citation) == owner["rendered_text"]
    citation_style = doc.xml("Contents/header.xml").find(f".//hh:paraPr[@id='{first_citation.get('paraPrIDRef')}']", hh)
    assert citation_style.find("hh:breakSetting", hh).get("keepWithNext") == "0"


@pytest.mark.corpus
def test_editorial_picture_captions_are_registered_before_profile_and_keep_declared_style(inputs, tmp_path, monkeypatch):
    from doc_automation import layout
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    attachment = image_attachment(tmp_path, data)
    data["screens"][0]["after_attachment_ids"] = [attachment["id"]]
    original_apply = layout.apply_editorial_profile
    registered = []

    def observe(document, role, profile):
        registered.extend(own_text(p) for p in document._editorial_caption_paragraphs)
        assert len(registered) == 1 and registered[0].startswith("변경 화면 — ")
        assert "첨부 확인상태:" not in registered[0]
        assert len(document._editorial_picture_paragraphs) == 1
        assert all(not own_text(p) and p.find(".//hp:pic", NS) is None for p in document._editorial_picture_paragraphs)
        return original_apply(document, role, profile)

    monkeypatch.setattr(layout, "apply_editorial_profile", observe)
    output = generate_project(dataset(tmp_path, data), tmp_path / "caption-style", roles=["SF-TD3"], style_profile="reference-v1")["documents"][0]
    assert registered == [output["image_bindings"][0]["caption"]]
    doc = TemplateDocument(output["path"])
    paragraph = next(p for i in range(len(doc.sections)) for p in doc.root(i).iter(f"{{{HP}}}p") if own_text(p) == registered[0])
    hh = {"hh": "http://www.hancom.co.kr/hwpml/2011/head"}
    definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", hh)}
    profile = json.loads(Path(output["editorial_profile"]["profile_source"]["path"]).read_text())
    assert all(int(definitions[run.get("charPrIDRef")].get("height")) == profile["targets"]["caption_height_hwp"] for run in paragraph.findall("hp:run", NS) if run.find("hp:t", NS) is not None)


@pytest.mark.corpus
def test_reference_td3_compact_specs_keep_typed_values_sources_and_exact_attachment_appendix(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    from doc_automation.narrative import typed_value
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    attachment = image_attachment(tmp_path, data)
    attachment["caption"] = "EXPLICIT-CAPTION-V6 " + "원문을 정확히 보존하는 긴 제공 캡션 " * 8
    data["screens"][0]["after_attachment_ids"] = [attachment["id"]]
    data["screens"][0]["notes"] = "SCREEN-NOTES-V6"
    for field, default in zip(data["screens"][0]["fields"], [0, False, "", "0", None, {}]):
        field["default_value"] = default
    shared = data["requirements"][0]
    shared.update(details=["SHARED-REQUIREMENT-DETAIL-V6"], constraints=["SHARED-CONSTRAINT-V6"])
    if shared["id"] not in data["screens"][1]["requirement_ids"]:
        data["screens"][1]["requirement_ids"].append(shared["id"])
    output = generate_project(dataset(tmp_path, data), tmp_path / "td3-compact", roles=["SF-TD3"], style_profile="reference-v1")["documents"][0]
    doc = TemplateDocument(output["path"])
    cards = [table for i in range(len(doc.sections)) for table in doc.tables(i) if table.get("colCnt") == "4" and table.get("rowCnt") == "5"]
    assert len(cards) == 2
    picture_cell = "".join(doc.cell(cards[0], 2, 1).itertext())
    binding = output["image_bindings"][0]
    assert binding["attachment_note_key"] == "A1" and "[A1]" in binding["caption"]
    assert attachment["id"] not in binding["caption"] and attachment["caption"] not in picture_cell
    assert attachment["purpose"] not in picture_cell and attachment["notes"] not in picture_cell
    assert binding["caption"].count("합성 시안·실제 실행화면 아님") == 1
    paragraphs = doc.cell(cards[0], 3, 1).findall("hp:subList/hp:p", NS)
    values = [own_text(p) for p in paragraphs]
    for index, field in enumerate(data["screens"][0]["fields"], 1):
        location = next(i for i, value in enumerate(values) if value.startswith(f"필드 {index}. {field['name']} — "))
        assert typed_value(field["default_value"]) in values[location]
        assert values[location + 1].startswith("검증: ") and field["validation"] in values[location + 1]
        assert "출처: [S" in values[location + 1]
        hh = {"hh": "http://www.hancom.co.kr/hwpml/2011/head"}
        definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:paraPr", hh)}
        first_flags = definitions[paragraphs[location].get("paraPrIDRef")].find("hh:breakSetting", hh)
        second_flags = definitions[paragraphs[location + 1].get("paraPrIDRef")].find("hh:breakSetting", hh)
        assert first_flags.get("keepWithNext") == "1" and second_flags.get("keepWithNext") == "0"
    for index, button in enumerate(data["screens"][0]["buttons"], 1):
        assert any(value.startswith(f"버튼 {index}. {button['name']} — ") and button["action"] in value and "출처: [S" in value for value in values)
    all_text = text(output["path"])
    assert all_text.count("SHARED-REQUIREMENT-DETAIL-V6") == 1 and all_text.count("SHARED-CONSTRAINT-V6") == 1
    for card in cards:
        check = "".join(doc.cell(card, 4, 1).itertext())
        assert shared["id"] in check and "[R1]" in check
        assert "SHARED-REQUIREMENT-DETAIL-V6" not in check
        assert "메뉴 단계" not in check
        assert "자료 상태:" in "".join(doc.cell(card, 1, 1).itertext())
    appendix = all_text.split("부록. 첨부 그림 대응표", 1)[1]
    for value in (attachment["caption"], attachment["purpose"], attachment["notes"], attachment["sha256"], attachment["id"]):
        assert value in appendix
    notes = json.loads(Path(output["source_notes"]["path"]).read_text())
    assert notes["attachments"][0]["key"] == "A1" and notes["attachments"][0]["attachment"] == attachment
    supplied_refs = [reference for field in data["screens"][0]["fields"] for reference in field["source_refs"]]
    assert all(reference in [record["source_ref"] for record in notes["references"]] for reference in supplied_refs)
    hh = {"hh": "http://www.hancom.co.kr/hwpml/2011/head"}
    chars = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", hh)}
    for screen in data["screens"]:
        menu = next(p for i in range(len(doc.sections)) for p in doc.root(i).iter(f"{{{HP}}}p") if own_text(p) == f"{screen['path']} → {screen['id']}")
        assert all(chars[run.get("charPrIDRef")].find("hh:bold", hh) is None for run in menu.findall("hp:run", NS))
    assert "menu_levels:" not in all_text and "메뉴 단계" in all_text


@pytest.mark.corpus
def test_editorial_profile_bytes_are_frozen_and_mid_apply_changes_are_rejected(inputs, tmp_path, monkeypatch):
    from doc_automation import layout, renderers
    from doc_automation.compose import ComposeError
    fake_repo = tmp_path / "source-snapshot"
    role = "SF-AD2"
    active = fake_repo / "resources/style-upgrade/profiles" / f"{role}.json"
    active.parent.mkdir(parents=True)
    raw = (REPOSITORY / "resources/style-upgrade/profiles" / f"{role}.json").read_bytes()
    active.write_bytes(raw)
    monkeypatch.setattr(renderers, "__file__", str(fake_repo / "src/doc_automation/renderers.py"))
    output = generate_project(EXAMPLES / "demo-suite.project.json", tmp_path / "profile-frozen", roles=[role], style_profile="reference-v1")["documents"][0]
    source = output["editorial_profile"]["profile_source"]
    assert Path(source["path"]).read_bytes() == raw
    assert source["path"] == str(tmp_path / "profile-frozen/profiles" / f"{role}.json")
    assert source["origin_path"] == str(active) and source["origin_sha256"] == source["sha256"]
    original = layout.apply_editorial_profile

    def unstable(document, role, profile):
        result = original(document, role, profile)
        active.write_bytes(raw + b"\n")
        return result

    monkeypatch.setattr(layout, "apply_editorial_profile", unstable)
    destination = tmp_path / "profile-changed-during-apply"
    with pytest.raises(ComposeError, match="changed during application"):
        generate_project(EXAMPLES / "demo-suite.project.json", destination, roles=[role], style_profile="reference-v1")
    assert not list(destination.glob("*.hwpx")) and not (destination / "manifest.json").exists()
    assert Path(source["path"]).read_bytes() == raw


@pytest.mark.corpus
def test_literal_object_defaults_preserve_original_keys_types_and_never_register_fake_sources(inputs, tmp_path):
    from doc_automation.narrative import SourceNotes, source_note_scope, typed_value
    literals = [{"status": 0}, {"status": "0"}, {"source_refs": [0]}, {"source_refs": [{"source_id": "LITERAL-ONLY", "locator": "/literal"}]}, {"review_type": "business_facts", "verification_status": "provided"}]
    notes = SourceNotes()
    with source_note_scope(notes):
        descriptions = [typed_value(value) for value in literals]
    assert len(set(descriptions)) == 5 and not notes.records and not notes.code_mappings
    assert "키: status (문자열); 값: 0 (정수)" in descriptions[0]
    assert "키: status (문자열); 값: 0 (문자열)" in descriptions[1]
    assert "source_refs (문자열)" in descriptions[2] and "LITERAL-ONLY (문자열)" in descriptions[3]
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["screens"][0]["fields"][0]["default_value"] = literals
    output = generate_project(dataset(tmp_path, data), tmp_path / "literal-keys", roles=["SF-TD3"], style_profile="reference-v1")["documents"][0]
    body = text(output["path"])
    for description in descriptions:
        assert description.replace("\n", "") in body
    sidecar = json.loads(Path(output["source_notes"]["path"]).read_text())
    assert all(record["source_ref"]["source_id"] != "LITERAL-ONLY" for record in sidecar["references"])


@pytest.mark.corpus
def test_linked_review_appendix_keeps_comments_evidence_sources_and_artifact_hash_once(inputs, tmp_path):
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    review = data["reviews"][0]
    review.update(comments="REVIEW-COMMENTS-V7", review_type="business_facts", evidence_ids=[data["attachments"][0]["id"]],
                  artifact_id=data["attachments"][0]["id"], artifact_sha256=data["attachments"][0]["sha256"], notes="REVIEW-NOTES-V7")
    data["screens"][0]["review_ids"] = [review["id"]]
    data["requirements"][0]["review_ids"] = [review["id"]]
    output = generate_project(dataset(tmp_path, data), tmp_path / "linked-review", roles=["SF-TD3"], style_profile="reference-v1")["documents"][0]
    appendix = text(output["path"]).split("부록. 연결 검토 기록", 1)[1]
    for value in ("REVIEW-COMMENTS-V7", "REVIEW-NOTES-V7", review["artifact_id"], review["artifact_sha256"], data["screens"][0]["id"], data["requirements"][0]["id"]):
        assert value in appendix
    assert appendix.count("REVIEW-COMMENTS-V7") == 1
    assert "검토 종류: 사업 사실 검토" in appendix
    notes = json.loads(Path(output["source_notes"]["path"]).read_text())
    assert len(notes["linked_reviews"]) == 1 and notes["linked_reviews"][0]["review"] == review
    connected = {rid for screen in data["screens"] for rid in screen.get("requirement_ids", [])}
    expected_owners = {screen["id"] for screen in data["screens"] if review["id"] in screen.get("review_ids", [])}
    expected_owners.update(requirement["id"] for requirement in data["requirements"] if requirement["id"] in connected and review["id"] in requirement.get("review_ids", []))
    assert set(notes["linked_reviews"][0]["referenced_by"]) == expected_owners
    assert all(reference in [item["source_ref"] for item in notes["references"]] for reference in review["source_refs"])


def test_compact_appendix_fields_keep_typed_values_nested_context_and_long_prose():
    from doc_automation.narrative import SourceNotes, source_note_scope
    from doc_automation.renderers import _append_context_fields

    class Paragraph:
        def __init__(self, value):
            self.value = value

    class Document:
        def new_paragraph(self, value, *, prototype):
            return Paragraph(value)

        def use_character_style(self, paragraph, **options):
            paragraph.character_options = options

        def use_paragraph_style(self, paragraph, **options):
            paragraph.paragraph_options = options

        def use_paragraph_keep(self, paragraph, **options):
            paragraph.keep_options = options

    data = {"status": "synthetic", "actual": None, "required": False, "length": 0,
            "default_value": "", "description": "긴 원문 보존; " * 60,
            "reviewer": {"name": None, "review_status": "pending"},
            "evidence_ids": [], "source_refs": [{"source_id": "SOURCE-ONE", "locator": "/review/0"}]}
    before = deepcopy(data)
    records = SourceNotes()
    paragraphs = []
    with source_note_scope(records):
        _append_context_fields(Document(), paragraphs, None, "[RV2]", data, compact=True)
    actual = "\n".join(p.value for p in paragraphs)
    # Value/type distinctions survive co-locating short labelled fields.
    for marker in ("확인 상태: 합성 자료", "제공 실제 값: 미확인(null)", "필수 여부: 아니오 (false·논리값)",
                   "길이: 0", "기본값: 빈 문자열(문자열)", "증거 연결: 연결 입력 0개(빈 목록)", "출처: [S1]"):
        assert marker in actual
    assert any("확인 상태: 합성 자료; 제공 실제 값:" in p.value for p in paragraphs)
    long = next(p for p in paragraphs if data["description"] in p.value)
    assert long.value == "[RV2] 설명: " + data["description"]
    assert not long.keep_options["keep_lines"]
    nested = [p.value for p in paragraphs if "검토자:" in p.value or "검토 상태:" in p.value]
    assert nested == ["[RV2] 검토자: 명칭: 미확인(null)", "[RV2] 검토 상태: 검토 대기"]
    assert all(p.value.startswith("[RV2] ") and p.keep_options["keep_with_next"] is False for p in paragraphs)
    assert records.records[0]["source_ref"] == data["source_refs"][0]
    assert records.code_mappings == {"synthetic": "합성 자료", "pending": "검토 대기"}
    assert data == before


@pytest.mark.corpus
@pytest.mark.parametrize("role", ["SF-AD2", "SF-TD3", "SF-TD5"])
def test_compact_source_review_appendices_keep_exact_source_contract_and_reference_owners(inputs, tmp_path, role):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["reviews"][0].update(comments="독립 검토 의견 원문; 상태·승인 근거 미확인", notes="검토 상세 비고 원문")
    supplied = dataset(tmp_path, data)
    data = json.loads(supplied.read_text())
    output = generate_project(supplied, tmp_path / role, roles=[role], style_profile="reference-v1")["documents"][0]
    document = TemplateDocument(output["path"])
    sidecar = json.loads(Path(output["source_notes"]["path"]).read_text())
    paragraphs = [p for section in range(len(document.sections)) for p in document.root(section).iter(f"{{{HP}}}p")]
    source_start = next(i for i, p in enumerate(paragraphs) if own_text(p) == "부록. 출처 대응표")
    source_body = "\n".join(own_text(p) for p in paragraphs[source_start:])
    for record in sidecar["references"]:
        original = next(s for s in data["sources"] if s["id"] == record["source_ref"]["source_id"])
        assert record["source"] == original
        assert original["id"] in source_body and original["title"] in source_body
        for key in ("path", "sha256", "notes"):
            if key in original:
                assert original[key] in source_body
        owner = record["owner"]
        nodes = document.xml(owner["section"]).xpath(owner["xpath"], namespaces=sidecar["xml_namespaces"])
        assert len(nodes) == 1 and own_text(nodes[0]) == owner["rendered_text"]
        assert f"[{record['source_key']}]" in own_text(nodes[0])
        assert f"[{record['key']}] {record['source_ref']['locator']}" in own_text(nodes[0])
    for original, label in sidecar["code_mappings"].items():
        assert f"{label} ← {original}" in source_body
    ref_groups = {}
    for record in sidecar["references"]:
        ref_groups.setdefault((record["owner"]["section"], record["owner"]["xpath"]), []).append(record)
    if role == "SF-TD5":
        assert any(len(records) > 3 for records in ref_groups.values())
        hh = {"hh": "http://www.hancom.co.kr/hwpml/2011/head"}
        for records in ref_groups.values():
            owner = records[0]["owner"]
            paragraph = document.xml(owner["section"]).xpath(owner["xpath"], namespaces=sidecar["xml_namespaces"])[0]
            if 240 < len(own_text(paragraph)) <= 480:
                props = document.xml("Contents/header.xml").find(f".//hh:paraPr[@id='{paragraph.get('paraPrIDRef')}']", hh)
                assert props.find("hh:breakSetting", hh).get("keepLines") == "1"
                assert props.find("hh:breakSetting", hh).get("keepWithNext") == "0"
    for record in sidecar.get("linked_reviews", []):
        head = next(p for p in paragraphs if own_text(p).startswith(f"검토 {record['review']['id']} — "))
        assert own_text(head).endswith(f"[{record['key']}]")
        continuation = [own_text(p) for p in paragraphs if own_text(p).startswith(f"[{record['key']}] ")]
        assert continuation and all(record["review"]["id"] not in p for p in continuation)
        joined = "\n".join(continuation)
        assert record["review"]["comments"] in joined and record["review"]["notes"] in joined
        assert record["review"] == data["reviews"][0]


@pytest.mark.corpus
def test_reference_pm4_trace_grid_keeps_each_directed_record_once_with_exact_common_definitions(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["trace_links"][0]["notes"] = "TRACE-PRIVATE-NOTE-V7"
    data["trace_links"][1]["rationale"] = "DISTINCT-RATIONALE-V7"
    data["requirements"][0].update(fulfillment_status="in_progress", deliverable_ids=[data["attachments"][0]["id"]])
    output = generate_project(dataset(tmp_path, data), tmp_path / "trace-grid", roles=["SF-PM4"], style_profile="reference-v1")["documents"][0]
    doc = TemplateDocument(output["path"])
    sidecar = json.loads(Path(output["source_notes"]["path"]).read_text())
    bindings = sidecar["explicit_trace_links"]
    assert len(bindings) == len(data["trace_links"])
    assert [binding["trace"] for binding in bindings] == data["trace_links"]
    meaning = json.loads(Path(output["meaning_map"]["path"]).read_text())
    namespaces = meaning["xml_namespaces"]
    first_requirement = next(entity for entity in meaning["entities"] if entity["input_pointer"] == "/requirements/0")
    for key, expected in (("fulfillment_status", "진행 중(입력)"), ("deliverable_ids", data["attachments"][0]["id"])):
        field = next(field for field in first_requirement["fields"] if field["input_pointer"].endswith("/" + key))
        assert field["input_value"] == data["requirements"][0][key] and field["owners"]
        owners = []
        for owner in field["owners"]:
            paragraph = doc.xml(owner["section"]).xpath(owner["xpath"], namespaces=namespaces)
            assert len(paragraph) == 1 and own_text(paragraph[0]) == owner["rendered_text"]
            owners.append(own_text(paragraph[0]))
        assert any(expected in value and value.startswith("[T1] ") for value in owners)
    reasons = {item["key"]: item["value"] for item in sidecar["trace_rationale_definitions"]}
    additions = {item["key"]: item["value"] for item in sidecar["trace_additional_definitions"]}
    for trace, binding in zip(data["trace_links"], bindings):
        owner = binding["owner"]
        rows = doc.xml(owner["section"]).xpath(owner["xpath"], namespaces=namespaces)
        assert len(rows) == 1
        cells = rows[0].findall("hp:tc", NS)
        assert len(cells) == 7
        assert trace["id"] == "".join(own_text(p) for p in cells[0].findall("hp:subList/hp:p", NS))
        assert trace["source_id"] in "".join(cells[1].itertext()) and trace["target_id"] in "".join(cells[2].itertext())
        assert reasons[binding["rationale_key"]] == trace["rationale"]
        assert additions[binding["additional_key"]]["name"] == trace["name"]
        if "notes" in trace:
            assert additions[binding["additional_key"]]["notes"] == trace["notes"]
    body = text(output["path"])
    shared = data["trace_links"][0]["rationale"]
    assert body.count(shared) == 1 and body.count("DISTINCT-RATIONALE-V7") == 1 and body.count("TRACE-PRIVATE-NOTE-V7") == 1
    assert "시험 연결" in body and "미착수(입력)" in body and "not_started (문자열)" not in body
    assert '"source_kind"' not in body and "명시 추적 연결 원문: {" not in body
    assert len({binding["owner"]["xpath"] for binding in bindings}) == len(bindings)
    assert validate_package(output["path"])["valid"]


@pytest.mark.corpus
def test_editorial_figure_contract_matches_exact_role_entity_slot_attachment_and_embedded_owner(inputs, tmp_path):
    """Independent role contract: equal picture counts cannot hide wrong slots."""
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    source = EXAMPLES / "style-upgrade/illustrated-extended-v2/illustrated.project.json"
    data = json.loads(source.read_text())
    contracts = {
        "SF-AD1": [(data["project"]["business_processes"], ["as_is_attachment_ids"]), (data["project"]["systems"], ["as_is_diagram_ids"])],
        "SF-TD1": [(data["project"]["business_processes"], ["as_is_attachment_ids", "to_be_attachment_ids"])],
        "SF-TD2": [(data["project"]["systems"], ["as_is_diagram_ids", "to_be_diagram_ids"])],
        "SF-TD3": [(data["screens"], ["before_attachment_ids", "after_attachment_ids", "standard_attachment_ids"])],
        "SF-TD4": [(data["programs"], ["module_flow_attachment_ids"])],
        "SF-TI3": [(data["project"]["manual_sections"], ["attachment_ids"]), (data["screens"], ["standard_attachment_ids", "before_attachment_ids", "after_attachment_ids"])],
    }
    result = generate_project(source, tmp_path / "figure-contract", roles=list(contracts), style_profile="reference-v1")
    for output in result["documents"]:
        expected = {(item["id"], slot, attachment) for collection, slots in contracts[output["role"]] for item in collection for slot in slots for attachment in item.get(slot, [])}
        actual = {(binding["entity_id"], binding["slot"], binding["attachment_id"]) for binding in output["image_bindings"]}
        assert actual == expected
        doc = TemplateDocument(output["path"])
        package = doc.xml("Contents/content.hpf")
        binaries = {item.get("id"): item.get("href") for item in package.iter() if item.tag.rsplit("}", 1)[-1] == "item"}
        with ZipFile(output["path"]) as archive:
            for binding in output["image_bindings"]:
                caption = next(p for member in doc.sections for p in doc.xml(member).iter(f"{{{HP}}}p") if own_text(p) == binding["caption"])
                picture = caption.getprevious().find("hp:run/hp:pic", NS)
                assert picture is not None
                image = next(node for node in picture.iter() if node.tag.rsplit("}", 1)[-1] == "img")
                assert hashlib.sha256(archive.read(binaries[image.get("binaryItemIDRef")])).hexdigest() == binding["embedded_sha256"]


@pytest.mark.corpus
def test_editorial_test_literals_and_nullable_group_metadata_keep_own_meaning(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    for index, case in enumerate(data["test_cases"]):
        case.update(data={"source_refs": [0]}, expected={"status": 0 if index % 2 == 0 else "0"}, notes=None)
        if case["stage"] in {"integration", "acceptance"}:
            case.update(case_number=None, group_id=None, process_name=None)
    result = generate_project(dataset(tmp_path, data), tmp_path / "test-literal-boundaries", roles=["SF-CD1", "SF-TI1", "SF-TI4"], style_profile="reference-v1")
    for output in result["documents"]:
        body = text(output["path"])
        assert "키: source_refs (문자열)" in body and "키: status (문자열)" in body
        assert "비고: 미확인(null)" in body
        if output["role"] == "SF-CD1":
            assert "값: 0 (정수)" in body and "값: 0 (문자열)" in body
        else:
            doc = TemplateDocument(output["path"])
            meaning = json.loads(Path(output["meaning_map"]["path"]).read_text())
            for entity in meaning["entities"]:
                if not entity["input_pointer"].startswith("/test_cases/"):
                    continue
                for key in ("case_number", "group_id", "process_name"):
                    field = next(field for field in entity["fields"] if field["input_pointer"].endswith("/" + key))
                    assert field["input_value"] is None and field["representation"] == "readable_supplement"
                    owner = field["owner"]
                    paragraph = doc.xml(owner["section"]).xpath(owner["xpath"], namespaces=meaning["xml_namespaces"])
                    assert len(paragraph) == 1 and "미확인(null)" in own_text(paragraph[0])


@pytest.mark.corpus
def test_source_reference_groups_keep_every_exact_key_locator_and_real_owner(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    output = generate_project(EXAMPLES / "demo-suite.project.json", tmp_path / "source-groups", roles=["SF-AD2"], style_profile="reference-v1")["documents"][0]
    doc = TemplateDocument(output["path"])
    notes = json.loads(Path(output["source_notes"]["path"]).read_text())
    namespaces = json.loads(Path(output["meaning_map"]["path"]).read_text())["xml_namespaces"]
    assert notes["xml_namespaces"] == namespaces
    owners = set()
    for record in notes["references"]:
        owner = record["owner"]
        nodes = doc.xml(owner["section"]).xpath(owner["xpath"], namespaces=namespaces)
        assert len(nodes) == 1 and own_text(nodes[0]) == owner["rendered_text"]
        assert f"[{record['key']}]" in own_text(nodes[0]) and record["source_ref"]["locator"] in own_text(nodes[0])
        assert f"[{record['source_key']}]" in own_text(nodes[0])
        owners.add((owner["section"], owner["xpath"]))
    assert len(owners) < len(notes["references"])


@pytest.mark.corpus
def test_reference_fk_explanation_pairs_actual_target_with_column_detail_and_preserves_note(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    table_index, column = next((i, column) for i, table in enumerate(data["database_tables"])
                               for column in table["columns"] if column.get("foreign_table_id"))
    table = data["database_tables"][table_index]
    note = "외래 키 원자료는 foreign_rule 항목을 참조한다. 원문 보존용 메모."
    table["notes"] = note
    source = dataset(tmp_path, data)
    before = sha(source)
    output = generate_project(source, tmp_path / "fk-readable-summary", roles=["SF-TD5"], style_profile="reference-v1")["documents"][0]
    doc = TemplateDocument(output["path"])
    paragraphs = [own_text(p) for member in doc.sections for p in doc.xml(member).iter(f"{{{HP}}}p")]
    summary = next(value for value in paragraphs if value.startswith(f"제공 참조 설계: {table['id']}.{column['id']} → "))
    assert column["foreign_table_id"] in summary
    assert all(identifier in summary for identifier in column["foreign_column_ids"])
    assert "상세 [C" in summary and "실제 DB 구현은 미확인" in summary
    assert f"제공 제약·비고 원문: {note}" in paragraphs
    meaning = json.loads(Path(output["meaning_map"]["path"]).read_text())
    entity = next(x for x in meaning["entities"] if x["input_pointer"] == f"/database_tables/{table_index}")
    field = next(x for x in entity["fields"] if x["input_pointer"].endswith("/notes"))
    assert field["input_value"] == note
    assert any(owner["rendered_text"] == f"제공 제약·비고 원문: {note}" for owner in field["owners"])
    assert sha(source) == before


@pytest.mark.corpus
def test_reference_supplement_continuations_have_identity_keys_and_bounded_intro_keep(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    index, case = next((i, case) for i, case in enumerate(data["test_cases"]) if case["stage"] == "integration")
    case.update(group_id=None, process_name="접수 단계\n검증 단계\n확정 단계")
    output = generate_project(dataset(tmp_path, data), tmp_path / "supplement-context", roles=["SF-TI1"], style_profile="reference-v1")["documents"][0]
    doc = TemplateDocument(output["path"])
    meaning = json.loads(Path(output["meaning_map"]["path"]).read_text())
    entity = next(x for x in meaning["entities"] if x["input_pointer"] == f"/test_cases/{index}")
    key = entity["supplement_key"]
    field = next(x for x in entity["fields"] if x["input_pointer"].endswith("/process_name"))
    assert field["input_value"] == case["process_name"] and len(field["owners"]) == 3
    for value, owner in zip(case["process_name"].split("\n"), field["owners"]):
        paragraph = doc.xml(owner["section"]).xpath(owner["xpath"], namespaces=meaning["xml_namespaces"])[0]
        assert own_text(paragraph) == owner["rendered_text"] and own_text(paragraph).startswith(f"[{key}] ")
        assert value in own_text(paragraph)
    null_field = next(x for x in entity["fields"] if x["input_pointer"].endswith("/group_id"))
    assert null_field["input_value"] is None and "미확인(null)" in null_field["rendered_text"]
    hh = {"hh": "http://www.hancom.co.kr/hwpml/2011/head"}
    defs = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:paraPr", hh)}
    title = next(p for member in doc.sections for p in doc.xml(member).iter(f"{{{HP}}}p") if own_text(p) == "부록. 항목별 보완 명세")
    chain = [title, title.getnext(), title.getnext().getnext(), title.getnext().getnext().getnext()]
    assert [defs[p.get("paraPrIDRef")].find("hh:breakSetting", hh).get("keepWithNext") for p in chain] == ["1", "1", "1", "0"]


@pytest.mark.corpus
def test_reference_trace_short_rows_keep_record_identity_with_row_atomic_flow(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    output = generate_project(dataset(tmp_path, data), tmp_path / "trace-row-identity", roles=["SF-PM4"], style_profile="reference-v1")["documents"][0]
    doc = TemplateDocument(output["path"])
    notes = json.loads(Path(output["source_notes"]["path"]).read_text())
    namespaces = json.loads(Path(output["meaning_map"]["path"]).read_text())["xml_namespaces"]
    for trace, binding in zip(data["trace_links"], notes["explicit_trace_links"]):
        owner = binding["owner"]
        row = doc.xml(owner["section"]).xpath(owner["xpath"], namespaces=namespaces)[0]
        table = row.getparent()
        assert table.get("pageBreak") == "TABLE" and table.get("repeatHeader") == "1"
        cells = row.findall("hp:tc", NS)
        assert own_text(cells[0].find("hp:subList/hp:p", NS)) == trace["id"]
        assert trace["source_id"] in "".join(cells[1].itertext())
        assert trace["target_id"] in "".join(cells[2].itertext())


@pytest.mark.corpus
def test_td5_editorial_short_grid_uses_row_pagination_and_short_unknown_key_codes(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["database_tables"][0]["columns"][1]["key"] = None
    output = generate_project(dataset(tmp_path, data), tmp_path / "td5-row-policy", roles=["SF-TD5"], style_profile="reference-v1")["documents"][0]
    doc = TemplateDocument(output["path"])
    grid = next(table for member in range(len(doc.sections)) for table in doc.tables(member) if table.get("colCnt") == "9")
    assert grid.get("pageBreak") == "TABLE" and grid.get("repeatHeader") == "1"
    assert grid.find("hp:pos", NS).get("treatAsChar") == "0"
    expected = [(table, column) for table in data["database_tables"] for column in table["columns"]]
    rows = grid.findall("hp:tr", NS)
    assert len(rows) == len(expected) + 1
    for row, (table, column) in zip(rows[1:], expected):
        cells = row.findall("hp:tc", NS)
        values = ["".join(own_text(p) for p in cell.findall("hp:subList/hp:p", NS)) for cell in cells]
        assert values[:4] == [table["name"], table["id"], column["name"], column["id"]]
        if column["key"] is None:
            assert values[5:7] == ["?", "?"]
    body = text(output["path"])
    assert "?=원입력 미확인" in body and "키 구분: 미확인(null)" in body
    assert validate_package(output["path"])["valid"]


@pytest.mark.corpus
def test_editorial_business_identity_keeps_year_and_provenance_with_actual_owners(inputs, tmp_path):
    from doc_automation.compose import TemplateDocument
    from doc_automation.hwpx import own_text
    data = json.loads((EXAMPLES / "demo-suite.project.json").read_text())
    data["project"]["name"] = "공통 사업명 보존 검증"
    data["synthetic_notice"] = NOTICE
    original = deepcopy(data)
    output = generate_project(dataset(tmp_path, data), tmp_path / "business-identity", roles=["SF-AD2"], style_profile="reference-v1")["documents"][0]
    doc = TemplateDocument(output["path"])
    meaning = json.loads(Path(output["meaning_map"]["path"]).read_text())
    context = next(e for e in meaning["entities"] if e["input_pointer"] == "/project")
    fields = {f["input_pointer"]: f for f in context["fields"]}
    required = ["/project/name", "/project/program_year", "/project/program_name", "/project/status", "/project/source_refs",
                "/project/customer/name", "/project/customer/status", "/project/customer/source_refs",
                "/project/supplier/name", "/project/supplier/status", "/project/supplier/source_refs", "/synthetic_notice"]
    for pointer in required:
        field = fields[pointer]
        assert field["content_review_status"] == "pending" and field["owners"]
        value = data
        for key in pointer.lstrip("/").split("/"):
            value = value[key]
        assert field["input_value"] == value and field["input_type"] == type(value).__name__
        for owner in field["owners"]:
            nodes = doc.xml(owner["section"]).xpath(owner["xpath"], namespaces=meaning["xml_namespaces"])
            assert len(nodes) == 1 and own_text(nodes[0]) == owner["rendered_text"]
    assert data["project"]["name"] in fields["/project/name"]["rendered_text"]
    assert str(data["project"]["program_year"]) in fields["/project/program_year"]["rendered_text"]
    assert data["synthetic_notice"] in fields["/synthetic_notice"]["rendered_text"]
    notes = json.loads(Path(output["source_notes"]["path"]).read_text())
    for party in (data["project"], data["project"]["customer"], data["project"]["supplier"]):
        for ref in party["source_refs"]:
            assert any(ref == entry["source_ref"] for entry in notes["references"])
    assert data == original
