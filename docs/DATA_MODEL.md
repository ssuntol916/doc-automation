# 공통 사업 사실 데이터 모델

이 모델은 로컬에서 분석한 개발산출물 **19종**과 관련 서식 **34종**을 위한 사실 입력 계약이다. 기준은 [project.schema.json](../schemas/project.schema.json)의 JSON Schema Draft 2020-12이며 `schema_version`은 `1.0`이다. 현재 공고·법령·기관 승인 요건을 별도로 확정한 모델은 아니다. 서식의 원문 지침, 참고문서에서 관찰한 작성 방식, 실제 사업 사실, 생성기의 표시 정책을 서로 구분한다.

## 1. 데이터셋과 생성 범위

루트 필수 키는 `schema_version`, `dataset_kind`, `project`, `sources`, 아래 16개 도메인 배열, `extraction_issues`, `submission_ready`다. 각 배열은 비어 있을 수 있다. 선택 키는 `synthetic_notice`, `form_records`다. 스키마가 기본값을 자동 입력하지 않으므로 `submission_ready`도 명시한다.

| `dataset_kind` | 용도 | 제출 상태 |
|---|---|---|
| `project` | 실제 사업에서 제공·확인된 사실과 미확인 자료 | 스키마 통과만으로 제출 가능하지 않음 |
| `reference_extraction` | 전문가 참고문서에서 관찰값과 원문 오류를 추출 | `submission_ready=false` 필수 |
| `synthetic` | 생성·검증용 가상 자료 | `submission_ready=false`, `synthetic_notice="검증용 합성 자료(제출용 아님)"` 필수 |

`project.requested_deliverables`는 **필수 키**이며 canonical 양식코드의 중복 없는 배열 또는 `null`이다. 예를 들어 `["SF-AD2","SF-AD3","SF-TD3"]`는 이번 생성·제출 검토의 범위를 뜻한다. 허용된 19종은 아래 coverage 표와 같다. `null`과 `[]`는 대상 미확정이며 전체 19종을 승인한 것으로 해석하지 않는다. 관련 34서식의 대상은 선택 키 `project.requested_forms`에 `"1"`, `"1-1"` 등의 문자열로 별도 지정한다.

양식코드, 문서 역할, 원문 개체 ID를 나눈다. 예를 들어 현재 양식 `SF-PM4`의 역할은 요구사항추적표다. 참고자료의 `SF-PM7`이 같은 역할을 맡더라도 canonical 범위에 `SF-PM7`로 기록하지 않는다. 참고자료 파일코드는 `sources.document_code`, 의미 역할은 `sources.document_role`에 원문 근거와 함께 보관한다. 참고의 문서별 역할 대응은 [mapping.json](../resources/stage2/mapping.json)을 따른다. 한편 시험 개체의 원문 `MES-CD2-001`은 파일코드 `SF-CD1`과 다른 별개 식별자이며 자동으로 고치지 않는다.

## 2. 사실 상태, 미확인 값, 출처

공통 의미 개체는 `id`, `name`, `status`, `source_refs`를 갖는다. `id`는 비어 있지 않은 문자열이며 `name`은 미상일 때 `null`이다. 요구사항·화면 등 도메인 개체뿐 아니라 DB 컬럼, 프로젝트 내부 공정·시스템·일정·인력·매뉴얼·지원 항목에도 이 계약이 적용된다. 연락처 등 작은 값 객체는 각각의 필수 키를 따른다.

| 상태 | 의미 |
|---|---|
| `provided` | 해당 출처에서 제공받음. 사실 확인·승인 완료를 뜻하지 않음 |
| `unverified` | 해석, 사실성 또는 적용 여부를 아직 확인하지 못함 |
| `verified` | 명시한 근거를 대조해 확인한 개체. 최소 한 개의 `source_refs` 필요 |
| `synthetic` | 시험을 위해 만든 값. 실제 사업·실행 결과로 승격하지 않음 |
| `not_applicable` | 적용되지 않음을 판단한 개체. 판단 이유와 근거를 남김 |

값의 `null`은 자료 미제공 또는 미확인이다. `0`은 관측한 영, `false`는 확인한 부정값이다. `[]`는 현재 보유한 항목이 없음을 나타내며 실제 기능·결함이 없다는 확인으로 취급하지 않는다. 적용 없음은 `not_applicable`과 근거로 표현한다. 빈 문자열로 미확인을 숨기지 않는다. 숫자를 적을 수 없는 셀도 `"미확인"` 문자열 대신 `null`과 상태를 쓴다.

개체 안 일부 필드의 상태가 다르면 `field_states`에 **해당 개체 기준 JSON Pointer**를 키로 기록한다. 예: `"/actual": {"status":"unverified","reason":"시험 미수행","source_refs":[]}`. 키는 `/`로 시작해야 하며 참조 필드가 실제 존재하는지는 의미검증에서 확인한다. 필수 키가 있다는 이유로 실제 결과나 승인자를 채우지 않는다. 날짜·담당자·실적·서명이 없는 초안은 각각 `null`/빈 배열과 미확인 상태로 유효하다.

`source_refs`는 `{source_id, locator}` 배열이며 `source_id`는 `sources.id`를 가리킨다. `locator`는 원본 ZIP/XML 경로와 표·셀·문단 또는 사실 입력 파일의 JSON Pointer처럼 재현 가능한 위치다. 원본 관찰값은 `original_id`, `original_classification`에 그대로 보존하고, 충돌·추정 수정안은 `extraction_issues`에 별도로 기록한다. 정규화 값과 원문을 묵시적으로 바꾸지 않는다.

`sources`의 필수 키는 `id/title/kind/path/sha256/verification_status`다. `kind`는 `template`, `reference_document`, `project_document`, `meeting_record`, `interview`, `system_export`, `database_export`, `image`, `manual_input`, `synthetic`, `other` 중 하나다. 선택 키 `document_role/document_code/document_version/retrieved_at/notes`로 식별을 보강한다. 로컬 파일의 SHA-256은 소문자 64자리이며 자료가 없으면 경로·해시는 `null`이다. 파일 바이트가 일치한다는 `verification_status=verified`와 그 안의 사업 사실을 확인했다는 개체 `status=verified`는 독립적이다.

## 3. 프로젝트와 사업개요

`project`의 필수 키는 공통 네 키와 `requested_deliverables/program_name/program_year/template_version/customer/supplier/start_date/end_date`다. `program_year`는 사업 연도이며 원본 파일명·현재 연도에서 추정하지 않는다. 날짜는 ISO `YYYY-MM-DD` 또는 `null`이다. `customer`는 도입기업, `supplier`는 공급기업이고 서로 바꾸지 않는다.

기업 객체는 `name/status/source_refs`가 필수다. 선택 항목은 사업자번호, 대표자, 주소, 연락처, 이메일, 업종, 주생산품, 인원, 연혁, 연도별 매출·부채·자본금 등이다. 금액의 `currency/unit`을 함께 보존한다. 이력/재무자료를 모르는 기업은 기업명만 제공하거나 기업 객체 전체를 `null`로 둘 수 있다.

| 선택 묶음 | 구체 입력과 반복 단위 |
|---|---|
| `task_number`, `implementation_scope`, `business_profile` | 과제번호, 구축 범위 목록, 기업·사업 설명 |
| `current_smart_factory_level`, `target_smart_factory_level` | 현·목표 수준의 원문 값. 확인 증빙은 출처·첨부로 연결 |
| `business_processes[]` | 공정별 `description/current_steps/target_steps/issues/expected_effects`; AS-IS/TO-BE 그림, 요구사항, 대상 여부, 수집방식, 자동화 수준, 실시간 제어, 연계 공정 ID |
| `systems[]` | 시스템별 설명·현재/목표 구성·연결·통신방법·구성도 및 lifecycle |
| `schedule_items[]` | 단계별 계획 시작/종료, 실제 시작/종료, 담당자, 계획/실제 진도 |
| `budget_items[]` | 항목별 계획·승인·집행액, 통화·단위, 출자형태·부담주체·산출근거. 양식별 A/B/C는 `original_cost_code`에 보존 |
| `staff_members[]` | 기업 역할, 참여 역할·내용·기간·참여율·인적 정보 |
| `manual_sections[]` | 사용자/관리자별 주제·내용, 화면·첨부·온라인 URL·버전 |
| `support_activities[]` | 지원 유형, 계획·기간·담당 연락처·실제 결과·증거 |

선택 묶음을 아예 제공하지 않은 것과 적용 없음을 구분한다. `expected_effects`는 전망이며 이를 실측 KPI로 바꾸지 않는다. 다이어그램은 `attachments`로 보존하고 실제 의미는 공정·시스템의 설명과 관계에서 확인한다. 도식 이미지가 존재하는 것만으로 공정 분석 완료로 판정하지 않는다.

## 4. 16개 도메인의 입력 계약

아래 목록의 필수 값도 대부분 `null`을 허용한다. **키 필수**와 **사업 사실 확보 완료**는 다른 조건이다. 선택 키와 각 enum·수치 경계의 완전한 기준은 스키마의 `$defs`다.

| 도메인 | 공통 네 키 외의 필수 키 | 주요 선택 입력·의미 |
|---|---|---|
| `requirements` | `system_name,business_area,kind,change_type,description,details,constraints,owner` | `kind`: functional/nonfunctional. `change_type`: existing/new/modified/deleted 또는 null. 원문의 기능적/비기능적 분류와 신규/변경은 별개. `owner`는 이름·확인 상태가 있는 사람 또는 null. `fulfillment_status`, 완료 첨부 `deliverable_ids`, 검토 `review_ids` |
| `features` | `system_name,major_category,middle_category,minor_category,change_type,description,before,after,requirement_ids` | 기준 기능과 사업별 전후 요건, 협의 회의·증거. 분류 그룹의 병합은 출력 정책이며 데이터는 기능별 한 건 |
| `screens` | `system_name,path,description,change_type,steps,checks,requirement_ids,feature_ids,program_ids` | 화면/보고서/팝업, 4단계 `menu_levels`, 표준·기존·변경 캡처, 필드별 형식/필수/초깃값/검증, 버튼 동작, 역할별 허용 여부, 검토 ID |
| `programs` | `system_name,description,change_type,functions,requirement_ids,screen_ids,table_ids` | 모듈 흐름도, 조회/등록 조건, 출력 항목, 인터페이스, 계산 규칙, 기준 명세의 예상 이름·설명과 출처 |
| `database_tables` | `description,columns` | 테이블별 한 건. 물리 ID=`id`, 논리명=`name`. 기준 명세 ID/이름·출처, 실제 물리 DB 내보내기 첨부, 변경구분 |
| `test_cases` | `stage,scenario,data,expected,actual,result,execution_date,executor,evidence_ids` | `stage`: unit/integration/acceptance. 공정별 `group_id`와 그룹 내 `case_number`, 환경·흐름도·요구/화면/프로그램 연결, 명시적 비교 규칙 |
| `defects` | `test_case_id,description,cause,detected_date,resolution,resolved_date,resolution_status,evidence_ids` | 결함별 원인·조치·조치 완료일·담당자·재확인 증거. 운영장애이면 시험 ID는 null 허용 |
| `deployment_items` | `category,planned_specification,actual_specification,planned_quantity,installed_quantity,unit,installation_date,installation_status,verification_method,verification_result,evidence_ids` | HW/SW/NW/cloud/initial_data별 계획·설치·검증, 제조사·모델·일정·라이선스, 유형별 데이터 전환 건수·검사 결과, 프로그램/DB/검토 연결 |
| `operation_periods` | `period_start,period_end,raw_records,reported_totals,aggregation_method` | 일/주/월/시범/집중AS 기간별 사용 원시값·보고 집계·필드별 집계 규칙, 장애·지원 기록·설치 항목·증거 |
| `progress_reports` | `report_kind,period_start,period_end,current_plan_percent,current_actual_percent,cumulative_plan_percent,cumulative_actual_percent,work_items,risks` | 보고일, 작성자, 계산 근거, 구분별 계획·실적·다음 계획, 위험·이슈·조치·검토. 모든 진도는 0~100 또는 null |
| `meetings` | `date,location,organizer,agenda,discussions,decisions,attendees` | 요일·시각·특기사항·증거·검토. 참석자는 이름·기업 역할·사실 상태·출처를 보존하며 실제 서명 검토는 별도 ID |
| `changes` | `categories,request_number,request_date,reason,before,after,impact,approval_status,approval_evidence_ids,meeting_ids` | 범위/일정/인력/요구/장비/비용별 변경, 요청자, 회신번호/일자/내용, 영향 개체, 검토. 요청과 승인은 별개 상태 |
| `kpis` | `unit,direction,formula_kind,formula,numerator,denominator,baseline,target,actual` | 기준·목표·실적 각각의 출처, 실측 기간·반올림 자릿수·기간별 측정값·증거 |
| `trace_links` | `source_kind,source_id,target_kind,target_id,relation,rationale` | 양 끝의 kind는 이 표의 16개 배열명. 실제 내용 검토 `content_review_status`를 존재 검증과 분리 |
| `attachments` | `path,sha256,source_id,purpose,verification_status` | 캡션·원본 이름·매체 형식·문서 역할. `status`는 의미, `verification_status`는 파일 대조 상태 |
| `reviews` | `review_type,outcome,artifact_id,artifact_sha256,reviewer,reviewed_at,evidence_ids` | business_facts/approval/native_render/technical/compliance별 검토. 결과 pending도 유효. 대상 개체·의견·근거. 검토자는 실제 이름 또는 null |

### ID와 참조

도메인 배열 안에서 `id`는 유일해야 한다. DB 컬럼 ID는 **해당 테이블 안에서** 유일하며 서로 다른 테이블의 `id` 컬럼을 중복으로 보지 않는다. 의미검증기가 중복·존재 여부를 검사하고, 스키마는 개체 모양을 검사한다. 원본 중복은 `reference_extraction`에 관찰된 채 남을 수 있으며 이 경우 의미 오류와 `extraction_issues`를 함께 낸다. 자동 재번호로 참고문서를 정상화하지 않는다.

`*_attachment_ids`, `evidence_ids`, `approval_evidence_ids`, `verification_evidence_ids`, `requirements.deliverable_ids`는 `attachments.id`를 가리킨다. 화면 `program_ids`는 `programs.id`, 프로그램 `table_ids`는 `database_tables.id`, 요구/기능/화면/회의/검토/설치 참조도 각각 해당 배열의 ID다. `operation_periods.incident_ids`는 `defects.id`다. `attachments.source_id`와 모든 `source_refs.source_id`는 `sources.id`다. `reviews.artifact_id`는 현재 검토한 파일의 `attachments.id`이며 `artifact_sha256`은 그 파일의 실제 해시와 일치해야 한다. 원문에 있는 ID는 `original_id`에 보존할 수 있다.

`trace_links.relation`은 implements/implemented_by/tests/tested_by/verifies/verified_by/depends_on/changes/supports/documents/produces/derived_from/related_to 중 하나다. 연결된 ID의 존재, 내용이 요구사항을 구현/시험하는지, 실제 수행·승인됐는지를 따로 판단한다. `content_review_status=confirmed`도 근거 없는 자동 판정으로 채우지 않는다. 자연어 의미를 ID·제목 일치만으로 확정하지 않는다.

통합/사용자 시험은 원본 시험 ID 한 건 아래 여러 케이스를 둔다. 데이터는 각 케이스의 독립 `id`로 저장하고 동일한 `group_id`와 서로 다른 `case_number`로 그룹화한다. PM4가 원문의 그룹 시험 ID를 참조할 때 개별 케이스 ID와 혼동하지 않도록 명시적 대응을 남긴다. 시험/요구 ID의 문서 접두어는 양식의 예시 규칙과 별도 확인하고 원본 CD1/CD2, TI4/TI5 충돌을 자동 고치지 않는다.

### DB 컬럼

`columns[]`는 공통 네 키와 `type/length/nullable/key/default_value/encryption`이 필수다. `id`=물리 컬럼명, `name`=사람이 읽는 논리명이다. `type`의 원문을 유지하고 `length`, 선택 `precision/scale`를 분리한다. `nullable=null`은 미확인이고 `false`는 NOT NULL이다. `key`는 none/primary/foreign/primary_foreign 또는 null이다. `default_value`는 JSON 원래 값을 보존하며 `null`만으로 “기본값 없음”과 “미확인”을 구분할 수 없으면 `field_states`로 설명한다.

암호화는 `encryption=null` 또는 `{applied,algorithm,notes,source_refs}`다. 미확인과 암호화 미적용은 다르다. FK 대상과 복합 FK 컬럼은 선택 항목으로 보존한다. 실제 기준사전이 있으면 `expected_id/expected_name/definition_source_refs`로 대조한다. 한글/영문 모양만으로 이름·ID 전치를 오류로 확정하지 않는다. 물리 DB Excel 제출은 `physical_export_attachment_ids`로 별도 보관하며 합성 메타데이터를 구현 DB 증거로 삼지 않는다.

### 미수행 시험과 승인

시험 결과는 planned/passed/failed/blocked/not_run이다. 미수행이면 `actual/execution_date/executor=null`, `evidence_ids=[]`가 유효하다. 수행 결과로 채운 시험은 실제 결과·일자·수행자·증거를 별도로 확인한다. expected/actual/data는 문자열 외에도 숫자·객체·배열을 보존한다. 자연어 예상/실제 결과를 자동 문자열 비교로 합격 처리하지 않는다.

명시적 `comparison`이 있을 때만 `operator`(equal/not_equal/greater_than/greater_or_equal/less_than/less_or_equal/contains)를 적용한다. 수치 equal/not_equal의 허용 오차는 선택 `tolerance`다. 비교 방향은 **actual operator expected**이며 contains는 actual 안에 expected가 포함되는지다. 비교 규칙이 없으면 완결성·참조·일자를 점검하고 의미상 합격 여부는 미판정이다.

변경의 `approval_status`는 unrequested/requested/pending/approved/rejected/not_required/unverified 또는 null이다. 승인되지 않은 변경도 데이터로 보관한다. `reviews.outcome=pending`, `reviewer/reviewed_at/artifact_id/artifact_sha256=null`인 검토 대기 행도 유효하다. 필요한 실제 서명·날인·기관 승인은 첨부와 검토 기록으로 확보하며, 데이터 입력이나 생성으로 대신 만들지 않는다.

### 운영·진도·KPI의 계산

운영 원시행은 `date/status/source_refs`와 사용자수·이용분·장애수·로그인수·등록수·트랜잭션수 중 제공된 값으로 구성한다. 횟수/인원은 음이 아닌 정수, 이용분은 음이 아닌 숫자다. `reported_totals`는 같은 6개 수치와 `average_user_count/average_usage_minutes`를 지원한다. 일별 사용자수의 합계를 기간별 고유 사용자수로 재해석하지 않는다.

`aggregation_method`는 원문의 집계 설명이다. 선택 `aggregation_rules`는 보고 합계의 키별 `{source_field,method}` 객체이며 source_field는 원시 6개 수치 키, method는 sum/average/min/max/last다. 명시 규칙이 우선하고, 규칙이 없으면 정확히 식별되는 단일 산식만 계산한다. 원시값 미상은 0으로 대체하지 않는다. average는 제공 기간의 원시행 산술평균이며 임의 가중치·영업일 보정을 하지 않는다. last는 날짜순 마지막 관측값이며 동일 일자 복수 관측의 순서가 불분명하면 보류한다. 기간 전체를 대표하는지와 누락 행 여부는 출처 검토가 필요하다.

진도는 당월 계획/실적과 누적 계획/실적을 별도로 보관한다. 계획/실제 진도를 월별 단순 합산하지 않으며 `calculation_basis`와 계획표를 대조한다. 회의 요일은 ISO 날짜에서 독립 제공한 `weekday`(월=0, 일=6)와 비교하고 원문 요일은 `original_weekday`에 보존한다.

KPI의 `direction`은 increase/decrease/maintain이다. 지표 이름만으로 개선 방향을 추정하지 않는다. `ratio=numerator/denominator`, `percent=100*numerator/denominator`, `difference=numerator-denominator`로 정의한다. direct는 제공된 실측값으로 별도 검증한다. 분모 0은 계산 불가이며 임의 0%로 출력하지 않는다. `actual_precision`은 실적 표기 소수 자릿수(0~12)이며 재계산 허용 오차 기준에 쓴다. `baseline/target/actual`은 서로 다른 시점의 사실이며 출처도 구분한다. 목표 미달은 실제 사업 결과일 수 있으므로 실적을 고쳐 성공으로 만들지 않는다.

## 5. 개발산출물 19종의 입력 coverage

근거의 `s0/s1`은 각각 ZIP 멤버 `Contents/section0.xml/section1.xml`이다. `Tn`은 section 내 문서순 표 1기반, `RrCc`는 논리 0기반 좌표다. AD/TD의 `p[n]`은 section 직접 자식 문단 순서, CD/TI/OS/PM의 `Pn`은 중첩 표를 포함한 모든 문단의 전위 순서다. 두 문단 표기법을 섞지 않는다. 각 근거의 실제 XPath·원문·해시는 [분석·설계 분석](../resources/stage1/analysis-design.md), [시험·관리 분석](../resources/stage1/test-management.md)과 연결 JSON에 있다. 이 표는 **사실 입력 수용 범위**이며 각 문서의 생성·서식·제출 검증 통과를 뜻하지 않는다.

| canonical 역할 | 원본 표·필드/지침 근거 | 대응 데이터와 보류 입력 |
|---|---|---|
| SF-AD1 현행업무분석서 | `s1:T1/R0C0`; `p[9]` 기업소개/연혁/생산품/조직, `p[10]~p[18]` 업무·시스템/HW/SW/NW·메뉴·문제 | `project.customer/business_profile/business_processes/systems`, 조직·공정·구성·메뉴 `attachments`. 현 시스템 없음도 PC/NW 현황을 확인 |
| SF-AD2 요구사항정의서 | `s1:T1` 8×4; R0 시스템/업무, R1 ID/이름, R2~4 설명/요건/제약, R5 유형/담당자, R6 출처, R7 기타 | `requirements` 전체 필수 키와 `notes/original_classification/review_ids`; 실제 담당자·서명은 별도 근거 |
| SF-AD3 기능대비표 | `s0:T2/R0C0~C5` 대/중/소/구분/내용/비고; `p[29]~p[36]` 기준기능·전후요건·협의 | `features`, `requirement_ids/meeting_ids/evidence_ids`; 기준 고유기능·사업비 기능의 출처 필요 |
| SF-TD1 개선업무설계서 | `s1:T1/R0C0`; `p[7]~p[9]` 전체·공정별 TO-BE와 기대효과 | `project.business_processes.target_steps/expected_effects`, TO-BE 첨부, 요구·현재 문제 `trace_links` |
| SF-TD2 아키텍처설계서 | `s1:T1/R0C0`; `p[13]~p[20]` 구성/연결/모델·규격·일정·검증/클라우드 | `project.systems`, 계획 `deployment_items`, 구성도 `attachments`; 클라우드는 실제 적용 여부 필요 |
| SF-TD3 화면설계서 | `s0:T2` 5×4; R0 ID/명칭, R1 경로, R2 구성, R3 항목, R4 체크; `p[63/64/73]` 표준승인/4단계메뉴·권한/화면별검토 | `screens`와 fields/buttons/permissions/menu_levels, 전후 캡처, `reviews`; 표준승인·도입기업 검토는 사실 입력 필요 |
| SF-TD4 프로그램설계서 | `s0:T2` 5×4; ID/명칭/설명/흐름/기능/관련테이블; `p[40/46~48]` 인터페이스·연결 | `programs`, 흐름도 첨부, `table_ids`, 명시 기준 명세; 전체 목록과 추가·변경 상세 대상 구분 |
| SF-TD5 데이터베이스설계서 | `s0:T2/R0C0~C8` 테이블명/ID·컬럼명/ID·Datatype·PK/FK/Null/비고; `p[51/53]` 암호화/물리DB Excel | `database_tables.columns`, 암호화·FK·출처, `physical_export_attachment_ids`; 실제 구현 DB 파일은 별도 확보 |
| SF-CD1 단위테스트결과서 | `s1:T1/R0C0~C5` 시험 ID/명/시나리오/데이터/예상/결과; T2 결함·조치일자; P114~120 요건·증거 | `test_cases.stage=unit`, `defects`, 요구·화면·프로그램 연결. 양식에 독립 시험자/수행일 열은 없지만 검증 보조값 보존 |
| SF-TI1 통합테스트결과서 | `s1:T1/R0~2` 공정·ID/명·흐름, R3~7 케이스/데이터/예상/결과; T2 결함; P71 개발자 관점 | `test_cases.stage=integration`, group/case/process/flow, `defects`; 공정 목표 근거와 개발자 실행 사실 필요 |
| SF-TI2 시스템전환결과서 | `s0:T2/R0C0`, P72~81 계획/실설치·규격·수량·라이선스·개발본수·DB·초기데이터·검증/확인 | 실제 `deployment_items`, 관련 프로그램/DB, migration_counts, 증거·`reviews`; 확인할 수 없는 장비의 고객 서명 등은 생성 불가 |
| SF-TI3 메뉴얼 | `s0:T2/R0C0`; P75~82 사용자 개요/구성/메뉴/화면별 설명, P84~90 관리자 설치/보안/장애/백업/연락·cloud | `project.manual_sections`, `screens`, 운영 구성·`attachments`; 온라인 사용자 매뉴얼 대체 시 URL·버전·접근 사실 확보 |
| SF-TI4 사용자테스트결과서 | `s1:T1` 7×7 시험 그룹·흐름·케이스; T2 결함+업무담당자; P76 도입기업이 운영환경에서 확인 | `test_cases.stage=acceptance`, executor/environment/process/group/case, `defects.owner`, 실제 고객 실행 증거 |
| SF-OS1 운영지원계획서 | `s0:T2/R0C0` 헬프데스크/운영분석/추가교육/시범운영 계획·연락·일정 | `project.support_activities`, 담당자·기간·계획·첨부. 계획과 실제 지원 결과를 분리 |
| SF-OS2 운영현황보고서 | `s0:T2/R0C0` 구축 및 일일/주간 사용자·시간·자료등록·장애·지원 현황 | `operation_periods.raw_records/reported_totals/support_records`, `deployment_items/defects`, 집계·기간·출처 |
| SF-PM1 월간보고서 | `s0:T2` 당월/차월, T3 이슈; P29~33 보고월·기간·당월/누적 계획·실적4값; P115~116 작성일/PM날인 | `progress_reports`, project.schedule/staff/budget, `changes/meetings/reviews`; 진도 계산 근거와 날인 별도 |
| SF-PM2 회의록 | `s0:T2` 8×2 회의일/장소/주관/안건/협의/결정/특기/참석자 | `meetings`, attendee 역할·요일·증거, 필요 서명 `reviews`; 실제 협의 없는 결정문 생성 금지 |
| SF-PM3 변경관리내역서 | `s0:T2` 변경관리대장 요청/회신·일자, T3 변경신청 전후/사유/영향; P124~126 변경신청·양사 서명회의록·기관승인 증거 | `changes`, `meetings`, `approval_evidence_ids/reviews`; 변경 종류·요청과 승인 상태 분리 |
| SF-PM4 요구사항추적표 | `s0:T2` 6×10 기능요구→화면/프로그램/단위·통합·사용자시험, T3 6×7 비기능 산출물/추진상태/비고 | `requirements`, `trace_links`, 각 설계/시험, `fulfillment_status/deliverable_ids`; ID 존재와 내용 충족은 별개 |

## 6. 관련 서식 34종의 사실 입력

공통 도메인으로 반복되는 사업 사실을 재사용한다. 은행계좌, 확인문, 평가·심의·통보 등 서식 전용 필드는 선택 루트 `form_records[]`에 보관한다. 이는 34서식의 **입력 보존 통로**이며 각 서식의 계산·권한·생성 구현 전체를 대체하지 않는다. 현 단계에서 34서식 모두의 자동 생성이나 의미검증이 완료됐다는 뜻도 아니다.

한 `form_record`는 공통 네 키와 `form_id/author_role/record_date/fields`가 필수이고 `form_version/document_role/attachment_ids/review_ids`를 추가할 수 있다. 각 `fields[]`에는 `key/label/locator/value_type/value/status/source_refs`가 필수다. key는 서식 안의 안정 식별자, label은 원문 항목, locator는 해당 **양식 필드** 위치이며 source_refs는 그 **입력값의 실제 출처**다. 작성 권한은 form/field의 `author_role`, 실제 확인은 `review_id`에 남긴다. `value_type`은 text/number/integer/boolean/date/money/percent/list/table/attachment_ref이며 값의 타입을 검사한다. money에는 원 단위·통화 정보를 관련 필드나 notes로 명시한다. table은 원문 행·열을 보존하는 배열이며 셀별 상태가 필요하면 여러 개의 typed field로 펼친다.

아래의 T 번호는 `2025년 선도형 스마트공장 서식자료.hwpx`의 `Contents/section1.xml` 문서순이다. 서식자료 SHA-256은 `dcfe3b1f20a1fc1acebaf46f09e0dee0a0bbd868ddf383568890fe1a8b3d2e29`. 표 범위와 모든 필드의 원문 위치는 [forms-catalog.md](../resources/stage1/forms-catalog.md), [forms-catalog.json](../resources/stage1/forms-catalog.json), forms-structure.json (로컬 자료: `analysis/stage1/forms-structure.json`)에 있다. 이 카탈로그의 R/C는 **1기반 물리 순서**이므로 위 19종의 논리 0기반 좌표와 구별한다.

| 서식 | 표/이미지 근거 | 공통 사실 및 보존할 전용 사실·작성 주체 |
|---|---|---|
| 1 신청서(시스템입력) | T2 | 기업·재무·인원·과거이력 `project.customer`, 사업유형·동의·대표날인 typed fields/증거 |
| 1-1 공통신청서 | T3~12 | 기업/공정·AS-IS·목표수준·도입범위, 선택표준·적용범위 typed fields |
| 2 서면평가표 | T13~15 | 과제·기업 공통값, 평가 항목별 점수·의견·위원 서명은 평가자 제공값 |
| 3 공급기업추천요청서 | T16~17 | 고객·공급기업, 코디네이터·추천 필요 경위·요청일·확인 날인 |
| 4 사업계획서 | T18~48 | project 공정/시스템/일정/비용/인력·requirements/features/kpis, 교육·보안·과거이력·합의 전용값 |
| 5 기술성평가표 | T49~51 | 과제·기업, 평가 점수·의견·서명은 평가자 제공값 |
| 6 현장확인서 | T52~58 | 기업 현황·수준·구축이력, 현장 확인/가점/의견·점검자 증거 |
| 7 협약변경신청서 | T59~61 | changes의 전후·사유·요청, 협약/기관 처리 전용번호·확인 |
| 8 착수계 | T62~66 | 사업기간·범위·장비·일정·착수 제출일·기업 확인 |
| 8-1 입금계좌신고 | T67~71 | 기업/과제, 은행·예금주·계좌번호·통장증빙·확인 전용값 |
| 8-2 현물출자확약 | T72~75 | budget/staff, 현물 항목·수량·금액·확약일·실제 확약 증거 |
| 8-3 기업부담금확약 | T76~77 | budget의 부담주체·금액, 지급 계획·확약일·실제 확약 증거 |
| 9 이행약정서 | T78~80 | 당사자·사업, 실제 약정 의사·일자·서명. 고정 약정문은 양식에서 유지 |
| 10 사용실적보고 | JPG7장, P4142 | 집행 금액·정산 명세·원시 증빙. 이미지 필드는 이미지 영역으로 위치 기록; OCR만으로 금액 확정하지 않음 |
| 10-1 납품검수확인 | T81~84 | deployment의 계획/납품·검수·장비사진, 인수/검수일·실제 고객 확인 |
| 11 중간보고 | T85~113 | progress/일정·비용·도입상태·개발범위, 점검 체크·작성자 확인 전용값 |
| 12 완료보고 | T114~142 | 구현·시험·교육·운영·KPI·최종비용, 완료 선언·확인·변경 최종본. 완료 사실 미확인이면 상태 보류 |
| 13 최종점검/감리 | T143~164 | 범위·KPI·설계/시험/운영 증거, 점검자 평가·수준 판정·의견·서명 |
| 13-1 시정계획 | T165~167 | defects/changes, 지적항목·조치계획·예정일·책임·확인 |
| 13-2 시정결과 | T168~170 | defects 조치·완료일·증거, 항목별 실제 결과 |
| 13-3 시정확인 | T171~172 | 조치결과·실제 확인자 판정·확인일·서명 |
| 14 운영현황 | T173~177 | operation_periods/support/deployment/KPI, 집중AS 적용 여부·확인 전용값 |
| 15 집중AS완료확인 | T178~179 | 지원기간·운영 결과·연락, 실제 완료 확인·고객 서명 |
| 15-1 AS개선확인 | T180~183 | defects/support의 개선 전후·실제 결과·확인 |
| 16 최종평가 | T184~186 | 사업 공통값·KPI·증거, 평가자 점수·판정·서명 |
| 16-1 최종재평가 | T187~189 | 재평가 사유·보완·증거, 평가자 점수·판정·서명 |
| 17 수시/특별점검 | T190~193 | 진행/집행/구축 사실과 점검 항목, 점검자 의견·판정·확인 |
| 18 제재심의평가 | T194 | 사건·근거·의견, 위원회의 심의·평가·서명은 실제 제공값만 |
| 18-1 제재통보 | T195 | 실제 결정·통보일·조치·기관 발행/담당 정보 |
| 19 이의신청 | T196~197 | 처분/사건 식별·신청 취지·사유·증거·신청일·신청인 확인 |
| 20 멘토수행일지 | T198~200 | staff/support/meetings, 수행일·시간·활동·결과·멘토/기업 실제 확인 |
| 21 참여인력일지 | T201~202 | staff와 수행일·작업·참여시간·당사자 확인 |
| 22 집중AS요청 | T203~204 | customer/support/defects, 요청 증상·범위·요청일·담당자·기업 확인 |
| 23 협약서 | T205~206 | 당사자·기간·부담금·연락·실제 체결일/서명. 고정 조항은 양식에서 유지 |

평가·심의·기관 통보의 주체가 공급기업으로 자동 바뀌면 안 된다. 승인/서명 이미지나 과거 전문가의 실제 기업 자료를 새 사업에 복사하지 않는다. 서식의 예시 MES 기능·수치·장비는 양식 설명이며 실제 사실 입력이 아니다. 동일 기호의 비용 분류 차이, HW 구매율 50/60 문구 충돌, KPI 방향/산식 불일치는 원문·해석·확인 결과를 issue로 남긴다.

## 7. 오류 보존과 품질 게이트

`extraction_issues[]`는 공통 네 키와 `issue_type/severity/description/resolution_status`가 필수다. source_conflict/missing_input/unverified_fact/original_id_mismatch/classification_ambiguity/layout_risk/other를 구분하고, 원문 값/제안 값/영향 개체/해결 이유를 보존한다. `accepted_with_reason`는 사실을 고쳤다는 뜻이 아니다.

검사는 순서와 책임을 나눈다.

1. **스키마 검사:** 타입·필수 키·enum·알 수 없는 키·수치 경계·합성/참고 제출금지. `jsonschema[format]` 의존성과 `FormatChecker`를 켠 Draft202012Validator로 날짜·날짜시간·이메일·URI를 확인한다. 선택 의존성이 없으면 FormatChecker도 일부 형식을 조용히 무시할 수 있으므로 필요한 체커의 등록 여부까지 검사한다.
2. **의미 검사:** 중복/참조·시간 선후·날짜/요일·시험 수행/조치 증거·KPI 산술·원시 운영 집계·명시 기준사전과의 대조·범위별 완결성. 이름/ID 모양 또는 참고 한 건의 관행만으로 의미 오류를 단정하지 않는다.
3. **사업 사실/승인 검토:** 출처 내용·해시·실제 담당자·날인·기관승인·실행/실측자료를 사람이 확인한 기록. 사실·승인·네이티브 출력 검토를 독립적으로 보존한다.
4. **현재 생성물의 네이티브 출력 검토:** 현재 HWPX 첨부 해시에 연결된 `native_render` 검토와 실제 한글 버전·검토 범위·전체 페이지의 증거. 원본 렌더나 이전 생성물의 승인을 새 파일로 승계하지 않는다.

`submission_ready`는 입력자의 희망 표시만으로 승인되지 않는다. 합성/참고는 항상 false이고 실제 사업도 범위 확정, 검증된 사실, 필요한 승인·수행·첨부, 현재 생성물의 네이티브 검토가 갖춰져야 한다. 스키마는 이러한 외부 사실을 증명할 수 없으며 의미검증의 보수적 게이트가 결과를 별도로 산출한다. 부속 DB Excel 등 HWPX 밖의 의무도 요청 역할에 따라 확인한다.

## 8. 검증과 변경

모델 자체의 재현 검사는 [check_project_schema.py](../schemas/check_project_schema.py), 실행 결과는 project-schema-validation.json (로컬 자료: `verification/project-schema-validation.json`)에 있다. `.venv/bin/python schemas/check_project_schema.py`로 스키마 메타 검증, 유효/무효 경계 180사례, 존재하는 정식 예시 3종을 검사한다. 보고서에는 스키마·예시 파일 해시와 실행환경을 남긴다. 사례의 값은 검증용이고 제출 자료가 아니다. 실제 추출/합성 데이터와 의미검증은 별도 담당 산출물로 대조한다.

새 필드를 추가하거나 의미를 바꾸면 스키마·이 문서·의미검증·생성 프로필·예시를 함께 검토한다. 모르는 입력을 임의의 이름 없는 확장 속성으로 숨기지 않고, 공식 서식 전용 사실은 위치가 있는 typed `form_records`에 넣는다. 다른 사업/연도의 양식이 들어오면 기존 corpus의 지침을 그대로 의무화하지 말고 새 버전과 근거를 등록한다.
