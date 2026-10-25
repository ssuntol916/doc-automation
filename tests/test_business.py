"""Business contradictions and draft/submission separation, using local fixtures."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from doc_automation.business import DOMAINS, validate_project


def entity(identifier, **fields):
    return {"id": identifier, "name": identifier, "status": "synthetic", "source_refs": [], **fields}


def requirement(identifier="R1", **fields):
    return entity(identifier, system_name="MES", business_area="생산", kind="functional",
                  change_type="new", description="생산실적 등록", details=[], constraints=[], owner=None, **fields)


def case(identifier="T1", **fields):
    values = dict(stage="unit", scenario="등록 버튼을 누른다", data=0, expected=0,
                  actual=None, result="not_run", execution_date=None, executor=None, evidence_ids=[])
    values.update(fields)
    return entity(identifier, **values)


def kpi(**fields):
    values = dict(unit="%", direction="increase", formula_kind="percent", formula="분자/분모*100",
                  numerator=18, denominator=20, baseline=80, target=95, actual=90)
    values.update(fields)
    return entity("K1", **values)


def column(identifier="item_id", **fields):
    values = dict(type="varchar", length=20, nullable=False, key="primary", default_value=None, encryption=None)
    values.update(fields)
    return entity(identifier, **values)


def table(identifier="items", **fields):
    values = dict(description="품목", columns=[column()])
    values.update(fields)
    return entity(identifier, **values)


def operation(**fields):
    values = dict(period_start="2025-01-01", period_end="2025-01-31", aggregation_method="sum",
                  raw_records=[{"date": "2025-01-02", "login_count": 3, "status": "synthetic", "source_refs": []},
                               {"date": "2025-01-01", "login_count": 5, "status": "synthetic", "source_refs": []}],
                  reported_totals={"login_count": 8})
    values.update(fields)
    return entity("O1", **values)


@pytest.fixture
def draft():
    return {"schema_version": "1.0", "dataset_kind": "synthetic", "sources": [],
            "project": entity("P1", program_name="지원사업", program_year=2025, template_version="2025",
                              customer=None, supplier=None, start_date="2025-01-01", end_date="2025-12-31",
                              requested_deliverables=["SF-AD2"]),
            **{d: [] for d in DOMAINS}, "extraction_issues": [], "submission_ready": False,
            "synthetic_notice": "검증용 합성 자료(제출용 아님)"}


def codes(result, level="errors"):
    return {issue["code"] for issue in result[level]}


def clean(result):
    assert "SCHEMA_INVALID" not in codes(result), result["errors"]
    return result


def test_incomplete_synthetic_is_valid_draft_and_input_unchanged(draft):
    before = deepcopy(draft)
    result = clean(validate_project(draft))
    assert result["errors"] == []
    assert result["draft_ready"] and not result["submission_ready"]
    assert "NONPROJECT_DATASET" in codes(result, "submission_blockers")
    assert draft == before


@pytest.mark.parametrize("data", [None, [], {"project": None}, {"schema_version": "bad"}])
def test_malformed_structures_return_report(data):
    result = validate_project(data)
    assert "SCHEMA_INVALID" in codes(result)
    assert not result["draft_ready"] and not result["submission_ready"]


def test_duplicate_ids_are_scoped_to_domain_and_references_exist(draft):
    draft["requirements"] = [requirement(), requirement()]
    draft["database_tables"] = [table("R1")]
    draft["features"] = [entity("F1", system_name=None, major_category=None, middle_category=None,
                                minor_category=None, change_type=None, description=None, before=None,
                                after=None, requirement_ids=["missing"])]
    result = clean(validate_project(draft))
    assert codes(result) == {"DUPLICATE_ID", "REFERENCE_MISSING"}
    assert "REQUIREMENT_NAME_DUPLICATE" in codes(result, "warnings")


def test_schedule_order_and_meeting_weekday(draft):
    draft["project"]["schedule_items"] = [entity("S1", phase="개발", planned_start="2025-02-02",
        planned_end="2025-02-01", actual_start=None, actual_end=None)]
    draft["meetings"] = [entity("M1", date="2025-01-06", weekday=1, location=None, organizer=None,
                               agenda=[], discussions=[], decisions=[], attendees=[])]
    result = clean(validate_project(draft))
    assert {"DATE_ORDER", "WEEKDAY_MISMATCH"} <= codes(result)


@pytest.mark.parametrize("field,value", [("start_date", "2025-02-30"), ("start_date", "tomorrow")])
def test_invalid_iso_dates(draft, field, value):
    draft["project"][field] = value
    assert "SCHEMA_INVALID" in codes(validate_project(draft))


def add_source(draft, tmp_path, payload=None):
    content = json.dumps(payload or {"facts": {"a/b": {"~key": 0}}}, ensure_ascii=False).encode()
    path = tmp_path / "facts.json"
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    draft["sources"] = [{"id": "S1", "title": "provided fixture", "kind": "project_document",
                         "path": "facts.json", "sha256": digest, "verification_status": "verified"}]
    return [{"source_id": "S1", "locator": "/facts"}], digest


def test_relative_sources_and_json_pointer_escapes(draft, tmp_path, monkeypatch):
    add_source(draft, tmp_path)
    draft["project"]["source_refs"] = [{"source_id": "S1", "locator": "/facts/a~1b/~0key"}]
    monkeypatch.chdir(tmp_path.parent)
    result = clean(validate_project(draft, base_dir=tmp_path))
    assert not result["errors"]
    assert result["summary"]["source_file_checks"]["S1"]["hash_matches"]
    assert result["summary"]["locator_counts"] == {"valid": 1}
    draft["project"]["source_refs"][0]["locator"] = "/facts/missing"
    assert "SOURCE_LOCATOR_INVALID" in codes(validate_project(draft, base_dir=tmp_path))


def test_hash_mismatch_and_disabled_verification(draft, tmp_path):
    add_source(draft, tmp_path)
    draft["sources"][0]["sha256"] = "0" * 64
    assert "SOURCE_HASH_MISMATCH" in codes(validate_project(draft, base_dir=tmp_path))
    result = clean(validate_project(draft, verify_files=False, base_dir=tmp_path))
    assert not result["errors"]
    assert "FILE_VERIFICATION_DISABLED" in codes(result, "submission_blockers")


def test_hwpx_locator_checks_declared_xml_cell(draft, tmp_path):
    path = tmp_path / "facts.hwpx"
    with ZipFile(path, "w") as z:
        z.writestr("Contents/section0.xml", '<section xmlns:h="urn:h"><h:p/><h:tbl><h:tr><h:tc><h:cellAddr rowAddr="0" colAddr="1"/></h:tc></h:tr></h:tbl></section>')
    draft["sources"] = [{"id": "S1", "title": "XML fixture", "kind": "project_document", "path": str(path),
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "verification_status": "verified"}]
    draft["project"]["source_refs"] = [{"source_id": "S1", "locator": "Contents/section0.xml#T1/R0C1"}]
    assert not validate_project(draft)["errors"]
    draft["project"]["source_refs"][0]["locator"] = "Contents/section0.xml#T1/R0C0"
    assert "SOURCE_LOCATOR_INVALID" in codes(validate_project(draft))
    draft["project"]["source_refs"][0]["locator"] = "$.sections"
    result = validate_project(draft)
    assert not result["errors"]
    assert "SOURCE_LOCATOR_UNCHECKED" in codes(result, "warnings")


def test_database_duplicates_foreign_keys_and_sourced_baseline(draft, tmp_path):
    refs, _ = add_source(draft, tmp_path)
    draft["database_tables"] = [table(columns=[column(), column(foreign_table_id="items", foreign_column_ids=["missing"])])]
    result = clean(validate_project(draft, base_dir=tmp_path))
    assert {"DATABASE_COLUMN_ID_DUPLICATE", "DATABASE_FOREIGN_COLUMN_MISSING"} <= codes(result)
    draft["database_tables"] = [table(columns=[column("품목코드", name="item_id")])]
    result = clean(validate_project(draft, base_dir=tmp_path))
    assert not result["errors"] and "DATABASE_ID_NAME_REVIEW" in codes(result, "warnings")
    col = draft["database_tables"][0]["columns"][0]
    col.update(expected_id="item_id", expected_name="품목코드")
    assert "DEFINITION_MISMATCH" not in codes(validate_project(draft, base_dir=tmp_path))
    col["definition_source_refs"] = refs
    assert "DEFINITION_MISMATCH" in codes(validate_project(draft, base_dir=tmp_path))


def test_unexecuted_tests_are_harmless_but_execution_claim_needs_evidence(draft):
    draft["test_cases"] = [case()]
    assert clean(validate_project(draft))["errors"] == []
    draft["test_cases"][0]["result"] = "passed"
    assert "TEST_EXECUTION_INCOMPLETE" in codes(validate_project(draft))


def executed_case(draft, tmp_path, **fields):
    refs, digest = add_source(draft, tmp_path)
    draft["attachments"] = [entity("A1", path="facts.json", sha256=digest, source_id="S1",
        purpose="test fixture", verification_status="synthetic")]
    return case(result="passed", actual=0, execution_date="2025-01-01", evidence_ids=["A1"],
                executor={"name": "tester", "review_status": "synthetic"}, **fields)


def test_declared_comparison_detects_contradiction_and_preserves_zero(draft, tmp_path):
    test = executed_case(draft, tmp_path, comparison={"operator": "equal", "tolerance": 0})
    draft["test_cases"] = [test]
    assert clean(validate_project(draft, base_dir=tmp_path))["errors"] == []
    test["actual"] = 1
    assert "TEST_RESULT_CONTRADICTION" in codes(validate_project(draft, base_dir=tmp_path))
    del test["comparison"]
    assert "TEST_RESULT_CONTRADICTION" not in codes(validate_project(draft, base_dir=tmp_path))


def test_same_image_across_stages_is_observation_not_execution_proof(draft, tmp_path):
    test = executed_case(draft, tmp_path)
    second = deepcopy(test)
    second.update(id="T2", stage="acceptance")
    draft["test_cases"] = [test, second]
    result = clean(validate_project(draft, base_dir=tmp_path))
    assert not result["errors"]
    assert "TEST_EVIDENCE_REUSED" in codes(result, "warnings")


@pytest.mark.parametrize("changes,code", [({"denominator": 0}, "KPI_ZERO_DENOMINATOR"),
    ({"actual": 91}, "KPI_ARITHMETIC_MISMATCH"), ({"target": 70}, "KPI_TARGET_DIRECTION")])
def test_kpi_explicit_formula_and_direction(draft, changes, code):
    draft["kpis"] = [kpi(**changes)]
    assert code in codes(clean(validate_project(draft)))


def test_kpi_missing_target_is_draft_and_precision_is_explicit(draft):
    draft["kpis"] = [kpi(numerator=2, denominator=3, actual=66.67, actual_precision=2, target=None)]
    result = clean(validate_project(draft))
    assert result["errors"] == []


def test_operation_rules_recompute_without_guessing_missing_values(draft):
    draft["operation_periods"] = [operation()]
    assert clean(validate_project(draft))["errors"] == []
    draft["operation_periods"][0]["reported_totals"]["login_count"] = 7
    assert "OPERATION_TOTAL_MISMATCH" in codes(validate_project(draft))
    draft["operation_periods"][0]["raw_records"][0]["login_count"] = None
    result = validate_project(draft)
    assert not result["errors"] and "OPERATION_TOTAL_UNVERIFIED" in codes(result, "warnings")


def test_operation_per_metric_average_and_last_use_date_order(draft):
    op = operation(reported_totals={"average_user_count": 4, "login_count": 3}, aggregation_rules={
        "average_user_count": {"source_field": "login_count", "method": "average"},
        "login_count": {"source_field": "login_count", "method": "last"}})
    draft["operation_periods"] = [op]
    assert clean(validate_project(draft))["errors"] == []
    op["raw_records"][1]["date"] = "2025-01-02"
    result = validate_project(draft)
    assert "OPERATION_LAST_ORDER_UNVERIFIED" in codes(result, "warnings")
    assert "DECLARED_CHECK_UNRESOLVED" in codes(result, "submission_blockers")


def test_changed_approval_claim_requires_evidence_but_request_does_not(draft):
    change = entity("C1", categories=[], request_number=None, request_date=None, reason=None,
                    before=None, after=None, impact=None, approval_status="requested", approval_evidence_ids=[], meeting_ids=[])
    draft["changes"] = [change]
    assert clean(validate_project(draft))["errors"] == []
    change["approval_status"] = "approved"
    assert "CHANGE_APPROVAL_EVIDENCE_MISSING" in codes(validate_project(draft))


def test_original_issues_are_separate_from_schema_errors(draft):
    draft["extraction_issues"] = [entity("I1", issue_type="source_conflict", severity="error",
        description="원본ID 불일치", resolution_status="open")]
    result = clean(validate_project(draft))
    assert not result["errors"]
    assert "ORIGINAL_ISSUE_UNRESOLVED" in codes(result, "warnings")
    assert "ORIGINAL_ISSUE_UNRESOLVED" in codes(result, "submission_blockers")
    assert result["summary"]["extraction_issue_counts"] == {"open": 1}


def formally_reviewed_project(draft, tmp_path):
    """Records formal evidence only; tests do not assert that these claims are true."""
    refs, digest = add_source(draft, tmp_path)
    draft["dataset_kind"] = "project"
    draft["project"].update(status="verified", source_refs=refs,
        customer={"name": "도입기업", "status": "verified", "source_refs": refs},
        supplier={"name": "공급기업", "status": "verified", "source_refs": refs})
    draft["requirements"] = [requirement(status="verified", source_refs=refs)]
    artifact = tmp_path / "final.hwpx"
    with ZipFile(artifact, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/header.xml", "<header/>")
        z.writestr("Contents/section0.xml", "<section/>")
    artifact_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    draft["sources"].append({"id": "TEMPLATE", "title": "검증용 template fixture", "kind": "template",
        "path": "final.hwpx", "sha256": artifact_digest, "verification_status": "verified"})
    draft["attachments"] = [entity("A1", status="verified", source_refs=refs, path="final.hwpx",
        sha256=artifact_digest, source_id="S1", purpose="최종 산출물 테스트 fixture", verification_status="verified", document_role="SF-AD2")]
    import fitz
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), "FORMAL TEST FIXTURE ONLY")
        document.save(tmp_path / "native.pdf")
        document[0].get_pixmap(dpi=96).save(tmp_path / "page-1.png")
    review_report = {
        "schema_version": "1.0",
        "artifact": {"path": "final.hwpx", "sha256": artifact_digest, "input_dataset_sha256": digest, "template_sha256": artifact_digest},
        "native_export": {"application": "Hancom fixture record", "version": "1", "build": "test",
            "source_sha256": artifact_digest, "pdf_path": "native.pdf",
            "pdf_sha256": hashlib.sha256((tmp_path / "native.pdf").read_bytes()).hexdigest(), "page_count": 1, "compatibility_notices": []},
        "render": {"engine": "Poppler fixture record", "dpi": 96, "pages": [{"page": 1, "path": "page-1.png", "sha256": hashlib.sha256((tmp_path / "page-1.png").read_bytes()).hexdigest()}]},
        "checks": [{"id": "fixture", "passed": True, "scope": "formal evidence wiring only", "evidence": "synthetic assertions"}],
        "visual_review": {"reviewer": "fixture", "reviewed_at": "2025-02-01T09:00:00+09:00", "pages": [{"page": 1, "status": "passed", "observations": ["synthetic claim"]}]},
        "status": "passed", "limitations": ["Test fixture; never actual execution or visual approval proof"],
    }
    report_file = tmp_path / "quality.json"
    report_file.write_text(json.dumps(review_report), encoding="utf-8")
    draft["attachments"].append(entity("Q1", status="verified", source_refs=refs, path="quality.json",
        sha256=hashlib.sha256(report_file.read_bytes()).hexdigest(), source_id="S1", purpose="quality report fixture", verification_status="verified"))
    for kind in ("business_facts", "approval", "native_render"):
        draft["reviews"].append(entity(kind, status="verified", source_refs=refs, review_type=kind,
            outcome="approved", artifact_id="A1" if kind != "business_facts" else None,
            artifact_sha256=artifact_digest if kind != "business_facts" else None,
            reviewer="검토기록 fixture", reviewed_at="2025-02-01T09:00:00+09:00", evidence_ids=["Q1"] if kind == "native_render" else ["A1"]))
    return draft


def test_ad2_only_scope_does_not_require_executed_tests(draft, tmp_path):
    data = formally_reviewed_project(draft, tmp_path)
    result = clean(validate_project(data, base_dir=tmp_path))
    assert not result["errors"] and result["submission_ready"], result["submission_blockers"]
    assert result["summary"]["trace_coverage"]["submission_scope_missing"] == []
    assert "TRACE_COVERAGE_INCOMPLETE" in codes(result, "warnings")
    assert any("truth" in limitation for limitation in result["summary"]["not_verified"])


def test_one_review_cannot_approve_other_unreviewed_artifact(draft, tmp_path):
    data = formally_reviewed_project(draft, tmp_path)
    another = deepcopy(data["attachments"][0])
    another.update(id="A2", document_role="SF-TD5")
    data["attachments"].append(another)
    data["database_tables"] = [table(status="verified", source_refs=data["project"]["source_refs"],
        columns=[column(status="verified", source_refs=data["project"]["source_refs"])])]
    data["project"]["requested_deliverables"].append("SF-TD5")
    result = clean(validate_project(data, base_dir=tmp_path))
    assert not result["submission_ready"]
    assert "DELIVERABLE_REVIEW_INCOMPLETE" in codes(result, "submission_blockers")


def test_nested_fact_status_and_stale_native_hash_close_gate(draft, tmp_path):
    data = formally_reviewed_project(draft, tmp_path)
    data["project"]["customer"]["status"] = "provided"
    result = validate_project(data, base_dir=tmp_path)
    assert not result["submission_ready"]
    assert "FACTS_UNVERIFIED" in codes(result, "submission_blockers")
    data["project"]["customer"]["status"] = "verified"
    data["reviews"][-1]["artifact_sha256"] = "0" * 64
    result = validate_project(data, base_dir=tmp_path)
    assert "REVIEW_ARTIFACT_HASH_MISMATCH" in codes(result)
    assert not result["submission_ready"]


def test_invalid_review_datetime_is_schema_error(draft, tmp_path):
    data = formally_reviewed_project(draft, tmp_path)
    data["reviews"][0]["reviewed_at"] = "tomorrow"
    assert "SCHEMA_INVALID" in codes(validate_project(data, base_dir=tmp_path))


def test_undefined_scope_blocks_formally_verified_data(draft, tmp_path):
    data = formally_reviewed_project(draft, tmp_path)
    data["project"]["requested_deliverables"] = None
    result = validate_project(data, base_dir=tmp_path)
    assert not result["errors"] and not result["submission_ready"]
    assert "SUBMISSION_SCOPE_UNDEFINED" in codes(result, "submission_blockers")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_numbers_are_errors_even_inside_freeform_data(draft, value):
    draft["test_cases"] = [case(data={"raw": [value]})]
    result = validate_project(draft)
    assert "NUMBER_NOT_FINITE" in codes(result)
    assert any(e["path"] == "/test_cases/0/data/raw/0" for e in result["errors"])
    assert not result["draft_ready"] and not result["submission_ready"]


def test_verified_label_cannot_hide_missing_core_fact(draft, tmp_path):
    data = formally_reviewed_project(draft, tmp_path)
    data["requirements"][0]["description"] = None
    result = clean(validate_project(data, base_dir=tmp_path))
    assert not result["errors"] and not result["submission_ready"]
    assert "SUBMISSION_FACTS_INCOMPLETE" in codes(result, "submission_blockers")


def test_same_registration_number_cannot_fill_both_company_roles(draft, tmp_path):
    data = formally_reviewed_project(draft, tmp_path)
    data["project"]["customer"]["business_registration_number"] = "123-45-67890"
    data["project"]["supplier"]["business_registration_number"] = "123-45-67890"
    assert "ORGANIZATION_ROLES_COLLIDE" in codes(clean(validate_project(data, base_dir=tmp_path)))


def test_field_state_pointer_must_exist_in_owning_entity(draft):
    draft["requirements"] = [requirement(field_states={"/not_a_field": {
        "status": "unverified", "reason": "missing input", "source_refs": []}})]
    assert "FIELD_STATE_TARGET_MISSING" in codes(clean(validate_project(draft)))


def test_not_applicable_requires_reason_and_verified_basis_for_submission(draft, tmp_path):
    data = formally_reviewed_project(draft, tmp_path)
    data["requirements"][0]["field_states"] = {"/owner": {"status": "not_applicable", "reason": None, "source_refs": []}}
    result = clean(validate_project(data, base_dir=tmp_path))
    assert not result["errors"] and not result["submission_ready"]
    assert "NOT_APPLICABLE_UNJUSTIFIED" in codes(result, "submission_blockers")


def test_negative_test_payload_keys_are_not_structural_references_or_dates(draft):
    draft["test_cases"] = [case(data={"requirement_ids": ["MISSING-ON-PURPOSE"],
        "artifact_id": "invalid-upload", "start_date": "2026-12-31", "end_date": "2026-01-01",
        "source_refs": [{"source_id": "negative-test", "locator": "/nonexistent"}]})]
    result = clean(validate_project(draft))
    assert not result["errors"] and result["draft_ready"]


def test_native_approved_label_without_quality_evidence_is_insufficient(draft, tmp_path):
    data = formally_reviewed_project(draft, tmp_path)
    data["reviews"][-1]["evidence_ids"] = []
    result = clean(validate_project(data, base_dir=tmp_path))
    assert not result["errors"] and not result["submission_ready"]
    assert "NATIVE_REVIEW_EVIDENCE_INCOMPLETE" in codes(result, "submission_blockers")


def test_native_page_bytes_must_match_reviewed_images(draft, tmp_path):
    data = formally_reviewed_project(draft, tmp_path)
    (tmp_path / "page-1.png").write_bytes(b"tampered page")
    result = validate_project(data, base_dir=tmp_path)
    assert "NATIVE_PAGE_HASH_MISMATCH" in codes(result)
    assert not result["submission_ready"]


def test_native_report_cannot_skip_review_of_an_actual_pdf_page(draft, tmp_path):
    data = formally_reviewed_project(draft, tmp_path)
    path = tmp_path / "quality.json"
    report = json.loads(path.read_text())
    report["native_export"]["page_count"] = 2
    path.write_text(json.dumps(report))
    data["attachments"][1]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = clean(validate_project(data, base_dir=tmp_path))
    assert not result["errors"] and not result["submission_ready"]
    reasons = result["summary"]["native_review_checks"]["Q1"]["reasons"]
    assert {"all_page_review_incomplete", "pdf_page_count_mismatch"} <= set(reasons)


def test_group_case_number_is_unique_within_stage_and_group(draft):
    draft["test_cases"] = [case("T1", group_id="G1", case_number=1), case("T2", group_id="G1", case_number=1)]
    assert "TEST_GROUP_CASE_DUPLICATE" in codes(clean(validate_project(draft)))
    draft["test_cases"][1]["stage"] = "integration"
    assert not validate_project(draft)["errors"]


def test_td5_requires_separate_physical_excel_attachment(draft, tmp_path):
    data = formally_reviewed_project(draft, tmp_path)
    data["project"]["requested_deliverables"] = ["SF-TD5"]
    data["attachments"][0]["document_role"] = "SF-TD5"
    refs = data["project"]["source_refs"]
    data["database_tables"] = [table(status="verified", source_refs=refs,
        columns=[column(status="verified", source_refs=refs)])]
    result = clean(validate_project(data, base_dir=tmp_path))
    assert not result["errors"] and not result["submission_ready"]
    assert "DATABASE_PHYSICAL_EXPORT_MISSING" in codes(result, "submission_blockers")
    path = tmp_path / "physical.xlsx"
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    data["attachments"].append(entity("DBX", status="verified", source_refs=refs, path="physical.xlsx",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), source_id="S1", purpose="container fixture only", verification_status="verified"))
    data["database_tables"][0]["physical_export_attachment_ids"] = ["DBX"]
    assert validate_project(data, base_dir=tmp_path)["submission_ready"]
