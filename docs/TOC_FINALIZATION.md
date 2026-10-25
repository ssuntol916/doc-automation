# 실제 출력에 근거한 목차 쪽수 확정

`src/doc_automation/toc.py`와 `scripts/finalize_toc.py`는 **현재 HWPX에서 한컴으로 출력한 PDF**의 본문 기준점을 측정해 목차를 갱신한다. PDF 파일 순서와 본문 인쇄쪽을 구별하며, 찾을 수 없는 기준점의 쪽수를 추정하지 않는다. 목차가 바뀐 HWPX는 다시 네이티브 출력해야 한다. 이 도구의 고정점 판정은 전체 페이지의 시각검토·사업 사실·승인·제출 적합성을 대신하지 않는다.

## 입력과 역할

입력은 생성 HWPX, 해당 바이트에서 출력한 native PDF, 생성에 쓴 사실 JSON, canonical 역할 코드, 다른 출력 경로다. 원본 `_templates`/`_references`는 수정하지 않는다. 사실 JSON의 요구사항/화면/프로그램/DB/시험 ID와 렌더러의 현재 `_toc_entries` 계약으로 목차 항목을 연결한다. 원본 예시 목차를 임의 사업의 완료된 목차로 간주하지 않는다.

14개 역할 AD1/AD2/TD1~5/CD1/TI1~4/OS1~2에는 목차가 있다. **SF-AD3와 SF-PM1~4는 `not_applicable`**이며 새 파일을 쓰지 않는다. 프로필과 다르게 목차가 생겼다면 자동 적용하지 않고 `UNEXPECTED_TOC`로 중단한다. 관련 34서식의 목차나 임의의 다른 HWPX는 지원 범위에 포함하지 않는다.

## 현재 바이트와 PDF의 연결

API의 `native_source_sha256`은 호출자가 실제 native 출력에 사용했다고 확인한 HWPX SHA-256이다. 도구는 현재 입력 바이트와 반드시 비교한다. 선택 `native_pdf_sha256`도 전달하면 PDF 바이트를 함께 대조한다. CLI는 **두 해시 모두 필수**다. manifest에는 입력 HWPX·PDF·사실 파일 경로와 해시를 남긴다.

호출자가 현재 파일의 해시를 적었다는 사실만으로 실제 한컴 실행의 진위를 증명할 수는 없다. `association_basis=caller_attested_native_export_hash_pair`는 이 경계를 나타낸다. 실제 앱 이름·버전·빌드, 열기/저장/재열기 관찰과 출력 해시는 별도 `quality-review` 보고서로 남긴다. 오래된 PDF에 새 HWPX 해시를 붙이는 행위로 출력 검증을 우회하지 않는다.

## 측정 규칙

PDF의 `목 차` 제목과 **현재 HWPX의 목차 시작/끝 문구 및 항목 순서**를 대조해 목차 페이지 범위를 찾는다. 긴 목차가 여러 쪽에 걸쳐도 그 범위와 앞표지를 본문 기준점 검색에서 제외한다. 첫 pass의 끝 표시는 `쪽수: 네이티브 출력 후 확인 예정`, 이후에는 이미 기록된 마지막 목차 항목·쪽수 문자열이다. 일치하지 않으면 `PDF_TOC_*` 또는 `TOC_CONTENT_MISMATCH`로 중단한다.

| 역할·항목 | 본문 기준점 |
|---|---|
| AD2 요구사항 | ID 값이 `요구사항 ID`와 `요구사항명` 라벨 사이 값 영역의 같은 가로 band에 존재 |
| TD3 화면 상세 | ID 값이 `화면(보고서) ID`와 `화면(보고서)명` 라벨 사이 같은 가로 band에 존재. 메뉴 구조도 등의 먼저 나온 ID는 제외 |
| TD4 프로그램 | ID 값이 `프로그램 ID`와 `프로그램명` 사이의 상세카드 첫 행에 존재 |
| TD5 테이블 | 테이블명/테이블ID/컬럼명/컬럼ID header 아래 테이블ID 열에 존재하고, 같은 data-row band의 컬럼ID 열에서 해당 테이블의 실제 컬럼 식별자도 확인. 전체 목록 고지의 ID만으로 완료하지 않음 |
| CD1 단위시험 | 단위테스트 ID/이름/시나리오/데이터 header에 따른 시험 ID 열의 첫 유효 행 |
| TI1/TI4 시험 | 테스트케이스/데이터/예상/결과 header 아래의 개별 케이스 ID. 그룹 ID와 개별 케이스 ID를 동일시하지 않음 |
| 절 제목·결함관리 | 본문 절 제목의 정확한 문자열 또는 아래 명시적 별칭. 제목 안의 번호도 함께 확인 |

AD2는 입력 kind에 따라 기능→비기능→유형 미확인 순서로 묶고 각 그룹 안의 입력 순서를 유지한다. 목차와 상세카드는 같은 순서를 사용한다. 그룹 첫 항목 label에는 그룹 제목과 줄바꿈 뒤 첫 자식 ID/이름을 함께 넣어 카드당 측정 항목 하나를 유지한다. 그룹 제목의 위치를 별도로 추측하지 않으며 해당 첫 요구사항의 실제 ID/name band를 기준점으로 쓴다. null 분류와 원래 ID는 바꾸지 않는다. 과거 선형 AD2 목차/고정점은 역사적 기록으로 보존하지만 현재 그룹 프로필로 갱신하려 하면 `TOC_CONTENT_MISMATCH`로 쓰기 전에 거부한다. 다른 역할의 기존 프로필·고정점에는 이 변경을 적용하지 않는다.

PDF raw glyph bbox로 라벨과 값의 위치를 비교하므로 한 추출 텍스트 줄 안에 여러 셀이 합쳐져도 문구 전체의 bbox를 ID의 bbox로 오인하지 않는다. ID는 대소문자를 유지하고 문자가 정확히 같아야 한다. ID 안의 조판 공백·줄바꿈은 허용하지만 인접한 다른 열을 이어 붙이지 않는다. 더 긴 ID의 접두어(`...001`과 `...0010`)도 구별한다. 동일 테이블의 여러 data row에서 반복되는 ID는 첫 유효 행을 사용한다. 미확인·누락·맥락 불명확이면 `BODY_ANCHOR_MISSING`과 찾았지만 기각한 언급의 bbox/이유를 기록한다.

절별 별칭은 현재 생성 프로필에 한정한다.

| 목차 표현 | 실제 본문 절 제목 |
|---|---|
| TD2 시스템/HW/SW/NW/도입·설치/클라우드 | 시스템 구성도/하드웨어 구성도/소프트웨어 구성도/네트워크 구성도/장비 도입 및 설치 계획/클라우드 서비스 이용 내용 |
| TI2 하드웨어/소프트웨어·전환/네트워크/초기데이터 결과 | 하드웨어 설치 결과/소프트웨어 설치 및 전환 결과/네트워크 설치 결과/초기데이터 전환 결과 |
| TI3 사용자·관리자 검토안 | 사용자 매뉴얼/관리자(운영자) 매뉴얼 |
| OS1 운영 지원 대상/기간/인력/내용 | 운영 지원 대상/운영 지원 기간/운영 지원 인력/운영 지원 내용 |
| OS2 구축계획/운영집계/KPI계산 | 시스템 구축 현황/시스템 (시범)운영 현황/KPI 계산 검토(실측 성과와 구별) |

PDF 하단의 `- 1 -` 같은 인쇄쪽을 우선한다. 중앙 최하단의 독립 숫자도 위치 조건에 따라 인정한다. 한 페이지에 서로 다른 쪽번호가 여럿 잡히면 `AMBIGUOUS_PRINTED_PAGE`로 중단한다. 인쇄쪽을 찾지 못하면 목차에 **`PDF n쪽`**이라고 명시하며 본문 쪽번호인 것처럼 숫자만 넣지 않는다. 모든 항목에 PDF 순서, 인쇄쪽, 표시 기준, 기준점·라벨·footer bbox를 남긴다. PDF 텍스트 추출은 OCR이 아니며 글자를 추출할 수 없는 스캔본을 추측해 처리하지 않는다.

## API와 상태

```python
from doc_automation.toc import finalize_toc, measure_toc, check_toc_convergence

result = finalize_toc(input_hwpx, native_pdf, input_dataset, "SF-AD2",
                      output_hwpx, native_source_sha256,
                      native_pdf_sha256=native_pdf_sha256)
```

`measure_toc(...)`는 같은 입력을 읽고 편집 없이 기준점/쪽수 manifest를 반환한다. `finalize_toc(...)`는 실제 쪽수가 들어간 항목을 `항목 ... 쪽수`로 기록하고 대기 문구를 제거한다. 기존 문단/run의 본문 서식을 유지하면서 소유 텍스트만 검정으로 처리한다. 표지·표·그림·머리말·section 첫 문단의 secPr를 덮어쓰지 않는다. 변경 XML/캐시·미리보기 처리는 compose 코어를 따른다.

편집 범위는 현재 생성 프로필의 **한 논리 문단**이다. `목 차` 다음 첫 텍스트 문단 전체가 역할·사실 입력의 예상 항목 순서와 대기 표시, 또는 각 항목의 `... 숫자`/`... PDF n쪽` 형식에 정확히 대응해야 한다(조판 공백은 무시). 항목 앞뒤의 다른 본문, 대기 표시 누락, 여러 논리 문단으로 나뉜 목차, 중복 제목처럼 범위가 불확실하면 쓰기 전에 거부한다. 이 범위 계약은 임의 원본 양식의 목차 지원을 뜻하지 않는다. 한 논리 문단이 PDF 여러 쪽에 걸치는 경우에는 기존 PDF 범위 측정을 그대로 사용한다.

목차 뒤의 빈 문단·합성 고지·설계 설명 등은 다음 pageBreak나 표까지 이어지더라도 목차에 포함하지 않는다. TOC 갱신은 선택한 한 문단의 소유 텍스트만 바꾸며, 뒤따르는 본문 문단의 텍스트·인라인 tail·제어·표·머리말은 보존한다.

| 상태 | 파일·검증 의미 |
|---|---|
| `updated` | 다른 HWPX를 작성함. `native_status=pending_reexport`, `pdf_reuse_allowed=false`. 기존 PDF로 변경 결과를 승인할 수 없음 |
| `unchanged` | 현재 HWPX의 목차 문자열이 **현재 바이트의 PDF에서 재측정한 값과 동일**함. 새 ZIP을 쓰지 않음. 현재 바이트의 TOC 고정점이며 전체 출력 합격은 아님 |
| `not_applicable` | 해당 v2 역할에는 목차가 없음. 새 파일을 쓰지 않음 |
| `failed` | 기준점·해시·목차 맥락 등의 실패. Python API는 `TocError.report`, CLI는 실패 manifest와 종료코드 2 |

현재 사용할 파일은 `active_hwpx/active_sha256`, 실제 새 파일 작성 여부는 `output_written`으로 확인한다. unchanged/not_applicable에서는 요청한 output 경로에 파일을 만들지 않으므로 그 경로가 있다고 가정하지 않는다. updated의 manifest에는 output 경로·해시와 compose 검사 결과를 함께 기록한다.

## 두 번 출력해 확인하기

첫 native PDF로 목차를 갱신한 다음 **갱신 파일에서 새 PDF를 출력**한다. 두 가지 경로를 구별한다.

1. **바이트가 그대로인 재출력:** 이전 manifest의 output HWPX를 변경 없이 출력했다면 `check_toc_convergence(previous_manifest, current_measurement)` 또는 `previous_manifest=`로 비교한다. 이전 output SHA와 현재 input SHA가 같아야 하며 이전 PDF 바이트 재사용은 거부한다. 목차 항목·표시쪽·표시 기준이 같으면 converged다. 목차가 늘어 파일 내 물리 위치만 달라졌으나 본문 인쇄쪽이 동일한 경우는 별도 `physical_pdf_positions_changed`로 남긴다.
2. **한컴이 다른 이름 저장으로 canonical 바이트를 새로 만든 경우:** 앱 재저장으로 HWPX SHA가 달라지므로 strict check에 억지로 해시를 연결하지 않는다. 재저장된 **현재 HWPX를 다시 열어 새 PDF를 출력**하고, 그 현재 해시 쌍으로 `finalize_toc`를 다시 실행한다. `previous_manifest` 없이 `status=unchanged`이면 현재 바이트·현재 PDF에서 목차가 고정점임을 직접 확인한 것이다. 다시 updated라면 새 파일을 또 출력·측정한다.

긴 목차의 wrap이나 쪽수 자릿수 변화는 페이지 배치에 영향을 줄 수 있다. 고정점 확인 뒤에도 **최종 현재 바이트**에 대한 전체 페이지 native/Poppler 시각검토가 필요하다. 옛 PDF·이미지·검토 기록은 바뀐 파일에 재사용하지 않는다.

## 실행 예시

```sh
.venv/bin/python scripts/finalize_toc.py input.hwpx native.pdf \
  --dataset project.json --role SF-AD2 --output toc-pass1.hwpx \
  --native-source-sha256 HWPX_SHA256 --native-pdf-sha256 PDF_SHA256 \
  --manifest toc-pass1.json

# 위 output에서 실제 한컴으로 새 PDF를 출력한 뒤, 바이트 불변 경로의 측정
.venv/bin/python scripts/finalize_toc.py toc-pass1.hwpx native-pass2.pdf \
  --dataset project.json --role SF-AD2 --measure-only \
  --native-source-sha256 CURRENT_HWPX_SHA256 --native-pdf-sha256 NEW_PDF_SHA256 \
  --previous-manifest toc-pass1.json --manifest toc-pass2.json
```

단독 스크립트는 설치된 프로젝트의 Python 환경에서 실행한다. 루트 CLI·렌더러 파일은 이 도구가 수정하지 않는다. 실패 시 기존 output을 덮어쓰지 않고 원인 report를 남긴다. manifest 경로가 입력/출력 파일이나 읽기 전용 원본을 가리키면 거부한다.

## 실제 실증과 회귀 범위

`verification/generation-pilot/AD2-fixed.hwpx/.pdf`의 실제 native 출력에서 요구사항 3건은 **PDF 3·4·5쪽 / 인쇄 1·2·3쪽**으로 측정됐다. 그 값으로 갱신한 `AD2-toc-pass1.hwpx`를 root 담당자가 한컴으로 다시 출력했으며, 현재 새 PDF에서도 같은 1·2·3이 측정되어 고정점을 확인했다. 입력/출력 해시·bbox와 결과는 pass1 manifest (로컬 자료: `verification/generation-pilot/AD2-toc-pass1.json`), pass2 수렴 기록 (로컬 자료: `verification/generation-pilot/AD2-toc-pass2-convergence.json`), 최종 도구·검증 기록 (로컬 자료: `verification/generation-pilot/toc-verification.json`)에 있다. 이 AD2 실증을 다른 역할의 native 검토 완료로 일반화하지 않는다.

`.venv/bin/python -m pytest tests/test_toc.py -q`는 실제 AD2 native 두 pass, stale source/PDF SHA, 누락·접두어 ID, 메뉴/고지의 우연한 ID, 상세카드/DB 열 맥락, 줄분리 ID, 명시적 절제목 별칭, PDF쪽 fallback, paragraph scope, 업데이트 뒤 native 대기, 이전 PDF 재사용 금지, 원본 보호·CLI 실패기록을 검사한다. 합성 PDF fixture는 좌표/파서 회귀 자료이며 실제 한컴 출력이라는 증거가 아니다.

2026-10-24 범위 회귀는 기존에 해시 쌍이 기록된 14개 역할의 실제 seed/PDF와 기존 고정점 9기록(8역할)을 재사용한다. 수정 전에는 TD4·TD5·TI2·TI3·OS1·OS2의 목차 뒤 고지가 지워졌고, TD5 `Contents/section0.xml /hs:sec/hp:p[31]`의 첫 테이블 설명·복합 UNIQUE도 사라졌다. 같은 실제 입력의 보존 검사가 수정 전 7실패/17통과, 수정 후 전체 TOC 회귀 46통과다. 14개 업데이트는 목차 외 모든 최상위 문단 subtree(소유 텍스트·tail·제어·표 포함)와 header 바이트가 같고, 기존 고정점은 모두 새 파일을 쓰지 않는다. 불확실한 목차 거부와 한 논리 문단/두 PDF 목차 쪽도 별도 검사한다.

근거는 수정 전 소스 해시 (로컬 자료: `verification/generated/toc-scope-fix/before-source-sha256.json`), 수정 전 실패 (로컬 자료: `verification/generated/toc-scope-fix/before-recorded-native-regression.txt`), 수정 후 회귀 (로컬 자료: `verification/generated/toc-scope-fix/after-regression.txt`), 입력·출력 해시 및 문단별 보존 기록 (로컬 자료: `verification/generated/toc-scope-fix/verification.json`)에 있다. 이전 도구 사본·오류 출력과 새 업데이트는 각각 `toc-scope-fix/before`, `toc-scope-fix/after/seed`에 격리했다. **새 출력 14개는 모두 `pending_reexport`**이며 이 회귀에서 native 실행·새 PDF 출력·시각검토를 수행하지 않았다. 기존 PDF는 수정 전 seed 바이트에만 연결되며 새 출력의 최종 페이지 품질 근거로 사용할 수 없다.

참고 편집 개선 이후 TI2·OS1은 입력의 null만으로 미설치·미수행·실인원 부재를 단정하지 않는 중립 목차를 사용한다. 따라서 과거 `toc-v4-ready13`의 TI2(`계획/미설치` 등)와 OS1(`지원 계획/실제 미수행` 등)는 현재 계약과 호환되지 않는다. 원본 HWPX·PDF·사실 입력과 기록 해시는 그대로 보존하고 `TOC_CONTENT_MISMATCH`·출력 미생성·세 입력의 바이트 불변을 회귀로 검사한다. 실제 거부와 해시·XML 위치 진단 (로컬 자료: `verification/semantic-v5/historical-toc-diagnostic.json`)에 원인이 있다. strict label 검증을 완화하거나 과거 목차를 현재 프로필로 자동 승인하지 않는다.

현재 기록된 seed 중 업데이트 호환 검사는11건이며, 별도의 TD5 설명 보존 검사1건을 더하면12개 positive 검사다. 앞서 분리한 선형 AD2와 이번 TI2·OS1은 역사적 거부 사례다. TI2·OS1의 현행 중립 목차는 각4개 절을 가진 **합성 PDF 좌표 fixture**로 갱신·본문/표/제어/header 범위 보존·인쇄쪽 대응을 검증한다. 이2종의 새 native 해시 쌍 검토를 대신하지 않으며, 이 계약 변경 자체로 과거 native 출력 기록의 완료 상태를 새 생성 바이트에 승계하지 않는다.
