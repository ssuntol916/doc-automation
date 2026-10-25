"""Readable, lossless value descriptions for document prose.

The words here describe supplied values. They never infer an approval, a
missing value's cause, or a relationship not present in the input.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
from typing import Any


LABELS = {
    "id": "식별자", "name": "명칭", "status": "확인 상태", "notes": "비고",
    "source_refs": "출처", "source_id": "출처 식별자", "locator": "근거 위치",
    "source_kind": "연결 시작 종류", "target_kind": "연결 대상 종류",
    "target_id": "연결 대상 식별자", "relation": "관계", "rationale": "연결 사유",
    "content_review_status": "내용 검토 상태", "field_states": "필드별 확인 상태",
    "reason": "사유", "review_status": "검토 상태", "reviewer": "검토자",
    "reviewed_at": "검토일", "review_type": "검토 종류", "outcome": "검토 결과",
    "executor": "수행자 세부",
    "data_type": "형식", "required": "필수 여부", "default_value": "기본값",
    "validation": "검증 조건", "action": "동작", "role": "역할", "permission": "권한",
    "applied": "적용 여부", "algorithm": "알고리즘", "length": "길이",
    "precision": "정밀도", "scale": "소수 자릿수", "key": "키 구분",
    "nullable": "NULL 허용", "foreign_table_id": "참조 테이블",
    "foreign_column_ids": "참조 컬럼", "expected_id": "기준 식별자",
    "expected_name": "기준 명칭", "definition_source_refs": "정의 근거",
    "implementation_scope": "도입 범위", "configuration": "구성",
    "query_conditions": "조회 조건", "registration_conditions": "등록 조건",
    "calculation_rules": "계산 규칙", "version": "버전", "audience": "대상 사용자",
    "content": "설명 내용", "online_url": "온라인 주소", "lifecycle": "사용 단계",
    "description": "설명", "original_id": "원문 식별자", "original_classification": "원문 분류",
    "review_ids": "검토 연결", "evidence_ids": "증거 연결", "owner": "담당자 세부",
    "meeting_ids": "회의 연결", "requirement_ids": "요구사항 연결", "feature_ids": "기능 연결",
    "screen_ids": "화면 연결", "program_ids": "프로그램 연결", "table_ids": "테이블 연결",
    "related_program_ids": "관련 프로그램", "related_table_ids": "관련 테이블",
    "environment": "시험 환경", "preconditions": "선행 조건", "steps": "처리 순서",
    "process_name": "업무 프로세스명", "case_number": "케이스 번호", "stage": "시험 단계", "group_id": "시험 그룹 ID",
    "approval_evidence_ids": "승인 근거 연결", "verification_evidence_ids": "검증 근거 연결",
    "requester": "요청자 세부", "contact": "담당자 세부", "special_notes": "특이사항",
    "period_start": "기간 시작", "period_end": "기간 종료", "report_date": "보고일",
    "current_steps": "현행 업무 단계", "target_steps": "개선 업무 단계", "issues": "문제점",
    "expected_effects": "기대효과", "data_collection_mode": "데이터 수집 방식",
    "automation_level": "자동화 수준", "real_time_control": "실시간 제어 여부",
    "as_is_description": "현행 설명", "to_be_description": "목표 계획", "network_method": "통신 방식",
    "migration_counts": "초기데이터 전환 수량", "fulfillment_status": "이행 상태",
    "deliverable_ids": "결과물 연결", "reviewer": "검토자", "author": "작성자 세부",
    "title": "자료명", "kind": "분류", "path": "제공 경로", "sha256": "SHA-256",
    "verification_status": "자료 검증 상태", "category": "업무 구분", "system_name": "시스템명",
    "change_type": "변경 구분", "screen_kind": "화면 구분", "topic": "설명 주제",
    "organization_role": "기업 역할", "organization_name": "기업명", "person": "인원 세부",
    "work_description": "담당 업무", "phase": "단계", "person_name": "담당자명",
    "plan": "계획", "actual": "제공 실제 값", "next_plan": "다음 계획",
    "planned_progress": "계획 진도", "actual_progress": "입력 실적 진도",
    "number": "관리 번호", "handling_status": "처리 상태", "weekday": "요일",
    "period_kind": "기간 구분", "deployment_item_ids": "설치 항목 연결",
    "support_records": "지원 기록", "affected_refs": "영향 대상", "categories": "변경 분류",
    "measurement_period_start": "측정기간 시작", "measurement_period_end": "측정기간 종료",
    "measurements": "측정 입력", "actual_precision": "실적 소수 자릿수", "direction": "개선 방향",
    "actual_source_refs": "실적 출처", "baseline_source_refs": "기준값 출처", "target_source_refs": "목표값 출처",
    "as_is_attachment_ids": "현행 흐름도 연결", "to_be_attachment_ids": "개선 흐름도 연결",
    "as_is_diagram_ids": "현행 구성도 연결", "to_be_diagram_ids": "목표 구성도 연결",
    "module_flow_attachment_ids": "모듈 흐름도 연결", "attachment_ids": "설명 그림 연결",
    "caption": "제공 캡션 원문", "purpose": "제공 용도", "media_type": "파일 형식",
    "original_filename": "원본 파일명", "details": "세부 요건", "constraints": "제약·전제",
    "menu_levels": "메뉴 단계",
    "major_category": "대분류", "middle_category": "중분류", "minor_category": "소분류",
    "field_definitions": "입력 필드 명세", "buttons": "버튼 명세", "permissions": "역할별 권한",
    "before_attachment_ids": "기존 화면 그림 연결", "after_attachment_ids": "변경 화면 그림 연결",
    "standard_attachment_ids": "표준 화면 그림 연결",
    "before": "변경 전 입력", "after": "변경 후 입력", "approval_status": "승인 입력 상태",
    "artifact_id": "대상 결과물", "artifact_sha256": "대상 결과물 SHA-256", "comments": "검토 의견",
    "business_area": "업무 영역", "screen_kind": "화면 구분",
}

DOMAIN_LABELS = {
    "requirements": "요구사항", "features": "기능", "screens": "화면",
    "programs": "프로그램", "database_tables": "DB 테이블", "test_cases": "시험",
    "defects": "결함", "changes": "변경", "reviews": "검토",
    "deployment_items": "설치 항목", "operation_periods": "운영 기간", "progress_reports": "진도 보고",
    "meetings": "회의", "kpis": "성과지표", "trace_links": "추적 연결", "attachments": "첨부 자료",
}

CODE_LABELS = {
    "synthetic": "합성 자료", "provided": "제공됨", "unverified": "미확인",
    "verified": "검증됨(입력)", "planned": "계획", "pending": "검토 대기",
    "not_reviewed": "미검토", "needs_changes": "수정 필요", "approved": "승인됨(입력)",
    "unrequested": "미요청", "rejected": "반려됨(입력)", "functional": "기능", "nonfunctional": "비기능",
    "allowed": "허용", "denied": "불허", "conditional": "조건부 허용",
    "implements": "구현 관계", "depends_on": "의존 관계", "related_to": "관련 관계",
    "verifies": "검증 관계", "satisfies": "충족 관계", "not_run": "미수행",
    "passed": "통과(입력)", "failed": "실패(입력)", "blocked": "진행 불가(입력)",
    "tests": "시험 연결", "not_started": "미착수(입력)",
    "implemented_by": "구현 대상 관계", "tested_by": "시험 대상 관계", "verified_by": "검증 대상 관계",
    "changes": "변경 관계", "supports": "지원 관계", "documents": "문서화 관계", "produces": "산출 관계",
    "derived_from": "파생 관계", "in_progress": "진행 중(입력)", "completed": "완료(입력)",
    "not_applicable": "적용 대상 아님(입력)",
    "existing": "기존", "new": "추가", "modified": "변경", "deleted": "삭제",
    "screen": "화면", "report": "보고서", "user": "사용자", "administrator": "관리자",
    "unit": "단위시험", "integration": "통합시험", "acceptance": "사용자시험",
    "pilot": "시범운영", "training": "교육",
    "business_facts": "사업 사실 검토", "approval": "승인 검토", "native_render": "한컴 출력 검토",
    "technical": "기술 검토", "compliance": "요건 검토",
}


class SourceNotes:
    """Per-document correspondence keys; exact reference objects stay intact."""

    def __init__(self):
        self.records: list[dict[str, Any]] = []
        self.code_mappings: dict[str, str] = {}
        self._keys: dict[str, str] = {}

    def reference(self, references):
        if not references:
            return "출처 미제공(빈 목록; 부재 여부 미판정)"
        keys = []
        for reference in references:
            identity = json.dumps(reference, ensure_ascii=False, sort_keys=True)
            if identity not in self._keys:
                key = f"S{len(self.records) + 1}"
                self._keys[identity] = key
                self.records.append({"key": key, "source_ref": dict(reference)})
            keys.append(f"[{self._keys[identity]}]")
        return ", ".join(keys)


_SOURCE_NOTES: ContextVar[SourceNotes | None] = ContextVar("document_source_notes", default=None)


@contextmanager
def source_note_scope(notes: SourceNotes | None):
    token = _SOURCE_NOTES.set(notes)
    try:
        yield
    finally:
        _SOURCE_NOTES.reset(token)


def source_reference_text(references):
    notes = _SOURCE_NOTES.get()
    return notes.reference(references) if notes is not None else None


def editorial_context_active():
    return _SOURCE_NOTES.get() is not None


def code_label(value):
    """Localize supplied enums only inside the explicit editorial context."""
    notes = _SOURCE_NOTES.get()
    if notes is not None and isinstance(value, str) and value in CODE_LABELS:
        notes.code_mappings[value] = CODE_LABELS[value]
        return CODE_LABELS[value]
    return readable_value(value)


def typed_value(value: Any) -> str:
    """Distinguish null, empty text/containers, booleans and numeric/text values."""
    if value is None:
        return "미확인(null)"
    if isinstance(value, bool):
        return f"{'예' if value else '아니오'} ({str(value).lower()}·논리값)"
    if isinstance(value, str):
        return "빈 문자열(문자열)" if value == "" else f"{value} (문자열)"
    if isinstance(value, int):
        return f"{value} (정수)"
    if isinstance(value, float):
        return f"{value} (수치)"
    if isinstance(value, list):
        return "빈 목록(0개; 부재 여부 미판정)" if not value else "목록\n" + "\n".join(
            f"{index}. {typed_value(item)}" for index, item in enumerate(value, 1))
    if isinstance(value, dict):
        # A JSON literal's keys are data, not domain labels or provenance.
        # In particular, literal status/source_refs must never enter enum or
        # source-note interpretation, and nested scalar types stay distinct.
        return "빈 객체(0개 항목)" if not value else "객체\n" + "\n".join(
            f"항목 {index}. 키: {typed_value(key)}; 값: {typed_value(item)}"
            for index, (key, item) in enumerate(value.items(), 1))
    raise TypeError(f"Unsupported document value type: {type(value).__name__}")


def readable_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        if not value:
            return typed_value(value)
        if isinstance(value, dict):
            return describe_fields(value)
        return "\n".join(f"{index}. {readable_value(item)}" for index, item in enumerate(value, 1))
    if value is None or value == "":
        return typed_value(value)
    if isinstance(value, bool):
        return typed_value(value)
    return str(value)


def describe_fields(value: dict[str, Any], *, typed: bool = False,
                    field_labels: dict[str, str] | None = None,
                    code_fields=()) -> str:
    """Describe supplied fields, with optional labels for this record only.

    Domain overrides do not propagate into nested records or literal JSON.
    Callers must explicitly select any additional enum fields for their domain.
    """
    def describe(item):
        if isinstance(item, dict) and item:
            return describe_fields(item, typed=typed)
        if isinstance(item, list) and item:
            return "\n".join(f"{index}. {describe(child)}" for index, child in enumerate(item, 1))
        return typed_value(item) if typed else readable_value(item)

    result = []
    for key, item in value.items():
        references = source_reference_text(item) if key.endswith("source_refs") and isinstance(item, list) else None
        code = code_label(item) if key in {"status", "verification_status", "review_status", "review_type", "outcome", "content_review_status", "kind", "original_classification", "relation", "permission", "change_type", "fulfillment_status", "screen_kind", "topic", "audience", "lifecycle", "stage", "approval_status"} or key in code_fields else None
        literal = typed_value(item) if key in {"default_value", "data", "expected", "actual"} and isinstance(item, (dict, list)) else None
        links = "연결 입력 0개(빈 목록)" if key.endswith("_ids") and isinstance(item, list) and not item else None
        label = (field_labels or {}).get(key, LABELS.get(key, key))
        result.append(f"{label}: {literal if literal is not None else references if references is not None else code if code is not None else links if links is not None else describe(item)}")
    return "\n".join(result)


def trace_paragraphs(trace: dict[str, Any]) -> list[str]:
    """One directed record, with every supplied field retained and no raw JSON."""
    start = DOMAIN_LABELS.get(trace.get("source_kind"), trace.get("source_kind", "미확인"))
    end = DOMAIN_LABELS.get(trace.get("target_kind"), trace.get("target_kind", "미확인"))
    values = [f"명시 연결 [{trace.get('id', '미확인')}] {readable_value(trace.get('name'))}",
              f"연결 방향: {start} {readable_value(trace.get('source_id'))} → {end} {readable_value(trace.get('target_id'))}"]
    consumed = {"id", "name", "source_kind", "source_id", "target_kind", "target_id"}
    values.extend(describe_fields({key: value}) for key, value in trace.items() if key not in consumed)
    return values
