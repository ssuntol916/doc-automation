# HWPX 구조 보존 생성 코어

공개 checkout에는 실제 사업 원문·참고 파생 입력·과거 native 검토 이력이 포함되지 않는다. 아래 과거 관측은 비공개 로컬 이력이며 새 출력 판정이 아니다. 현재 개선 반복은 중단 상태다. 원본 연결과 공개/비공개 경계는 [PRIVACY.md](PRIVACY.md)를 따른다.

`src/doc_automation/compose.py`는 검증된 양식의 텍스트·반복 블록·리소스를 편집하고 별도 HWPX로 저장한다. 도메인 문장 작성, 양식별 필드 매핑, 작성요령 구간 선택, 사업 사실 확인, 실제 페이지 조판은 별도 책임이다. ZIP/XML 검사를 통과했다는 이유로 네이티브 한글 열기·페이지 품질·제출 적합성을 승인하지 않는다.

## 원본과 범위

현재 1단계 inventory의 원본 21개와 SHA-256을 연결한다. 이 중 v2 개발산출물 19개가 실제 생성기의 공통 대상이며, 루트 2025 서식자료와 개발산출물 목록은 추가 원본 보존 회귀 대상이다. **34개 관련 서식 전체의 자동 생성 API가 구현됐다는 뜻이 아니다.** 원본의 상세 XML·서식 프로필은 `analysis/stage1/profiles/`에 있고 역할별 선택자는 도메인 렌더러에서 관리한다.

```python
from doc_automation.compose import TemplateDocument, HP, NS, validate_package

doc = TemplateDocument(template_path, expected_sha256=known_source_hash)
section = doc.root(1)  # OPF spine 순서의 0기반 section
table = doc.tables(1)[0]  # 해당 section의 문서순 0기반 표
doc.set_cell_text(doc.cell(table, 0, 1), "검증용 시스템")
doc.set_metadata(title="검증용 요구사항정의서", clear_legacy=True)
report = doc.save(output_path)
assert report["package_validation"]["valid"]
assert report["source_unchanged"]
assert report["native_verified"] is False
```

`expected_sha256`를 생략해도 프로젝트의 `resources/stage1/inventory.json`이 있으면 경로 또는 동일 해시로 원본 프로필을 연결하고 fingerprint를 대조한다. 별도 설치 환경에서는 해당 inventory가 없을 수 있으므로 명시 해시 또는 `profile_path`를 전달한다. 파일명만 같은 다른 양식을 승인된 원본으로 간주하지 않는다. `source_profile_id`, `source_sha256`, `template_path`, `sections`가 조회 속성이다.

## 편집 API

| API | 동작·주의 |
|---|---|
| `root(section=0)` | OPF spine 순서의 section XML. 파일명 숫자순에 기대지 않음 |
| `xml(member)` | header/OPF 등 기존 XML root. 직접 수정도 저장 시 감지 |
| `tables(section=0)` / `paragraphs(section=0)` | 중첩을 포함한 XML 문서순 목록. 분석 근거 `T1/P1`과 달리 Python 목록은 0기반 |
| `cell(table,row,col,covered=False)` | `cellAddr`의 논리 0기반 좌표. 병합 내부 좌표는 `covered=True`를 명시해야 시작 셀 반환 |
| `set_paragraph_text(p,text)` | 해당 문단 소유 `hp:t`만 교체. 자식 표·그림·구역/쪽번호/머리말 제어와 run 속성은 유지. 첫 own text run의 서식을 새 텍스트에 적용하고 다른 own text는 비움 |
| `set_text_node(t,text)` | 지정한 `hp:t`만 편집. 복합 문단은 직접 대상 텍스트를 고를 때 사용 |
| `set_cell_text(tc,text)` | 일반 텍스트 셀의 첫 문단을 사용하고 나머지 일반 문단 제거. 셀에 표·그림·수식·필드·제어가 있으면 **거부**하여 명시 편집 요구 |
| `new_paragraph(text="",prototype=None)` | prototype의 문단/run 속성만 가져온 detached 문단. 표·제어는 복사하지 않고 새 ID 부여. prototype 생략 시 첫 section 첫 문단의 서식을 쓰므로 본문에는 입력용 prototype를 명시하는 것이 좋음 |
| `append_text(container,text,prototype=None)` | 위 문단을 section 또는 subList 등에 append |
| `use_text_colour(scope,colour="#000000")` / `blacken_text_runs(scope)` | 해당 범위의 실제 소유 텍스트가 있는 run만 색 변경. 원본 charPr 정의를 고치지 않고 색/id만 다른 local 정의를 추가·재사용, itemCnt 갱신 |
| `clone_paragraph(p,insert_after=False,strip_scope_controls=True)` | 내용·서식·객체를 복사하고 인스턴스 ID 새로 부여. 기본 detached 반환. 원본의 문서범위 제어는 원본에 유지하고 복제본에서는 제거 |
| `clone_table(tbl,insert_after=False)` | 표·셀·모양·리소스 참조를 복사하고 새 인스턴스 ID 부여. 별도 카드의 경우 enclosing paragraph 복제가 더 안전 |
| `replace_body_rows(tbl,prototype_row_index,rows_count,header_rows=1)` | 앞 header_rows개 행을 남기고 body를 prototype 행의 복사본 rows_count개로 교체. 새 tr 목록 반환 |
| `repeat_header_rows(tbl,count=1)` | `tbl.repeatHeader`와 실제 제목 행 셀의 `tc.header`를 함께 설정. 반복할 행을 렌더러가 명시 |
| `use_table_pagination(tbl,break_mode=None,inline=None)` | pageBreak(NONE/TABLE/CELL)와 pos.treatAsChar만 명시 변경. 셀·열폭·높이·여백·폰트는 보존하며 CELL은 셀 내용의 다음 쪽 계속을 허용. 실제 배치는 native 검토 필요 |
| `use_character_style(scope, font=None, size_pt=None, bold=None, italic=None, colour=None, spacing_percent=None, ratio_percent=None, include_headers=False)` | 요청한 문자 속성만 local charPr로 파생. 실제 사용 run을 재연결하고 원정의와 인라인 개체를 보존. 기본적으로 머리말·꼬리말·각주·미주 제외 |
| `use_paragraph_style(scope, line_spacing_percent=None, align=None, break_latin=None, break_non_latin=None, keep_lines=None, keep_with_next=None, include_headers=False)` | 요청한 문단 속성만 local paraPr로 파생. lineSpacing은 switch의 case/default 모두 변경. 기본적으로 머리말·꼬리말·각주·미주 제외 |
| `set_page_layout(section=0, landscape=None, margins_mm=None, margins_hwp=None, sync_header_footer_frames=False)` | 선택 구역의 방향과 명시한 여백 변경. mm/HWPUNIT 중 한 단위만 지정. opt-in은 해당 구역의 직접 머리말·꼬리말 `subList.textWidth/textHeight`만 페이지 폭/거리와 동기화. 표폭·그림·쪽번호는 자동 조정하지 않음 |
| `split_section(before_paragraph, landscape=None, margins_mm=None, margins_hwp=None, discard_boundary_spacers=())` | 첫 carrier가 아닌 top-level 문단부터 새 OPF 구역으로 이동. section/column 설정과 활성 머리말·꼬리말을 복제하고 필드 ID를 재매핑. 기본적으로 빈 문단도 보존하며, 명시한 연속 순수 빈 suffix만 검증 후 제거 가능. 반환값은 새 구역 index |
| `set_table_layout(tbl, column_widths_mm=None, column_widths_hwp=None, cell_margins_mm=None, cell_margins_hwp=None)` | 명시한 논리 열폭 합으로 전체폭·병합 셀폭을 함께 변경. 셀 여백도 일관 적용. 행높이·앵커·텍스트·병합 주소는 보존 |
| `insert_picture(paragraph,data,media_type,extension,width_mm=...,height_mm=None,description="",prototype=None,raster_metadata_profile=None,viewport_pixels=None)` | 확인된 PNG/JPEG/BMP bytes를 새 inline 그림과 manifest로 삽입. 기본은 전체 이미지 비율 유지. 명시한 Mac PNG 프로필에서는 원본 payload를 보존하는 pixel viewport 선택 가능. 기존 문단 텍스트·개체는 보존 |
| `move_page_numbering(source_paragraphs,target_paragraph)` | 같은 section container의 명시된 pageNum/newNum(PAGE) 쌍을 실제 본문 시작 문단으로 이동. 동일한 중복쌍만 통합하고 충돌은 변경 전 거부. 텍스트·section·그 밖의 제어는 유지 |
| `remove(node,allow_scope_controls=False)` | 명시한 노드 제거. section/column/header/footer/pageNumber 등의 범위 제어를 포함하면 기본 거부 |
| `add_binary(data,media_type,extension)` | BinData와 OPF manifest에 충돌 없는 리소스 추가, binary ID 반환. 입력은 비어 있지 않은 bytes |
| `set_picture_image(pic,data,media_type,extension)` | 기존 그림의 geometry를 유지하고 binary 참조 교체. 새 그림 크기·비율·실제 식별성은 별도 검토 |
| `set_metadata(title=...,creator=...,subject=...,description=...,clear_legacy=False)` | 원본의 과거 제목·작성자·사업 설명 잔재를 명시적으로 교체/정리. clear_legacy는 language를 제외한 이전 메타데이터를 제거 |
| `validate()` | 현재 구성의 패키지·참조·표 격자 검사. 사실·최종 조판 검사는 아님 |
| `save(path)` | 검사 후 동일 디렉터리 임시 ZIP에서 검증하고 원자적으로 교체. 원본·hardlink·원본 자료 트리에는 쓰기 거부 |
| `validate_package(path,source_path=None)` | 저장된 파일의 ZIP/XML·참조·격자·ID 검사. 원본 중복 ID 예외를 정확히 적용하려면 source_path 제공 |

문자열은 `\n/\t/전각공백/줄바꿈방지공백`을 HWPX 인라인 요소와 tail로 표현한다. XML 1.0 금지 문자는 거부한다. `None`을 문자열로 강제 변환하지 않는다. 미확인 사실을 표시하는 문구는 렌더러가 상태와 근거를 보고 결정한다. 수식/필드 결과 문단을 일반 문단으로 덮어쓰는 작업도 거부한다.

문단에 여러 글자서식이 있으면 기존 각 run의 정의를 지우지 않지만 대체 문자열의 문자별 스타일을 자동 재배분하지는 않는다. 일부 강조 구간을 유지해야 한다면 `set_text_node`로 해당 run의 text를 선택하거나 렌더러가 명시적으로 구간을 만든다. 글자/문단/테두리 ID는 **파일 로컬 정의**다. 다른 문서의 숫자 ID를 가져오지 않는다.

원본 입력칸/자리표시자의 회색·파랑이 실제 작성값에 남아 읽기 어려울 수 있다. `set_*`는 원본 서식을 보존하므로 실제 입력 영역을 검정으로 바꾸는 것은 렌더러의 명시 정책이며 `blacken_text_runs`를 호출한다. 새 charPr는 textColor/id만 바꾸고 글꼴·크기·간격·기울임·굵기와 모든 다른 속성/자식을 그대로 복사한다. 원본 정의는 전부 보존한다. 표를 감싼 run이 자식 셀의 텍스트를 자기 것으로 중복 처리하지 않으며, 비어 있는 run은 바꾸지 않는다. 원본 header 바이트 불변은 색 API를 쓰지 않았을 때의 계약이고 색 API를 쓸 때는 원본 정의 보존+추가가 계약이다.

## 카드와 행 반복

AD2·TD3·TD4 상세카드의 enclosing paragraph에는 표 외에 section/쪽번호 제어가 함께 있을 수 있다. 최초 원본 블록은 제어를 유지한 채 사용하고 추가 카드만 복제한다.

```python
base_p = doc.root(1)[0]  # 실제 양식 프로필로 확인한 위치
extra_p = doc.clone_paragraph(base_p)
extra_table = next(extra_p.iter(HP + "tbl"))
doc.set_cell_text(doc.cell(extra_table, 1, 1), "QA-AD2-002")
doc.root(1).append(extra_p)
```

기본 복제에서 secPr/colPr/header/footer/pageNum/newNum/pageHiding은 원본에 남고 복제본에서 제거한다. 이때 빈 `hp:ctrl` wrapper와 범위 제어만 담았던 빈 run도 정리한다. `strip_scope_controls=False`는 실제 문서범위 제어가 필요한 경우에만 명시한다. 일반 반복카드에 이를 쓰면 구역·쪽번호를 다시 시작할 수 있다. 기존 guide/samplefacts가 남는지, 빈 안내 서명란을 실제 승인처럼 채우지 않았는지는 렌더러와 품질검사에서 확인한다.

원본 21개 모두에서 `secPr`은 각 section의 **첫 top-level 문단 own run**에 정확히 한 개 있다. 이 carrier 문단 앞에 공지/합성 표시/새 제목 문단을 삽입하지 않는다. 합성 표시는 별도 기존 표지 문단을 바꾸거나 첫 carrier 뒤에 삽입한다. 코어는 이 불변과 빈 `hp:ctrl` 금지를 검사한다. XML 파싱만 성공해도 네이티브 앱이 열 수 없는 구조가 될 수 있으므로 section 제어의 위치·wrapper를 데이터 없는 장식으로 취급하면 안 된다.

행 반복은 가로 병합을 보존하지만 prototype의 세로 병합은 거부한다. header/body 경계를 넘는 세로 병합도 거부한다. AD3의 예시 분류 병합을 무턱대고 복제하지 말고 원본 비병합 행 R8 또는 R9를 prototype로 삼는다.

```python
table = doc.tables(0)[1]  # AD3, T2
rows = doc.replace_body_rows(table, prototype_row_index=8,
                            rows_count=len(features), header_rows=1)
doc.repeat_header_rows(table, count=1)
for row_index, feature in enumerate(features, start=1):
    doc.set_cell_text(doc.cell(table, row_index, 0), feature["major_category"])
```

CD1은 header_rows=1, 통합시험 TI1 케이스 행은 header_rows=4/prototype=4처럼 양식마다 다르다. body 0개는 제목 행만 남기며 거짓 시험 1건을 생성하지 않는다. 원본 셀 폭·여백·borderFill·글자/문단 참조·가로 colspan은 보존하고 `cellAddr.rowAddr`, `rowCnt`, 표 높이만 필요에 따라 바꾼다. **표 높이는 원본 cellSz/줄 캐시/셀 여백에 근거한 추정치**이며 한글 조판 결과가 아니다. 긴 문자열·추가 줄·그림에 따른 실제 셀 확장·쪽분할·머리행 반복을 네이티브 출력으로 확인한다.

## 문단의 쪽 유지 속성

`doc.use_paragraph_keep(p, keep_lines=None, keep_with_next=None)`는 선택한 문단의 local paraPr를 파생해 `hh:breakSetting/@keepLines`와 `@keepWithNext` 중 명시한 bool만 `1/0`으로 바꾼다. None은 상속값을 유지한다. 원본 정의·여백·줄간격·폰트·다른 break 속성은 수정하지 않고 동일 변형은 재사용하며 paraProperties.itemCnt를 갱신한다. 이 API는 문단 선택이나 짧은 문단 판단을 자동으로 하지 않는다. 적합한 source breakSetting/속성이 없으면 추측해 추가하지 않는다.

현재 원본의 본문 paraPr에는 keepLines=0/keepWithNext=0이 있다. narrative 프로필은 짧은 텍스트 문단에 keepLines만, 제목에는 keepWithNext만 요청한다. 긴 표 문단이나 이어지는 전체 본문을 강제로 묶는 정책은 아니다. 속성의 실제 쪽 배치 효과는 수정된 현재 바이트를 한글에서 재출력해 검토해야 한다.

## ID, 필드와 리소스

원본 21개에는 p.id=`2147483648`과 `0`가 다수 반복되고 secPr/colPr/subList의 빈 id가 있다. 이를 표·그림 인스턴스의 새 중복과 동일하게 취급하지 않는다. 무편집 저장은 이 원본 값을 보존한다. 검사는 **원본 baseline에서 허용되던 중복 수보다 늘어난 충돌**을 거부한다. 원본을 받지 않은 독립 검사는 알려진 paragraph sentinel만 예외로 두므로 원본의 다른 예외가 있으면 추가 확인이 필요하다.

복제 문단·표·그림·shape·fieldBegin에는 기존 ID와 충돌하지 않는 새 수치 ID를 부여하고 `instid`도 갱신한다. 필드는 begin ID, end.beginIDRef, 양쪽 fieldid를 쌍으로 새로 매핑한다. 필드 쌍의 반쪽만 포함한 복제는 거부한다. 링크된 subList의 외부 참조를 자동으로 추측하지 않으며 nonzero linkList 참조가 있으면 명시 매핑을 요구한다.

기존 그림의 binary는 동일 패키지 안에서 공유할 수 있다. 복제만으로 바이너리를 다시 넣지 않는다. 새 바이너리는 OPF manifest와 함께 등록하고 누락·중복 리소스 ID를 검사한다. 이 코어는 19종 원본의 header 정의를 재설계하거나 다른 양식의 스타일·리소스를 무조건 합치는 프레임워크가 아니다.

## 버전을 지정한 새 PNG 좌표

`insert_picture(..., raster_metadata_profile="hancom-mac-12.30.0-png")`는 Mac 한컴 Office HWP 12.30.0(build 6544)의 전체 PNG clip/dimension 저장 동작을 반영하는 선택 옵션이다. PNG의 pixel×75 원좌표를 `orgSz`·사각형·배율에 유지하고 `imgClip`·`imgDim`만 가까운 60 HWPUNIT로 반올림한다(정확한 중간값은 위로). 원 PNG·표시 크기·전체 비율은 보존한다. 이는 해당 버전의 실제 viewport 순회와 새 API 진단 14개에서 확인한 동작이며 표준·다른 한컴 버전의 규칙이 아니다.

기본값 `None`은 기존 좌표를 유지한다. 명시한 모드에 알 수 없는 이름 또는 PNG 이외의 형식을 주면 삽입 전에 거부한다. 생성기는 JPEG에는 모드를 적용하지 않으며, BMP는 먼저 무손실 PNG로 변환한다. 기존 그림을 변경하지 않는다. `save()`의 `inserted_picture_metadata`는 선택과 실제 좌표를 기록하고 native QA는 계속 `false`다. 실제 문서별 Save As·재열기·현재 PDF/PNG 검토와 strict 비교를 생략하지 않는다.

`viewport_pixels=[left,top,right,bottom]`은 이 프로필을 명시한 새 PNG에만 사용할 수 있다. 원본 픽셀의 반열림 영역이며 정수·경계·비어 있지 않은 부분 영역을 삽입 전에 검사한다. 전체 원본은 기본 경로로 넣고 부분 보기를 별도로 추가한다. full payload·`orgSz`·전체 `imgRect`를 보존하면서 `imgClip`에는 원본 픽셀×75를, 표시 크기에는 선택 영역의 비율을 사용한다. 반올림한 `imgDim`으로 crop 좌표를 재정규화하면 실제 출력에서 한 픽셀을 잃는 사례가 있어 그렇게 계산하지 않는다. 새 viewport의 source-coupled offset/matrix와 float32→6decimal 표기는 내부·모서리·작은13×9/큰509×313 진단 및 모든 그림을 표시한 뒤 재저장에서 검증했다. 표현할 수 없는 offset은 쓰기 전에 거절한다.

관측 근거와 실패한 대조군은 [native profile](../resources/picture-viewport-native-profile.json)에 보관한다. 이것은 해당 버전에서 새로 작성한 객체의 제한된 표현이다. 다른 원본의 이미 존재하는 offset·회전·clip·matrix를 이 식으로 덮어쓰지 않는다. HWPX의 전체 원본 픽셀 보존과 native PDF의 JPEG 재압축은 다른 경계이며, PDF 픽셀의 무손실 동일성을 주장하지 않는다. 확대 보기의 실제 라벨 가독성은 현재 문서별로 별도 판정한다.

## 선택한 참고 서식 프로필

기본 `generate`는 기존 보존 경로다. `--style-profile reference-v1`을 명시하면 `src/doc_automation/layout.py`의 `apply_editorial_profile(doc,role,profile=None)`이 등록된 원본용 서식 프로필을 적용한다. Python 호출은 `generate_project(..., style_profile="reference-v1")`이다. 이 옵션은 승인된 편집 범위에서 의도적으로 글꼴·간격·표폭·본문 구역을 바꾸는 경로이며, 모든 원본 서식을 불변으로 유지한다는 계약과 혼동하지 않는다.

프로필은 `resources/style-upgrade/profiles/{SF-ROLE}.json`에 있고 `schema_version=reference-editorial-profile-1`, role, source_template SHA를 대조한다. `targets`는 실제 글꼴명, `charPr.height` 단위(포인트×100), 줄간격%, 페이지·표·셀의 HWPUNIT 값을 사용한다. 숫자형 서식 ID를 다른 문서에서 가져오지 않는다. `evidence`와 `allowed_changes`는 참고 관찰과 선택한 목표를 분리하며, target이 존재한다는 사실은 native 검증 완료를 뜻하지 않는다.

현재 선택 경로는 원본별 SHA와 표지/본문 표 경계가 확인된 V2.0 19종에 한정된다. `targets.cover_roles`가 있으면 customer/program/title/date/supplier 다섯 의미 owner 문단의 **글꼴·크기·굵기**를 명시적으로 변경한다. 별도 선언된 program owner의 `breakNonLatinWord`만 문단 속성의 선택 변경으로 허용하며, 나머지 문단 속성·페이지·표·셀·앵커와 제어는 보존한다. `cover_selectors`의 원본 SHA·XML·정확한 XPath·생성 전 own text를 원본 ZIP bytes와 대조하고, 렌더러가 보존한 `_editorial_cover_paragraphs`의 element identity 및 원문 map까지 일치해야 한다. 줄바꿈 대상은 원문 문단 정의도 대조한다. 오인·누락은 편집 전에 거절한다. 사업 사실은 입력값을 유지하고 전문가의 기업명·날짜를 복사하지 않는다. enclosing customer 문단의 서식을 바꿔도 자식 표 안 program/title의 own run은 별도 대상이므로 오염시키지 않는다. 표지 합성 고지와 선택하지 않은 run, 머리말·꼬리말·각주·미주의 서식은 제외한다.

본문 구역이 없는 원본은 본문 경계에서 새 구역을 만들어 표지의 페이지 속성을 유지한다. 렌더러가 명시한 제목 역할을 우선 사용하며, 제한된 원본 구조/장절명 힌트로 고른 대상은 실제 텍스트·XPath와 함께 report에 남긴다. 한 셀짜리 서술 본문 frame을 표머리로 취급하지 않으며, 상세카드 라벨과 입력값은 서로 다른 역할로 다룬다. 표지 적용 report `cover_roles`에는 각 role·target·member·원본/현재 XPath·변경한 own run 수·실제 local ID와 해결된 폰트/크기/굵기를 기록한다.

사업명 줄바꿈의 별도 선택은 `targets.cover_program_paragraph={"break_non_latin":"BREAK_WORD"}`이다. `cover_program_paragraph_source`에는 원본 SHA·XML·XPath·문단 C14N SHA·해결된 문단 정의 C14N SHA·원래 break 값을 고정한다. 기존 표지 owner 검증을 통과한 program 문단에만 적용하며, 이미 목표값이면 파생 API를 호출하지 않는다. 보고서의 `cover_program_paragraph`에서 실제 owner·전후 local ID·changed 값과 이 생략 여부를 확인한다. 현재 Hancom12.30.0(build6544)의 속성 비교 시험에서 관측한 동작이며, 다른 버전과 임의 길이의 사업명은 별도 native 검증이 필요하다.

그림 캡션은 렌더러의 `_editorial_caption_paragraphs`에 등록한 실제 캡션 owner만 선택한다. `변경 화면`, `현행업무 흐름도`, `프로그램 모듈`처럼 이름이 다른 캡션도 의미 역할로 선택하며, enclosing 셀의 머리행 서식을 적용한 뒤 캡션 폰트·크기·줄간격을 적용한다. `화면 구성: 아래 제공 이미지 참조` 같은 안내문이나 `그림`·`표`·`출처`로 시작하는 업무 문장은 접두어만으로 캡션으로 추론하지 않는다. 현재 별도 source-caption/note target이 없는 문단은 본문 서식을 유지한다. 원본에 이미 있는 캡션을 선택하려면 별도로 검증한 정확한 owner 선언이 필요하다. `_editorial_picture_paragraphs`와 등록 캡션 문단에는 `keepWithNext`를 설정해 그림→캡션→첨부 설명의 연결을 요청한다. 그림·텍스트·셀 기하는 바꾸지 않으며 실제 페이지 분할과 읽기 크기는 현재 native 출력으로 확인한다. report `caption_selections`에 실제 owner XPath와 선택 방식을 남긴다.

반복 카드에는 같은 prototype의 열폭 override를 재사용한다. 기본 열폭 변경은 원본 논리 열 비율을 유지하며, 명시 열폭이 있으면 해당 배열을 적용한다. 전체폭·열폭 합·병합폭·여백은 함께 변하지만, 긴 ID를 축약하거나 강제 공백을 넣지 않는다. `editorial_profile` manifest report의 selector, 실제 pages/tables/changes, profile source path/SHA를 확인한다.

v7 시점의 후보 프로필은 v4의 `sync_header_footer_frames=true`를 유지한다. TD5의 테이블ID 열은 17000HWP, 비고 열은 6000HWP로 선택하고 전체 75000HWP는 유지한다. 설치된 HCR Batang 11pt의 두 검증 ID advance는 약15945.60/15899.40HWP이며 좌우 padding566HWP를 더하면 기존16000HWP 열을 넘는다. 17000HWP는 글꼴·ID·내용을 유지하는 명시적 편집 선택이며 모든 새 입력의 단일행 배치를 보장하지 않는다. 비고의 짧은 제약 참조 키는 연결된 상세에 전체 의미를 유지한다. v4 재현은 기존 v3에 `.venv/bin/python scripts/resources/tool_sources/style-upgrade/build_profiles.py --refine-native-layout`을 적용한다. 기존 v3 JSON은 `profiles/history/v3`에 원바이트로 보존하고 active index와 `native-layout-refinement-evidence.json`의 SHA를 갱신한다. 이 단계는 새 native 통과나95% 판정을 생성하지 않는다.

v5의 `targets.toc_roles`는 원본과 선택 참고에 목차가 있는14종에만 `title/entries` 두 owner의 `font_face=함초롬바탕`을 선언한다. AD3·PM1~PM4에는 목차나 target을 만들지 않는다. `_editorial_toc_paragraphs={"title": p, "entries": p}` registry와 `toc_selectors`의 원본 SHA·XML·정확한 XPath·생성 전 own text를 편집 전에 확인한다. renderer가 여러 항목을 합쳐 쓰는 첫 항목 owner만 선택하며 전체 목차 영역을 범위 선택하지 않는다. 해당 owner의 문자 크기·굵기·직접 서식과 문단 서식·페이지 기하·인라인 tail·제어는 보존한다. 참고 항목의11/12/13pt와 혼합 굵기를 일괄 복제하지 않는 것은 명시한 구현 선택이다. OS1은 인접 OS2 참고임을 유지하며 원본 목차의 pageNum/newNum도 보호한다. 참고 TI1 목차의 footer는 관찰 근거에 기록하고 새 문서에 복사하지 않는다.

v5 재현 명령은 기존 v4에 `.venv/bin/python scripts/resources/tool_sources/style-upgrade/build_profiles.py --refine-toc-fonts`다. `profiles/history/v4`를 원바이트로 보존하고, 각14종의 `.toc-evidence.json`에 원본·참고 SHA·OPF spine 순서·실제 목차 owner/run XPath·local 문자 정의·일곱 script 글꼴과 대체글꼴·크기·굵기·보호 제어를 기록한다. `validate_profile_resources.py`는 현재19종v5/목차14종28owner/미대상5종 및 history v1~v4의 index SHA와 증거 파일을 확인해 새 `resource-validation-v5.json`에 쓴다. 기존 `resource-validation.json`은 덮어쓰지 않는다. 이 정적 검증과 회귀가 성공해도 새 바이트의 native 출력·목차 실측·전쪽 편집 검토는 별도로 필요하다.

v6은 새 본문 구역 직전의 순수 빈 suffix를 원본 SHA·XML·정확한 XPath와 초기 element identity로 선언한다. 실제 대상은 AD3 두 문단·TI2 한 문단·PM1 한 문단·PM4 세 문단이다. `section_boundary_spacer_selectors` 밖 문단은 제거하지 않으며, 현재 split 바로 앞의 연속 suffix여야 한다. 본문/표지 텍스트, 개체, 필드, 머리말·꼬리말·쪽번호, 번호 문단, page/column break가 있는 문단은 순수 빈 문단으로 허용하지 않는다. 이미 renderer가 해당 원본 빈 문단을 제거했다면 `absent_before_profile`로 기록한다. PM4의 과거 출력에서 공급기업명 뒤 빈 세 줄이 portrait header-only page로 흘렀다는 진단을 위한 선택이며, 제거 후 새 native 출력으로 공백 해소를 확인해야 한다.

PM4 기능표의10열은 `[2500,9000,9000,8500,8500,8500,9000,9000,9000,2000]`HWP로 재배분한다. HCR10pt에서 시험ID advance8249HWP와 좌우 여백566HWP는 기존6500HWP를 넘으므로 시험 세 열에9000HWP를 배정한다. 화면·프로그램ID는7600+566HWP로8500HWP에 배치한다. 설명·요구사항명은 더 좁아져 줄과 행 높이가 늘 수 있으며 전체 내용과 계속 표를 native로 검토한다. 별도7열 명시 추적 비교표는 `_editorial_trace_tables` registry로 선택해 `trace_table_column_widths_hwp=[10000,16000,16000,7000,9000,8000,9000]`을 적용한다. 원래 비기능7열·반복 prototype의 폭 캐시와 분리하고 둘 다 총75000HWP를 유지한다. 연결ID의9009+566HWP는10000HWP에 들어가며, 종류/ID 경계와 긴 상태값은 여러 줄일 수 있다. 글꼴 축소·원문 ID 변조는 하지 않는다.

v6 재현은 기존 v5에 `.venv/bin/python scripts/resources/tool_sources/style-upgrade/build_profiles.py --refine-pm4-boundary`를 적용한다. `profiles/history/v5` 원바이트와 과거 검토 기록을 보존하고 `pm4-boundary-refinement-evidence.json`에 원본 owner·과거 PDF/후보 SHA·측정값·편집 선택을 기록한다. 현재 정적 검증은 `resource-validation-v6.json`에 쓰고 history v1~v5를 확인한다. v5의 결과는 기존 `resource-validation-v5.json`에 남는다.

v7의 TD3 `body_section_selector`는 원본 `Contents/section0.xml`의 `/hs:sec/hp:p[54]`인 `3. 화면(보고서) 설계`와 `/hs:sec/hp:p[55]`인 첫4열 카드 owner를 SHA·원본 own text·초기 element 위치로 확인한다. 둘 사이에는 새로 생성한 `_editorial_body_paragraphs` 등록 owner 중 `과제: `로 시작하는 plain-text intro를 최대 한 문단만 허용한다. 그 제목부터 새 가로 구역으로 이동해 앞의1/2절은 세로에 남기고 제목·허용 intro·첫 카드가 같은 구역에 속하게 한다. 새 구역이 쪽 전환을 공급하므로3절 제목의 중복 pageBreak는 해제한다. 필드·표·그림·scope control을 포함한 intro나 등록하지 않은 추가 문단은 편집 전에 거절한다. 큰 카드 전체를 keep으로 묶지 않는다. 이는 과거 strict 통과와 별개로 관찰한 portrait 제목 단독면을 고치기 위한 선택이며 새 native 출력 전 해소 판정을 내리지 않는다.

제목은 렌더러가 실제 제목으로 등록한 identity와 원본의 top-level 번호 절 제목으로 선택한다. 새로 작성한 번호 절차나 `[Tn]`·`[Cn]`·`[Fn]` 문맥 키만으로 제목을 추론하지 않는다. PM4의 `[T1] 분류`, `[T1] 출처`, 비고·검토 등 본문 값은 렌더러가 지정한 일반 굵기와 keepWithNext를 유지한다. 실제 T/C/F의 ID·이름 제목은 별도 registry에 등록해야 하며, context 값을 전부 bold/keep으로 연결하는 긴 체인을 만들지 않는다.

PM4 비기능7열은 v7에서 `[2500,9000,14000,20000,17000,9000,3500]`HWP로 재배분한다. `연결 시험: DEMO-TEST-004`는 HCR10pt에서 advance약13049+padding566HWP를 차지하므로 결과물명 열에17000HWP를 선택한다. 총75000HWP와 원문·10pt를 유지하며 기능10열과 registry 추적7열의 폭은 각각 독립적으로 유지한다. v7 재현 명령은 기존 v6에 `.venv/bin/python scripts/resources/tool_sources/style-upgrade/build_profiles.py --refine-td3-section`이다. `profiles/history/v6`와 이전 검토 기록을 보존하고 `td3-section-and-heading-refinement-evidence.json`에 원본 owner·이전 native/strict SHA·폭 측정·채택 이유를 기록한다. 현재 정적 검증은 `resource-validation-v7.json`에 쓰며 history v1~v6와 active inventory 자체의 동결 profile snapshot을 확인한다. 이전 profile snapshot의 native 판정은 현재 profile로 승계하지 않는다.

```python
# 기존 정의를 유지하며 선택한 문단의 own text run만 변경한다.
doc.use_character_style(p, font="함초롬바탕", size_pt=11,
                        spacing_percent=0, ratio_percent=100)
doc.use_paragraph_style(p, line_spacing_percent=130, keep_with_next=False)

# 새 구역의 방향과 표의 논리 열폭은 각각 명시한다.
body_section = doc.split_section(body_p, landscape=True,
                                margins_mm={"left": 15, "right": 15, "top": 15, "bottom": 15})
doc.set_table_layout(table, column_widths_mm=[30, 50, 80],
                     cell_margins_mm={"left": 1, "right": 1, "top": 0.5, "bottom": 0.5})
```

문자 API의 scope가 문단이면 그 문단이 소유한 run만, run이면 그 run만 변경한다. section/cell 등 container scope는 그 아래 실제 텍스트 run을 변경한다. `font` 문자열은 hangul/latin/hanja/japanese/other/symbol/user 일곱 script 모두에 적용하고, dict는 지정한 script만 바꾼다. 필요한 fontface를 local 정의로 추가하되 원정의와 대체글꼴 선언을 삭제하지 않는다. `spacing_percent=0`은 자간0%, `ratio_percent=100`은 장평100%이며 포인트나 페이지 HWPUNIT가 아니다. 요청하지 않은 굵기·기울임·강조·색·직접서식은 유지한다. 명시적으로 머리말 등을 편집할 때만 `include_headers=True`를 사용한다.

구역 API의 `landscape=True`는 HWPX `pagePr.landscape=NARROWLY`, 세로는 `WIDELY`를 사용한다. 원본의 짧은/긴 용지 변 길이와 orientation을 함께 해석하며 width/height를 무작정 뒤집지 않는다. 새 구역은 첫 문단에 `secPr`을 놓고 OPF manifest/spine·header.secCnt를 갱신한다. PAGE 재시작 제어는 원문 앵커에 남기고 새 구역의 startNum.page는0으로 이어간다. 새 구역 자체가 쪽 경계이므로 첫 이동 문단의 중복 pageBreak는 해제한다. 실제 쪽번호·계속 머리행·상하단·표지 숨김·목차는 현재 바이트의 한글 출력으로 다시 확인한다.

기본 구역 API는 머리말·꼬리말 frame extent도 보존한다. 페이지 방향/여백을 선택적으로 바꿀 때 `set_page_layout(..., sync_header_footer_frames=True)`를 명시하면 선택 구역 top-level 문단의 `header/footer` 직접 `subList`에 한해 `textWidth=방향을 해석한 용지폭−좌여백−우여백−제본여백`, `textHeight=해당 header/footer 거리`를 적용한다. frame의 다른 속성·ID·텍스트·자식 개체·문자/문단 서식은 보존하며, before/after 값과 XPath를 report에 남긴다. 새 구역 분리 뒤 그 구역에만 호출하므로 표지 frame은 유지한다. TD5의 과거 Hancom Office HWP12.30.0 build6544 저장에서 stale49324×4252 frame을75684×2268로 수정한 관찰이 구현 근거다. 해당 과거 native 변경을 strict 허용 예외로 만들지 않으며, 새 생성 바이트에서 저장/재열기/출력을 다시 확인해야 한다.

`insert_picture`로 새로 만드는 그림은 scale matrix를 소수 여섯 자리로 반올림하고 불필요한 후행0을 생략한다. 과거 TD3 strict SaveAs 비교에서 e5 `0.5119473684210526`이 `0.511947`로 바뀐 관찰에 따라 생성 시점부터 동일 정밀도를 사용한다. 기존 원본 그림의 matrix는 정규화하지 않으며, raster bytes·정수 display extents·clip·ID 연결은 유지한다. 이 변경은 strict 검사기의 예외가 아니며 새 그림 바이트의 native 재검증이 필요하다.

그림 삽입의 description은 설명 메타데이터이며 눈에 보이는 캡션을 대신하지 않는다. 첨부 ID/SHA·대응 화면·출처·실제/합성 구분과 캡션은 렌더러가 연결한다. `width_mm`와 `height_mm`는 최대 표시영역이다. 기본은 전체 이미지 비율을 유지하고, 명시한 viewport는 전체 payload를 유지하면서 선택 영역 비율로 맞춘다. 입력 bytes의 실제 포맷과 MIME/확장자가 다르면 거절한다. 새 그림이 들어갔다는 사실은 캡처의 진위·승인·인쇄 식별력의 증명이 아니다. 슬롯별 첨부 지원 범위는 현재 렌더러와 생성 문서를 확인한다.

## 의미 구성·서식 적용·native 저장의 세 경계

1. **원자료/양식→내용 구성:** 값·타입·ID·방향·관계·상태·출처와 문서 확인 위치를 대응한다. raw JSON을 업무 문장·표로 바꾸는 의도한 텍스트 변환은 기록하고, JSON 문자열 완전 일치로 의미 보존을 판정하지 않는다. `false/0/null/빈문자열`과 미확인·미수행의 구별을 유지한다.
2. **내용 구성→서식 적용:** 작성 텍스트·셀 소유권·개체 연결을 유지하고 선택 프로필의 허용 서식 차이만 실제 정의로 확인한다. 표지는 명시한 다섯 owner의 글자 속성과 별도 선언한 program 문단의 breakNonLatinWord 외 모든 기하·문단·개체·제어를 보호하고, 고정 문구·허용 범위 밖 개체도 계속 보호한다.
3. **서식 적용→native 저장:** 이미 선택한 서식을 적용한 현재 bytes가 strict 비교 기준이다. 한컴 저장 중 의도하지 않은 폰트·간격·표·그림·구역 변화는 새 프로필 허용 변경으로 면제하지 않는다. fallback 복원도 아래 별도 절차와 새 최종 bytes QA를 따른다.

새 편집 API와 후보 프로필은 구현·기계 검사 범위다. 참고 수준95% 목표, 전체19종의 최종 편집 적합성과 native 재저장 검토는 현재 진행 중인 출력별 근거가 확보되기 전까지 pending이다. 기존 `reviewed-suite`의 과거 해시·PDF나 회귀 통과를 새 프로필의 완료 판정으로 승계하지 않는다.

## 변경 감지와 저장

무편집 roundtrip은 모든 기존 ZIP 멤버의 바이트를 보존한다. 수정 XML만 재직렬화한다. 패키지 전체의 ZIP 압축 스트림 자체가 원본과 같아야 한다는 뜻은 아니다. `mimetype`은 첫 멤버이자 무압축으로 저장하고 나머지 기존 멤버의 ZIP 속성·압축방식은 유지한다.

수정된 문단과 그 레이아웃에 영향받는 조상 문단의 파생 줄 캐시를 대상으로 무효화한다. 나머지 문단의 캐시, table/page geometry, margin, shape transform, borderFill/charPr/paraPr 정의를 일괄 삭제하지 않는다. `root()`로 직접 바꾼 문단도 저장 시 fingerprint로 감지한다. 이 캐시 정책의 실제 네이티브 호환성은 현재 생성물로 별도 시험해야 하며 파싱 성공으로 추정하지 않는다.

본문이 바뀌면 `Preview/PrvText.txt`를 현재 소유 텍스트로 갱신하고 오래된 `Preview/PrvImage.*`를 제거한다. 관련 manifest/container/RDF 선언이 있으면 함께 정리한다. 미리보기 그림이 본문 리소스로도 사용되면 자동 삭제하지 않고 거부한다. 오래된 썸네일을 남겨 기존 기업·예시가 새 문서에 보이는 것을 방지하기 위한 정책이다. 실제 새 미리보기 생성은 한글 재저장으로 확인해야 한다.

`save()`는 source의 현재 해시를 다시 비교한다. 검증 실패 시 기존 output을 덮어쓰지 않는다. 보고서에는 output/source SHA-256, profile ID, 변경/제거 멤버, package 검사 결과, `source_unchanged`, `native_verified=false`를 남긴다. 출력 파일을 수정한 뒤 이전 네이티브 승인이나 PDF를 그대로 재사용하지 않는다.

## native 저장 후 대체글꼴 선언 보존

한글 Save As가 `hh:substFont`를 제거했다면 숫자 ID 재배치로 면제하지 않는다. 이 코퍼스의 PM3에서 선언11개가 소실됐으며 실제 사용 선언5개·비어 있지 않은 소유 문단7개가 영향을 받았다. 이는 macOS 한글 12.30.0 build6544에서 관찰한 저장 한계이며 성공 서식 규칙이 아니다.

별도 [restore_native_font_fallbacks.py](../scripts/restore_native_font_fallbacks.py)는 같은 언어의 primary font 정의에서 local ID를 제외한 속성·text·자식이 모두 일치하고 전후 대응이 유일한 경우에만 빠진 `substFont`를 원문 그대로 복원한다. 임베디드/resource-backed 글꼴·기존 fallback 충돌·중복 대응·다른 정의 변화는 거부한다. `Contents/header.xml` 외 ZIP 멤버의 내용과 순서를 보존하고 새 파일·전체 멤버 해시·복원 보고서를 남긴다. 이는 compose 저장의 자동 정규화가 아닌 명시적인 package 후처리다.

실제 Save As 중간물과 복원 최종물의 path/SHA를 분리하고, 생성 전→중간물과 생성 전→복원 최종물의 독립 서식 검사를 구분한다. 최종물은 한컴에서 저장한 그대로라고 보고하지 않는다. 복원 최종 바이트를 실제 열기·닫기·재열기·PDF로 검토하는 [품질 경로](OUTPUT_QUALITY.md)가 필요하다. 다시 Save As하면 다시 바이트와 fallback을 대조하고 새 최종물의 QA를 수행한다.

## 검사 범위와 네이티브 실증

`tests/test_compose.py`는 21원본 멤버바이트 무편집 보존, 19종 최소 텍스트편집의 header/표 geometry 보존, 인라인 tail, 복합 문단의 제어·표 보존, merged row 반복, 필드 쌍 재매핑, 이미지 manifest, 캐시 변경 범위, 원본 보호·원자적 실패를 검사한다. 실행은 `.venv/bin/python -m pytest tests/test_compose.py -q`다. 로컬 원본이 없는 환경의 corpus 통합 사례는 skip된다.

이 검사는 줄바꿈·표 겹침·그림 식별·머리말 실제 출력·쪽번호·목차·한글 앱 호환성을 증명하지 않는다. 네이티브 열기 실패나 앱 crash가 발견되면 패키지 검사가 정상이어도 완료로 처리하지 않고 최소 무편집/단일편집/캐시/미리보기/메타데이터 A/B로 원인을 분리한다. 네이티브 QA는 실제 버전·현재 생성물 해시·전체 쪽수와 검토 페이지 범위·PDF/이미지 해시를 별도 `quality-review` 보고서에 남긴다.

현재 AD2 원본 기반 무편집·동일 길이 1텍스트 편집·XML 재직렬화·수정 문단 캐시 제거·미리보기 정리·메타데이터 정리 등 **7개 최소 대조물**은 Hancom Office HWP 12.30.0/build 6544에서 열림을 root 담당자가 확인했다. 이후 빈 control wrapper와 해당 제어 전용 빈 run을 함께 정리한 **추가 카드 1개 복제 대조물**도 열기·4쪽 PDF 출력에 성공했다. 2³¹ 이상 신규 ID를 유지한 복제본으로 성공했으므로 ID 범위가 crash 원인이라는 가설은 지지되지 않았다. 빈 ctrl만 제거한 경우와 빈 run만 제거한 경우를 개별 실증한 것은 아니므로 두 정리의 효과를 따로 단정하지 않는다.

파일별 해시와 성공/실패 범위는 native-open-isolation.json (로컬 자료: `verification/generation-pilot/native-open-isolation.json`), 복제 대조물 입력 해시는 compose-pruned-clone-pilots.json (로컬 자료: `verification/generation-pilot/compose-pruned-clone-pilots.json`)에 있다. 이는 열기·복제 격리 시험이며 전체 19종의 출력 승인이나 전체 PDF 시각 검토가 아니다. 최초 section 문단 위치와 복제 wrapper/run을 교정한 실제 생성물은 별도로 다시 검증해야 한다.
