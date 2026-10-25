# 패키지 분석과 보존 편집

근거 자원은 repo의 `docs/FORMAT_SOURCES.md`, `src/doc_automation/hwpx.py`, `docs/HWPX_COMPOSE.md`와 분석 프로필이다. 경로는 `scripts/run.py path <repo상대경로>`로 찾는다. 현재 분석 구현은 코퍼스에서 확인한 2011 본문 네임스페이스를 지원하며, 다른 네임스페이스를 임의 변환하지 않는다. 공식 규격 출처를 현재 코드의 모든 XSD/버전 지원 증명으로 해석하지 않는다.

## 분석할 때

1. 원본 파일 SHA·패키지 구성과 `Contents/content.hpf` manifest/spine을 기록한다. 디렉터리 이름 정렬로 구역 순서를 대신하지 않는다. spine 참조·구역 누락/중복도 확인한다.
2. 표/셀 병합·논리 주소, 페이지 속성·여백·방향, 개체의 앵커·크기·감싸기, 머리말/꼬리말·필드·수식·BinData 관계를 추출한다. 보이는 텍스트만으로 편집 범위를 정하지 않는다.
3. 문단 텍스트는 해당 문단에 속한 `hp:t`만 읽는다. 인라인 자식의 tail도 읽고 줄바꿈/탭/특수공백을 보존한다. 외곽 문단에 표의 셀 텍스트를 중복 포함하지 않는다.
4. 서식은 실제 사용 run의 `charPrIDRef`·`paraPrIDRef`·`styleIDRef`와 header의 글꼴·크기·간격·색·테두리 정의를 함께 해결한다. 같은 숫자 ID가 두 문서에서 같은 서식을 뜻하지 않는다.

원본의 여러 추출 산출물은 좌표 관례가 다를 수 있다. 공통 프로필의 `#Tn/R0C0`는 `cellAddr` 기반0이며, 별도 상세 보고서의 물리 셀 표기와 혼용하지 않는다. 항상 해당 파일의 locator 설명·XPath·실제 `cellAddr`를 확인한다.

## 바꿀 때

수정은 승인된 입력값과 검토한 프로필의 텍스트 소유 위치에 한정한다. 단순 텍스트 문단/셀인지, 복합 개체를 포함한 문단인지 먼저 검사한다. 바뀌지 않는 패키지 멤버는 가능한 그대로 유지하고 변경 목록·해시를 남긴다.

- 일반 텍스트를 바꿀 때도 목적에 맞는 run의 문자모양·문단모양을 보존한다. 굵기·색·수치 단위가 의미를 구분하면 전체를 한 run으로 평탄화하지 않는다.
- 표는 의미 반복 단위(전체 상세 카드/행/그룹)를 프로필로 정한다. 병합 범위·셀 주소/폭·표 높이·분할 속성·반복 머리행을 갱신한다. 행 수만 늘리고 주소/병합/페이지 처리를 방치하지 않는다.
- 복제되는 개체·참조 ID는 파일 안의 유일성과 관계를 보존한다. 다른 파일에서 가져온 서식 숫자나 이미지 참조를 해결 없이 붙이지 않는다.
- 현재 양식의 `secPr`은 구역 첫 문단의 run에 있다. 그 앞에 고지 문단을 넣어 구역 설정을 뒤로 밀지 않는다. 반복 카드에서 구역/단/쪽 제어를 제거할 때는 빈 `hp:ctrl`과 제어 전용 빈 run도 함께 정리한다. 이 코퍼스의 복제 실증에서 빈 제어가 남은 파일은 한컴이 종료됐고, 정리한 파일은 정상적으로 열렸다.
- `hp:p` 내부에 `tbl`, 그림, 수식, 필드, 구역/단·쪽 제어, 머리말/꼬리말 등이 있으면 전체 내용을 지우는 방식으로 교체하지 않는다. 해당 텍스트 노드/전용 반복 블록을 수정한다.
- 작성요령과 입력 예시를 색만으로 판별해 삭제하지 않는다. 문서별 안내 블록과 업무 내용을 구분한다. 고정 약정·동의·규정 문구는 요청 없이 재작성하지 않는다.
- 저장된 줄 위치/캐시와 목차의 인쇄쪽은 편집 후 실제 출력과 달라질 수 있다. 캐시 처리와 목차 갱신은 현재 compose API를 따르고 실제 페이지로 확인한다.

## 선택한 서식 변경

기본 생성은 기존 보존 경로다. 사용자가 참고 수준의 서식 개선을 요청한 경우 등록된 역할에서 `--style-profile reference-v1`을 선택할 수 있다. 프로필은 repo `resources/style-upgrade/profiles/{SF-ROLE}.json`, 실제 적용은 `src/doc_automation/layout.py`다. source_template SHA·role·schema_version을 대조하고 관찰 근거와 편집 목표, allowed_changes를 읽는다. 후보·미검토 status는 성공 판정이 아니다. 같은 폰트·여백·가로 페이지를 모든 역할의 필수 규칙으로 승격하지 않는다.

기계적 기능의 상세 계약과 예제는 repo `docs/HWPX_COMPOSE.md`를 따른다.

표지 `targets.cover_roles`를 선언하면 customer/program/title/date/supplier 다섯 owner 문단의 font_face/height_hwp/bold만 변경한다. 원본 ZIP bytes의 정확한 XML/XPath·원문 own text·source SHA와 렌더러 `_editorial_cover_paragraphs` registry/원문 map의 element identity를 편집 전에 대조한다. 모호하거나 누락되면 거절한다. customer 문단이 표를 감싸도 own run만 변경하여 자식 program/title 문단을 일괄 덮지 않는다. 별도 프로필 선언이 있는 program 문단의 `breakNonLatinWord`는 원문 문단 정의까지 대조하여 그 속성만 파생할 수 있다. 이미 목표값이면 파생 호출을 생략하여 불필요한 local ID 변경도 피한다. 나머지 문단 속성·페이지·표·셀·앵커·개체·제어·선택하지 않은 run과 합성 고지는 보존한다. 실제 사업명/기업명/날짜를 참고자료의 값으로 대체하지 않는다. `cover_roles` report에서 각 role·target·member·원본/현재 XPath·실제 local ID/해결된 글꼴·크기·굵기를 확인한다. 줄바꿈 변경은 현재 native 출력에서 실제 단어 분절·상자 높이·문서명과 후속 쪽 배치를 다시 확인한다. 속성의 영문 이름이나 한 표지의 성공만으로 다른 버전·긴 사업명의 동작을 일반화하지 않는다.

- `use_character_style`: 원 charPr를 유지하고 요청한 글꼴·포인트 크기·굵기·기울임·색·자간·장평만 local 정의로 파생한다. 문자열 font는 한글/영문/한자/일본어/기타/기호/사용자7script, dict는 지정 script만 바꾼다. 자간0%·장평100%는 실제 사용 정의에서 확인한다. 문단 scope는 own run만, container scope는 하위 실제 텍스트 run을 선택한다.
- `use_paragraph_style`: lineSpacing의 switch case/default를 함께 바꾸며 정렬·단어 끊기·keep은 요청한 값만 변경한다. 기본 문자/문단 스타일 적용은 머리말·꼬리말·각주·미주를 제외한다. 이 영역을 의도적으로 편집할 때만 `include_headers=True`를 명시한다.
- `set_page_layout`/`split_section`: mm 또는 HWPUNIT를 명시한다. 가로=NARROWLY·세로=WIDELY이며 종이의 짧은/긴 변과 함께 해석한다. 새 구역은 실제 첫 본문 문단의 own run에 secPr/column을 넣고 OPF spine·manifest·secCnt를 갱신한다. 표지 페이지 속성은 유지하고 PAGE 앵커·머리말·꼬리말·목차를 따로 검토한다. 내용 구성 후 `1.`로 시작하게 된 목차 항목을 본문 제목으로 오인하지 않는다.
- `set_table_layout`: 논리 열폭 배열의 합·병합 셀폭·셀 여백을 함께 바꾸고 주소/병합·텍스트·행높이·앵커는 보존한다. 반복 카드에는 같은 prototype 열폭을 재사용한다. 한 셀짜리 서술 frame과 상세카드의 라벨/값은 표머리와 다르다. 용지 본문폭뿐 아니라 outMargin·horzOffset까지 확인한다. 목표를 넘으면 프로필 값을 명시적으로 고치고 변경을 기록하며 조용히 clamp하지 않는다.
- `insert_picture`: 확인된 PNG/JPEG/BMP bytes와 MIME/확장자를 받아 새 manifest·그림을 넣는다. 최대 폭/높이에 전체 비율을 유지해 맞추고 크롭하지 않는다. 기존 그림 geometry 교체 API와 다른 기능이다. description은 화면에 보이는 캡션이 아니므로 첨부 ID/SHA·대응 화면 ID·출처·실제/합성 구분과 캡션을 렌더러에서 연결한다.

참고 원문 그림을 과거 비교자료로 재현할 때는 repo `docs/REFERENCE_QUOTATIONS.md`의 전용 typed slot과 원본 검증을 따른다. 초기 지원은 등록한6개 소유 인스턴스뿐이며 일반 evidence/flow 슬롯으로 대신 넣지 않는다. 전체 bitmap·실제 픽셀 종횡비·영구 인용 고지를 보존하고 Q키/현재 부모 ID/정확한 XML owner를 연결한다. `detail_regions`는 전체 원본을 먼저 보존한 뒤 원본 픽셀의 명시한 부분 영역을 추가하며, `hancom-mac-12.30.0-png`를 선택해야 한다. 임의 원본에 좌표식을 일반화하지 말고 해당 repo의 native profile과 현재 출력의 원페이지로 검증한다. 등록·픽셀 동일성이 새 출력의 가독성·실제 수행·G01/G02/G03 합격을 뜻하지 않는다.

`editorial_profile` 적용 report의 source SHA, profile source path/SHA, source 본문 경계, 선택한 제목의 실제 텍스트/XPath, pages/tables/changes를 읽는다. source-specific selector는 등록된 V2.0 19종 범위이고 임의 HWPX의 일반 레이아웃 판별기가 아니다. 선언된 서식 변화 밖의 텍스트·셀 소유권·필드·수식·그림·고정 문구는 계속 보존한다. 큰 표·그림의 실제 배치와 계속 쪽, 둘 이상의 floating 표/뒤따르는 본문의 순서는 native 출력에서 확인한다.

원자료→업무 표현은 값·타입·ID·관계·상태·출처와 문서 확인 위치로 의미를 검증한다. 내용 구성→서식 적용은 선택한 범위의 의도한 서식만 허용한다. 서식 적용→native 저장은 이미 선택한 서식을 적용한 현재 bytes 기준으로 엄격히 비교한다. 마지막 비교에 첫 번째 단계의 텍스트 재작성이나 프로필 허용 변경을 다시 적용해 실제 저장 손실을 면제하지 않는다.

Mac 한컴 Office HWP 12.30.0(build 6544)에 새 PNG를 삽입하는 생성에서는 `--raster-metadata-profile hancom-mac-12.30.0-png`를 명시할 수 있다. 기본값은 기존 좌표 유지다. 이 선택은 PNG bytes·원크기·표시 크기·비율을 보존하면서 전체 clip/dimension 좌표만 해당 버전의 관찰된 격자로 작성한다. 상세 API와 버전 경계는 repo `docs/HWPX_COMPOSE.md`의 ‘버전을 지정한 새 PNG 좌표’를 읽는다. 업무 서식 프로필이나 범용 HWPX 규칙이 아니며 새 출력의 strict/native 검토는 계속 필요하다.

## 장문과 목차의 편집 범위

`pageBreak=CELL`만 설정해도 다쪽 표가 된다고 가정하지 않는다. [한컴의 여러 쪽 지원 도움말](https://help.hancom.com/hoffice/multi/ko_kr/hwp/table/tableattribute/table(many).htm)은 글자처럼 취급한 표의 한 쪽 밖 내용은 화면·인쇄에 나타나지 않는다고 설명한다. 이 코퍼스의 AD2/TD3 장문 카드에서는 `CELL`과 `treatAsChar=0`의 조합으로 내용이 출력됐고, 계속 쪽의 식별자에는 해당 카드의 제목 행 반복이 필요했다. 다른 표의 앵커·감싸기까지 일괄 바꾸지 말고 현재 프로필에서 검증한다.

짧은 문단의 `keepLines`와 제목의 `keepWithNext`는 쪽 경계의 단어 분리·제목 고립을 줄이는 선택이다. 전체 카드나 모든 상세를 연쇄 연결하면 한 쪽보다 큰 묶음이 생긴다. TD5에서는 작은 **개별 컬럼 항목**만 길이·문단 수를 제한해 묶고 큰 항목은 흐르도록 했다. 이 임계값은 이 생성기의 구현 선택이며 규격이나 전문가 공통 표준이 아니다. 실제 출력에서 완결 여부와 과도한 공백을 확인한다.

현재 등록한 AD1/TD1/TD2/TI2/TI3/OS1/OS2의 길이가 제한되지 않은 1셀 본문 frame은 source별 계약으로 `CELL`과 `treatAsChar=0`을 사용한다. Mac12.30.0의 새 inline frame 후보에서6역할의 본문/그림이 페이지 밖으로 잘리고 다음 쪽이 곧바로 부록으로 시작한 실제 실패를 근거로 수정했다. TI2는 이번 짧은 입력에서 마지막 문장이 보였으나 같은 unbounded frame의 예방 선택으로 구분한다. 짧은 행 목록·다른 원본의 표 전체에 이 관찰을 일반화하지 않으며, 현재 전체 페이지와 계속 문맥을 재검증한다.

목차 제목과 첫 본문 사이 전체를 목차로 간주하지 않는다. 실제 목차 항목을 소유한 문단을 식별하고 그 텍스트만 갱신한다. 그 사이의 과제 고지·부속 안내·테이블 설명과 뒤의 본문·제어는 보존한다. 위치가 불명확하면 임의 범위를 지우지 말고 거부하고 분석한다. 목차가 실측과 같아도 비목차 내용이 삭제되지 않았는지는 별도 불변식이다.

## 저장 뒤 확인

ZIP/XML/spine·manifest·이미지/서식 참조·ID·표 주소/병합·의미 반복 수를 검사한다. 보존해야 할 개체가 실제 남았는지 원본 프로필과 대조한다. 다른 표를 포함한 문단의 외곽 텍스트 변경으로 셀/도형을 잃지 않았는지 확인한다. 그 다음 현재 바이트의 네이티브 출력 검토로 넘긴다. 모든 HWPX 또는 모든 한글 버전에서 동일하게 동작한다는 보장은 하지 않는다.

native Save As가 `hh:substFont`를 없앴다면 실제 글꼴 정의 변화다. local 숫자 ID 차이나 `typeInfo` 메타데이터 정규화로 면제하지 않는다. repo `scripts/restore_native_font_fallbacks.py`는 같은 언어에서 ID를 제외한 primary의 모든 속성·text·자식이 같고 양쪽 대응이 유일할 때만 누락된 원문 선언을 복원한다. 임베디드/resource-backed 글꼴·기존 fallback 충돌·모호한 대응·다른 정의 변경은 거부하고 header 외 멤버 내용·순서를 보존한다. 실제 Save As 중간물과 새 복원 최종물의 path/SHA·전체 report를 남긴 뒤 [quality-gates.md](quality-gates.md)의 최종 바이트 경로로 검토한다.
