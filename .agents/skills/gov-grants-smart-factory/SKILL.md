---
name: gov-grants-smart-factory
description: Draft and review Korean government-grant smart-factory deliverables and related forms in HWPX using source-backed project facts and local templates. Use for 정부지원사업 산출물, 스마트공장 문서, and HWP/HWPX grant forms; binary HWP requires verified native conversion first.
---

# 스마트공장 정부지원 산출물

로컬 개발산출물 19종과 2025년 독립 서식 34종의 작성 지침이다. 한 사업의 전문가 문서를 관찰한 결과이며 다른 연도·사업의 현행 제출 기준으로 일반화하지 않는다. HWPX 편집·패키지 보존은 `$hwpx-authoring` 또는 저장소의 같은 canonical 스킬을 읽어 적용한다.

현재 CLI 초안 생성은 V2.0 개발산출물19종이다. 34서식의 분석·typed 사실 입력 지원은 해당 서식 전체의 생성·native 실증과 구분한다.

## 입력과 대상 확정

`python3 <이 스킬>/scripts/run.py locate`로 저장소를 찾고 [references/workspace.md](references/workspace.md)의 리소스 확인 방법을 따른다. 사업/연도/양식 버전/문서 역할/원본 해시를 함께 식별한다. 과거 파일코드를 현재 역할과 곧바로 동일시하지 않는다.

사업 사실은 `sources`의 SHA·위치와 공통 데이터 계약에 연결한다. [references/facts-and-writing.md](references/facts-and-writing.md)를 읽어 양식 지침·전문가 관행·사업 사실·구현 선택·미확인을 분리한다. 알려지지 않은 사실은 `null`/확인 필요로 남긴다. 미수행은 입력에서 그렇게 확인된 경우에만 표시하며 결과·승인·서명·계량 증거를 만들지 않는다.

제공 양식 작성은 표의 열·병합·항목 순서·작성 주체별 칸을 유지하는 작업이다. 자료량이나 가독성을 이유로 표를 요약·재설계하지 않는다. 반복 행이 필요하면 양식이 허용한 반복 단위를 유지한다. 사용자 검토본은 `$hwpx-authoring`의 `references/review-feedback.md`에 따라 우선 반영하고, 이 스킬의 [references/reviewed-writing.md](references/reviewed-writing.md)로 문체·요약·본문과 근거 원장의 경계를 확인한다.

검토본에 공정별 입력 구분·단절 지점·아키텍처·KPI 산출근거·장비 위치 설명이 추가되면 같은 참조의 세부 기준을 적용한다. 자료 분석이 부족하면 `$grant-project-analysis`의 공정·데이터·AI 연결 근거를 보강하고, 원래 번호나 소제목을 바꾸어 설명을 이동하지 않는다.

항목 번호와 소제목을 그대로 두고 해당 항목의 내용도 그 아래에 유지한다. 원형 유지와 글꼴·줄 간격 개선은 별개다. 사용자가 스킬에 따른 서식 정리를 지정하면 입력 예시의 문자 속성을 그대로 복사하지 말고 제목·본문·표 머리·값·주석·도식의 역할에 맞게 편집한다. 구조가 같다는 이유로 지나치게 작은 글자·낮은 대비·본문 전체 기울임·제목용 본문 글꼴을 남기지 않는다.

## 문서별 참조

요청한 역할의 절만 읽는다. 19종 모두 분석되었다는 것과 현재 생성기로 지원·실증한 범위는 다르므로 CLI·manifest에서 실제 지원 결과를 확인한다.

| 요청 역할 | 작성 참조 |
|---|---|
| SF-AD1 현행업무분석, AD2 요구사항, AD3 기능대비 | [references/analysis-design.md](references/analysis-design.md) |
| SF-TD1 개선업무, TD2 아키텍처, TD3 화면, TD4 프로그램, TD5 DB | [references/analysis-design.md](references/analysis-design.md) |
| SF-CD1 단위시험, TI1 통합시험, TI2 시스템전환, TI3 매뉴얼, TI4 사용자시험 | [references/testing-transition.md](references/testing-transition.md) |
| SF-OS1 운영지원계획, OS2 운영현황, PM1 월간보고, PM2 회의, PM3 변경, PM4 추적 | [references/operations-management.md](references/operations-management.md) |
| 2025년 서식 1~23 및 가지번호, 총34개 | [references/forms-routing.md](references/forms-routing.md) |

성과측정 참고문서는 19종 목록에 독립 양식이 없다. 주간보고와 월간보고는 부분 대응이다. 코드가 다른 회의·변경·추적 문서는 내부 역할로 대응한다. 폰트 크기·색·가로 페이지·표 추가·반복 건수는 전문가 한 사례의 관행일 수 있으며 고정 규칙으로 승격하지 않는다.

## 작성과 검증

먼저 요청 범위를 `project.requested_deliverables` 또는 `requested_forms`에 명시하고 `validate-project`를 수행한다. 생성 명령은 `generate INPUT OUTPUT [--role SF-AD2 ...] [--template-root PATH]`이며 출력 manifest와 실제 지원 범위를 확인한다. 예시·명령·QA 경로는 workspace 참조에 있다.

요약→구체 요건→업무 절차→제약/전제→출처의 구성을 활용하되 실제 정보에 맞춘다. 기능·화면·프로그램·테이블·시험·추적의 ID가 존재한다는 사실과 내용 충족·실제 수행을 구분한다. 기간·기업 역할·합계·단위·산식·원문 불일치를 검증한다.

참고자료 수준의 편집을 요청하면 [references/editorial-quality.md](references/editorial-quality.md)를 읽는다. `reference-v1`은 역할별 서식과 업무 표현을 선택하는 생성 옵션이며, 프로필 선택이나 정상 생성만으로 편집 품질이 검증되는 것은 아니다. 현재 검증 상태와 실제 출력 증거는 해당 실행 기록에서 확인한다.

완료 전 [references/quality-review.md](references/quality-review.md)를 적용한다. 합성 고지는 문서 안에 표시하고 `submission_ready=false`를 유지한다. 계약·동의·은행계좌·심사/위원회 결과는 작성 주체와 근거를 확인하며, 서식 분석이나 형식이 있는 필드 계약이 자동 승인·날인 권한을 주지는 않는다.
