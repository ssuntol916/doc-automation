#!/usr/bin/env python3
"""Reproducible schema contract checks; fixtures are QA data, never submissions."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/project.schema.json"
DOMAIN_DEFS = {
    "requirements": "requirement", "features": "feature", "screens": "screen",
    "programs": "program", "database_tables": "database_table",
    "test_cases": "test_case", "defects": "defect", "deployment_items": "deployment_item",
    "operation_periods": "operation_period", "progress_reports": "progress_report",
    "meetings": "meeting", "changes": "change", "kpis": "kpi",
    "trace_links": "trace_link", "attachments": "attachment", "reviews": "review",
}


def run_checks() -> dict:
    raw = SCHEMA_PATH.read_bytes()
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    format_checker = FormatChecker()
    required_formats = {"date", "date-time", "email", "uri"}
    missing_formats = required_formats - set(format_checker.checkers)
    if missing_formats:
        raise RuntimeError("Missing JSON Schema format checkers: " + ", ".join(sorted(missing_formats))
                           + ". Install jsonschema[format] in this Python environment.")
    validator = Draft202012Validator(schema, format_checker=format_checker)
    defs = schema["$defs"]

    def minimum(node):
        """Only construct unknown draft shapes; explicit cases below set tested values."""
        if "$ref" in node:
            return minimum(defs[node["$ref"].split("/")[-1]])
        if "const" in node:
            return node["const"]
        if "enum" in node:
            return None if None in node["enum"] else node["enum"][0]
        if "anyOf" in node:
            if any(child.get("type") == "null" for child in node["anyOf"]):
                return None
            return minimum(node["anyOf"][0])
        types = node.get("type")
        if types is None or types == "null" or isinstance(types, list) and "null" in types:
            return None
        if types == "object":
            return {key: minimum(node["properties"][key]) for key in node.get("required", [])}
        if types == "array":
            return []
        if types == "boolean":
            return False
        if types in ("number", "integer"):
            return node.get("minimum", 0)
        return "QA"

    def entity(def_name, entity_id):
        result = minimum(defs[def_name])
        result.update(id=entity_id, name=None, status="unverified", source_refs=[])
        return result

    base = minimum(schema)
    base.update(dataset_kind="project", submission_ready=False)
    base["project"] = entity("project", "QA-PROJECT")
    base["project"]["requested_deliverables"] = None
    populated = copy.deepcopy(base)
    for domain, def_name in DOMAIN_DEFS.items():
        populated[domain] = [entity(def_name, "QA-" + domain)]
    # Relationship existence, truth and readiness belong to the semantic validator.
    populated["trace_links"][0].update(
        source_kind="requirements", source_id="QA-requirements",
        target_kind="screens", target_id="QA-screens", relation="implemented_by",
    )

    results = []

    def case(name, valid, data):
        errors = sorted(validator.iter_errors(data), key=lambda e: (str(list(e.path)), e.message))
        results.append({
            "name": name, "expected_valid": valid, "actual_valid": not errors,
            "passed": (not errors) == valid, "error_count": len(errors),
            "errors": [{"path": "/" + "/".join(map(str, e.path)), "message": e.message}
                       for e in errors[:4]],
        })

    def modified(name, valid, path, value=None, *, delete=False, source=populated):
        data = copy.deepcopy(source)
        current = data
        for key in path[:-1]:
            current = current[key]
        if delete:
            del current[path[-1]]
        else:
            current[path[-1]] = value
        case(name, valid, data)

    case("minimal_unknown_project_is_valid_draft", True, base)
    case("all_16_domains_accept_unknown_draft_fields", True, populated)
    modified("reference_extraction_does_not_assert_project_truth", True,
             ["dataset_kind"], "reference_extraction")
    synthetic = copy.deepcopy(populated)
    synthetic.update(dataset_kind="synthetic", synthetic_notice="검증용 합성 자료(제출용 아님)")
    synthetic["project"]["status"] = "synthetic"
    for domain in DOMAIN_DEFS:
        synthetic[domain][0]["status"] = "synthetic"
    case("synthetic_notice_and_false_readiness", True, synthetic)
    modified("unperformed_test_needs_no_invented_actual_or_executor", True,
             ["test_cases", 0, "result"], "not_run")
    pending = copy.deepcopy(populated)
    pending["reviews"][0].update(outcome="pending", reviewer=None, reviewed_at=None,
                                  artifact_id=None, artifact_sha256=None)
    case("pending_review_needs_no_invented_signature", True, pending)
    modified("unknown_requirement_change_type_is_preserved", True,
             ["requirements", 0, "change_type"], None)
    modified("provided_classification_is_preserved", True,
             ["requirements", 0, "original_classification"], "기능적")
    modified("structured_expected_result_is_preserved", True,
             ["test_cases", 0, "expected"], {"count": 0, "enabled": False, "rows": []})
    modified("weekday_monday_zero", True, ["meetings", 0, "weekday"], 0)
    modified("unknown_scope_is_valid_but_not_ready_proof", True,
             ["project", "requested_deliverables"], [])
    modified("canonical_scope_has_three_roles", True,
             ["project", "requested_deliverables"], ["SF-AD2", "SF-AD3", "SF-TD3"])
    modified("forms_scope_uses_strings", True, ["project", "requested_forms"], ["1", "1-1", "23"])
    modified("field_level_unknown_actual", True, ["test_cases", 0, "field_states"], {
        "/actual": {"status": "unverified", "reason": "미수행", "source_refs": []}})
    modified("valid_iso_date", True, ["meetings", 0, "date"], "2024-02-29")
    modified("valid_timezone_datetime", True, ["reviews", 0, "reviewed_at"], "2026-10-24T09:00:00+09:00")
    modified("valid_sha256", True, ["attachments", 0, "sha256"], "a" * 64)
    modified("per_field_aggregation_is_explicit", True, ["operation_periods", 0, "aggregation_rules"], {
        "login_count": {"source_field": "login_count", "method": "sum"},
        "average_user_count": {"source_field": "user_count", "method": "average"}})
    modified("zero_and_false_are_facts_not_unknown", True, ["operation_periods", 0, "raw_records"], [
        {"date": "2026-01-01", "user_count": 0, "usage_minutes": 0,
         "status": "provided", "source_refs": []}])
    column = entity("column", "qa_id")
    column.update(name="검증 식별자", type="integer", length=None, nullable=False,
                  key="primary", default_value=0, encryption={
                      "applied": False, "algorithm": None, "notes": "검증용",
                      "source_refs": []})
    modified("physical_logical_db_fields_and_false_nullability", True,
             ["database_tables", 0, "columns"], [column])
    source = {"id": "QA-SRC", "title": None, "kind": "manual_input", "path": None,
              "sha256": None, "verification_status": "unverified"}
    modified("manual_source_without_file_is_allowed", True, ["sources"], [source])
    verified = copy.deepcopy(populated)
    verified["sources"] = [source]
    verified["requirements"][0].update(status="verified", source_refs=[
        {"source_id": "QA-SRC", "locator": "/qa/requirements/0"}])
    case("verified_entity_has_explicit_source_reference_shape", True, verified)

    form = entity("form_record", "QA-FORM")
    form.update(form_id="8-1", author_role="customer", record_date=None)
    form_values = {"text": "검증", "number": 1.5, "integer": 1, "boolean": False,
                   "date": "2026-01-01", "money": 0, "percent": 0,
                   "list": ["검증"], "table": [{"item": "검증", "amount": None}],
                   "attachment_ref": "QA-attachments"}
    for value_type, value in form_values.items():
        item = {"key": "qa_" + value_type, "label": "검증용 필드", "locator": "s1:T67",
                "value_type": value_type, "value": value, "status": "synthetic", "source_refs": []}
        form["fields"] = [item]
        modified("typed_form_" + value_type, True, ["form_records"], [form])
        item["value"] = None
        modified("typed_form_" + value_type + "_unknown", True, ["form_records"], [form])
        item["value"] = {"invalid": True}
        modified("typed_form_" + value_type + "_rejects_object", False, ["form_records"], [form])

    for domain in DOMAIN_DEFS:
        modified(domain + "_missing_id", False, [domain, 0, "id"], delete=True)
        modified(domain + "_empty_id", False, [domain, 0, "id"], "")
        modified(domain + "_invalid_status", False, [domain, 0, "status"], "approved")
        modified(domain + "_verified_requires_source", False, [domain, 0, "status"], "verified")
        modified(domain + "_rejects_unknown_key", False, [domain, 0, "invented_field"], "QA")
    modified("missing_root_domain", False, ["requirements"], delete=True)
    modified("unknown_root_key", False, ["approval_is_automatic"], True)
    modified("version_mismatch", False, ["schema_version"], "2.0")
    modified("invalid_dataset_kind", False, ["dataset_kind"], "approved")
    modified("missing_scope_key", False, ["project", "requested_deliverables"], delete=True)
    modified("unknown_deliverable_code", False, ["project", "requested_deliverables"], ["SF-TI5"])
    modified("duplicate_deliverable_code", False, ["project", "requested_deliverables"], ["SF-AD2", "SF-AD2"])
    modified("numeric_form_id_rejected", False, ["project", "requested_forms"], [1])
    modified("unknown_form_id", False, ["project", "requested_forms"], ["24"])
    modified("invalid_calendar_date", False, ["meetings", 0, "date"], "2026-02-30")
    modified("invalid_datetime", False, ["reviews", 0, "reviewed_at"], "tomorrow")
    organization = {"name": None, "status": "unverified", "source_refs": [], "email": "invalid"}
    modified("invalid_email", False, ["project", "customer"], organization)
    manual = entity("manual_section", "QA-MANUAL")
    manual["online_url"] = "not a uri"
    modified("invalid_manual_uri", False, ["project", "manual_sections"], [manual])
    modified("empty_unknown_text_rejected", False, ["requirements", 0, "description"], "")
    modified("sha256_is_not_arbitrary_text", False, ["attachments", 0, "sha256"], "fake")
    modified("sha256_is_lowercase_hex", False, ["attachments", 0, "sha256"], "A" * 64)
    modified("invalid_requirement_kind", False, ["requirements", 0, "kind"], "기능적")
    modified("invalid_change_type", False, ["features", 0, "change_type"], "추가")
    modified("invalid_test_stage", False, ["test_cases", 0, "stage"], "user")
    modified("invalid_test_result", False, ["test_cases", 0, "result"], "approved")
    modified("negative_tolerance", False, ["test_cases", 0, "comparison"], {"operator": "equal", "tolerance": -1})
    modified("invalid_comparison_operator", False, ["test_cases", 0, "comparison"], {"operator": "looks_similar"})
    modified("negative_install_quantity", False, ["deployment_items", 0, "installed_quantity"], -1)
    modified("progress_over_100", False, ["progress_reports", 0, "current_actual_percent"], 101)
    modified("negative_progress", False, ["progress_reports", 0, "cumulative_plan_percent"], -1)
    modified("weekday_outside_range", False, ["meetings", 0, "weekday"], 7)
    modified("invalid_clock_time", False, ["meetings", 0, "start_time"], "24:00")
    modified("unknown_approval_state", False, ["changes", 0, "approval_status"], "done")
    modified("unknown_kpi_formula", False, ["kpis", 0, "formula_kind"], "auto")
    modified("invalid_kpi_precision", False, ["kpis", 0, "actual_precision"], 13)
    modified("trace_kind_is_domain_not_template_code", False, ["trace_links", 0, "target_kind"], "SF-TD3")
    modified("invalid_aggregation_method_token_in_rule", False, ["operation_periods", 0, "aggregation_rules"], {
        "user_count": {"source_field": "user_count", "method": "estimated"}})
    modified("unknown_aggregation_target", False, ["operation_periods", 0, "aggregation_rules"], {
        "total_success": {"source_field": "user_count", "method": "sum"}})
    modified("invalid_field_state_pointer", False, ["test_cases", 0, "field_states"], {
        "actual": {"status": "unverified", "reason": None, "source_refs": []}})
    for metric in ("user_count", "usage_minutes", "incident_count", "login_count", "registration_count", "transaction_count"):
        modified("negative_operation_" + metric, False, ["operation_periods", 0, "raw_records"], [
            {"date": None, metric: -1, "status": "unverified", "source_refs": []}])
    modified("fractional_user_count", False, ["operation_periods", 0, "reported_totals"], {"user_count": 1.5})
    modified("bad_column_key", False, ["database_tables", 0, "columns"], [{**column, "key": "Y"}])
    modified("negative_column_length", False, ["database_tables", 0, "columns"], [{**column, "length": -1}])
    modified("missing_column_nullable", False, ["database_tables", 0, "columns"], [
        {key: value for key, value in column.items() if key != "nullable"}])
    modified("synthetic_cannot_be_submission_ready", False, ["submission_ready"], True, source=synthetic)
    modified("synthetic_must_have_notice", False, ["synthetic_notice"], delete=True, source=synthetic)
    modified("synthetic_notice_cannot_be_silent", False, ["synthetic_notice"], "예시", source=synthetic)
    reference = copy.deepcopy(base)
    reference["dataset_kind"] = "reference_extraction"
    modified("reference_cannot_be_submission_ready", False, ["submission_ready"], True, source=reference)
    example_datasets = []
    for filename in ("demo.project.json", "demo-suite.project.json", "reference-extract.project.json"):
        path = ROOT / "examples" / filename
        if not path.exists():
            continue
        example_raw = path.read_bytes()
        example = json.loads(example_raw)
        errors = list(validator.iter_errors(example))
        example_datasets.append({
            "path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(example_raw).hexdigest(),
            "valid": not errors, "error_count": len(errors),
            "errors": [{"path": "/" + "/".join(map(str, e.path)), "message": e.message}
                       for e in errors[:4]],
        })
    model_doc = (ROOT / "docs/DATA_MODEL.md").read_text()
    role_section = model_doc.split("## 5.", 1)[1].split("## 6.", 1)[0]
    form_section = model_doc.split("## 6.", 1)[1].split("## 7.", 1)[0]
    documented_roles = re.findall(r"^\| (SF-[A-Z]{2}\d) ", role_section, re.M)
    documented_forms = re.findall(r"^\| (\d+(?:-\d+)?) ", form_section, re.M)
    expected_roles = defs["project"]["properties"]["requested_deliverables"]["anyOf"][0]["items"]["enum"]
    expected_forms = defs["form_record"]["properties"]["form_id"]["enum"]
    coverage = {
        "document": "docs/DATA_MODEL.md",
        "document_sha256": hashlib.sha256(model_doc.encode()).hexdigest(),
        "deliverables": len(documented_roles), "forms": len(documented_forms),
        "canonical_deliverables_exact": documented_roles == expected_roles,
        "form_ids_exact": documented_forms == expected_forms,
        "limitation": "Checks table membership, not truth or complete generation/semantic support.",
    }
    return {
        "schema_path": str(SCHEMA_PATH.relative_to(ROOT)),
        "schema_sha256": hashlib.sha256(raw).hexdigest(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "draft": "2020-12", "check_schema": "passed", "format_checker": True,
        "required_format_checkers": sorted(required_formats),
        "python_version": sys.version.split()[0],
        "jsonschema_version": importlib.metadata.version("jsonschema"),
        "domain_arrays": len(DOMAIN_DEFS), "cases": len(results),
        "positive_cases": sum(r["expected_valid"] for r in results),
        "negative_cases": sum(not r["expected_valid"] for r in results),
        "passed": (all(r["passed"] for r in results) and all(item["valid"] for item in example_datasets)
                   and coverage["canonical_deliverables_exact"] and coverage["form_ids_exact"]),
        "example_datasets": example_datasets,
        "input_coverage_table": coverage,
        "limitations": ["Schema checks do not prove business truth, meaningful links, approvals, execution or native layout.",
                        "Cross-object references, duplicate identifiers and calculated values belong to semantic validation."],
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "verification/project-schema-validation.json")
    args = parser.parse_args()
    report = run_checks()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("check_schema", "cases", "positive_cases", "negative_cases", "passed")}))
    if not report["passed"]:
        print(json.dumps([item for item in report["results"] if not item["passed"]], ensure_ascii=False, indent=2))
        raise SystemExit(1)
