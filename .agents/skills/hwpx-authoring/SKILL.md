---
name: hwpx-authoring
description: Analyze, edit, and verify Hancom HWPX (.hwpx) documents with semantic-object preservation and declared font, paragraph, page, table, or image edits. For binary HWP (.hwp), verify native conversion to HWPX before XML work.
---

# HWPX 문서 작성

HWPX 패키지·본문·서식 보존을 담당한다. 사업별 작성 내용은 해당 도메인 지침에서 정한다. 이 스킬의 CLI 생성기는 저장소에 등록된 프로필 범위에 한정되며 임의의 HWPX 양식을 자동 지원한다고 가정하지 않는다.

## 시작

이 스킬은 `doc-automation` 저장소와 함께 사용하는 로컬 스킬이다. 설치 위치나 cwd를 추측하지 말고 `python3 <이 스킬>/scripts/run.py locate`로 실제 저장소 경로를 확인한다. 리소스와 실행 방법은 [references/workspace.md](references/workspace.md)를 읽는다. 다른 곳에 스킬만 복사하면 코드·스키마·분석 코퍼스가 포함되지 않는다.

요청에 맞는 참조만 읽는다.

- 양식 분석, 텍스트/표/그림 추출, 구조를 보존하는 편집: [references/package-editing.md](references/package-editing.md)
- 생성·수정 결과의 내용 및 한글 출력 검증: [references/quality-gates.md](references/quality-gates.md)
- 스마트공장 정부지원 산출물: 함께 설치된 `$gov-grants-smart-factory`가 업무별 입력·문체·역할을 담당한다. 없으면 저장소의 해당 canonical 스킬을 읽는다.

## 지켜야 할 경계

- 원본의 SHA-256을 먼저 기록하고 프로젝트 안의 사본에서 작업한다. 사용자가 제공한 `_templates`와 `_references` 원본은 읽기 전용이다.
- `.hwp` 바이너리를 ZIP/XML로 다루거나 확장자만 바꾸지 않는다. 한글의 **다른 이름 저장**으로 HWPX 사본을 만들고 변환 전후 페이지·표·수식·그림·필드를 확인한다. 변환본의 SHA와 실제 한글 버전을 따로 남긴다.
- OPF spine의 모든 구역을 순서대로 읽는다. 인라인 제어 뒤 tail을 보존하고 표를 담은 문단의 텍스트에 셀 문단을 중복 합치지 않는다.
- 문자/문단/테두리/글꼴의 숫자 ID는 그 파일 안에서만 유효하다. 실제 run과 참조 정의를 해결해 비교하고 직접 서식도 보존한다.
- 기본 보존 경로와 선택한 참고 서식 적용을 구분한다. `--style-profile reference-v1`은 등록된 원본 SHA와 역할별 프로필의 명시한 범위만 바꾸며, 원정의를 파생해 대상 run/문단에 연결한다. profile·selector·실제 변경을 manifest에 남긴다. 사용법과 지원 경계는 package-editing/workspace 참조를 따른다.
- 표지 글자 서식은 명시된 customer/program/title/date/supplier owner의 글꼴·크기·굵기에 한정한다. 별도로 선언한 program owner의 `breakNonLatinWord`만 문단 속성의 선택 변경으로 허용한다. 정확한 원본 XPath·own text·원문 문단 정의와 렌더러 registry를 함께 대조하며, 나머지 문단 속성·페이지·표·셀·개체·제어와 합성 고지는 보호한다.
- 표·그림·수식·필드·구역·머리말/꼬리말 제어를 포함한 문단 전체를 일반 문자열로 교체하지 않는다. 수정할 텍스트 소유 문단/셀/반복 블록을 식별한다.
- 현재 생성 바이트의 구조 검사, 사실·연결 검사, 네이티브 출력 검토를 구분한다. ZIP 파싱이나 그림/OCR의 존재를 사실·승인·페이지 품질의 증거로 삼지 않는다.
- native Save As가 대체글꼴 선언을 누락하면 숫자 ID 정규화로 면제하지 않는다. 정확히 일치하는 선언만 제한 복원하고 실제 저장 중간물·복원 최종물과 각 native 검토를 분리한다. 절차와 재저장 후 재검토는 quality-gates 참조를 따른다.

## 실행과 완료

`scripts/run.py`는 `uv run --project <실제 저장소> doc-automation`을 실행한다. `analyze`, `validate-project`, `generate` 계약과 QA 경로는 workspace 참조에 있다. 실행 전 현재 CLI `--help`와 필요한 프로필을 확인한다. 지원하지 않는 양식은 기존 프로필을 억지로 적용하지 않고 새 원본 분석부터 수행한다.

합성 입력은 출력 문서 안에도 `검증용 합성 자료(제출용 아님)`으로 표시한다. 최종 보고에는 생성 파일·manifest·검증 보고서·실제 한글 버전·PDF/페이지 이미지·검토 범위·남은 문제를 연결한다. 네이티브 검토를 하지 못했다면 완료 범위를 명시하고 최종 페이지 품질 합격을 주장하지 않는다.

내용 구성의 의미 보존, 선택한 서식 적용의 허용 변경, 이미 서식 적용한 현재 bytes의 native strict 보존은 서로 다른 검증 경계다. 새 프로필·API·회귀 통과만으로 참고 수준95%나 전체19종 편집 적합성을 선언하지 않는다. 현재 출력별 근거와 미검토 범위는 quality-gates 참조에 따라 확인한다.
