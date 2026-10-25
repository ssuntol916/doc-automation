# 자원과 로컬 실행

canonical 스킬은 `<repo>/.agents/skills/gov-grants-smart-factory`다. helper가 실제 checkout을 찾고 `uv run --project <repo> doc-automation`을 실행한다. 스킬만 복사한 경우 전체 checkout과 `DOC_AUTOMATION_PROJECT` 지정이 필요하다. 한컴·글꼴·Poppler와 비공개 코퍼스는 포함하지 않는다.

```sh
python3 <skill>/scripts/run.py locate
python3 <skill>/scripts/run.py resources
python3 <skill>/scripts/run.py path docs/PRIVACY.md docs/GENERATION.md
```

공개 자원은 스키마·템플릿 지침·SHA 핀·개인정보 없는 역할별 프로필·일반 작성 원칙과 독립 합성 예제다. 원사업 원문·그림·수동 관측·같은 문안 비교와 과거 실제 출력 이력은 비공개 로컬 자료다. 원문 관측이 필요하면 사용자 제공 자료를 새 ignored 작업공간에서 읽고 SHA·XML owner를 기록한다.

| 목적 | 공개 안내 |
|---|---|
| 지원 범위·작업 상태 | `docs/PLAN.md` |
| 입력·출처·미확인 | `schemas/project.schema.json`, `docs/DATA_MODEL.md`, `docs/DATA_EXAMPLES.md` |
| 양식 역할·지침 | `resources/stage1/`의 역할별 규칙·카탈로그 |
| 생성·서식 프로필 | `docs/GENERATION.md`, `resources/style-upgrade/profiles/index.json` |
| 편집·인용 | `docs/HWPX_COMPOSE.md`, `docs/REFERENCE_QUOTATIONS.md` |
| 실제 출력 계약 | `docs/OUTPUT_QUALITY.md`, `schemas/quality-review.schema.json` |
| 공개/비공개 경계와 원본 설정 | `docs/PRIVACY.md`, `docs/GIT_RETENTION.md` |

```sh
python3 <skill>/scripts/run.py validate-project INPUT.json --report outputs/validation.json
python3 <skill>/scripts/run.py generate INPUT.json outputs/draft --role SF-AD2 --template-root TEMPLATE_FOLDER
python3 <skill>/scripts/run.py verify-output REVIEW.json --input INPUT.json --template TEMPLATE.hwpx --report outputs/output-qa.json
```

원본은 읽기 전용이다. `DOC_AUTOMATION_TEMPLATE_ROOT` 또는 비공개 `DOC_AUTOMATION_SOURCE_MAP`도 사용할 수 있으며 SHA/selector를 우회할 수 없다. 입력 JSON의 상대 source/attachment 경로는 그 JSON 부모 기준, CLI 인자의 상대경로는 호출 cwd 기준이다.

공개 시작 입력은 `examples/demo.project.json`·`demo-suite.project.json`과 독립 합성 원시 `examples/sources/demo-facts.json`이다. 실제 사업에서 추출한 예제는 이름만 바꿔 공개하거나 합성으로 표시하지 않는다. 그림을 포함한 합성 시안도 실제 실행·서명·승인 근거가 아니다.

문서 품질 개선 반복은 중단된 상태다. 공개 테스트·프로필 선택이나 과거 로컬 판정으로 전체19종·95%·실제 제출 적합성을 선언하지 않는다. 새 현재 bytes에 대한 실제 한컴·PDF·원페이지 검토와 미확인 범위를 별도로 남긴다.
