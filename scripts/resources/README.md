# 분석·프로필 재사용 도구

`tool_sources/`는 분석과 프로필 구축에 쓰는 일반 로직이다. 실제 사업 원문·인물·장비 식별값·같은 문안 입력·수동 관측·과거 시각 판정은 포함하지 않는다. [공개·비공개 계약](../../docs/PRIVACY.md)을 따른다.

`run.py`는 새 ignored 작업공간에 코드를 준비하고 실행한다. canonical source나 과거 분석 폴더를 직접 덮어쓰지 않는다.

```sh
uv run python scripts/resources/run.py list
uv run python scripts/resources/run.py --workspace outputs/resource-rebuild/run-01 --prepare-only stage1/extract_root_forms.py
uv run python scripts/resources/run.py --workspace outputs/resource-rebuild/run-01 --templates /local/private/templates stage1/extract_root_forms.py
```

원본 위치는 `--templates`·`--references`로 명시한다. 양식의 환경 기본값은 `DOC_AUTOMATION_TEMPLATE_ROOT`, 참고자료는 `DOC_AUTOMATION_REFERENCE_ROOT`다. 실제 원본 SHA와 필요한 fresh `analyze` 산출물은 별도로 준비한다.

수동 관측 보고 도구는 `--observations PRIVATE_JSON`이 필수다. 분석/설계 패턴은 `patterns`, `template_instruction_assessments`와 명시 source selectors, 시험/전환 패턴은 `issues`, `patterns`, 역할별 `compliance`, 운영/관리 문서화는 `title`, `sections[{heading,paragraphs}]`를 받는다. 없는 관측을 생성하거나 이전 판정을 현재 native 관측으로 재기록하지 않는다.

도구 추가 인자는 task 뒤 `--`로 구분한다. optional 원문 그림 control 검사는 `--control-input PRIVATE_PROJECT --label-evidence PRIVATE_LABELS`를 함께 제공한다. 공개 합성 검사만 실행한 경우 private control 검토까지 수행했다고 보고하지 않는다.

원문 선택·추출·그림·보고서는 해당 작업공간에만 쓴다. 검토 후 공개할 수 있는 일반 규칙과 비공개 관측을 다시 분리한다. source code·자원 이관 해시는 `resources/migration.json`을 따르며, 해시만으로 native 품질·실제 사업 사실을 판정하지 않는다.

`style-upgrade/build_evaluation_specs.py`의 원문 선택은 `--selections-plan PRIVATE_JSON`을 명시할 때만 만든다. 각 항목은 `role`, `rid`, `section`, `index`, `rows`, `purpose`, `issues`를 제공한다. 옵션이 없으면 rubric/합성 입력 계획만 만들며 원문 선택을 수행했다고 보고하지 않는다.
