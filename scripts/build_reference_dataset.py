"""Build reproducible, non-submission datasets from independent source files.

The reference profile is read-only extraction evidence. Source strings and defects
are retained; this script never changes an original HWPX or repairs its IDs.
The synthetic fixture is a separate, hand-authored source, not generated from the
normalized project data and not a record of real execution or approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = (
    "requirements", "features", "screens", "programs", "database_tables",
    "test_cases", "defects", "deployment_items", "operation_periods",
    "progress_reports", "meetings", "changes", "kpis", "trace_links",
    "attachments", "reviews",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_ref(source_id: str, locator: str):
    return {"source_id": source_id, "locator": locator}


def empty_dataset(kind: str):
    return {
        "schema_version": "1.0", "dataset_kind": kind,
        "project": {}, "sources": [],
        **{domain: [] for domain in DOMAINS},
        "extraction_issues": [], "submission_ready": False,
    }


def normalize_label(value: str) -> str:
    """Used for field matching/comparison only; never replace source text."""
    return re.sub(r"\s+", "", value)


def cell_at(table: dict, row: int, column: int) -> dict:
    matches = [
        cell for cell in table["cells"]
        if int(cell["address"]["rowAddr"]) == row
        and int(cell["address"]["colAddr"]) == column
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one source cell at {table['evidence']} R{row}C{column}")
    return matches[0]


def reference_dataset(profile_path: Path, output_dir: Path) -> dict:
    profile = load_json(profile_path)
    original = Path(profile["source_path"])
    if not original.is_absolute():
        original = profile_path.parent / original
    if digest(original) != profile["sha256"]:
        raise ValueError("The original HWPX no longer matches the analyzed profile")
    dataset = empty_dataset("reference_extraction")
    original_source = "SOURCE-REF-AD2"
    profile_source = "SOURCE-REF-AD2-PROFILE"
    dataset["sources"] = [
        {
            "id": original_source, "title": profile["display_name"],
            "kind": "reference_document", "path": str(original),
            "sha256": digest(original), "verification_status": "provided",
        },
        {
            "id": profile_source, "title": "요구사항정의서 원본 분석 프로필",
            "kind": "other", "path": os.path.relpath(profile_path, output_dir),
            "sha256": digest(profile_path), "verification_status": "provided",
        },
    ]
    paragraphs = [paragraph for section in profile["sections"] for paragraph in section["paragraphs"]]
    by_index = {paragraph["index"]: paragraph for paragraph in paragraphs}
    if len(profile["sections"]) != 1:
        raise ValueError("This curated AD2 extraction expects the reviewed one-section source")
    # These cover values were individually inspected; they are not inferred from filenames.
    customer, program, supplier = (by_index[n] for n in [16, 18, 29])
    years = re.findall(r"(?<!\d)(\d{4})년도", program["text"])
    if len(years) != 1:
        raise ValueError("A unique program year is not explicitly stated in the reviewed cover paragraph")
    dataset["project"] = {
        "id": "REFERENCE-AD2-EXTRACTION",
        "name": None,
        "source_refs": [source_ref(original_source, p["evidence"]) for p in [customer, program, supplier]],
        "requested_deliverables": ["SF-AD2"],
        "program_name": program["text"], "program_year": int(years[0]),
        "template_version": None,
        "customer": {"name": customer["text"], "status": "unverified", "source_refs": [source_ref(original_source, customer["evidence"])]},
        "supplier": {"name": supplier["text"], "status": "unverified", "source_refs": [source_ref(original_source, supplier["evidence"])]},
        "start_date": None, "end_date": None, "status": "unverified",
    }
    toc = []
    for paragraph in paragraphs:
        match = re.match(r"\s*(\d+)\)\s+(MES-AD2-\d+)\s+(.+?)\t\s*(\d+)\s*$", paragraph["text"])
        if match:
            toc.append({
                "ordinal": int(match[1]), "id": match[2], "name": match[3],
                "printed_page": int(match[4]), "raw_text": paragraph["text"],
                "source_ref": source_ref(original_source, paragraph["evidence"]),
            })
    source_tables = [table for section in profile["sections"] for table in section["tables"]]
    tables = [table for table in source_tables if any(normalize_label(cell["text"]) == "요구사항ID" for cell in table["cells"])]
    if len(tables) != 14 or len(toc) != 14:
        raise ValueError(f"Expected 14 body requirements and 14 TOC entries; found {len(tables)}, {len(toc)}")
    classifications = {"기능적": "functional", "비기능적": "nonfunctional"}
    for ordinal, table in enumerate(tables, 1):
        fields = {
            "system_name": cell_at(table, 0, 1), "business_area": cell_at(table, 0, 3),
            "id": cell_at(table, 1, 1), "name": cell_at(table, 1, 3),
            "description": cell_at(table, 2, 1), "details": cell_at(table, 3, 1),
            "constraints": cell_at(table, 4, 1), "classification": cell_at(table, 5, 1),
            "owner": cell_at(table, 5, 3), "origin_statement": cell_at(table, 6, 1),
            "notes": cell_at(table, 7, 1),
        }
        raw_type = fields["classification"]["text"]
        if raw_type not in classifications:
            raise ValueError(f"Unreviewed requirement classification at {table['evidence']}: {raw_type!r}")
        requirement = {
            "id": fields["id"]["text"], "name": fields["name"]["text"],
            "status": "unverified",
            "source_refs": [source_ref(original_source, value["evidence"]) for value in fields.values()],
            "system_name": fields["system_name"]["text"], "business_area": fields["business_area"]["text"],
            "kind": classifications[raw_type], "change_type": None,
            "description": fields["description"]["text"],
            # One raw cell per array item preserves all line breaks/bullet characters.
            "details": [fields["details"]["text"]] if fields["details"]["text"] else [],
            "constraints": [fields["constraints"]["text"]] if fields["constraints"]["text"] else [],
            "owner": {"name": fields["owner"]["text"] or None, "review_status": "unverified"},
            "original_classification": raw_type,
            "notes": "출처(원문):\n" + fields["origin_statement"]["text"] + "\n기타사항(원문):\n" + fields["notes"]["text"],
        }
        dataset["requirements"].append(requirement)
        toc_entry = toc[ordinal - 1]
        if toc_entry["ordinal"] != ordinal:
            raise ValueError("TOC ordinal order changed; manual review required")
        # Extraction issues use both source values. No guessed correction is applied.
        if toc_entry["id"] != requirement["id"]:
            dataset["extraction_issues"].append({
                "id": f"REF-TOC-ID-{ordinal:03d}",
                "name": "목차와 본문의 요구사항 ID 불일치",
                "status": "unverified",
                "source_refs": [toc_entry["source_ref"], source_ref(original_source, fields["id"]["evidence"])],
                "description": json.dumps({"ordinal": ordinal, "toc_id": toc_entry["id"], "body_id": requirement["id"], "toc_raw_text": toc_entry["raw_text"], "action": "원문 두 값을 보존; 자동 정정하지 않음"}, ensure_ascii=False),
            })
        if normalize_label(toc_entry["name"]) != normalize_label(requirement["name"]):
            dataset["extraction_issues"].append({
                "id": f"REF-TOC-NAME-{ordinal:03d}",
                "name": "목차와 본문의 요구사항 명칭 차이",
                "status": "unverified",
                "source_refs": [toc_entry["source_ref"], source_ref(original_source, fields["name"]["evidence"])],
                "description": json.dumps({"ordinal": ordinal, "toc_name": toc_entry["name"], "body_name": requirement["name"], "toc_raw_text": toc_entry["raw_text"], "action": "문자열 관찰값을 보존; 의미 동일성은 확정하지 않음"}, ensure_ascii=False),
            })
    # All TOC entries are retained, not only mismatches, in a source-linked observation.
    dataset["extraction_issues"].append({
        "id": "REF-TOC-OBSERVATION", "name": "요구사항 목차 14개 원문 관찰",
        "status": "unverified", "source_refs": [entry["source_ref"] for entry in toc],
        "description": json.dumps({"toc_entries": toc, "note": "본문 요구사항과 별도로 목차의 원문 ID·명칭·인쇄쪽을 보존함"}, ensure_ascii=False),
    })
    dataset["extraction_issues"].append({
        "id": "REF-SCOPE-UNVERIFIED", "name": "추출 범위와 미확인 항목",
        "status": "unverified", "source_refs": [source_ref(original_source, "Contents/section0.xml#P1"), source_ref(profile_source, "/sections")],
        "description": "이 자료는 AD2 본문14개 및 목차의 관찰 추출이다. 다른 도메인의 빈 배열은 업무가 없다는 뜻이 아니라 이 추출 범위에서 수집하지 않았다는 뜻이다. 실제 과제명·협약기간·현재 양식 버전·담당자 검토/승인·수행 증적은 미확인이다. 출처 칸의 사업계획서/회의록 문구는 원문 주장으로 보존하며, 해당 원본의 진위를 확인했다고 해석하지 않는다. 원문에 change_type 전용 필드가 없어 null로 둔다.",
    })
    for issue in dataset["extraction_issues"]:
        issue["issue_type"] = (
            "original_id_mismatch" if issue["id"].startswith("REF-TOC-ID") else
            "source_conflict" if issue["id"].startswith("REF-TOC-NAME") else
            "unverified_fact" if issue["id"] == "REF-SCOPE-UNVERIFIED" else "other"
        )
        issue["severity"] = "info" if issue["id"] == "REF-TOC-OBSERVATION" else "warning"
        issue["resolution_status"] = "open"
        issue["resolution"] = "원문을 자동 정정하지 않고 관찰값으로 보존한다."
        if issue["description"].startswith("{"):
            issue["original_value"] = json.loads(issue["description"])
            issue["proposed_value"] = None
            issue["description"] = (
                "목차와 본문에서 관찰한 두 원문 ID가 다르다. 어느 쪽도 자동 정정하지 않는다."
                if issue["issue_type"] == "original_id_mismatch" else
                "목차와 본문의 명칭 문자열이 다르다. 의미가 같은지는 확정하지 않고 두 원문 값을 보존한다."
                if issue["issue_type"] == "source_conflict" else
                "14개 목차 항목의 순번·ID·명칭·인쇄쪽·문단 원문을 본문과 별도로 보존한다."
            )
    dataset["extraction_issues"][-2]["resolution_status"] = "accepted_with_reason"
    return dataset


DELIVERABLES = [
    "SF-AD1", "SF-AD2", "SF-AD3", "SF-TD1", "SF-TD2", "SF-TD3",
    "SF-TD4", "SF-TD5", "SF-CD1", "SF-TI1", "SF-TI2", "SF-TI3",
    "SF-TI4", "SF-OS1", "SF-OS2", "SF-PM1", "SF-PM2", "SF-PM3", "SF-PM4",
]


def synthetic_dataset(facts_path: Path, output_dir: Path, *, suite: bool = False) -> dict:
    """Normalize an independently authored synthetic fixture, retaining its pointers."""
    facts = load_json(facts_path)
    if not (
        facts.get("classification") == "synthetic"
        and facts.get("execution_assertion") == "not_performed"
        and facts.get("approval_assertion") == "not_requested_or_approved"
        and facts.get("signature_assertion") == "no_signatures"
    ):
        raise ValueError("The demo source must explicitly be synthetic and unexecuted")
    data = empty_dataset("synthetic")
    data["synthetic_notice"] = "검증용 합성 자료(제출용 아님)"
    source_id = "SOURCE-DEMO-FACTS"
    raw_hash = digest(facts_path)
    relative_path = os.path.relpath(facts_path, output_dir)
    data["sources"] = [{
        "id": source_id, "title": "검증용 독립 합성 원시 사실",
        "kind": "synthetic", "path": relative_path, "sha256": raw_hash,
        "verification_status": "synthetic", "notes": facts["purpose"],
    }]

    def refs(pointer: str):
        return [source_ref(source_id, pointer)]

    def entity(identifier: str, name, pointer: str, **fields):
        return {"id": identifier, "name": name, "status": "synthetic", "source_refs": refs(pointer), **fields}

    def person(name=None):
        return {"name": name, "review_status": "synthetic"}

    ids = {}
    id_specs = [
        ("requirement_notes", "DEMO-AD2"), ("feature_inventory", "DEMO-AD3"),
        ("screen_plan", "DEMO-TD3"), ("program_plan", "DEMO-TD4"),
        ("test_plan", "DEMO-TEST"),
    ]
    for collection, prefix in id_specs:
        for i, row in enumerate(facts[collection], 1):
            ids[row["key"]] = f"{prefix}-{i:03d}"
    for row in facts["database_plan"]:
        ids[row["key"]] = row["physical_name"]
    ids.update({"D01": "DEMO-DEFECT-001", "DP01": "DEMO-TI2-001", "DP02": "DEMO-TI2-002",
                "OP01": "DEMO-OS2-001", "PR01": "DEMO-PM1-001", "M01": "DEMO-PM2-001",
                "C01": "DEMO-PM3-001", "K01": "DEMO-KPI-001", "RV01": "DEMO-REVIEW-001"})
    lookup = {row["key"]: row for collection, _ in id_specs for row in facts[collection]}
    p = facts["project_input"]
    context = facts["project_context"]
    data["project"] = entity(p["internal_id"], p["display_name"], "/project_input",
        requested_deliverables=DELIVERABLES if suite else ["SF-AD2", "SF-AD3", "SF-TD3"],
        requested_forms=[], program_name=p["program_name"], program_year=p["program_year"],
        template_version=p["template_version"],
        customer={"name": p["customer_label"], "status": "synthetic", "source_refs": refs("/project_input/customer_label")},
        supplier={"name": p["supplier_label"], "status": "synthetic", "source_refs": refs("/project_input/supplier_label")},
        start_date=p["planned_start"], end_date=p["planned_end"],
        implementation_scope=context["scope"], business_profile=context["business_profile"],
        notes="계획기간도 합성 가정이다. 실제 착수·완료·승인·서명은 없으며 19종 출력시험을 위한 최소 구조를 포함한다.")
    process = context["process"]
    data["project"]["business_processes"] = [entity("DEMO-PROCESS-001", process["name"], "/project_context/process",
        description=context["business_profile"], current_steps=process["current_steps"], target_steps=process["target_steps"],
        issues=process["issues"], expected_effects=process["expected_effects"],
        requirement_ids=[ids["R01"], ids["R02"], ids["R03"]],
        data_collection_mode=process["collection"], automation_level=process["automation"], real_time_control=None)]
    system = context["system"]
    data["project"]["systems"] = [entity("DEMO-SYSTEM-001", system["name"], "/project_context/system",
        lifecycle="planned", description=system["configuration"], as_is_description=system["before"],
        to_be_description=system["after"], configuration=system["configuration"], network_method=system["network_method"])]
    data["project"]["schedule_items"] = [entity("DEMO-SCHEDULE-" + str(i + 1).zfill(3), row["name"], f"/project_context/schedule/{i}",
        phase=row["phase"], planned_start=row["start"], planned_end=row["end"], actual_start=None, actual_end=None,
        owner=person(), planned_progress=None, actual_progress=None)
        for i, row in enumerate(context["schedule"])]
    budget = context["budget"]
    data["project"]["budget_items"] = [entity("DEMO-BUDGET-001", budget["name"], "/project_context/budget",
        category=budget["category"], planned_amount=budget["planned_krw"], approved_amount=budget["approved_krw"],
        spent_amount=budget["spent_krw"], currency="KRW", unit="원", contribution_kind=None, payer_role=None, basis=budget["basis"])]
    data["project"]["staff_members"] = [entity("DEMO-STAFF-" + str(i + 1).zfill(3), row["person_name"], f"/project_context/staff_roles/{i}",
        organization_role=row["organization_role"], role=row["role"], person=person(), work_description=row["role"])
        for i, row in enumerate(context["staff_roles"])]
    data["project"]["manual_sections"] = [entity("DEMO-MANUAL-" + str(i + 1).zfill(3), row["name"], f"/project_context/manual_topics/{i}",
        audience=row["audience"], topic=row["topic"], content=row["content"],
        screen_ids=[ids[row["screen_key"]]] if row["screen_key"] else [], attachment_ids=[], version="검증용 초안")
        for i, row in enumerate(context["manual_topics"])]
    data["project"]["support_activities"] = [entity("DEMO-SUPPORT-" + str(i + 1).zfill(3), row["name"], f"/project_context/support_plan/{i}",
        category=row["category"], plan=row["plan"], period_start=row["start"], period_end=row["end"],
        contact=person(), actual_result=None, evidence_ids=[])
        for i, row in enumerate(context["support_plan"])]

    for i, row in enumerate(facts["requirement_notes"]):
        data["requirements"].append(entity(ids[row["key"]], row["title"], f"/requirement_notes/{i}",
            system_name=row["system"], business_area=row["business_area"], kind=row["kind"], change_type=row["change"],
            description=row["summary"], details=row["details"], constraints=row["constraints"], owner=person(row["owner_name"]),
            original_classification=row["kind"], fulfillment_status="not_started", deliverable_ids=[], review_ids=[ids["RV01"]],
            notes="독립 합성 요구사항이며 실제 사업 협의·구현·수행은 미수행이다."))
    for i, row in enumerate(facts["feature_inventory"]):
        first_requirement = lookup[row["requirement_keys"][0]]
        data["features"].append(entity(ids[row["key"]], row["name"], f"/feature_inventory/{i}",
            system_name=first_requirement["system"], major_category="DEMO MES", middle_category=first_requirement["business_area"],
            minor_category=row["name"], change_type=row["classification"], description=row["reason"],
            before=row["before"], after=row["after"], requirement_ids=[ids[key] for key in row["requirement_keys"]],
            meeting_ids=[], evidence_ids=[], notes="기존·추가·수정 구분은 실제 설치 상태가 아닌 합성 시나리오의 가정이다."))
    for i, row in enumerate(facts["screen_plan"]):
        program = next(r for r in facts["program_plan"] if r["screen_key"] == row["key"])
        feature_keys = ["F01", "F02", "F03", "F04", "F06"] if i == 0 else ["F05", "F06"]
        data["screens"].append(entity(ids[row["key"]], row["title"], f"/screen_plan/{i}",
            system_name="DEMO MES", screen_kind="screen", path=row["menu"], menu_levels=row["menu"].split(" > "),
            description="입력: " + ", ".join(row["input_fields"]) + "; 출력: " + ", ".join(row["output_fields"]),
            change_type=row["change"], steps=row["steps"], checks=row["checks"],
            fields=[{"name": field["name"], "data_type": field["data_type"], "required": field["required"],
                     "default_value": field["default"], "validation": field["validation"],
                     "source_refs": refs(f"/screen_plan/{i}/field_definitions/{j}")}
                    for j, field in enumerate(row["field_definitions"])],
            buttons=[{"name": b["name"], "action": b["action"], "source_refs": refs(f"/screen_plan/{i}/button_definitions/{j}")}
                     for j, b in enumerate(row["button_definitions"])],
            permissions=[{"role": row["role"], "permission": "allowed", "source_refs": refs(f"/screen_plan/{i}/role")}],
            requirement_ids=[ids[key] for key in row["requirement_keys"]], feature_ids=[ids[key] for key in feature_keys],
            program_ids=[ids[program["key"]]], before_attachment_ids=[], after_attachment_ids=[],
            notes="화면 설계 초안이며 실제 화면·캡처·수행 증거는 없다. 허용 권한도 합성 계획이다."))
    for i, row in enumerate(facts["program_plan"]):
        screen = lookup[row["screen_key"]]
        data["programs"].append(entity(ids[row["key"]], row["title"], f"/program_plan/{i}",
            system_name="DEMO MES", description=row["entrypoint"], change_type=screen["change"], functions=row["logic"],
            interfaces=[row["entrypoint"]], requirement_ids=[ids[key] for key in row["requirement_keys"]],
            screen_ids=[ids[row["screen_key"]]], table_ids=[ids[key] for key in row["database_keys"]],
            output_fields=screen["output_fields"], module_flow_attachment_ids=[], notes="API 설계 계획이며 구현·실행은 미수행이다."))
    for i, row in enumerate(facts["database_plan"]):
        columns = []
        for j, col in enumerate(row["columns"]):
            column_id, name, sql_type, raw_length, nullable, key, default, encryption = col
            length = int(raw_length) if raw_length is not None and "," not in raw_length else None
            column = entity(column_id, name, f"/database_plan/{i}/columns/{j}", type=sql_type, length=length,
                nullable=nullable, key={"PK": "primary", "FK": "foreign", None: "none"}[key], default_value=default,
                encryption={"applied": None, "algorithm": None, "notes": encryption,
                            "source_refs": refs(f"/database_plan/{i}/columns/{j}/7")})
            if raw_length and "," in raw_length:
                column["precision"], column["scale"] = map(int, raw_length.split(","))
                column["notes"] = "원시 길이 표현: " + raw_length
            if key == "FK":
                fk = row["foreign_rule"]
                column["foreign_table_id"] = ids[fk["target_table_key"]]
                column["foreign_column_ids"] = [fk["target_column"]]
            columns.append(column)
        data["database_tables"].append(entity(ids[row["key"]], row["title"], f"/database_plan/{i}",
            description=row["title"] + "의 합성 논리설계. 실제 DB 내보내기·설치 증거는 없다.", columns=columns,
            change_type="new", notes=("복합 UNIQUE 설계안: " + ", ".join(row["unique_rule"])) if "unique_rule" in row else "외래 키 설계안은 원시 foreign_rule에 보존한다."))
    for i, row in enumerate(facts["test_plan"]):
        program_keys = [row["program_key"]] if row["program_key"] else ["P01", "P02"]
        data["test_cases"].append(entity(ids[row["key"]], row["name"], f"/test_plan/{i}",
            stage=row["stage"], scenario=row["scenario"], data=row["input"], expected=row["expected"], actual=None,
            result="not_run", execution_date=None, executor=person(), evidence_ids=[],
            requirement_ids=[ids[key] for key in row["requirement_keys"]], program_ids=[ids[key] for key in program_keys],
            environment=None, notes="계획 시험이며 실제 실행·통과·검수·서명은 미수행이다."))
    defect = facts["unconfirmed_defect_fixture"]
    data["defects"] = [entity(ids[defect["key"]], defect["name"], "/unconfirmed_defect_fixture",
        test_case_id=ids[defect["test_key"]], description=defect["description"], cause=None,
        detected_date=None, resolution=None, resolved_date=None, resolution_status="unverified", owner=person(),
        evidence_ids=[], verification_evidence_ids=[], notes="결함 발생·조치 완료로 해석하지 않는다.")]
    for pointer in ["deployment_plan", "initial_data_plan"]:
        row = facts[pointer]
        fields = dict(category=row["category"], system_name="DEMO MES", planned_specification=row["planned_specification"],
            actual_specification=None, planned_quantity=row["planned_quantity"], installed_quantity=None,
            unit=row["unit"], scheduled_date=row["planned_date"], installation_date=None, installation_status="planned",
            verification_method=row["verification_plan"], verification_result=None, evidence_ids=[],
            related_program_ids=[ids["P01"], ids["P02"]], related_table_ids=[ids["DB01"], ids["DB02"]])
        if "migration_counts" in row:
            fields["migration_counts"] = [{**r, "source_refs": refs(f"/{pointer}/migration_counts/{j}")} for j, r in enumerate(row["migration_counts"])]
        data["deployment_items"].append(entity(ids[row["key"]], row["name"], "/" + pointer,
            **fields, notes="설치·초기 적재 계획이며 실제 납품·설치·적재·확인은 미수행이다."))
    op = facts["operation_calculation_fixture"]
    expected = op["expected_totals"]
    computed = {
        "login_events": sum(row["login_events"] for row in op["rows"]),
        "access_minutes": sum(row["access_minutes"] for row in op["rows"]),
        "distinct_actors": len({row["actor_key"] for row in op["rows"]}),
    }
    computed["mean_minutes_per_login"] = computed["access_minutes"] / computed["login_events"]
    if computed != expected:
        raise ValueError("Independent synthetic operation fixture expectations disagree with raw rows")
    data["operation_periods"] = [entity(ids[op["key"]], op["name"], "/operation_calculation_fixture",
        period_kind="other", period_start=op["period_start"], period_end=op["period_end"], system_name="DEMO MES",
        raw_records=[{"date": row["day"], "login_count": row["login_events"], "usage_minutes": row["access_minutes"],
                      "status": "synthetic", "source_refs": refs(f"/operation_calculation_fixture/rows/{i}")}
                     for i, row in enumerate(op["rows"])],
        reported_totals={"login_count": expected["login_events"], "usage_minutes": expected["access_minutes"]},
        aggregation_method="sum", support_records=[], evidence_ids=[], deployment_item_ids=[ids["DP01"]],
        notes=op["warning"] + f" 합성 고유사용자는{computed['distinct_actors']}명, 접속1회당 평균{computed['mean_minutes_per_login']}분이다. user_count의 단순 합으로 고유사용자를 계산하지 않는다. 실제 운영은 미수행이다.")]
    progress = facts["progress_plan"]
    data["progress_reports"] = [entity(ids[progress["key"]], progress["name"], "/progress_plan",
        report_kind="weekly", period_start=progress["period_start"], period_end=progress["period_end"], report_date=None,
        current_plan_percent=progress["planned_increment_percent"], current_actual_percent=progress["actual_increment_percent"],
        cumulative_plan_percent=progress["planned_cumulative_percent"], cumulative_actual_percent=progress["actual_cumulative_percent"],
        calculation_basis="합성 계획 진도20%, 미수행 실제 진도0%. 월간 실적으로 재분류하지 않는다.",
        work_items=[{"category": "development", "phase": "분석·설계", "person_name": None,
                     "plan": "\n".join(progress["current_work"]), "actual": None, "next_plan": "\n".join(progress["next_work"]),
                     "planned_progress": progress["planned_increment_percent"], "actual_progress": 0,
                     "status": "synthetic", "source_refs": refs("/progress_plan")}],
        risks=[{"number": "DEMO-RISK-001", "kind": "risk", "description": progress["risk"], "handling_status": "확인 필요",
                "action": "실제 사업 사실·승인·수행 자료 수집 전에는 제출 상태로 전환하지 않는다.",
                "status": "synthetic", "source_refs": refs("/progress_plan/risk")}], author=person(), review_ids=[ids["RV01"]])]
    meeting = facts["meeting_plan"]
    data["meetings"] = [entity(ids[meeting["key"]], meeting["name"], "/meeting_plan",
        date=None, weekday=None, location=None, organizer=None, agenda=meeting["agenda"], discussions=[], decisions=[],
        attendees=[], evidence_ids=[], review_ids=[ids["RV01"]],
        special_notes="개최 계획일 " + meeting["planned_date"] + ". 실제 개최·참석·합의·서명은 미수행. 원시 가상 참여 역할은 참석 사실이 아니므로 attendees에 기재하지 않는다.")]
    change = facts["change_proposal"]
    data["changes"] = [entity(ids[change["key"]], change["name"], "/change_proposal",
        categories=["requirement"], request_number=None, request_date=None, requester=person(), reason=change["reason"],
        before=change["proposed_before"], after=change["proposed_after"], impact="\n".join(change["impact"]),
        response_number=None, response_date=None, response_content=None, approval_status="unrequested",
        approval_evidence_ids=[], meeting_ids=[], affected_refs=[{"kind": "requirements", "id": ids["R01"]}],
        review_ids=[ids["RV01"]], notes="검토안이며 변경 요청·승인·적용은 미수행이다.")]
    kpi = facts["kpi_calculation_fixture"]
    actual = kpi["numerator_count"] / kpi["denominator_count"] * 100
    if actual != kpi["expected_calculated_actual_percent"]:
        raise ValueError("Independent synthetic KPI fixture expectation disagrees with input counts")
    attainment = (actual - kpi["baseline_percent"]) / (kpi["target_percent"] - kpi["baseline_percent"]) * 100
    improvement = (actual - kpi["baseline_percent"]) / kpi["baseline_percent"] * 100
    if not (math.isclose(attainment, kpi["expected_attainment_percent"]) and math.isclose(improvement, kpi["expected_improvement_percent"])):
        raise ValueError("Independent synthetic KPI attainment/improvement expectations disagree with inputs")
    data["kpis"] = [entity(ids[kpi["key"]], kpi["name"], "/kpi_calculation_fixture",
        unit=kpi["unit"], direction=kpi["direction"], formula_kind="percent", formula="numerator / denominator * 100",
        numerator=kpi["numerator_count"], denominator=kpi["denominator_count"], baseline=kpi["baseline_percent"],
        target=kpi["target_percent"], actual=kpi["expected_calculated_actual_percent"], actual_precision=2,
        measurement_period_start=None, measurement_period_end=None,
        baseline_source_refs=refs("/kpi_calculation_fixture/baseline_percent"), target_source_refs=refs("/kpi_calculation_fixture/target_percent"),
        actual_source_refs=refs("/kpi_calculation_fixture/expected_calculated_actual_percent"),
        measurements=[], evidence_ids=[], notes=kpi["warning"] + f" 목표달성률{kpi['expected_attainment_percent']}%, 개선율{kpi['expected_improvement_percent']}%도 계산 검증용 예상값이며 실제 성공 판정이 아니다.")]
    data["attachments"] = [entity("DEMO-ATTACHMENT-001", "독립 합성 원시 사실 JSON", "/source_use_policy",
        path=relative_path, sha256=raw_hash, source_id=source_id,
        purpose="출처 및 계산 검증 입력. 실제 화면·시험·승인·운영 증빙이 아니다.", verification_status="synthetic",
        media_type="application/json", caption="검증용 합성 입력(제출용 아님)", original_filename=facts_path.name)]
    review = facts["review_plan"]
    data["reviews"] = [entity(ids[review["key"]], review["name"], "/review_plan",
        review_type="business_facts", outcome="pending", artifact_id=None, artifact_sha256=None, reviewer=None,
        reviewed_at=None, evidence_ids=[], comments="검토 미수행. 실제 업무 사실·승인·서명·네이티브 출력 검토의 대체 근거가 아니다.")]

    # Every relation states planned design intent; endpoint existence does not mean fulfillment.
    for domain in ["features", "screens", "programs", "test_cases"]:
        for item in data[domain]:
            for requirement_id in item.get("requirement_ids", []):
                relation = "tests" if domain == "test_cases" else "implements"
                data["trace_links"].append(entity(f"DEMO-TRACE-{len(data['trace_links']) + 1:03d}", "합성 계획 연결", item["source_refs"][0]["locator"],
                    source_kind=domain, source_id=item["id"], target_kind="requirements", target_id=requirement_id,
                    relation=relation, rationale="독립 합성 원시 입력의 요구사항 연결을 설계·시험 계획으로 선언한다. 실제 구현·시험·요구사항 충족을 확정하지 않는다.",
                    content_review_status="not_reviewed"))
    data["extraction_issues"] = [entity("DEMO-NOT-A-PROJECT", "검증용 합성 범위 및 미수행 사실", "/purpose",
        issue_type="unverified_fact", severity="info", description=facts["purpose"] + " 모든 실제 실행·설치·회의 개최·변경 승인·검토·서명은 미수행이다.",
        resolution_status="accepted_with_reason", resolution="기계적 생성과 검증 예시로만 사용하며 submission_ready=false를 유지한다.")]
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-profile", type=Path,
                        help="Explicit full AD2 analysis profile for optional reference extraction; synthetic demos do not require the local corpus")
    parser.add_argument("--demo-facts", type=Path, default=ROOT / "examples/sources/demo-facts.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/example-datasets")
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.reference_profile is not None:
        if output_dir.is_relative_to(ROOT) and not output_dir.is_relative_to(ROOT / "outputs") and not output_dir.is_relative_to(ROOT / "private"):
            parser.error("Private reference extraction must use ignored outputs/private or an external local directory")
        reference = reference_dataset(args.reference_profile.resolve(), output_dir)
        (output_dir / "reference-extract.project.json").write_text(json.dumps(reference, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Extracted {len(reference['requirements'])} source requirements; retained {len(reference['extraction_issues'])} observations/issues")
    facts_path = args.demo_facts.resolve()
    for suite in [False, True]:
        demo = synthetic_dataset(facts_path, output_dir, suite=suite)
        name = "demo-suite.project.json" if suite else "demo.project.json"
        (output_dir / name).write_text(json.dumps(demo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Built {name}: {len(demo['requirements'])} synthetic requirements; {len(demo['project']['requested_deliverables'])} requested deliverables")


if __name__ == "__main__":
    main()
