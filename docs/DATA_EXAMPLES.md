# 공개 합성 예제와 비공개 참고 입력

공개 예제는 실제 사업과 무관하게 별도로 작성한 사실·가정·계산 입력이다. 실제 기업 자료를 이름만 바꾼 합성 예제로 공개하지 않는다. 원문 추출과 같은 문안 비교 입력은 저장소에 포함하지 않는다. [개인정보 경계](PRIVACY.md)를 따른다.

| 공개 입력 | 용도 |
|---|---|
| `examples/sources/demo-facts.json` | 독립 합성 원시 사실 |
| `examples/demo.project.json` | 첫 생성 대상의 합성 초안 입력 |
| `examples/demo-suite.project.json` | 19종 요청 범위의 합성 입력 |
| `examples/stress.project.json` | 장문·반복·경계값 검사 |
| `examples/style-upgrade/illustrated*/` | 합성 화면·설계 도식과 연결 입력 |
| `examples/manufact-ai-interim/content.json` | 별도 제조AI 중간보고서 합성 사례 |

모든 입력 내부 source/attachment 상대경로는 그 JSON 파일의 부모 기준이다. 합성 그림도 실행화면·설치·승인 증거가 아니다. `null`, false, 0, 빈 문자열과 계획·수행을 구분하며 실제 시험값·실행일·서명은 미확인 또는 미수행 상태를 유지한다. 합성 계산 fixture의 값은 실제 사업 실적이 아니다.

```sh
uv run python scripts/build_reference_dataset.py
uv run python scripts/audit_example_datasets.py
uv run doc-automation validate-project examples/demo-suite.project.json --report outputs/demo-validation.json
uv run python scripts/build_editorial_fixtures.py examples/demo-suite.project.json outputs/new-design-fixture --with-diagrams
```

데이터 빌더의 기본 출력은 ignored `outputs/example-datasets/`다. 공개 독립 합성 원시 입력을 수정한 경우에만 명시한 `--output-dir examples`로 파생 예제를 갱신하고 출처 SHA를 함께 검토한다. 생성기는 현재 source·첨부 SHA를 검증하며 출력별 native 검토는 별도로 필요하다.

원문 추출은 비공개 분석 profile을 `build_reference_dataset.py --reference-profile PRIVATE_PROFILE --output-dir outputs/private-extraction`에 제공한다. `audit_example_datasets.py --reference-dataset PRIVATE_DATASET`은 요청된 비공개 원문 대응도 추가로 검사한다. 이 옵션이 없으면 합성 검사만 수행하며 원문 검토를 수행했다고 보고하지 않는다.

같은 문안 재현은 `build_reference_quality_controls.py --selections PRIVATE_SELECTIONS --asset-manifest PRIVATE_ASSET_MANIFEST --reference-root PRIVATE_REFERENCES --output-dir outputs/private-controls`로 만든다. 원본 SHA·셀 소유·그림 bytes를 대조하며 `reference_extraction`/`unverified` 상태를 사용한다. 실제 원문을 독립 합성으로 재분류하지 않는다. 모든 원문 파생 입력과 출력은 비공개 로컬 영역에만 보관한다.

공개 예제의 생성·검증 성공은 실제 사업 사실·수행·승인 또는 전체 양식의 필수 증적 충족을 뜻하지 않는다. `submission_ready=false`와 문서 안 합성 고지를 유지한다.
