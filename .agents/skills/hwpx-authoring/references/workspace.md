# 저장소 자원과 실행

이 스킬은 canonical `<repo>/.agents/skills/hwpx-authoring`와 같은 저장소의 Python 패키지·스키마·분석 자료를 사용한다. 사용자 스킬 위치가 symlink여도 `scripts/run.py`는 `Path(__file__).resolve()` 후 부모를 탐색한다. 원본 코퍼스나 수백 MB의 분석 이미지를 스킬에 복제하지 않는다. 스킬만 따로 복사한 환경에서는 전체 checkout을 제공하고 `DOC_AUTOMATION_PROJECT`를 지정한다. helper는 필요한 파일이 없으면 경로를 추측하지 않고 알린다.

```sh
python3 <skill>/scripts/run.py locate
python3 <skill>/scripts/run.py resources
python3 <skill>/scripts/run.py path docs/FORMAT_SOURCES.md
python3 <skill>/scripts/run.py --help
```

`<skill>`은 읽은 SKILL.md의 디렉터리로 바꾼다. `locate` 결과가 실제 repo다. `path`는 repo 상대 자원의 절대 경로를 출력한다. 아래 경로는 모두 **repo 상대 경로**다. 실행 명령의 상대 입력/출력 경로는 **호출 cwd** 기준이며 입력 JSON 내부 source 경로는 그 JSON 기준이다.

| 필요 작업 | 먼저 볼 자원 |
|---|---|
| 지원 형식/공식 형식 설명 출처 | `docs/FORMAT_SOURCES.md` |
| 진행 범위/원본 읽기 전용 경계 | `docs/PLAN.md`, `AGENTS.md` |
| 패키지 분석 구현 | `src/doc_automation/hwpx.py`, `scripts/audit_extraction.py` |
| 구조 보존 편집 API | `docs/HWPX_COMPOSE.md`; 아직 없으면 현재 CLI와 소스 지원 범위부터 확인 |
| 선택한 참고 서식·허용 변경 | `src/doc_automation/layout.py`, `resources/style-upgrade/profiles/{SF-ROLE}.json`, `docs/REFERENCE_QUALITY_UPGRADE_PLAN.md` |
| 입력 모델과 의미 검증 | `schemas/project.schema.json`, `docs/DATA_MODEL.md`, `docs/BUSINESS_VALIDATION.md` |
| 생성 명령/프로필/manifest | `docs/GENERATION.md`; 없으면 미구현 내용을 지원한다고 보고하지 않음 |
| 네이티브 출력 검토 | `docs/OUTPUT_QUALITY.md`, `schemas/quality-review.schema.json` |
| 과거 원본 기준 출력 | `verification/baselines/native-environment.json`, `native-audit.json`; 새 생성물 검토 대체 불가 |

## CLI 계약

helper는 `uv run --project <repo> doc-automation ...`으로 프로젝트의 선언된 의존성을 사용한다. 설치된 `uv`와 전체 repo가 필요하다. 네이티브 한글·Poppler는 별도 환경 자원이며 이 스킬에 포함되지 않는다.

```sh
python3 <skill>/scripts/run.py analyze COPY_FOLDER ANALYSIS_FOLDER --kind template
python3 <skill>/scripts/run.py validate-project INPUT.json --report VALIDATION.json
python3 <skill>/scripts/run.py generate INPUT.json OUTPUT_FOLDER --role SF-AD2 --role SF-AD3 --role SF-TD3 --template-root TEMPLATE_FOLDER
python3 <skill>/scripts/run.py generate INPUT.json EDITORIAL_OUTPUT_FOLDER --role SF-AD2 --style-profile reference-v1
python3 <skill>/scripts/run.py verify-output REVIEW.json --input INPUT.json --template TEMPLATE.hwpx --report OUTPUT_QA.json
python3 <skill>/scripts/run.py qa-paths
```

`analyze`는 폴더 입력 계약이다. 단일 문서는 원본 해시를 남기고 프로젝트 내 분석 폴더의 사본으로 다룬다. `.hwp`는 먼저 검증된 네이티브 HWPX 전환 사본이 필요하다.

`generate`는 등록된 스마트공장 양식 역할/프로필을 사용한다. `--role`은 여러 번 지정할 수 있고 생략 시 INPUT의 요청 범위를 따른다. 별도 양식 루트는 실제 적용할 원본과 해시·버전을 확인한다. 생성 후 manifest의 산출물·입력/양식/출력 해시·지원 결과·검사 상태를 읽는다. 정확한 필드는 현재 `docs/GENERATION.md`와 CLI `generate --help`가 기준이다.

`--style-profile`을 생략하면 기존 기본 보존 경로를 사용한다. `reference-v1`은 등록된 V2.0 19종의 source SHA에 묶인 선택 경로이며, 임의 파일명/다른 원본으로 프로필을 우회 적용하지 않는다. 선택한 경우 `editorial_profile`의 profile source path/SHA·실제 selector/changes/pages/tables/cover_roles를 읽는다. 표지 다섯 owner의 선택 글자서식은 source exact XPath/원문/registry로 검증하고 기하·문단·개체·제어는 유지한다. 본문 표현·첨부 슬롯 지원과 검토 상태는 문서별 manifest에서 확인한다. 신규 프로필의 후보 생성과 테스트 통과는 최종 native·참고 수준95% 달성 판정이 아니다.

`verify-output`은 검토 기록이 현재 입력·양식·HWPX·PDF·모든 페이지 PNG와 연결되는지 검사한다. 한글 실행·PDF 출력·시각검토를 대신 수행하는 명령이 아니다. 각 REVIEW.json의 상대 경로는 REVIEW.json 기준이다. 같은 파일을 나중에 저장했다면 바뀐 HWPX에서 다시 출력·검토한다.

Git checkout에는 `resources/`의 선별된 규칙·프로필이 포함된다. `analysis/`의 원문 전체 추출·OCR 및 `verification/`의 실제 출력 이력은 선택적인 로컬 자료이며 기본 실행 자원이 아니다. 준비와 기본/통합 검사 구분은 repo `docs/GIT_RETENTION.md`를 따른다.

공개/비공개 구분과 개인 경로 없는 원본 연결은 `docs/PRIVACY.md`를 따른다. `DOC_AUTOMATION_TEMPLATE_ROOT` 또는 비공개 `DOC_AUTOMATION_SOURCE_MAP`을 사용하고 원본 SHA 핀을 유지한다. 참고 원문 파생 입력과 수동 관측·과거 native 이력은 공개 스킬에 포함하지 않으며 존재한다고 가정하지 않는다.
