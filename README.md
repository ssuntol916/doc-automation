# 문서 자동화

정부지원사업 산출물을 시작으로 HWPX 문서의 구조·서식·의미를 보존하며 초안을 생성하는 프로젝트입니다. 공통 사업 사실, 원본별 프로필, 작성 지침과 품질 검증을 분리합니다.

공개 저장소에는 코드·스키마·스킬·서식 프로필과 독립 합성 예제만 포함합니다. 실제 기업·사업 원문, 참고 파생 입력, 원본 그림·서명과 과거 한컴 검토 이력은 비공개 로컬 자료입니다. [공개·비공개 경계](docs/PRIVACY.md)와 [Git 보관 정책](docs/GIT_RETENTION.md)을 따릅니다.

현재 생성기는 V2.0 개발산출물 19종의 초안을 지원합니다. 별도로 분석한 34개 독립 서식은 구조·지침·typed 입력의 범위이며 전체 자동 생성이나 native 출력 검증을 뜻하지 않습니다. 실제 수행 결과·승인·서명·측정값은 입력 근거 없이 만들지 않습니다. 문서 품질 개선 반복은 현재 중단된 상태이며, 전체 95% 달성을 선언하지 않습니다.

## 시작

Python 3.11 이상과 uv를 사용합니다.

```sh
uv sync --extra dev
uv run pytest -q
uv run doc-automation --help
uv run doc-automation validate-project examples/demo-suite.project.json --report outputs/demo-validation.json
```

실제 양식은 배포하지 않습니다. 로컬 원본 폴더를 지정하고 공개 SHA 핀과 대조한 뒤 생성합니다.

```sh
uv run doc-automation generate examples/demo-suite.project.json outputs/demo-suite \
  --template-root "$DOC_AUTOMATION_TEMPLATE_ROOT"
```

`DOC_AUTOMATION_TEMPLATE_ROOT`와 비공개 `DOC_AUTOMATION_SOURCE_MAP`의 계약은 [개인정보·원본 연결 안내](docs/PRIVACY.md)에 있습니다. 원본 폴더는 읽기 전용이며 결과는 새 로컬 작업 폴더에 저장합니다.

선택한 `--style-profile reference-v1`은 등록 원본과 명시된 역할별 서식 변경에 한정됩니다. `--raster-metadata-profile hancom-mac-12.30.0-png`는 명시한 Mac 한컴 버전의 새 PNG 좌표 선택입니다. 둘 다 실제 출력 검토를 대신하지 않습니다.

## 안내

- [계획·지원 범위](docs/PLAN.md), [생성 계약](docs/GENERATION.md), [HWPX 편집 API](docs/HWPX_COMPOSE.md)
- [사실 입력 모델](docs/DATA_MODEL.md), [독립 합성 예제](docs/DATA_EXAMPLES.md), [의미 검증](docs/BUSINESS_VALIDATION.md)
- [참고 그림 인용](docs/REFERENCE_QUOTATIONS.md), [출력 품질 계약](docs/OUTPUT_QUALITY.md), [편집 개선 경계](docs/REFERENCE_QUALITY_UPGRADE.md)
- [HWPX 스킬](.agents/skills/hwpx-authoring/SKILL.md), [스마트공장 작성 스킬](.agents/skills/gov-grants-smart-factory/SKILL.md)

기본 검사는 비공개 자료 없이 실행합니다. `corpus`/`native` 검사는 별도 원본·실제 출력 근거가 필요합니다. 새 출력은 실제 한컴 열기·저장·닫기·재열기·PDF 출력과 원페이지 검토를 수행해야 하며 과거 판정을 승계하지 않습니다. 이미지나 해시 일치는 실제 사업 사실·승인의 증거가 아닙니다.

커밋 규칙은 [AGENTS.md](AGENTS.md#커밋-규칙)에 있습니다. 새 checkout에서는 `bash scripts/hooks/install.sh`로 검사 훅을 설치합니다.
