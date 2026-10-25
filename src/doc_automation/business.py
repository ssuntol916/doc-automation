"""Project-data checks with explicit limits on what machine validation proves.

No remote resources are fetched. A matching local digest proves byte identity,
not that a business event, signature, approval or test execution is genuine.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import hashlib
from io import BytesIO
from importlib import resources
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


DOMAINS = (
    "requirements", "features", "screens", "programs", "database_tables",
    "test_cases", "defects", "deployment_items", "operation_periods",
    "progress_reports", "meetings", "changes", "kpis", "trace_links",
    "attachments", "reviews",
)
_METRICS = (
    "user_count", "usage_minutes", "incident_count", "login_count",
    "registration_count", "transaction_count",
)
_DATE_PAIRS = (
    ("start_date", "end_date"), ("period_start", "period_end"),
    ("occurrence_date", "completion_date"), ("occurred_date", "resolved_date"),
    ("request_date", "approval_date"), ("requested_date", "approved_date"),
    ("detected_date", "resolved_date"), ("request_date", "response_date"),
    ("measurement_period_start", "measurement_period_end"),
    ("planned_start", "planned_end"), ("actual_start", "actual_end"),
    ("participation_start", "participation_end"),
)
_HWPX_LOCATOR = re.compile(
    r"^(Contents/section\d+\.xml)#(?:(P)([1-9]\d*)|(T)([1-9]\d*)(?:/R(\d+)C(\d+))?)$"
)
_HEX_DIGEST = re.compile(r"^[0-9a-fA-F]{64}$")
_FREE_VALUE_FIELDS = {"data", "expected", "actual", "value", "default_value", "original_value", "proposed_value"}


def _schema(name: str = "project.schema.json") -> dict:
    repository_schema = Path(__file__).resolve().parents[2] / "schemas" / name
    if repository_schema.is_file():
        return json.loads(repository_schema.read_text(encoding="utf-8"))
    packaged = resources.files("doc_automation").joinpath("schemas/" + name)
    return json.loads(packaged.read_text(encoding="utf-8"))


def _pointer(parts: list | tuple) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _numeric(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _resolve_pointer(value: Any, pointer: str) -> Any:
    if not pointer:
        return value
    for segment in pointer[1:].split("/"):
        if re.search(r"~(?![01])", segment):
            raise ValueError("Invalid JSON Pointer escape")
        segment = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9]\d*", segment):
                raise ValueError("Invalid JSON Pointer array index")
            value = value[int(segment)]
        elif isinstance(value, dict):
            value = value[segment]
        else:
            raise KeyError(segment)
    return value


def _day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normal_name(value: Any) -> str:
    return re.sub(r"\s+", "", value).casefold() if isinstance(value, str) else ""


class _Check:
    def __init__(self, data: Any, verify_files: bool, base_dir: Path):
        self.data = data
        self.verify_files = verify_files
        self.base_dir = base_dir
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.blockers: list[dict] = []
        self.seen: set[tuple] = set()
        self.index: dict[str, dict[str, dict]] = {d: {} for d in DOMAINS}
        self.sources: dict[str, dict] = {}
        self.file_checks: dict[str, dict] = {}
        self.attachment_checks: dict[str, dict] = {}
        self._bytes: dict[Path, bytes] = {}
        self.locator_checks: dict[tuple[str, str], str] = {}
        self.coverage: dict = {}
        self.native_checks: dict[str, dict] = {}
        self.quotation_checks: list[dict] = []

    def add(self, level: str, code: str, path: str, message: str, **details: Any) -> None:
        key = level, code, path, message
        if key in self.seen:
            return
        self.seen.add(key)
        issue = {"code": code, "path": path, "message": message}
        if details:
            issue["details"] = details
        {"error": self.errors, "warning": self.warnings, "blocker": self.blockers}[level].append(issue)

    def items(self, domain: str):
        values = self.data.get(domain, []) if isinstance(self.data, dict) else []
        return [(i, x) for i, x in enumerate(values) if isinstance(x, dict)] if isinstance(values, list) else []

    def numbers(self) -> None:
        def walk(node: Any, parts: tuple) -> None:
            if isinstance(node, float) and not math.isfinite(node):
                self.add("error", "NUMBER_NOT_FINITE", _pointer(parts), "NaN/Infinity는 유효한 JSON 수치가 아닙니다. 결측값은 null로 기록하세요.")
            elif isinstance(node, dict):
                for key, value in node.items():
                    walk(value, parts + (key,))
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, parts + (i,))
        walk(self.data, ())

    def schema(self) -> None:
        try:
            schema = _schema()
            Draft202012Validator.check_schema(schema)
        except (OSError, ValueError, SchemaError) as exc:
            self.add("error", "SCHEMA_UNAVAILABLE", "/", "프로젝트 스키마를 읽을 수 없습니다.", reason=str(exc))
            return
        checker = FormatChecker()
        missing_formats = sorted({"date", "date-time", "uri", "email"} - checker.checkers.keys())
        if missing_formats:
            self.add("error", "SCHEMA_FORMAT_UNAVAILABLE", "/", "필요한 형식 검사기가 없습니다. jsonschema[format] 설치 상태를 확인하세요.", formats=missing_formats)
            return
        for error in sorted(
            Draft202012Validator(schema, format_checker=checker).iter_errors(self.data),
            key=lambda e: tuple(map(str, e.absolute_path)),
        ):
            self.add("error", "SCHEMA_INVALID", _pointer(tuple(error.absolute_path)), error.message)

    def identities(self) -> None:
        for domain in DOMAINS:
            for i, item in self.items(domain):
                value = item.get("id")
                if not isinstance(value, str) or not value:
                    continue  # The schema reports missing or invalid IDs.
                if value in self.index[domain]:
                    self.add("error", "DUPLICATE_ID", f"/{domain}/{i}/id", "같은 도메인 안에 ID가 중복됩니다.", id=value, domain=domain)
                else:
                    self.index[domain][value] = item
        for i, item in self.items("sources"):
            value = item.get("id")
            if not isinstance(value, str) or not value:
                continue
            if value in self.sources:
                self.add("error", "DUPLICATE_SOURCE_ID", f"/sources/{i}/id", "출처 ID가 중복됩니다.", id=value)
            else:
                self.sources[value] = item
        project = _object(self.data.get("project"))
        for path, values in [("/form_records", self.data.get("form_records", []))] + [(f"/project/{key}", value) for key, value in project.items() if isinstance(value, list)]:
            seen = set()
            for i, item in enumerate(values if isinstance(values, list) else []):
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    continue
                if item["id"] in seen:
                    self.add("error", "DUPLICATE_ID", path + f"/{i}/id", "같은 개체 목록 안에 ID가 중복됩니다.", id=item["id"])
                seen.add(item["id"])

    def file(self, item: dict, path: str, code: str, *, base_dir: Path | None = None) -> dict:
        result = {"checked": False, "hash_matches": False, "path": None, "actual_sha256": None}
        value = item.get("path")
        if _empty(value):
            return result
        if not isinstance(value, str):
            return result
        # Explicitly reject network/URI fetching. Only supplied filesystem paths are read.
        try:
            scheme = urlsplit(value).scheme
        except ValueError:
            scheme = "invalid-uri"
        if scheme:
            self.add("warning", f"{code}_NONLOCAL", path + "/path", "외부 URI는 접속하지 않았습니다. 로컬 제공 파일만 검증합니다.")
            return result
        try:
            target = Path(value).expanduser()
            target = target if target.is_absolute() else (base_dir or self.base_dir) / target
            target = target.resolve()
            result["path"] = str(target)
            if not self.verify_files:
                return result
            if not target.is_file():
                raise FileNotFoundError(str(target))
            if target not in self._bytes:
                self._bytes[target] = target.read_bytes()
            content = self._bytes[target]
        except (OSError, ValueError, RuntimeError) as exc:
            self.add("error", f"{code}_FILE_UNAVAILABLE", path + "/path", "제공된 로컬 파일을 읽을 수 없습니다.", reason=str(exc))
            return result
        result["checked"] = True
        result["actual_sha256"] = hashlib.sha256(content).hexdigest()
        digest = item.get("sha256")
        if not isinstance(digest, str) or not _HEX_DIGEST.fullmatch(digest):
            self.add("warning", f"{code}_HASH_MISSING", path + "/sha256", "기준 SHA-256이 없어 파일 동일성을 확인하지 못했습니다.")
        elif digest.lower() != result["actual_sha256"]:
            self.add("error", f"{code}_HASH_MISMATCH", path + "/sha256", "제공 파일의 SHA-256이 기준과 다릅니다.", actual_sha256=result["actual_sha256"])
        else:
            result["hash_matches"] = True
        return result

    def provenance(self) -> None:
        for i, source in self.items("sources"):
            if isinstance(source.get("id"), str):
                self.file_checks[source["id"]] = self.file(source, f"/sources/{i}", "SOURCE")
        for i, attachment in self.items("attachments"):
            if isinstance(attachment.get("id"), str):
                self.attachment_checks[attachment["id"]] = self.file(attachment, f"/attachments/{i}", "ATTACHMENT")
            source_id = attachment.get("source_id")
            if source_id is not None and (not isinstance(source_id, str) or source_id not in self.sources):
                self.add("error", "SOURCE_REFERENCE_MISSING", f"/attachments/{i}/source_id", "첨부가 가리키는 출처가 없습니다.", source_id=source_id)
        self.walk_refs(self.data, ())

    def reference_quotations(self) -> None:
        from .quotations import check_quotations
        errors, self.quotation_checks = check_quotations(
            self.data, self.base_dir, verify_files=self.verify_files)
        for error in errors:
            self.add("error", "REFERENCE_QUOTATION_INVALID", error["path"],
                     "역사적 원문 그림의 출처·소유 관계를 확인하지 못했습니다.",
                     reason=error["reason"])

    def walk_refs(self, node: Any, parts: tuple) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _FREE_VALUE_FIELDS:
                    continue
                if key.endswith("source_refs") and isinstance(value, list):
                    for i, ref in enumerate(value):
                        if isinstance(ref, dict):
                            self.source_ref(ref, _pointer(parts + (key, i)))
                else:
                    self.walk_refs(value, parts + (key,))
        elif isinstance(node, list):
            for i, item in enumerate(node):
                self.walk_refs(item, parts + (i,))

    def source_ref(self, ref: dict, path: str) -> None:
        source_id, locator = ref.get("source_id"), ref.get("locator")
        if not isinstance(source_id, str) or source_id not in self.sources:
            self.add("error", "SOURCE_REFERENCE_MISSING", path + "/source_id", "인용한 출처 ID가 없습니다.", source_id=source_id)
            return
        if not isinstance(locator, str):
            return
        key = source_id, locator
        if key in self.locator_checks:
            return
        checked = self.file_checks.get(source_id, {})
        if not self.verify_files or not checked.get("checked"):
            self.locator_checks[key] = "not_checked"
            return
        target = Path(checked["path"])
        content = self._bytes[target]
        try:
            if locator.startswith("/") or locator.startswith("#/") or locator in ("", "#"):
                pointer = locator[1:] if locator.startswith("#") else locator
                value = json.loads(content.decode("utf-8-sig"))
                _resolve_pointer(value, pointer)
            elif match := _HWPX_LOCATOR.fullmatch(locator):
                member, is_p, pnum, is_t, tnum, row, col = match.groups()
                with ZipFile(BytesIO(content)) as archive:
                    root = ET.fromstring(archive.read(member))
                tag, number = ("p", int(pnum)) if is_p else ("tbl", int(tnum))
                elements = [el for el in root.iter() if el.tag.rsplit("}", 1)[-1] == tag]
                element = elements[number - 1]
                if is_t and row is not None:
                    cells = [c for c in element if c.tag.rsplit("}", 1)[-1] == "tr"]
                    addresses = {
                        (a.get("rowAddr"), a.get("colAddr"))
                        for tr in cells for c in tr
                        if c.tag.rsplit("}", 1)[-1] == "tc"
                        for a in c if a.tag.rsplit("}", 1)[-1] == "cellAddr"
                    }
                    if (row, col) not in addresses:
                        raise KeyError(f"R{row}C{col}")
            else:
                self.locator_checks[key] = "unsupported"
                self.add("warning", "SOURCE_LOCATOR_UNCHECKED", path + "/locator", "지원하지 않는 인용 구문을 추측해 해석하지 않았습니다.", locator=locator)
                return
        except (ValueError, KeyError, IndexError, TypeError, UnicodeError, BadZipFile, ET.ParseError, RuntimeError, OSError) as exc:
            self.locator_checks[key] = "invalid"
            self.add("error", "SOURCE_LOCATOR_INVALID", path + "/locator", "명시한 출처 위치가 실제 파일에 없거나 해석할 수 없습니다.", locator=locator, reason=str(exc))
        else:
            self.locator_checks[key] = "valid"

    def reference(self, domain: str, value: Any, path: str) -> None:
        if value is not None and (not isinstance(value, str) or value not in self.index.get(domain, {})):
            self.add("error", "REFERENCE_MISSING", path, "참조 대상 ID가 해당 도메인에 없습니다.", target_kind=domain, target_id=value)

    def references(self) -> None:
        arrays = {
            "requirement_ids": "requirements", "feature_ids": "features",
            "screen_ids": "screens", "program_ids": "programs",
            "table_ids": "database_tables", "test_case_ids": "test_cases",
            "evidence_ids": "attachments", "approval_evidence_ids": "attachments",
            "verification_evidence_ids": "attachments", "attachment_ids": "attachments",
            "before_attachment_ids": "attachments", "after_attachment_ids": "attachments",
            "standard_attachment_ids": "attachments", "module_flow_attachment_ids": "attachments",
            "physical_export_attachment_ids": "attachments", "flow_attachment_ids": "attachments",
            "as_is_attachment_ids": "attachments", "to_be_attachment_ids": "attachments",
            "as_is_diagram_ids": "attachments", "to_be_diagram_ids": "attachments",
            "organization_chart_attachment_ids": "attachments",
            "related_program_ids": "programs", "related_table_ids": "database_tables",
            "review_ids": "reviews", "meeting_ids": "meetings", "deliverable_ids": "attachments",
            "incident_ids": "defects", "deployment_item_ids": "deployment_items",
        }
        singles = {"requirement_id": "requirements", "test_case_id": "test_cases", "artifact_id": "attachments", "signature_review_id": "reviews", "review_id": "reviews"}
        def walk(node: Any, parts: tuple) -> None:
            if isinstance(node, dict):
                for field, target in arrays.items():
                    if isinstance(node.get(field), list):
                        for j, value in enumerate(node[field]):
                            self.reference(target, value, _pointer(parts + (field, j)))
                for field, target in singles.items():
                    if field in node:
                        self.reference(target, node[field], _pointer(parts + (field,)))
                if parts and parts[-2:-1] in (("affected_refs",), ("subject_refs",)):
                    kind = node.get("kind")
                    if isinstance(kind, str) and kind in DOMAINS:
                        self.reference(kind, node.get("id"), _pointer(parts + ("id",)))
                if node.get("value_type") == "attachment_ref":
                    self.reference("attachments", node.get("value"), _pointer(parts + ("value",)))
                for key, value in node.items():
                    if key not in _FREE_VALUE_FIELDS:
                        walk(value, parts + (key,))
            elif isinstance(node, list):
                for j, item in enumerate(node):
                    walk(item, parts + (j,))
        walk(self.data, ())
        processes = _object(self.data.get("project")).get("business_processes", [])
        process_ids = {x["id"] for x in processes if isinstance(x, dict)}
        for i, process in enumerate(processes):
            for j, pid in enumerate(process.get("related_process_ids", [])):
                if pid not in process_ids:
                    self.add("error", "REFERENCE_MISSING", f"/project/business_processes/{i}/related_process_ids/{j}", "관련 공정 ID가 프로젝트 공정 목록에 없습니다.", target_id=pid)
        for domain in DOMAINS:
            for i, item in self.items(domain):
                if domain == "trace_links":
                    for side in ("source", "target"):
                        kind = item.get(side + "_kind")
                        if not isinstance(kind, str) or kind not in DOMAINS:
                            self.add("error", "TRACE_KIND_INVALID", f"/{domain}/{i}/{side}_kind", "연결 도메인명이 올바르지 않습니다.", kind=kind)
                        else:
                            self.reference(kind, item.get(side + "_id"), f"/{domain}/{i}/{side}_id")

    def dates(self) -> None:
        def walk(node: Any, parts: tuple) -> None:
            if isinstance(node, dict):
                for first, last in _DATE_PAIRS:
                    a, b = _day(node.get(first)), _day(node.get(last))
                    if a and b and a > b:
                        self.add("error", "DATE_ORDER", _pointer(parts + (last,)), "종료/완료/승인일이 시작/발생/요청일보다 이릅니다.", first_field=first, first=str(a), last_field=last, last=str(b))
                for key, value in node.items():
                    if key not in _FREE_VALUE_FIELDS:
                        walk(value, parts + (key,))
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, parts + (i,))
        walk(self.data, ())
        project = _object(self.data.get("project"))
        first, last = _day(project.get("start_date")), _day(project.get("end_date"))
        for i, meeting in self.items("meetings"):
            day = _day(meeting.get("date", meeting.get("meeting_date")))
            weekday = meeting.get("weekday")
            if day and isinstance(weekday, int) and not isinstance(weekday, bool) and day.weekday() != weekday:
                self.add("error", "WEEKDAY_MISMATCH", f"/meetings/{i}/weekday", "회의 날짜와 요일이 다릅니다. 월요일은 0입니다.", actual_weekday=day.weekday())
        for domain, field in (("test_cases", "execution_date"), ("deployment_items", "installation_date")):
            for i, item in self.items(domain):
                day = _day(item.get(field))
                if day and ((first and day < first) or (last and day > last)):
                    self.add("warning", "DATE_OUTSIDE_PROJECT", f"/{domain}/{i}/{field}", "일자가 사업기간 밖에 있습니다. 기간/개정 기준을 검토하세요.")

    def organizations(self) -> None:
        project = _object(self.data.get("project"))
        organizations = {}
        for field, role in (("customer", "customer"), ("supplier", "supplier")):
            org = project.get(field)
            if not isinstance(org, dict):
                continue
            organizations[field] = org
            if org.get("role") is not None and org["role"] != role:
                self.add("error", "ORGANIZATION_ROLE_MISMATCH", f"/project/{field}/role", "기업 필드와 명시한 역할이 다릅니다.", expected=role, actual=org["role"])
        customer, supplier = organizations.get("customer", {}), organizations.get("supplier", {})
        same_id = bool(customer.get("id")) and customer.get("id") == supplier.get("id")
        same_registration = bool(customer.get("business_registration_number")) and customer.get("business_registration_number") == supplier.get("business_registration_number")
        if same_id or same_registration:
            self.add("error", "ORGANIZATION_ROLES_COLLIDE", "/project", "도입기업과 공급기업이 같은 식별자로 연결됩니다. 역할 배정을 확인하세요.")
        elif _normal_name(customer.get("name")) and _normal_name(customer.get("name")) == _normal_name(supplier.get("name")):
            self.add("warning", "ORGANIZATION_NAMES_EQUAL", "/project", "도입기업과 공급기업의 이름이 같습니다. 동일 기업인지 역할 배정인지 검토하세요.")

    def requirements(self) -> None:
        names: dict[tuple, list[str]] = defaultdict(list)
        for i, requirement in self.items("requirements"):
            key = tuple(v if isinstance(v, str) else None for v in (requirement.get("system_name"), requirement.get("business_area"), requirement.get("kind"))) + (_normal_name(requirement.get("name")),)
            if key[-1]:
                names[key].append(requirement.get("id", str(i)))
        for key, ids in names.items():
            if len(ids) > 1:
                self.add("warning", "REQUIREMENT_NAME_DUPLICATE", "/requirements", "같은 시스템/업무영역/구분 안에 요구사항명이 중복됩니다. 의미와 ID를 검토하세요.", ids=ids)
        links: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for _, link in self.items("trace_links"):
            if link.get("status") == "not_applicable":
                continue
            sk, sid, tk, tid = (link.get(k) for k in ("source_kind", "source_id", "target_kind", "target_id"))
            if sk == "requirements" and isinstance(sid, str) and isinstance(tk, str) and isinstance(tid, str):
                if tid in self.index.get(tk, {}):
                    links[sid].add((tk, tid))
            if tk == "requirements" and isinstance(tid, str) and isinstance(sk, str) and isinstance(sid, str):
                if sid in self.index.get(sk, {}):
                    links[tid].add((sk, sid))
        # Domain entities can explicitly name requirements without a separate trace row.
        for domain in DOMAINS:
            if domain in ("requirements", "trace_links"):
                continue
            for _, item in self.items(domain):
                if item.get("status") == "not_applicable":
                    continue
                for rid in item.get("requirement_ids", []) if isinstance(item.get("requirement_ids"), list) else []:
                    if isinstance(rid, str) and isinstance(item.get("id"), str):
                        links[rid].add((domain, item["id"]))
        active = [r for _, r in self.items("requirements") if r.get("change_type") != "deleted" and r.get("status") != "not_applicable"]
        missing = []
        for req in active:
            rid = req.get("id")
            if not isinstance(rid, str):
                continue
            targets = links.get(rid, set())
            if req.get("kind") == "functional":
                absent = [kind for kind in ("screens", "programs") if not any(k == kind for k, _ in targets)]
                for stage in ("unit", "integration", "acceptance"):
                    if not any(k == "test_cases" and self.index[k][tid].get("stage") == stage for k, tid in targets):
                        absent.append("test_cases:" + stage)
            else:
                absent = [] if any(k in ("attachments", "deployment_items", "reviews", "test_cases", "operation_periods") for k, _ in targets) else ["nonfunctional_outcome"]
            if absent:
                missing.append({"requirement_id": rid, "missing": absent})
        requested = _object(self.data.get("project")).get("requested_deliverables") or []
        requested = requested if isinstance(requested, list) else []
        required = set()
        for deliverable, target in (("SF-TD3", "screens"), ("SF-TD4", "programs"), ("SF-CD1", "test_cases:unit"), ("SF-TI1", "test_cases:integration"), ("SF-TI4", "test_cases:acceptance")):
            if deliverable in requested or "SF-PM4" in requested:
                required.add(target)
        if "SF-PM4" in requested:
            required.add("nonfunctional_outcome")
        scope_missing = [{"requirement_id": row["requirement_id"], "missing": [x for x in row["missing"] if x in required]} for row in missing]
        scope_missing = [x for x in scope_missing if x["missing"]]
        self.coverage = {"active_requirements": len(active), "fully_linked_requirements": len(active) - len(missing), "missing": missing, "submission_scope_missing": scope_missing, "requested_target_kinds": sorted(required), "scope": "Full-lifecycle ID links are reported; submission blockers use requested deliverable roles. Relevance, satisfaction and execution are not verified."}
        if missing:
            self.add("warning", "TRACE_COVERAGE_INCOMPLETE", "/trace_links", "요구사항의 설계/시험 또는 비기능 결과물 연결에 빈 항목이 있습니다.", missing=missing)

    def database(self) -> None:
        physical = {}
        for i, table in self.items("database_tables"):
            pid = table.get("physical_id", table.get("id"))
            if isinstance(pid, str):
                if pid in physical:
                    self.add("error", "DATABASE_PHYSICAL_ID_DUPLICATE", f"/database_tables/{i}", "물리 테이블 ID가 중복됩니다.", physical_id=pid)
                physical[pid] = i
            self.definition(table, f"/database_tables/{i}", "physical_id" if "physical_id" in table else "id")
            seen = set()
            columns = table.get("columns", [])
            for j, column in enumerate(columns if isinstance(columns, list) else []):
                if not isinstance(column, dict):
                    continue
                cid = column.get("id")
                path = f"/database_tables/{i}/columns/{j}"
                if isinstance(cid, str) and cid in seen:
                    self.add("error", "DATABASE_COLUMN_ID_DUPLICATE", path + "/id", "같은 테이블의 물리 컬럼 ID가 중복됩니다.", column_id=cid)
                if isinstance(cid, str):
                    seen.add(cid)
                self.definition(column, path, "id")
                foreign = column.get("foreign_table_id")
                if foreign is not None:
                    self.reference("database_tables", foreign, path + "/foreign_table_id")
                    other = self.index["database_tables"].get(foreign, {}) if isinstance(foreign, str) else {}
                    other_columns = {c.get("id") for c in other.get("columns", []) if isinstance(c, dict) and isinstance(c.get("id"), str)}
                    for n, foreign_id in enumerate(column.get("foreign_column_ids", []) if isinstance(column.get("foreign_column_ids"), list) else []):
                        if not isinstance(foreign_id, str) or foreign_id not in other_columns:
                            self.add("error", "DATABASE_FOREIGN_COLUMN_MISSING", path + f"/foreign_column_ids/{n}", "외래 컬럼이 명시된 참조 테이블에 없습니다.", column_id=foreign_id)
                # A shape observation is deliberately a review warning, not a universal rule.
                if isinstance(cid, str) and re.search(r"[가-힣]", cid) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(column.get("name", ""))):
                    self.add("warning", "DATABASE_ID_NAME_REVIEW", path, "컬럼 ID/설명명의 배정을 기준 데이터사전과 대조하세요. 언어 모양만으로 전치 오류를 확정하지 않았습니다.")

    def definition(self, item: dict, path: str, id_field: str) -> None:
        declared = any(item.get(key) is not None for key in ("expected_id", "expected_name", "expected_description"))
        if not declared:
            return
        refs = item.get("definition_source_refs")
        if not isinstance(refs, list) or not refs:
            self.add("warning", "DEFINITION_BASELINE_UNSOURCED", path, "기준 ID/이름이 있지만 기준 명세의 출처가 없어 의미 오류를 확정하지 않았습니다.")
            return
        for actual_field, expected_field in ((id_field, "expected_id"), ("name", "expected_name"), ("description", "expected_description")):
            if expected_field in item and item.get(expected_field) is not None and item.get(actual_field) != item[expected_field]:
                self.add("error", "DEFINITION_MISMATCH", path + "/" + actual_field, "명시한 기준 명세와 ID/이름이 다릅니다.", actual=item.get(actual_field), expected=item[expected_field], basis=refs)

    def tests(self) -> None:
        shared_evidence = defaultdict(list)
        group_cases = set()
        for i, case in self.items("test_cases"):
            path = f"/test_cases/{i}"
            group, number = case.get("group_id"), case.get("case_number")
            if group is not None and number is not None:
                group_key = case.get("stage"), group, number
                if group_key in group_cases:
                    self.add("error", "TEST_GROUP_CASE_DUPLICATE", path + "/case_number", "같은 시험 단계·그룹 안에서 케이스 번호가 중복됩니다.", stage=case.get("stage"), group_id=group, case_number=number)
                group_cases.add(group_key)
            result = case.get("result")
            if result in ("passed", "failed"):
                missing = [key for key in ("scenario", "expected", "actual", "execution_date", "executor", "evidence_ids") if _empty(case.get(key))]
                if missing:
                    self.add("error", "TEST_EXECUTION_INCOMPLETE", path, "수행 결과를 주장했지만 실제 결과/수행정보/증거가 누락됐습니다.", missing=missing)
            if result in ("planned", "not_run") and not _empty(case.get("actual")):
                self.add("warning", "TEST_UNEXECUTED_HAS_ACTUAL", path + "/actual", "미실행 시험에 실제 결과가 있습니다. 계획값과 수행값을 구분하세요.")
            comparison = case.get("comparison")
            for aid in case.get("evidence_ids", []) if isinstance(case.get("evidence_ids"), list) else []:
                attachment = self.index["attachments"].get(aid, {}) if isinstance(aid, str) else {}
                shared_evidence[attachment.get("sha256") or str(aid)].append((case.get("id"), case.get("stage")))
            if not isinstance(comparison, dict) or result not in ("passed", "failed"):
                continue
            expected, actual = case.get("expected"), case.get("actual")
            if _empty(expected) or _empty(actual):
                continue
            op, tolerance = comparison.get("operator"), comparison.get("tolerance", 0)
            outcome = self.compare(expected, actual, op, tolerance)
            if outcome is None:
                self.add("warning", "TEST_COMPARISON_UNCHECKED", path + "/comparison", "선언한 비교를 해당 값 유형에 적용할 수 없습니다. 의미 충족을 추측하지 않았습니다.")
            elif (result == "passed") != outcome:
                self.add("error", "TEST_RESULT_CONTRADICTION", path + "/result", "명시된 expected/actual 비교 결과와 시험 판정이 다릅니다.", comparison_result=outcome)
        for i, defect in self.items("defects"):
            if defect.get("resolution_status") in ("resolved", "verified"):
                if _empty(defect.get("evidence_ids")):
                    self.add("warning", "DEFECT_RESOLUTION_EVIDENCE_MISSING", f"/defects/{i}", "해결/완료 결함의 조치 증거 연결이 없습니다.")
        for key, cases in shared_evidence.items():
            if len({stage for _, stage in cases if isinstance(stage, str)}) > 1:
                self.add("warning", "TEST_EVIDENCE_REUSED", "/test_cases", "같은 증거 파일이 여러 시험 단계에 재사용됩니다. 독립 수행 여부를 단정하지 말고 값·날짜·목적을 대조하세요.", evidence_key=key, cases=cases)

    @staticmethod
    def compare(expected: Any, actual: Any, op: str, tolerance: Any) -> bool | None:
        if op in ("equal", "not_equal"):
            if _numeric(expected) and _numeric(actual) and _numeric(tolerance):
                equal = abs(actual - expected) <= tolerance
            else:
                equal = type(expected) is type(actual) and actual == expected
            return equal if op == "equal" else not equal
        if op in ("greater_than", "greater_or_equal", "less_than", "less_or_equal") and _numeric(expected) and _numeric(actual):
            return {"greater_than": actual > expected, "greater_or_equal": actual >= expected, "less_than": actual < expected, "less_or_equal": actual <= expected}[op]
        if op == "contains" and isinstance(actual, (str, list, dict)):
            try:
                return expected in actual
            except TypeError:
                return None
        return None

    def kpis(self) -> None:
        for i, kpi in self.items("kpis"):
            path = f"/kpis/{i}"
            values = {key: kpi.get(key) for key in ("numerator", "denominator", "baseline", "target", "actual")}
            for key, value in values.items():
                if value is not None and not _numeric(value):
                    self.add("error", "NUMBER_NOT_FINITE", path + "/" + key, "KPI 계산값은 유한한 숫자여야 합니다.")
            kind, num, den, actual = kpi.get("formula_kind"), values["numerator"], values["denominator"], values["actual"]
            computed = None
            if kind in ("ratio", "percent") and den == 0:
                self.add("error", "KPI_ZERO_DENOMINATOR", path + "/denominator", "분모가 0이어서 비율을 계산할 수 없습니다.")
            elif kind in ("ratio", "percent", "difference") and _numeric(num) and _numeric(den):
                computed = num - den if kind == "difference" else num / den * (100 if kind == "percent" else 1)
            if computed is not None and _numeric(actual):
                if not _numeric(computed):
                    self.add("error", "CALCULATION_NOT_FINITE", path, "KPI 재계산 결과가 유한한 수치 범위를 벗어났습니다.")
                    continue
                precision = kpi.get("actual_precision", 6)
                precision = precision if isinstance(precision, int) and 0 <= precision <= 12 else 6
                if not math.isclose(actual, computed, rel_tol=1e-9, abs_tol=0.5 * 10 ** -precision):
                    self.add("error", "KPI_ARITHMETIC_MISMATCH", path + "/actual", "명시한 KPI 산식의 재계산값과 실적값이 다릅니다.", computed=computed, actual=actual)
            baseline, target, direction = values["baseline"], values["target"], kpi.get("direction")
            if _numeric(baseline) and _numeric(target):
                contrary = (direction == "increase" and target < baseline) or (direction == "decrease" and target > baseline) or (direction == "maintain" and target != baseline)
                if contrary:
                    self.add("error", "KPI_TARGET_DIRECTION", path + "/target", "목표가 명시된 개선방향과 반대입니다.")
            if _numeric(actual) and _numeric(target):
                missed = (direction == "increase" and actual < target) or (direction == "decrease" and actual > target) or (direction == "maintain" and actual != target)
                if missed:
                    self.add("warning", "KPI_TARGET_NOT_MET", path + "/actual", "입력 실적이 목표에 도달하지 않았습니다. 이를 데이터 오류나 성공 실적으로 바꾸지 않습니다.")

    def operations(self) -> None:
        for i, period in self.items("operation_periods"):
            raw, totals = period.get("raw_records"), period.get("reported_totals")
            if not isinstance(raw, list) or not isinstance(totals, dict):
                continue
            first = _day(period.get("period_start", period.get("start_date")))
            last = _day(period.get("period_end", period.get("end_date")))
            for j, row in enumerate(raw):
                if not isinstance(row, dict):
                    continue
                day = _day(row.get("date"))
                if day and ((first and day < first) or (last and day > last)):
                    self.add("error", "OPERATION_RECORD_OUTSIDE_PERIOD", f"/operation_periods/{i}/raw_records/{j}/date", "운영 원시행의 날짜가 보고기간 밖에 있습니다.")
            rules = _object(period.get("aggregation_rules"))
            for field, declared in totals.items():
                if declared is None:
                    continue
                rule = _object(rules.get(field))
                method = rule.get("method", period.get("aggregation_method"))
                source_field = rule.get("source_field", field)
                if method not in ("sum", "average", "min", "max", "last") or source_field not in _METRICS:
                    self.add("warning", "OPERATION_AGGREGATION_UNCHECKED", f"/operation_periods/{i}/reported_totals/{field}", "알려진 명시적 집계식이 없어 합계/평균/고유 사용자 등을 추측하지 않았습니다.")
                    continue
                records = [row for row in raw if isinstance(row, dict)]
                values = [row.get(source_field) for row in records]
                if not values or any(not _numeric(value) for value in values):
                    self.add("warning", "OPERATION_TOTAL_UNVERIFIED", f"/operation_periods/{i}/reported_totals/{field}", "원시행에 누락된 값이 있어 보고 합계를 재계산하지 못했습니다.")
                    continue
                if method == "last":
                    days = [_day(row.get("date")) for row in records]
                    if any(day is None for day in days) or len(set(days)) != len(days):
                        self.add("warning", "OPERATION_LAST_ORDER_UNVERIFIED", f"/operation_periods/{i}/reported_totals/{field}", "마지막값 집계의 날짜가 누락되거나 중복되어 행 순서를 확정하지 못했습니다.")
                        continue
                    computed = max(records, key=lambda r: r["date"])[source_field]
                else:
                    computed = {"sum": sum, "average": lambda vs: sum(vs) / len(vs), "min": min, "max": max}[method](values)
                if not _numeric(computed):
                    self.add("error", "CALCULATION_NOT_FINITE", f"/operation_periods/{i}/reported_totals/{field}", "운영 집계 결과가 유한한 수치 범위를 벗어났습니다.")
                    continue
                if _numeric(declared) and not math.isclose(computed, declared, rel_tol=1e-9, abs_tol=1e-9):
                    self.add("error", "OPERATION_TOTAL_MISMATCH", f"/operation_periods/{i}/reported_totals/{field}", "보고 집계가 제공된 원시행과 명시한 산식의 재계산값과 다릅니다.", computed=computed, declared=declared, method=method, source_field=source_field)

    def deployment(self) -> None:
        for i, item in self.items("deployment_items"):
            if item.get("installation_status") in ("installed", "verified"):
                absent = [key for key in ("actual_specification", "installed_quantity", "installation_date", "evidence_ids") if _empty(item.get(key))]
                if absent:
                    self.add("error", "DEPLOYMENT_COMPLETION_INCOMPLETE", f"/deployment_items/{i}", "설치/검증 완료를 주장했지만 실제 결과나 증거가 빠졌습니다.", missing=absent)
            if item.get("installation_status") == "verified" and _empty(item.get("verification_result")):
                self.add("error", "DEPLOYMENT_VERIFICATION_MISSING", f"/deployment_items/{i}/verification_result", "검증 완료 주장에 검증결과가 없습니다.")
            a, b = item.get("planned_quantity"), item.get("installed_quantity")
            if _numeric(a) and _numeric(b) and a != b:
                self.add("warning", "DEPLOYMENT_QUANTITY_DIFFERENCE", f"/deployment_items/{i}/installed_quantity", "계획 수량과 실제 설치 수량이 다릅니다. 승인된 변경이나 범위를 확인하세요.", planned=a, installed=b)
            for j, row in enumerate(item.get("migration_counts", []) if isinstance(item.get("migration_counts"), list) else []):
                if isinstance(row, dict) and _numeric(row.get("planned_count")) and _numeric(row.get("actual_count")) and row["planned_count"] != row["actual_count"]:
                    self.add("warning", "MIGRATION_COUNT_DIFFERENCE", f"/deployment_items/{i}/migration_counts/{j}", "초기데이터 전환 대상과 결과 건수가 다릅니다. 정합성·충분성 판정은 별도 검토가 필요합니다.")

    def changes(self) -> None:
        for i, change in self.items("changes"):
            if change.get("approval_status") == "approved" and not change.get("approval_evidence_ids"):
                self.add("error", "CHANGE_APPROVAL_EVIDENCE_MISSING", f"/changes/{i}", "변경 승인으로 표시했지만 승인 증거가 연결되지 않았습니다.")

    def original_issues(self) -> None:
        for i, issue in self.items("extraction_issues"):
            resolution = issue.get("resolution_status")
            if resolution == "open":
                self.add("warning", "ORIGINAL_ISSUE_UNRESOLVED", f"/extraction_issues/{i}", "원본에서 관찰한 미해결 오류/미확인 사항입니다. JSON 구조 오류와 구분합니다.", issue_id=issue.get("id"), severity=issue.get("severity"), description=issue.get("description"))
                self.add("blocker", "ORIGINAL_ISSUE_UNRESOLVED", f"/extraction_issues/{i}", "미해결 원본 이슈에 대한 처리·검토 근거가 필요합니다.", issue_id=issue.get("id"))
            elif resolution in ("resolved", "accepted_with_reason") and (_empty(issue.get("resolution")) or not self._verified_refs(issue.get("source_refs"))):
                self.add("warning", "ORIGINAL_ISSUE_RESOLUTION_UNVERIFIED", f"/extraction_issues/{i}", "원본 이슈의 해결/사유 수용 근거가 충분하지 않습니다.")
                self.add("blocker", "ORIGINAL_ISSUE_RESOLUTION_UNVERIFIED", f"/extraction_issues/{i}", "해결·수용 사유와 확인된 출처가 필요합니다.")

    def field_states(self) -> None:
        def walk(node: Any, parts: tuple) -> None:
            if isinstance(node, dict):
                for pointer in _object(node.get("field_states")):
                    try:
                        _resolve_pointer(node, pointer)
                    except (ValueError, KeyError, IndexError, TypeError):
                        self.add("error", "FIELD_STATE_TARGET_MISSING", _pointer(parts + ("field_states", pointer)), "필드별 상태의 JSON Pointer가 해당 개체 안의 실제 필드를 가리키지 않습니다.")
                for key, value in node.items():
                    if key not in _FREE_VALUE_FIELDS:
                        walk(value, parts + (key,))
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, parts + (i,))
        walk(self.data, ())

    def _verified_refs(self, refs: Any) -> bool:
        if not isinstance(refs, list) or not refs:
            return False
        for ref in refs:
            if not isinstance(ref, dict):
                return False
            sid, locator = ref.get("source_id"), ref.get("locator")
            if not isinstance(sid, str) or not isinstance(locator, str):
                return False
            source, file = self.sources.get(sid, {}), self.file_checks.get(sid, {})
            if source.get("kind") in ("synthetic", "template") or source.get("verification_status") != "verified" or not file.get("hash_matches") or self.locator_checks.get((sid, locator)) != "valid":
                return False
        return True

    def native_review(self, review: dict, path: str, artifact: dict) -> bool:
        """Check supplied quality-report bytes, never infer that Hancom was run."""
        for aid in review.get("evidence_ids", []):
            evidence = self.index["attachments"].get(aid, {})
            checked = self.attachment_checks.get(aid, {})
            if evidence.get("verification_status") != "verified" or not checked.get("hash_matches"):
                continue
            report_path = Path(checked["path"])
            try:
                report = json.loads(self._bytes[report_path].decode("utf-8-sig"))
            except (ValueError, UnicodeError):
                continue
            try:
                schema = _schema("quality-review.schema.json")
                invalid = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(report))
            except (OSError, ValueError, SchemaError) as exc:
                self.add("warning", "NATIVE_REVIEW_SCHEMA_UNAVAILABLE", path, "네이티브 품질근거 스키마를 읽을 수 없습니다.", reason=str(exc))
                return False
            if invalid:
                self.add("warning", "NATIVE_REVIEW_REPORT_INVALID", path, "첨부 JSON이 네이티브 품질근거 계약을 충족하지 않습니다.", evidence_id=aid, schema_errors=[e.message for e in invalid])
                continue
            artifact_info, native, render, visual = (report[k] for k in ("artifact", "native_export", "render", "visual_review"))
            count = native["page_count"]
            expected_pages = set(range(1, count + 1))
            render_pages = [p["page"] for p in render["pages"]]
            visual_pages = [p["page"] for p in visual["pages"]]
            reasons = []
            digest = artifact.get("sha256", "").lower()
            if artifact_info["sha256"] != digest or native["source_sha256"] != digest:
                reasons.append("current_artifact_hash_mismatch")
            input_hashes = {x["actual_sha256"] for sid, x in self.file_checks.items() if x.get("hash_matches") and self.sources[sid].get("kind") != "template" and self.sources[sid].get("verification_status") == "verified"}
            template_hashes = {x["actual_sha256"] for sid, x in self.file_checks.items() if x.get("hash_matches") and self.sources[sid].get("kind") == "template" and self.sources[sid].get("verification_status") == "verified"}
            if artifact_info["input_dataset_sha256"] not in input_hashes or artifact_info["template_sha256"] not in template_hashes:
                reasons.append("input_or_template_hash_not_locally_bound")
            if report["status"] != "passed" or not all(c["passed"] for c in report["checks"]):
                reasons.append("quality_checks_not_passed")
            if len(render_pages) != count or set(render_pages) != expected_pages or len(visual_pages) != count or set(visual_pages) != expected_pages or any(p["status"] != "passed" for p in visual["pages"]):
                reasons.append("all_page_review_incomplete")
            application = native["application"].casefold()
            if not any(token in application for token in ("hancom", "hanword", "hwp", "한글", "한컴")):
                reasons.append("hancom_application_not_recorded")
            if "poppler" not in render["engine"].casefold() and "pdftoppm" not in render["engine"].casefold():
                reasons.append("poppler_render_not_recorded")
            base = report_path.parent
            actual_file = self.file(artifact_info, path + "/quality_report/artifact", "NATIVE_ARTIFACT", base_dir=base)
            pdf = self.file({"path": native["pdf_path"], "sha256": native["pdf_sha256"]}, path + "/quality_report/native_export", "NATIVE_PDF", base_dir=base)
            if not actual_file["hash_matches"] or not pdf["hash_matches"]:
                reasons.append("artifact_or_pdf_bytes_unverified")
            if actual_file["hash_matches"]:
                try:
                    with ZipFile(BytesIO(self._bytes[Path(actual_file["path"])])) as archive:
                        members = set(archive.namelist())
                        if archive.read("mimetype").decode().strip() != "application/hwp+zip" or "Contents/header.xml" not in members or not any(re.fullmatch(r"Contents/section\d+\.xml", member) for member in members):
                            reasons.append("artifact_not_hwpx_package")
                except (BadZipFile, KeyError, UnicodeError, RuntimeError, OSError):
                    reasons.append("artifact_not_hwpx_package")
            if pdf["hash_matches"]:
                try:
                    import fitz
                    with fitz.open(stream=self._bytes[Path(pdf["path"])], filetype="pdf") as document:
                        if document.page_count != count:
                            reasons.append("pdf_page_count_mismatch")
                except Exception as exc:
                    reasons.append("pdf_unreadable")
                    self.add("warning", "NATIVE_PDF_UNREADABLE", path, "제공된 네이티브 PDF를 읽을 수 없습니다.", reason=str(exc))
            for page in render["pages"]:
                page_file = self.file(page, path + f"/quality_report/render/page/{page['page']}", "NATIVE_PAGE", base_dir=base)
                if not page_file["hash_matches"]:
                    reasons.append("page_image_bytes_unverified")
                else:
                    try:
                        from PIL import Image
                        with Image.open(BytesIO(self._bytes[Path(page_file["path"])])) as picture:
                            picture.verify()
                    except (OSError, ValueError):
                        reasons.append("page_image_unreadable")
            self.native_checks[aid] = {"passed": not reasons, "artifact_sha256": digest, "page_count": count, "reasons": sorted(set(reasons)), "scope": "Supplied native export and page-review records plus local bytes; actual application execution and visual judgment authenticity are not independently proved."}
            if not reasons:
                return True
            self.add("warning", "NATIVE_REVIEW_EVIDENCE_INCOMPLETE", path, "네이티브 출력·전체 페이지 검토의 연결 근거가 불완전합니다.", evidence_id=aid, reasons=sorted(set(reasons)))
        self.add("blocker", "NATIVE_REVIEW_EVIDENCE_INCOMPLETE", path, "현재 파일 해시에 연결된 품질근거 JSON, 한글 버전, 실제 PDF/페이지 이미지, 전체 페이지 검토가 필요합니다.")
        return False

    def submission(self) -> None:
        if self.data.get("dataset_kind") != "project":
            self.add("blocker", "NONPROJECT_DATASET", "/dataset_kind", "합성 예시/참고 추출자료는 실제 사업 제출 가능 상태가 될 수 없습니다.")
        if not self.verify_files:
            self.add("blocker", "FILE_VERIFICATION_DISABLED", "/sources", "로컬 제공 파일의 SHA-256 대조가 비활성화됐습니다.")
        project = _object(self.data.get("project"))
        requested = project.get("requested_deliverables")
        requested = requested if isinstance(requested, list) else []
        if not requested and not project.get("requested_forms"):
            self.add("blocker", "SUBMISSION_SCOPE_UNDEFINED", "/project/requested_deliverables", "작성/제출 대상 산출물·서식의 범위가 확정되지 않았습니다.")
        if project.get("status") != "verified":
            self.add("blocker", "PROJECT_UNVERIFIED", "/project/status", "사업 사실의 확인 상태가 verified가 아닙니다.")
        required_project = ("name", "program_name", "program_year", "template_version", "customer", "supplier", "start_date", "end_date")
        missing = [key for key in required_project if _empty(project.get(key))]
        if missing:
            self.add("blocker", "PROJECT_FACTS_INCOMPLETE", "/project", "제출 판단에 필요한 공통 사업정보가 비어 있습니다.", missing=missing)
        unverified, unsourced, unexplained_na = [], [], []
        def inspect(node: Any, parts: tuple) -> None:
            if isinstance(node, dict):
                if node.get("status") == "not_applicable" or node.get("review_status") == "not_applicable":
                    if _empty(node.get("reason", node.get("notes"))) or not self._verified_refs(node.get("source_refs")):
                        unexplained_na.append(_pointer(parts))
                    return
                if ("status" in node and node["status"] != "verified") or ("review_status" in node and node["review_status"] != "verified"):
                    unverified.append(_pointer(parts))
                if "source_refs" in node and not self._verified_refs(node["source_refs"]):
                    unsourced.append(_pointer(parts))
                for key, value in node.items():
                    # Free-form business values can contain arbitrary keys named status.
                    if key not in {"sources", "extraction_issues"} | _FREE_VALUE_FIELDS and not key.endswith("source_refs"):
                        inspect(value, parts + (key,))
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    inspect(value, parts + (i,))
        inspect(self.data, ())
        if unexplained_na:
            self.add("blocker", "NOT_APPLICABLE_UNJUSTIFIED", "/", "적용 없음 판단에 이유와 확인된 근거가 필요합니다.", paths=unexplained_na)
        if unverified:
            self.add("blocker", "FACTS_UNVERIFIED", "/", "미확인/합성 의미 개체가 남아 있습니다.", paths=unverified)
        if unsourced or not self.sources:
            self.add("blocker", "PROVENANCE_INCOMPLETE", "/sources", "확인된 로컬 출처·SHA-256·인용 위치에 연결되지 않은 개체가 있습니다.", paths=unsourced)
        unchecked_attachments = [a.get("id") for _, a in self.items("attachments") if a.get("status") != "not_applicable" and (a.get("verification_status") != "verified" or not self.attachment_checks.get(a.get("id"), {}).get("hash_matches"))]
        if unchecked_attachments:
            self.add("blocker", "ATTACHMENT_PROVENANCE_INCOMPLETE", "/attachments", "첨부의 파일 대조·확인 상태가 충분하지 않습니다.", attachment_ids=unchecked_attachments)
        core_fields = {
            "requirements": ("name", "system_name", "business_area", "kind", "change_type", "description"),
            "features": ("name", "system_name", "description", "change_type"),
            "screens": ("name", "system_name", "path", "description", "steps"),
            "programs": ("name", "system_name", "description", "functions"),
            "database_tables": ("name", "description", "columns"),
            "operation_periods": ("period_start", "period_end", "raw_records", "reported_totals"),
            "kpis": ("name", "unit", "direction", "formula_kind", "formula", "baseline", "target", "actual"),
        }
        missing_facts = []
        for domain, fields in core_fields.items():
            for i, item in self.items(domain):
                if item.get("status") == "not_applicable":
                    continue
                declared_na = _object(item.get("field_states"))
                for field in fields:
                    if _empty(item.get(field)) and _object(declared_na.get("/" + field)).get("status") != "not_applicable":
                        missing_facts.append(f"/{domain}/{i}/{field}")
                if domain == "database_tables":
                    for j, col in enumerate(item["columns"]):
                        if col.get("status") != "not_applicable":
                            missing_facts.extend(f"/{domain}/{i}/columns/{j}/{key}" for key in ("name", "type") if _empty(col.get(key)))
        if missing_facts:
            self.add("blocker", "SUBMISSION_FACTS_INCOMPLETE", "/", "기본 작성 사실에 미확정 항목이 있습니다. 해당 없음은 field_states에 명시합니다.", paths=missing_facts)
        if not self._verified_refs(project.get("source_refs")):
            self.add("blocker", "PROJECT_PROVENANCE_INCOMPLETE", "/project/source_refs", "공통 사업정보가 확인된 출처와 연결되지 않았습니다.")
        if self.coverage.get("submission_scope_missing"):
            self.add("blocker", "TRACE_COVERAGE_INCOMPLETE", "/trace_links", "필수 설계/시험 또는 비기능 결과물의 ID 연결이 완전하지 않습니다.")
        if not self.items("requirements") and any(x in requested for x in ("SF-AD2", "SF-PM4")):
            self.add("blocker", "REQUIREMENTS_MISSING", "/requirements", "요구사항 원장이 없어 제출 범위의 커버리지를 판단할 수 없습니다.")
        scope_domains = {
            "SF-AD2": "requirements", "SF-AD3": "features", "SF-TD3": "screens",
            "SF-TD4": "programs", "SF-TD5": "database_tables", "SF-TI2": "deployment_items",
            "SF-OS2": "operation_periods", "SF-PM1": "progress_reports", "SF-PM2": "meetings",
            "SF-PM3": "changes", "SF-PM4": "trace_links",
        }
        missing_domains = sorted({domain for code, domain in scope_domains.items() if code in requested and not self.items(domain)})
        if missing_domains:
            self.add("blocker", "SUBMISSION_DOMAIN_DATA_MISSING", "/", "선택한 산출물의 작성 자료가 없습니다. 해당 없음 처리에는 명시적 판단이 필요합니다.", domains=missing_domains)
        project_sections = {"SF-AD1": "business_processes", "SF-TD1": "business_processes", "SF-TD2": "systems", "SF-TI3": "manual_sections", "SF-OS1": "support_activities"}
        missing_sections = sorted({section for code, section in project_sections.items() if code in requested and not project.get(section)})
        if missing_sections:
            self.add("blocker", "SUBMISSION_PROJECT_SECTIONS_MISSING", "/project", "선택한 산출물의 공정·시스템·매뉴얼·지원 자료가 비어 있습니다.", sections=missing_sections)
        requested_forms = project.get("requested_forms") or []
        form_records = [r for _, r in self.items("form_records") if r.get("status") != "not_applicable"]
        for fid in requested_forms:
            records = [r for r in form_records if r.get("form_id") == fid]
            if not records or any(not r.get("fields") or any(_empty(f.get("value")) and f.get("status") != "not_applicable" for f in r["fields"]) for r in records):
                self.add("blocker", "REQUESTED_FORM_INCOMPLETE", "/form_records", "요청한 서식의 입력 필드가 없거나 미확정입니다.", form_id=fid)
        for code, stage in (("SF-CD1", "unit"), ("SF-TI1", "integration"), ("SF-TI4", "acceptance")):
            if code not in requested:
                continue
            cases = [c for _, c in self.items("test_cases") if c.get("stage") == stage and c.get("status") != "not_applicable"]
            if not cases or any(c.get("result") != "passed" for c in cases):
                self.add("blocker", "TESTS_NOT_PASSED", "/test_cases", "선택한 시험 산출물에 미실행/미통과 시험이 남아 있습니다.", stage=stage)
            if stage == "acceptance":
                unresolved = [c.get("id") for c in cases if not isinstance(c.get("executor"), dict) or c["executor"].get("organization_role") != "customer" or _empty(c.get("environment"))]
                if unresolved:
                    self.add("blocker", "ACCEPTANCE_CONTEXT_UNVERIFIED", "/test_cases", "사용자시험의 도입기업 담당자·실행환경 정보가 부족합니다.", test_case_ids=unresolved)
        if any(code in requested for code in ("SF-CD1", "SF-TI1", "SF-TI4")):
            unresolved_defects = [d.get("id") for _, d in self.items("defects") if d.get("status") != "not_applicable" and (d.get("resolution_status") not in ("resolved", "verified") or not d.get("evidence_ids"))]
            if unresolved_defects:
                self.add("blocker", "DEFECTS_UNRESOLVED", "/defects", "선택한 시험 제출 판단에 미해결·미확인 결함 또는 조치 증거 누락이 남아 있습니다.", defect_ids=unresolved_defects)
        if "SF-TI2" in requested:
            incomplete = [x.get("id") for _, x in self.items("deployment_items") if x.get("status") != "not_applicable" and x.get("installation_status") != "verified"]
            if incomplete:
                self.add("blocker", "DEPLOYMENT_NOT_VERIFIED", "/deployment_items", "전환 결과의 검증 완료 자료가 부족합니다.", item_ids=incomplete)
        if "SF-TD5" in requested:
            missing_exports = []
            for _, table in self.items("database_tables"):
                if table.get("status") == "not_applicable":
                    continue
                aids = table.get("physical_export_attachment_ids", [])
                valid = bool(aids)
                for aid in aids:
                    checked = self.attachment_checks.get(aid, {})
                    if not checked.get("hash_matches"):
                        valid = False
                        continue
                    content = self._bytes[Path(checked["path"])]
                    is_excel = content.startswith(bytes.fromhex("d0cf11e0a1b11ae1"))
                    if not is_excel:
                        try:
                            with ZipFile(BytesIO(content)) as archive:
                                is_excel = {"[Content_Types].xml", "xl/workbook.xml"} <= set(archive.namelist())
                        except BadZipFile:
                            pass
                    if not is_excel:
                        valid = False
                if not valid:
                    missing_exports.append(table.get("id"))
            if missing_exports:
                self.add("blocker", "DATABASE_PHYSICAL_EXPORT_MISSING", "/database_tables", "선택한 DB 설계서에는 각 물리 테이블의 별도 Excel 출력 연결과 파일 확인이 필요합니다. 컨테이너 형식 확인은 내용 정합성 검토를 대신하지 않습니다.", table_ids=missing_exports)
        if "SF-PM4" in requested:
            unreviewed_links = [x.get("id") for _, x in self.items("trace_links") if x.get("status") != "not_applicable" and x.get("content_review_status") != "confirmed"]
            if unreviewed_links:
                self.add("blocker", "TRACE_CONTENT_REVIEW_PENDING", "/trace_links", "추적 연결의 의미 검토가 완료됐다는 명시 기록이 없습니다. ID 존재 검사와 구분합니다.", trace_ids=unreviewed_links)
        pending_changes = [x.get("id") for _, x in self.items("changes") if x.get("status") != "not_applicable" and x.get("approval_status") not in ("approved", "not_required")]
        if "SF-PM3" in requested and pending_changes:
            self.add("blocker", "CHANGE_APPROVAL_PENDING", "/changes", "변경 승인 여부가 미확정입니다.", ids=pending_changes)
        if any(w["code"] in ("OPERATION_AGGREGATION_UNCHECKED", "OPERATION_TOTAL_UNVERIFIED", "OPERATION_LAST_ORDER_UNVERIFIED", "TEST_COMPARISON_UNCHECKED") for w in self.warnings):
            self.add("blocker", "DECLARED_CHECK_UNRESOLVED", "/", "명시된 계산/비교 중 자동 확인을 완료하지 못한 항목이 있습니다.")
        accepted_types = set()
        reviewed_artifacts: dict[str, set[str]] = defaultdict(set)
        for i, review in self.items("reviews"):
            if review.get("outcome") in ("needs_changes", "rejected", "pending") and review.get("status") != "not_applicable":
                self.add("blocker", "REVIEW_NOT_APPROVED", f"/reviews/{i}", "완료/승인되지 않은 검토가 남아 있습니다.")
            if review.get("status") != "verified" or review.get("outcome") != "approved":
                continue
            if _empty(review.get("reviewer")) or _empty(review.get("reviewed_at")) or not self._verified_refs(review.get("source_refs")):
                continue
            kind = review.get("review_type")
            if not isinstance(kind, str):
                continue
            if kind in ("approval", "native_render"):
                aid, digest = review.get("artifact_id"), review.get("artifact_sha256")
                attachment = self.index["attachments"].get(aid, {}) if isinstance(aid, str) else {}
                checked = self.attachment_checks.get(aid, {}) if isinstance(aid, str) else {}
                equal_digest = isinstance(digest, str) and isinstance(attachment.get("sha256"), str) and digest.lower() == attachment["sha256"].lower()
                if digest and attachment.get("sha256") and not equal_digest:
                    self.add("error", "REVIEW_ARTIFACT_HASH_MISMATCH", f"/reviews/{i}/artifact_sha256", "승인/네이티브 검토의 해시가 연결 산출물과 다릅니다.")
                if not checked.get("hash_matches") or not equal_digest:
                    self.add("blocker", "REVIEW_ARTIFACT_UNBOUND", f"/reviews/{i}", "승인/네이티브 검토가 검증된 산출물 SHA-256과 연결되지 않았습니다.")
                    continue
                if kind == "native_render" and not self.native_review(review, f"/reviews/{i}", attachment):
                    continue
                reviewed_artifacts[aid].add(kind)
            accepted_types.add(kind)
        missing_reviews = sorted({"business_facts", "approval", "native_render"} - accepted_types)
        if missing_reviews:
            self.add("blocker", "REVIEW_EVIDENCE_INCOMPLETE", "/reviews", "사업 사실·승인·네이티브 출력 검토의 명시적 근거가 모두 갖춰지지 않았습니다.", missing_review_types=missing_reviews)
        for code in requested:
            artifacts = [aid for aid, a in self.index["attachments"].items() if a.get("document_role") == code and a.get("status") != "not_applicable"]
            if not artifacts or any(not {"approval", "native_render"} <= reviewed_artifacts[aid] for aid in artifacts):
                self.add("blocker", "DELIVERABLE_REVIEW_INCOMPLETE", "/attachments", "요청 산출물별 최종 파일과 동일 SHA의 승인·네이티브 검토가 필요합니다. document_role에 canonical 코드를 기록합니다.", deliverable_code=code, artifact_ids=artifacts)
        for fid in requested_forms:
            artifacts = {aid for r in form_records if r.get("form_id") == fid for aid in r.get("attachment_ids", [])}
            if not artifacts or any(not {"approval", "native_render"} <= reviewed_artifacts[aid] for aid in artifacts):
                self.add("blocker", "FORM_REVIEW_INCOMPLETE", "/form_records", "요청 서식별 최종 첨부와 동일 SHA의 승인·네이티브 검토가 필요합니다.", form_id=fid, artifact_ids=sorted(artifacts))
        if self.data.get("submission_ready") is True and (self.errors or self.blockers):
            self.add("warning", "SUBMISSION_CLAIM_REJECTED", "/submission_ready", "입력의 제출 가능 주장을 검증 결과가 뒷받침하지 않습니다.")

    def result(self) -> dict:
        return {
            "schema_version": "1.0",
            "errors": self.errors,
            "warnings": self.warnings,
            "submission_blockers": self.blockers,
            "draft_ready": not self.errors,
            "submission_ready": not self.errors and not self.blockers,
            "summary": {
                "error_count": len(self.errors), "warning_count": len(self.warnings),
                "submission_blocker_count": len(self.blockers),
                "entity_counts": {domain: len(self.items(domain)) for domain in DOMAINS},
                "extraction_issue_counts": dict(Counter(x.get("resolution_status") for _, x in self.items("extraction_issues"))),
                "form_record_count": len(self.items("form_records")),
                "file_verification_enabled": self.verify_files,
                "base_dir": str(self.base_dir),
                "source_file_checks": self.file_checks,
                "attachment_file_checks": self.attachment_checks,
                "native_review_checks": self.native_checks,
                "reference_quotation_checks": self.quotation_checks,
                "locator_counts": dict(Counter(self.locator_checks.values())),
                "trace_coverage": self.coverage,
                "verified_scope": [
                    "JSON schema and supported date formats", "Domain-scoped IDs and declared references",
                    "Declared calculations, date order and weekday", "Local supplied file SHA-256 and supported locator existence",
                    "Documented review and artifact-hash links",
                ],
                "not_verified": [
                    "Business fact truth, actual test execution, authentic signatures or actual approvals",
                    "Complete semantic requirement satisfaction or undocumented transformations",
                    "Native visual quality itself; only supplied native-review evidence is checked",
                    "Remote resources or unsupported locator syntax",
                ],
                "calculation_policy": "Explicit per-field aggregation_rules take precedence over a recognized aggregation_method; missing numeric data is not inferred as zero. KPI formulas and test comparisons are checked only when explicitly declared.",
            },
        }


def validate_project(data: Any, *, verify_files: bool = True, base_dir: Path | str | None = None) -> dict:
    """Validate a project without altering it or treating recorded claims as truth.

    Relative source/attachment paths are resolved against ``base_dir`` (cwd by
    default). Draft omissions are separate from submission gates. Synthetic and
    unverified data never become submission-ready just because the schema passes.
    """
    check = _Check(data, verify_files, Path(base_dir or Path.cwd()).resolve())
    check.numbers()
    check.schema()
    if not isinstance(data, dict) or any(e["code"] in ("SCHEMA_INVALID", "SCHEMA_UNAVAILABLE", "SCHEMA_FORMAT_UNAVAILABLE") for e in check.errors):
        check.add("blocker", "PROJECT_DATA_INVALID", "/", "프로젝트 데이터가 스키마에 맞지 않아 의미 검증과 제출 판단을 진행하지 않았습니다.")
        return check.result()
    check.identities()
    check.provenance()
    check.reference_quotations()
    check.references()
    check.dates()
    check.organizations()
    check.requirements()
    check.database()
    check.tests()
    check.kpis()
    check.operations()
    check.deployment()
    check.changes()
    check.original_issues()
    check.field_states()
    for i, program in check.items("programs"):
        check.definition(program, f"/programs/{i}", "id")
    check.submission()
    return check.result()
