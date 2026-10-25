# 출처 원장과 공통모델 연결

이 계약은 분석용 중간물이다. 기존 사업 입력 스키마의 지원 범위나 기관 제출 기준을 확장하지 않는다. 실제 자료와 파생물은 비공개 실행 폴더에 둔다.

## 산출물

| 파일 | 내용 |
|---|---|
| `source-inventory.json` | 원본·사본 SHA, 상대경로, 자료 유형, 읽기 범위, 제외 사유, 사업 귀속 |
| `analysis-plan.json` 또는 사용자에게 읽기 쉬운 계획 | 자료별 질문·순서·근거 위치·산출물·완료 조건·확인 사항 |
| `evidence-ledger.json` | `sources`와 안정된 주장 ID를 키로 갖는 `claims` 원장 |
| `analysis-review.json` | 상충·누락·혼입 후보·해결 근거와 보고서 항목별 작성 준비도 |
| `mapping.json` | 원장 주장→보고서 위치/공통모델 JSON Pointer, 미매핑 사유 |
| `project.candidate.json` | 필요할 때만 만드는 기존 공통 스키마에 맞춘 작성 후보 |

수집한 자료를 전부 정밀 분석한 것처럼 빈 목록을 채우지 않는다. claim이 없는 단계라면 `claims={}`와 사전조사 상태·미완료 범위를 명시한다.

## 주장 한 건의 권장 필드

- `id`, 대상 과제·사업장·엔터티, `field`, `original_value`, `normalized_value`, 타입·단위
- `information_class`: template_instruction / expert_convention / project_fact / implementation_choice / unresolved_issue
- `assertion_kind`: identity / plan / target / reported_result / static_observation / execution_observation / measurement / approval_record / calculation
- `source_refs`: source ID·원본 SHA·네이티브 locator·필요한 짧은 원문 발췌
- `applies_to`, `document_date`, `period_start/end`, `observed_at`, `report_cutoff`와 각각 미확인 사유
- 독립 검토 상태: `file_integrity`, `extraction_match`, `business_attribution`, `execution_basis`, `approval_basis`
- 검토자·확인 범위·근거 파일 ID, `conflicts_with`, `limitations`, 관련 보고서 항목

위 review 상태는 `pending`·`matched`·`mismatch`·`not_applicable` 등 명시한 어휘와 사유를 사용한다. 해시만 확인한 항목을 통째로 verified로 표시하지 않는다. `provided`는 자료에서 제공한 주장이고 사실 입증·승인을 뜻하지 않는다. 모르는 실제 값은 `null`과 사유를 보존한다.

네이티브 locator 예:

- HWPX: XML 멤버, XPath, P 번호, T 번호와 logical R/C(0 기반), 소유 문단
- PPTX: 슬라이드 순서·멤버, shape ID·단락·표 R/C, notes 여부
- PDF: 물리 page(1 기반), bbox와 추출 블록, OCR/텍스트 구분
- 코드: source SHA·파일 상대경로·행 범위(1 기반)·심벌
- XLSX: sheet·A1 셀, 수식/캐시/표시값 구분

상충 항목은 같은 필드·같은 적용기간인지 먼저 확인한다. 적용 범위가 다른 수치를 한 충돌로 합치지 않는다. 우선 적용 근거는 파일명·수정일 대신 실제 승인·버전·변경 이력과 사용자 확인에서 찾는다.

## 계산과 비용

계획예산 / 승인예산 / 원가·견적 산정 / 계약액 / 지급·집행을 각기 구분한다. 재원·현금/현물·원/천원·VAT 포함 여부·기준일·단가×수량·참여율×기간·소계/합계를 함께 남긴다. 금액 재계산은 십진 연산과 명시한 반올림을 사용하고 원문값을 덮어쓰지 않는다.

KPI는 기준값·목표·중간 실측값·측정기간·분자/분모·표본·단위·개선방향·원시 데이터 출처를 분리한다. 계획에서 가져온 목표를 실적으로 옮기지 않는다. 코드에 있는 예측값이나 다른 데이터셋의 성능을 과제 KPI로 전환하지 않는다.

## 기존 사업 입력으로 옮기기

현재 저장소 스키마의 실제 필드명을 확인한다. 분석 전용 키를 `additionalProperties=false`인 객체에 추가하지 않는다. 계획은 계획 필드, 근거 있는 관측은 실제 필드로 옮기고 원가 산정은 집행으로 옮기지 않는다. 부분 미확인은 `field_states`, 충돌은 `extraction_issues`, 승인 검토는 `reviews` 및 변경 승인 필드로 보존한다.

검증기가 PPTX·PDF bbox·코드 행 locator를 직접 지원한다고 가정하지 않는다. 한 방법은 원본 SHA/locator를 원장 안에 유지하고 공통모델의 source를 SHA가 고정된 원장 JSON으로 지정하여 `/claims/CLAIM-ID`를 참조하는 것이다. `mapping.json`에 공통모델 필드→원장→원본까지 연결하고 원본 파일도 source 목록에 보존한다. JSON Pointer 존재 확인은 원문 해석과 실제 수행 확인을 대체하지 않는다.

기존 `validate-project`는 공통모델 후보를 만들었을 때만 실행한다. 사전조사 목록이나 임의 ledger를 그 스키마에 억지로 넣지 않는다. 지원 여부·누락·미확인 사실과 `submission_ready=false`를 명시한다.
