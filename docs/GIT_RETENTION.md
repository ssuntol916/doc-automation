# Git 추적과 로컬 자료 보관

공개 대상은 재사용 코드·스키마·스킬·양식 SHA 핀·개인정보 없는 서식 프로필·독립 합성 입력과 합성 SVG/PNG다. 실제 회사·사업의 원문, 참고 파생 입력과 수동 관측·반례·화면·사진·서명은 공개 source 자원이 아니다. 자세한 경계와 로컬 source-map 계약은 [PRIVACY.md](PRIVACY.md)에 있다.

`analysis/`, `verification/`, `outputs/`, `generated/`, `archives/`, `private/`와 로컬 환경 설정은 Git에서 제외한다. 최종 문서를 포함한 모든 실행 HWPX/PDF/페이지 PNG·manifest·검토 보고서도 이 영역 또는 외부 비공개 작업공간에 둔다. 개인 절대경로와 업체명이 있는 메타데이터를 선별 자원이라는 이유로 공개하지 않는다.

이미 추적된 파일은 ignore 규칙만으로 제거되지 않는다. 공개 후보의 실제 파일과 Git 목록을 따로 검사하고 원사업 데이터가 포함된 이전 공개 이력은 별도 범위로 다룬다. `*.json`·`*.png`를 전역 무시하지 않으며 코드에 필요한 합성 fixture와 비공개 원자료를 구분한다.

## 테스트와 원본

```sh
uv sync --extra dev
uv run pytest -q
```

기본 검사는 비공개 코퍼스 없이 실행한다. 외부 자료 검사는 `corpus`, 과거 실제 native 근거 검사는 `native` 마커로 분리한다. 필요한 로컬 원본·private fixture·관측을 명시적으로 제공한 뒤 선택하며, 자료 부재를 자동 통과로 바꾸지 않는다.

```sh
uv run pytest -q -m 'corpus or native'
```

양식 위치는 `--template-root`, `DOC_AUTOMATION_TEMPLATE_ROOT` 또는 비공개 `DOC_AUTOMATION_SOURCE_MAP`으로 제공한다. 원본은 읽기 전용이며 공개 SHA 핀과 대조한다. 참고 분석과 과거 native 이력은 개인 로컬 자료이므로 새 checkout에 있다고 가정하지 않는다.

## 재현 도구

`scripts/resources/run.py`는 재사용 분석 도구를 새 ignored 작업공간에 준비한다. 참고 원문의 raw JSON·이미지와 수동 관측은 별도 비공개 입력이다. 기본 원시 데이터·보고서 출력은 ignored 작업 영역을 사용하며, 원사업 데이터가 source 폴더로 다시 유입되지 않도록 출력 위치를 확인한다.

독립 합성 원시 사실의 재생성만 명시적으로 `examples/`에 반영할 수 있다. 그림 bytes를 바꾸면 연결 SHA와 의미 대응을 함께 검토한다. 합성 시안은 실제 수행·승인 증거가 아니다.

## 제조AI 중간보고서 예제

공개 입력은 `examples/manufact-ai-interim/content.json`, 제작 코드는 `scripts/manufact_ai_interim/`다. 양식은 로컬에서 별도 지정하고 그림과 결과는 새 ignored 폴더에 생성한다.

```sh
uv run python scripts/manufact_ai_interim/build_assets.py --output outputs/my-interim/assets
uv run python scripts/manufact_ai_interim/build_report.py \
  --template /local/private/templates/interim.hwpx \
  --assets outputs/my-interim/assets --output outputs/my-interim/draft/report.hwpx
```

결과는 합성 초안이다. 실제 한컴 저장·재열기·PDF·원페이지 검토와 내용·필수 증적 판단을 별도로 수행한다. 과거 로컬 검토나 다른 bytes의 판정은 승계하지 않는다.
