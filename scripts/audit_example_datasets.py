"""Independently audit raw-source preservation and non-execution demo assertions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_NAMES = (
    "requirements", "features", "screens", "programs", "database_tables", "test_cases",
    "defects", "deployment_items", "operation_periods", "progress_reports", "meetings",
    "changes", "kpis", "trace_links", "attachments", "reviews",
)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-dataset", type=Path, help="Optional private reference-extraction dataset; never bundled with public examples")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/dataset-audit.json")
    args = parser.parse_args()
    checks = []

    def check(name, condition, **details):
        checks.append({"check": name, "passed": bool(condition), **details})

    reference = None
    if args.reference_dataset is not None:
        reference = load(args.reference_dataset.resolve())
        raw_source = Path(reference["sources"][0]["path"])
        if not raw_source.is_absolute():
            raw_source = args.reference_dataset.resolve().parent / raw_source
        check("original_hwp_digest_unchanged", hashlib.sha256(raw_source.read_bytes()).hexdigest() == reference["sources"][0]["sha256"])
        with ZipFile(raw_source) as archive:
            root = ET.fromstring(archive.read("Contents/section0.xml"))
        parent = {child: node for node in root.iter() for child in node}

        def local(node):
            return node.tag.rsplit("}", 1)[-1]

        def ancestor(node, tag):
            while node in parent:
                node = parent[node]
                if local(node) == tag:
                    return node
            return None

        # Independent stdlib parser, including the text after inline controls.
        substitutions = {"lineBreak": "\n", "br": "\n", "tab": "\t", "fwSpace": "\u3000", "nbSpace": "\u00a0", "nbHyphen": "\u2011", "softHyphen": "\u00ad"}

        def text_content(node):
            result = node.text or ""
            for child in node:
                result += substitutions.get(local(child), "") + text_content(child) + (child.tail or "")
            return result

        def paragraph_text(paragraph):
            return "".join(text_content(t) for t in paragraph.iter() if local(t) == "t" and ancestor(t, "p") is paragraph)

        def table_cell(table, row, column):
            found = []
            for cell in table.iter():
                if local(cell) != "tc" or ancestor(cell, "tbl") is not table:
                    continue
                address = next(c for c in cell if local(c) == "cellAddr")
                if (int(address.get("rowAddr")), int(address.get("colAddr"))) == (row, column):
                    found.append(cell)
            if len(found) != 1:
                raise AssertionError("Non-unique source cell")
            cell = found[0]
            texts = [paragraph_text(p) for p in cell.iter() if local(p) == "p" and ancestor(p, "tc") is cell]
            return "\n".join(t for t in texts if t)

        tables = [t for t in root.iter() if local(t) == "tbl"]
        check("fourteen_body_requirements", len(reference["requirements"]) == 14 and len(tables) == 15)
        positions = {"system_name": (0, 1), "business_area": (0, 3), "id": (1, 1), "name": (1, 3),
                     "description": (2, 1), "details": (3, 1), "constraints": (4, 1), "original_classification": (5, 1)}
        for ordinal, req in enumerate(reference["requirements"], 1):
            table = tables[ordinal]
            for field, address in positions.items():
                raw = table_cell(table, *address)
                actual = req[field]
                expected = [raw] if field in ("details", "constraints") and raw else [] if field in ("details", "constraints") else raw
                check(f"raw_field_preserved:{ordinal}:{field}", actual == expected)
            check(f"raw_owner_preserved:{ordinal}", req["owner"]["name"] == (table_cell(table, 5, 3) or None))
            expected_notes = "출처(원문):\n" + table_cell(table, 6, 1) + "\n기타사항(원문):\n" + table_cell(table, 7, 1)
            check(f"raw_origin_and_notes_preserved:{ordinal}", req["notes"] == expected_notes)
            check(f"unprovided_change_type_not_inferred:{ordinal}", req["change_type"] is None)
        check("requirement_classification_12_functional_2_nonfunctional", [r["kind"] for r in reference["requirements"]] == ["functional"] * 12 + ["nonfunctional"] * 2)
        paragraphs = [p for p in root.iter() if local(p) == "p"]
        observation = next(x for x in reference["extraction_issues"] if x["id"] == "REF-TOC-OBSERVATION")
        entries = observation["original_value"]["toc_entries"]
        check("all_fourteen_toc_entries_preserved", len(entries) == 14)
        for entry in entries:
            paragraph_number = int(re.search(r"#P(\d+)$", entry["source_ref"]["locator"])[1])
            check(f"raw_toc_paragraph_preserved:{entry['ordinal']}", entry["raw_text"] == paragraph_text(paragraphs[paragraph_number - 1]))
        id_issues = [i for i in reference["extraction_issues"] if i["issue_type"] == "original_id_mismatch"]
        check("toc_body_id_conflicts_preserved", [(i["original_value"]["toc_id"], i["original_value"]["body_id"]) for i in id_issues] == [("MES-AD2-014", "MES-AD2-013"), ("MES-AD2-015", "MES-AD2-014")])
        check("name_differences_not_repaired", len([i for i in reference["extraction_issues"] if i["id"].startswith("REF-TOC-NAME")]) == 3)

    facts_path = ROOT / "examples/sources/demo-facts.json"
    facts = load(facts_path)
    digest = hashlib.sha256(facts_path.read_bytes()).hexdigest()
    for filename, expected_requested in [("demo.project.json", 3), ("demo-suite.project.json", 19)]:
        data = load(ROOT / "examples" / filename)
        prefix = filename + ":"
        check(prefix + "independent_raw_fact_digest", data["sources"][0]["sha256"] == digest and data["sources"][0]["path"] == "sources/demo-facts.json")
        check(prefix + "synthetic_notice_and_submission_gate", data["dataset_kind"] == "synthetic" and data["synthetic_notice"] == "검증용 합성 자료(제출용 아님)" and data["submission_ready"] is False)
        check(prefix + "requested_scope", len(data["project"]["requested_deliverables"]) == expected_requested)
        check(prefix + "all_semantic_entities_synthetic", all(row["status"] == "synthetic" for domain in DOMAIN_NAMES for row in data[domain]))
        check(prefix + "tests_all_unexecuted", len(data["test_cases"]) == 5 and all(t["result"] == "not_run" and t["actual"] is None and t["execution_date"] is None and not t["evidence_ids"] and t["executor"]["name"] is None for t in data["test_cases"]))
        check(prefix + "installation_unperformed", all(x["installation_date"] is None and x["installed_quantity"] is None and x["actual_specification"] is None and x["verification_result"] is None for x in data["deployment_items"]))
        check(prefix + "meeting_not_held_or_signed", all(x["date"] is None and not x["attendees"] and not x["decisions"] for x in data["meetings"]) and not facts["meeting_plan"]["signatures"])
        check(prefix + "change_not_approved", all(x["approval_status"] == "unrequested" and x["request_date"] is None and not x["approval_evidence_ids"] for x in data["changes"]))
        check(prefix + "review_not_performed", all(x["outcome"] == "pending" and x["reviewer"] is None and x["reviewed_at"] is None for x in data["reviews"]))
        if reference is not None:
            check(prefix + "no_reference_company_reuse", all(org["name"] not in json.dumps(data, ensure_ascii=False) for org in [reference["project"]["customer"], reference["project"]["supplier"]]))
        rows = facts["operation_calculation_fixture"]["rows"]
        totals = data["operation_periods"][0]["reported_totals"]
        check(prefix + "operation_sums_recomputed", totals == {"login_count": sum(r["login_events"] for r in rows), "usage_minutes": sum(r["access_minutes"] for r in rows)})
        kpi = data["kpis"][0]
        check(prefix + "kpi_actual_is_calc_fixture_not_execution", kpi["actual"] == kpi["numerator"] / kpi["denominator"] * 100 == 90 and kpi["actual"] < kpi["target"] and kpi["status"] == "synthetic" and not kpi["evidence_ids"])
    report = {"scope": "Independent raw XML/string preservation and synthetic non-execution guards; not source authenticity or native layout approval.",
              "checks": checks, "passed": sum(c["passed"] for c in checks), "failed": sum(not c["passed"] for c in checks)}
    report["private_reference_scope"] = "requested" if reference is not None else "not_requested; synthetic checks only"
    destination = args.output.expanduser().resolve()
    if destination.is_relative_to(ROOT) and not destination.is_relative_to(ROOT / "outputs") and not destination.is_relative_to(ROOT / "private"):
        parser.error("Audit reports must stay in ignored outputs/private or an external directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['passed']} checks passed; {report['failed']} failed")
    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
