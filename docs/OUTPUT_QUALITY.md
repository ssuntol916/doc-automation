# 생성물의 현재 바이트와 네이티브 출력 검토

`verify-output`은 [quality-review.schema.json](../schemas/quality-review.schema.json) 형식의 검토 기록과 현재 파일의 연결을 검사한다. 생성 성공·XML 파싱 성공과 실제 한글의 편집·인쇄 품질은 별개다.

```sh
uv run doc-automation verify-output 검토.json --input 사업.json --template 양식.hwpx --report 검사결과.json
```

검토 JSON 안의 상대 경로는 해당 JSON의 폴더를 기준으로 한다. CLI의 입력·양식 경로는 호출 위치를 기준으로 해석한다. 한글에서 현재 HWPX를 열어 오류·복구 안내 유무를 확인하고 PDF를 출력한 뒤 Poppler로 모든 페이지를 렌더한다. 저장·수정으로 HWPX 바이트가 바뀌면 그 바이트에서 PDF를 다시 출력하고 영향받는 검토를 다시 수행한다. 열기만 한 파일을 편집·저장 시험을 통과했다고 보고하지 않는다.

검사 범위는 입력·양식·HWPX·PDF·전체 페이지 이미지 SHA, ZIP/XML과 spine의 기초 구조, PDF 실제 쪽수, 렌더와 시각검토의 페이지별 일대일 대응, 전체 검사·검토 상태다. 검토에는 실제 앱 이름·버전·빌드·호환성 안내, 검토자와 시간, 검사 근거, 남은 한계를 기록한다. 페이지 반복·누락·대기 상태나 오래된 파일의 해시는 통과하지 않는다.

현재 패키지의 서식·이미지 참조, 표 주소/병합, 새 ID 충돌, 첫 문단의 구역 설정과 빈 제어 노드도 생성 코어로 재검사한다. 목차는 [실측 갱신과 재출력](TOC_FINALIZATION.md)을 거쳐 최종 바이트의 PDF와 일치하는지 확인한다.

모든 페이지에서 표 잘림·글자 충돌·넘침·반복 헤더·읽기 크기·잘못된 샘플 잔존·합성/미수행 상태를 확인한다. 확대 검토가 필요한 표·긴 문장·연속 페이지는 별도로 확인한다. PDF 텍스트 추출이나 바깥쪽 좌표 검사만으로 육안 검토를 대신하지 않는다.

목차 고정점과 인쇄쪽의 정상 순서는 별도 검사다. 목차가 정확히 `2, 1`을 가리켜도 본문 번호의 역행은 품질 문제다. 여러 구역의 의도된 재시작과 제거한 작성지침에 남은 재시작을 구별한다. 좁은 칸의 긴 출처·상태 설명은 짧은 참조와 전체 상세 영역으로 나누며 내용은 보존한다.

한글 재저장 전후의 독립 의미 보존 검사는 실행 방법과 한계 (로컬 자료: `verification/generated/roundtrip-review.md`)를 따른다. 관찰한 생성물의 현재 단계별 상태와 재검토 대기 범위는 5단계 증거 (로컬 자료: `analysis/stage5/README.md`)에 있다.

일반 native 경로는 실제 `open → save_as → close → reopen → export_pdf`의 다섯 사건을 구분한다. 관찰 시각·앱 버전·입력/저장 결과/PDF 해시를 기록하며 파일 존재만으로 사건을 채우지 않는다. 여러 근거를 결합하는 보조 도구의 명시적 계약 (로컬 자료: `verification/generated/build_v4_quality_records.md`)은 `verify-output`과 별도이며, 마지막 검토자 판정도 native·전쪽 시각검토 뒤에 남긴다.

Save As에서 대체글꼴이 소실되면 local 숫자 ID 변화나 글꼴 정규화로 면제하지 않는다. [제한 복원 도구](../scripts/restore_native_font_fallbacks.py)는 동일 언어·유일한 primary 정의 대응에서 빠진 정확한 `substFont`만 복원한다. 중간 native 저장물 `native_saved`, 복원 최종물 `native_after`, 전체 복원 report `package_postprocess`를 서로 다른 path/SHA로 연결하고 `workflow=native_save_repair_reopen`을 명시한다. 이때 여덟 사건은 `open → save_as → close_saved → package_postprocess → open_final → close_final → reopen → export_pdf`다. 각 사건의 실제 대상 artifact·시각·관찰을 남기며, 저장 중간물의 옛 PDF를 최종물의 PDF로 재사용하지 않는다.

복원 보고서의 정적 통과와 최종 파일의 native QA는 별개다. 복원 당시 report의 pending 상태를 나중에 수정해 과거 실행을 통과로 만들지 않는다. 현재 최종물의 독립12항목·PDF·전쪽 원본 이미지·목차 고정점·검토자 판정은 일반 경로와 동일하게 필요하다. PM3에서 선언11개(사용5개)가 제거된 관찰은 현재 복원 보고서 (로컬 자료: `verification/generated/native-font-restoration/current/package-postprocess.json`)에 있다. 재차 Save As하면 fallback을 다시 확인하고 그 새 바이트에서 QA를 반복한다. 이 환경의 한계를 모든 한컴 버전의 동작으로 일반화하지 않는다.

기록에 한컴·Poppler가 적혀 있다는 사실만으로 실제 프로그램의 실행이나 검토자의 판단 진위를 증명할 수는 없다. 이 도구는 관찰 기록과 현재 바이트의 정합성 검사를 제공한다. `passed=true`도 사업 사실·시험 수행·서명·승인·제출 적합성을 승인하지 않는다. 그 판단은 공통 데이터 검증과 실제 담당자의 근거 검토를 별도로 요구한다.
