# 사업 데이터 의미 검증

`doc_automation.business.validate_project(data, *, verify_files=True, base_dir=None)`는 입력을 변경하지 않고 `errors`, `warnings`, `submission_blockers`, `draft_ready`, `submission_ready`, `summary`를 반환한다. 상대 출처·첨부 경로는 `base_dir` 기준이고 생략하면 현재 작업 폴더다. CLI는 입력 JSON의 부모 폴더를 전달한다. 스키마는 모듈 위치에 따른 저장소 경로 또는 패키지 리소스에서 읽는다.

## 초안과 제출 판단

- `errors`: 스키마/형식 오류, 비유한 수치, 같은 도메인 ID 중복, 없는 참조/인용 위치, 역전 날짜/잘못된 요일, 명시한 비교·계산·기준 명세와의 모순, 수행·승인 완료 주장의 증거 누락, 파일 해시 불일치.
- `warnings`: 같은 요구사항명, 출처 기준 없는 ID/이름 형태 관찰, 목표 미달, 계획과 실제 수량 차이, 단계 간 증거 재사용, 계산에 필요한 원시값 누락, 미해결 원본 관찰. 목표 미달은 산술 오류로 바꾸지 않는다.
- `submission_blockers`: 미확정 범위/사실/출처/첨부, 선택 산출물에 필요한 자료·시험·검토의 부족. 무해한 미입력 초안은 이 계층에 둔다. 스키마에 맞지 않는 입력에는 구조 오류를 보고하고 후속 의미 검증을 생략한다.

합성/참고 자료는 제출 가능 상태가 될 수 없다. 실제 사업도 `verified` 표지만으로 통과하지 않으며 중첩 기업·사람·컬럼·원시행·필드 상태를 확인한다. 적용 없음에는 이유와 확인된 근거가 필요하다. `field_states`의 JSON Pointer는 해당 개체 안의 실제 필드를 가리켜야 한다.

요구사항의 전체 생애주기 ID 커버리지는 항상 보고하되 제출 게이트는 `summary.trace_coverage.submission_scope_missing`을 사용한다. 예를 들어 AD2만 작성하는 초안에 단위·통합·사용자시험 완료를 강제하지 않는다. PM4는 전체 연결 및 기록된 의미 검토를 요구한다. 원본 그룹 ID와 개별 시험 ID를 구별하며 시험 단계·그룹 안의 케이스 번호 중복을 검사한다.

## 계산·출처의 경계

명시한 시험 비교만 `actual operator expected` 방향으로 검사하고 `contains`는 actual 안의 expected를 뜻한다. 숫자 0과 false를 미입력으로 취급하지 않는다. 자유 JSON인 시험 data/expected/actual, 컬럼 default_value, 서식 value, 원본 issue 값 내부의 키를 도메인 참조나 일정으로 해석하지 않는다. 그 안의 NaN/Infinity는 오류로 처리한다.

KPI ratio/percent/difference 산식은 각각 분자÷분모, 분자÷분모×100, 분자−분모다. 운영 `aggregation_rules`가 공통 `aggregation_method`보다 우선하며 sum/average/min/max/last만 재계산한다. last는 날짜순이고 같은 날짜의 복수행은 순서를 추정하지 않는다. 누락값을 0으로 채우거나 사용자 수 합계를 고유 사용자 수로 바꾸지 않는다.

DB ID/논리명·프로그램 설명의 불일치는 `expected_*`와 명시한 `definition_source_refs`가 있을 때 기준 명세와 대조한다. 언어 형태만으로 오류를 확정하지 않는다. TD5에는 각 테이블의 `physical_export_attachment_ids`로 별도 Excel을 연결한다. Excel ZIP/구형 컨테이너 표식 확인은 실제 테이블·컬럼 내용의 의미 정합성 검토를 대신하지 않는다.

출처는 제공된 로컬 파일만 읽는다. SHA-256은 바이트 동일성을 뜻한다. JSON Pointer와 `Contents/sectionN.xml#P번호`, `#T번호/R논리행C논리열`만 존재를 검사한다. P/T는 문서순 1기반, R/C는 HWPX cellAddr의 0기반이다. 지원하지 않는 인용 구문은 추측하지 않는다. 출처 위치가 존재한다는 사실은 해당 값이 올바르게 추출됐다는 증명이 아니다.

## 현재 산출물의 검토 연결

이 프로젝트의 품질 게이트이며 모든 기관의 법정 승인 요건을 뜻하지 않는다. 요청한 각 산출물은 `attachments.document_role`에 canonical 코드(SF-AD2 등)를 기록한다. 요청 서식은 해당 `form_records.attachment_ids`로 최종본을 연결한다. 각 파일의 현재 해시에 연결된 approval/native_render 검토를 별도로 요구하므로 한 파일의 검토가 미검토 파일 전체에 승계되지 않는다.

native_render의 `evidence_ids`는 [quality-review.schema.json](../schemas/quality-review.schema.json)에 맞는 첨부 JSON을 가리켜야 한다. 다음 기록과 바이트를 대조한다.

1. 현재 HWPX와 보고서 artifact/native source SHA 일치 및 HWPX 기본 패키지 표식.
2. 보고서의 입력 데이터·양식 SHA가 확인된 로컬 출처에 존재. 양식 출처 kind는 template이다.
3. 한글 애플리케이션·버전·빌드, Poppler 렌더 방식과 해상도 기록.
4. 실제 PDF SHA와 읽을 수 있는 PDF의 페이지 수, 각 렌더 이미지 SHA와 이미지 읽기.
5. 누락·중복 없는 전체 페이지의 passed 기록과 전체 checks/status 통과.

품질보고서 안 상대 경로는 그 보고서 JSON의 부모 폴더 기준이다. 입력 데이터 해시는 제공된 입력 스냅샷과 연결하며 현재 검증 API 인자의 JSON 직렬화 바이트와 자동 동일시하지 않는다.

이 검사는 사람이 기록한 사업 사실·실제 수행·진짜 서명·실제 승인·한글 실행·시각 판단의 진위를 입증하지 않는다. 의미 전체 충족도 자동 판정하지 않는다. `submission_ready=true`는 이 모델에 기록된 품질 게이트의 형식·연결 요건이 충족됐다는 뜻이며 제출 권한을 대신하지 않는다. 테스트의 가상 native fixture는 이 연결을 재현할 뿐 실제 한글 수행 사례가 아니다.

## 재현

`.venv/bin/python -m pytest tests/test_business.py -q`로 초안/제출 분리, 현재 코퍼스 오류 유형, 출처 해시·인용, 계산, 범위, native 증거 경계를 검사한다. 전체 검사는 `.venv/bin/python -m pytest -q`다. 대표 예시 3종은 데이터 구조 오류가 0이고 제출 가능 상태는 모두 false여야 한다.
