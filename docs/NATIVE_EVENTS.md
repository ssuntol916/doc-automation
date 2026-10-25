# Native output evidence binder

`scripts/quality_records.py` creates no native output and performs no visual review. It accepts one explicit spec per current artifact. There are no role-specific pass defaults, app-version defaults, fallback reviewers, or inferred page judgments. Missing files/observations, stale hashes, unfinished TOC measurement, and a passed judgment contradicted by evidence are rejected. Explicit pending/failed judgments remain pending/failed and fail `quality.py` verification.

The input contract is deliberately separate from the production `quality-review` schema. Existing evidence is read only. The helper writes only new `*.review.json`, `*.verification.json`, and `*.binding.json` filenames under `verification/generated`; an existing filename is never overwritten. The binding sidecar retains role, all exact input/evidence/tool hashes, JSON pointers, and the explicit final reviewer/time/judgment. Paths inside the output review are absolute.

```sh
.venv/bin/python scripts/quality_records.py SPEC.json --check-only
.venv/bin/python scripts/quality_records.py SPEC1.json SPEC2.json \
  --output-dir verification/generated/quality-v4-current
```

`--check-only` persists no review/approval record. It runs the existing `verify_quality_review` on a temporary JSON using the exact current files. Exit code 0 means all supplied specs verified as passed; 2 means rejection, pending, or failed quality. Each spec is independent, so an error in a later spec does not remove earlier newly written records. For `pending`/`failed`, the helper may write the explicit nonpassing review plus its failed verification report. Check the JSON results, not just file existence.

The entire spec/evidence inventory is hashed again immediately before writing. SHA consistency binds supplied assertions to current bytes; it cannot authenticate a UI operation or a reviewer's judgment. A quality pass does not approve project facts, signatures, execution results, or submission readiness. In particular, old pass1 records cannot establish new v4 UI actions. No new v4 approval was generated while preparing this helper.

## Spec

All fields below are required. Every file reference is `{ "path": "...", "sha256": "64 lowercase hex characters" }`. References resolve relative to the JSON containing them. Evidence JSON references additionally accept an optional RFC6901 `pointer`, for example `/documents/0`; the referenced whole JSON file is hashed before selection. `record_id` is a safe unique basename, so a stress case may use `SF-TD3-stress` while its canonical `role` remains `SF-TD3`.

```json
{
  "schema_version": "v4-quality-spec-1",
  "role": "SF-TD3",
  "record_id": "SF-TD3",
  "input": {"path": "INPUT.json", "sha256": "ACTUAL_SHA256"},
  "template": {"path": "TEMPLATE.hwpx", "sha256": "ACTUAL_SHA256"},
  "native_before": {"path": "BEFORE.hwpx", "sha256": "ACTUAL_SHA256"},
  "native_after": {"path": "AFTER.hwpx", "sha256": "ACTUAL_SHA256"},
  "pdf": {"path": "AFTER.pdf", "sha256": "ACTUAL_SHA256"},
  "render_manifest": {"path": "render-manifest.json", "sha256": "ACTUAL_SHA256", "pointer": "/documents/0"},
  "native_observation": {"path": "native-ui-observations.json", "sha256": "ACTUAL_SHA256", "pointer": "/documents/0"},
  "roundtrip": {"path": "roundtrip.json", "sha256": "ACTUAL_SHA256"},
  "toc_final": {"path": "toc-final.json", "sha256": "ACTUAL_SHA256"},
  "visual_review": {"path": "full-page-review.json", "sha256": "ACTUAL_SHA256", "pointer": "/documents/0"},
  "judgment": {
    "reviewer": "ACTUAL_REVIEWER",
    "reviewed_at": "ACTUAL_RFC3339_TIME",
    "status": "pending",
    "observations": ["Explicit actual decision and unresolved issues"]
  },
  "limitations": ["Synthetic project input; not a real execution, signature, approval or submission readiness determination."]
}
```

This is a contract example, not executable evidence. Placeholder hashes/times are rejected. The final judgment is independent of the visual reviewer identity, and must occur after the recorded native observation and visual review. A known failed native event, visual page, package check, or roundtrip requires an explicit failed final judgment.

## Native observation JSON (selected object)

The actual observer supplies the native app name, version and build. Do not copy a baseline version into an unobserved run. The five ordered events are individually explicit; no event is manufactured from file existence. `status` for each event is exactly `pending`, `passed`, or `failed`. `observed_at` is RFC3339; actions must be chronological. A pending event can explicitly state that the action has not yet been observed. `compatibility_notices` is an explicit string array (empty only when the observer actually observed none).

```json
{
  "role": "SF-TD3",
  "native_before": {"path": "BEFORE.hwpx", "sha256": "ACTUAL_SHA256"},
  "native_after": {"path": "AFTER.hwpx", "sha256": "ACTUAL_SHA256"},
  "pdf": {"path": "AFTER.pdf", "sha256": "ACTUAL_SHA256"},
  "application": {"name": "OBSERVED_NAME", "version": "OBSERVED_VERSION", "build": "OBSERVED_BUILD"},
  "observer": "ACTUAL_OBSERVER",
  "observed_at": "ACTUAL_RFC3339_TIME_AT_OR_AFTER_EXPORT",
  "compatibility_notices": ["Actual notice text, if any"],
  "events": [
    {"action": "open", "observed_at": "ACTUAL_TIME", "status": "pending", "observation": "Actual open path, error/recovery and notice observations"},
    {"action": "save_as", "observed_at": "ACTUAL_TIME", "status": "pending", "observation": "Actual destination path and save observations"},
    {"action": "close", "observed_at": "ACTUAL_TIME", "status": "pending", "observation": "Actual close observation"},
    {"action": "reopen", "observed_at": "ACTUAL_TIME", "status": "pending", "observation": "Actual final path and reopen/error observations"},
    {"action": "export_pdf", "observed_at": "ACTUAL_TIME", "status": "pending", "observation": "Actual PDF destination/export observation from the final current HWPX"}
  ]
}
```

## Full-page visual review JSON (selected object)

The actual reviewer supplies every page in physical PDF order, exactly once. All image paths/hashes must match the render manifest and current files. A page cannot pass unless `full_original_image` is true and it has nonempty actual observations. Contact-sheet-only inspection or text extraction cannot be substituted for that assertion. Each page and the whole document have explicit pending/passed/failed states; a document pass cannot hide a pending/failed page.

```json
{
  "role": "SF-TD3",
  "native_after": {"path": "AFTER.hwpx", "sha256": "ACTUAL_SHA256"},
  "pdf": {"path": "AFTER.pdf", "sha256": "ACTUAL_SHA256"},
  "page_count": 1,
  "reviewer": "ACTUAL_REVIEWER",
  "reviewed_at": "ACTUAL_RFC3339_TIME_AFTER_EXPORT",
  "status": "pending",
  "pages": [
    {"page": 1, "path": "page-1.png", "sha256": "ACTUAL_SHA256", "full_original_image": false,
     "status": "pending", "observations": ["Actual observations or explicit unreviewed status"]}
  ]
}
```

Review all current pages for clipping, overlap, overflow, repeated headers, legibility, images, header/footer, intended page sequence/TOC correspondence, sample residue, and synthetic/unperformed wording as required by `docs/OUTPUT_QUALITY.md`. Record actual page-specific observations and unresolved findings. TOC fixed point alone does not establish sensible printed-page order.

## Existing machine-evidence contracts

- Render: select a document from the existing `scripts/render_pdfs.py` output: `pdf`, `sha256`, integer `pages`, `renderer`, integer `dpi`, ordered `page_images`. The render record's `visual_review_status=pending` is never promoted into a visual pass. Reviewed image hashes come from the explicit visual JSON, since this renderer manifest does not itself store them.
- Roundtrip: the existing `scripts/audit_generated_roundtrip.py` output, with the exact before/after pair, current tool-source hash, explicit `passed`, nonempty boolean checks and errors. A report claiming pass alongside failed checks/errors is rejected. A failed report remains a failed quality check.
- Final TOC: the existing `finalize_toc.py` measurement with exact current input/active HWPX, input dataset, source/PDF hash pair, `output_written=false`, and `status=unchanged` or `not_applicable`. `updated`, failed, or incomplete measurements are rejected. `not_applicable` is accepted only for SF-AD3/SF-PM1–4; other roles require current measurements and entries.

The old `build_current_quality_records.py` is untouched and must not be used to approve these new artifacts. This helper does not change production quality validation, rendering, document generation, source documents, native outputs, or existing evidence.

## 명시적 저장 후 대체글꼴 복원 경로

일반 경로는 기존의 다섯 사건 `open, save_as, close, reopen, export_pdf`를 그대로 사용한다. `workflow`를 생략하거나 `native_save_close_reopen_export`로 명시할 수 있다. 복원 관련 필드를 일반 경로에 숨겨 넣을 수 없다. 이전 16개 기록을 만든 helper 원본은 `native-font-restoration/previous-binder/`에 원래 SHA와 함께 보존했다.

한컴 저장기가 명시된 대체글꼴을 누락한 경우에만 별도 경로 `native_save_repair_reopen`을 **spec과 native observation 양쪽에 명시**한다. 일반 품질 스키마와 `quality.py`의 검사는 그대로 유지한다. 이 경로는 역할 이름으로 예외를 주지 않는다.

1. spec과 observation에 `native_saved`를 추가한다. 실제 한컴 Save As로 생성한 중간 파일의 정확한 path/SHA다. `native_after`는 그 뒤 제한적 package postprocess로 생성한 최종 파일이다. 두 파일은 경로와 SHA가 달라야 한다.
2. spec과 observation에 `package_postprocess` 파일 참조를 추가한다. 전체 report를 참조해야 하며 JSON pointer는 허용하지 않는다.
3. 다음 여덟 사건을 실제 관찰과 시간으로 기록한다. 모든 사건에 `status`, `observed_at`, 비어 있지 않은 `observation`, 아래 대상의 `artifact` path/SHA가 필요하다.

| 순서 | action | artifact 대상 |
| --- | --- | --- |
| 1 | `open` | `native_before` |
| 2 | `save_as` | `native_saved` |
| 3 | `close_saved` | `native_saved` |
| 4 | `package_postprocess` | `native_after` |
| 5 | `open_final` | `native_after` |
| 6 | `close_final` | `native_after` |
| 7 | `reopen` | `native_after` |
| 8 | `export_pdf` | `pdf` |

`package_postprocess` 사건에는 동일 report의 `report` path/SHA도 필요하다. 이 사건은 완료된 복원의 보고서와 연결되므로 `passed`여야 한다. 나머지 관찰 없는 사건을 자동 통과시키지 않는다. `close_saved ≤ report.recorded_at ≤ package_postprocess ≤ open_final`을 비롯해 전체 시간 순서를 검사한다. 과거 중간 파일의 export를 최종 파일의 export로 바꿔 기록할 수 없다.

복원 도구는 다음과 같이 실행한다. 기존 파일은 덮어쓰지 않는다.

```sh
.venv/bin/python scripts/restore_native_font_fallbacks.py \
  --reference-source GENERATED_BEFORE.hwpx \
  --native-saved ACTUAL_NATIVE_SAVE_AS.hwpx \
  --output NEW_RESTORED_FINAL.hwpx \
  --report NEW_POSTPROCESS_REPORT.json
```

Report 계약은 `schema_version=native-font-fallback-restoration-1`, `operation=restore_native_font_fallbacks`, `passed=true`, 시간대가 있는 `recorded_at`, `reference_source/native_saved/output/tool`의 정확한 path/SHA, `restorations`, 전체 `entry_preservation`, `changed_entries=["Contents/header.xml"]`이다. 원본의 모든 fallback 선언 수와 실제 사용된 복원 선언/소유 문단 수는 구별한다. `native_status`는 복원 시점의 실제 UI 검증 대기 상태를 유지한다. 후속 UI가 끝나도 과거 postprocess report를 고쳐 통과로 만들지 않는다.

도구는 같은 언어에서 primary font의 ID를 제외한 모든 속성·text·자식 정의가 동일하고 양쪽 후보가 유일할 때만 빠진 `substFont`를 원문 그대로 삽입한다. 임베디드/resource-backed 글꼴, 충돌한 기존 fallback, 중복 대응, 다른 정의 변경은 거부한다. 다른 ZIP member의 내용과 순서는 그대로 보존한다. binder는 report의 통과 주장에 의존하지 않고 현재 세 파일 및 도구 SHA, 제한된 변환, 모든 ZIP member hash를 다시 계산한다. 서식 차이를 정규화하거나 native roundtrip 검사를 면제하지 않는다.

최종 파일은 “한컴 Save As 그대로”가 아니다. 기록의 native 검사는 실제 중간 저장, 별도 package 복원, **복원된 현재 바이트의 실제 열기·닫기·재열기·PDF export**를 구분해서 설명한다. 다시 한컴 Save As를 하면 fallback이 재차 소실될 수 있다는 관찰 환경의 한계는 명시하며, 이를 긍정적인 문서 스타일 규칙으로 취급하지 않는다. 최종 PDF·원본 전쪽 시각검토·TOC 고정점·독립 12항목·검토자 판정은 일반 경로와 동일하게 모두 필요하다.
