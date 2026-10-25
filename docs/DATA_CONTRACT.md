# 3단계 공통 데이터 계약

현재 코퍼스에 근거한 첫 버전이며 다른 사업의 공고·승인 요건을 일반화하지 않는다.

- 최상위: `schema_version="1.0"`, `dataset_kind`(project/reference_extraction/synthetic), `project`, `sources`, 각 도메인의 배열.
- 도메인 배열: `requirements`, `features`, `screens`, `programs`, `database_tables`, `test_cases`, `defects`, `deployment_items`, `operation_periods`, `progress_reports`, `meetings`, `changes`, `kpis`, `trace_links`, `attachments`, `reviews`.
- 각 의미 개체에는 `id`, `name`, `status`, `source_refs`를 둔다. status는 verified/provided/unverified/synthetic/not_applicable. 실제 입력에서 확인되지 않은 승인·서명·수행을 verified로 만들지 않는다.
- source_refs는 `{source_id, locator}` 배열. sources는 id/title/kind/path/sha256/verification_status를 가진다. 로컬 파일일 때 해시 대조를 할 수 있다. 인용 위치는 XML 표/셀·문단 또는 제공 사실 파일의 필드로 표현한다.
- requirements: system_name, business_area, kind(functional/nonfunctional), change_type(existing/new/modified/deleted), description, details(문자열배열), constraints(문자열배열), owner(name과review_status), notes. 원문 구분 어휘가 있으면 original_classification에 보존한다.
- project: id/name/program_name/program_year/template_version/customer/supplier/start_date/end_date/status. 기업의 역할을 바꾸지 않는다. 날짜는 ISO8601 날짜 문자열이며 사실이 없으면 null을 허용한다.
- trace_links는 source_kind/source_id/target_kind/target_id/relation/rationale/status/source_refs로 구성한다. 파일코드와 의미 역할을 혼용하지 않는다. ID 존재 검사와 의미·충족 검토 상태를 분리한다.
- database_tables는 물리 ID와 설명명, columns의 id/name/type/length/nullable/key/default_value/encryption을 구분한다. 동일 테이블ID/컬럼ID 중복을 검증한다.
- test_cases는 stage(unit/integration/acceptance), scenario/data/expected/actual/result(planned/passed/failed/blocked/not_run)/execution_date/executor/evidence_ids를 구분한다. 결과·서명·검수 자료가 없으면 수행완료로 생성하지 않는다.
- kpis는 단위, 개선방향, 산식 및 numerator/denominator, baseline/target/actual과 근거를 분리한다. 운영 집계는 원시 기간별 값과 보고 합계를 함께 두어 재계산한다.
- extraction_issues는 원본 관찰 오류/미확인을 보존한다. 데이터 스키마 정상과 사업 사실의 정상은 별개다.

`synthetic` 데이터는 기계적 생성과 출력 검증을 위한 예시다. 문서에도 검증용·제출용 아님을 표시한다. submission_ready는 단순히 스키마 통과만으로 true가 될 수 없다. 검증된 실제 출처, 승인·수행·첨부 및 네이티브 출력 검토는 각기 별도 근거가 필요하다.

세부 필드의 최종 기준은 `schemas/project.schema.json`이다. 스키마를 담당한 에이전트는 의미검증·예시 담당자에게 변경을 공유한다.

과거 참고 화면·설치 사진은 [전용 인용 계약](REFERENCE_QUOTATIONS.md)의 `reference_result_quotations`/`reference_installation_quotations`로만 제공한다. 초기 지원6개는 source-specific이며 evidence/flow와 겸용하지 않는다. 실제 결과·설치 사실과 필수 증적 의무는 그대로 남는다.
