# 과거 참고 그림의 전용 인용 계약

이 기능은 참고 원문을 비교자료로 재현한다. 새 사업의 실제 시험·설치·승인·성과 증적을 생성하지 않는다. 초기 지원은 source-specific registry에 고정한 TI1/TI4 시험 결과 화면 각2개와 TI2 설치 사진2개, 총6개 소유 인스턴스(4개 고유 비트맵)다. 다른 원본은 별도 분석과 등록이 필요하다.

| 소유 경로 | 인용 유형 | 출력 역할 |
|---|---|---|
| `test_cases[*].reference_result_quotations[]` | `historical_test_result` | integration→SF-TI1, acceptance→SF-TI4 |
| `deployment_items[*].reference_installation_quotations[]` | `historical_installation_photo` | SF-TI2 |

두 필드는 optional이며 없거나 빈 배열이면 문서·서식을 추가하지 않는다. 선택한 역할에서 nonempty 필드를 출력할 수 없으면 생성을 거절한다. `data`/`expected`/`actual` 등 자유값 내부의 동명 키를 이 슬롯으로 해석하지 않는다.

각 항목은 closed `$defs.reference_figure_quotation`을 따른다. `attachment_id`, `quotation_kind`, 고정 `scope=historical_reference_only`, 원본 문서 ID/SHA, source XML/picture XPath, binary ID/member/SHA, decoded pixel SHA와 `historical_owner`를 제공한다. `attachments[]`의 파일 경로·SHA·MIME를 사용하되 `purpose=historical_reference_quotation_only`, `status=provided`, `verification_status=provided`로 명시한다. 이는 제공 파일 확인 상태이며 실제 수행의 검증 완료 상태가 아니다.

`historical_owner`는 원문 역할과 소유 유형, 원문 그룹/케이스 또는 사진 패널 표기, 식별 셀의 XML/XPath·논리 주소·문단별 own text와 연결한 전체 문자열을 가진다. 케이스 행 순서에서 얻은 번호와 현재 입력의 controlled ID는 원문에 실제 인쇄된 ID와 구분한다. 원문 literal과 사업 자료는 ignored 검증 variant에 둔다.

검증기는 다음 근거를 모두 대조한다.

1. 등록된 원본 SHA·그림 위치·binary/pixel SHA·역사적 owner canonical JSON SHA와 역할
2. 실제 로컬 HWPX SHA, 모든 OPF spine 구역의 own paragraph, 고유 picture XPath와 `hc:img` 참조
3. OPF manifest의 binary ID→실제 BinData 멤버, 제공 첨부와 원본 payload의 완전한 바이트 동일성
4. RGBA 픽셀과 원래 가로·세로 크기, 선언 MIME와 실제 형식
5. 같은 원문 표에 속한 각 식별 셀의 실제 own paragraph·inline tail·논리 주소와 제공 literal

픽셀 digest는 `SHA256(uint32BE(width) || uint32BE(height) || RGBA8 row-major bytes)`다. owner digest는 UTF-8 JSON의 `ensure_ascii=False, sort_keys=True, separators=(',', ':')` 직렬화 SHA다. committed registry는 역할·해시·locator만 보관하며 원문·Serial·회사 사실·원비트맵을 포함하지 않는다. 파일 검증을 끈 상태에서는 nonempty 인용의 준비 완료를 인정하지 않는다.

인용에 사용한 source/bitmap 경로와 SHA를 snapshot으로 유지하고 각 저장 전후와 최종 manifest 공개 전후에 다시 대조한다. 중간 drift가 발견되면 생성을 거절하고 방금 쓴 동일 SHA의 인용 출력·manifest만 제거한다. absent/empty 경로에서는 source snapshot이나 문서 변경이 없다.

쓰기 전에 예정 HWPX·manifest·선택한 profile/meaning/source sidecar·companion 경로가 인용 source/bitmap의 lexical/resolved 경로나 samefile alias인지 확인하고 충돌하면 거절한다. 과거 owned companion 삭제도 같은 입력 보호 검사를 통과해야 한다. 입력을 덮어쓴 뒤 cleanup으로 복구하려 하지 않는다.

같은 첨부 ID, 같은 payload SHA 또는 재인코딩한 같은 decoded pixels를 evidence/flow/다른 artifact 슬롯에 겸용할 수 없다. 그림 안에 있는 과거의 '적합', 모델/Serial, 측정값을 현재 항목의 `actual`/result/설치수량·일자·검증결과에 옮기지 않는다. 사진의 존재로 납품·설치·수행을 추론하지 않는다.

실제 bytes를 MIME과 독립적으로 sniff하여 raster를 비교하며, TIFF/GIF나 octet-stream으로 재라벨한 PNG도 같은 픽셀이면 거절한다. 일반 non-raster artifact는 기존 파일/출처 검사 범위다. canonical pixels가 다르다는 결과만으로 독립 수행이나 사실 진실성을 인정하지 않는다.

출력은 현재 부모 ID와 Q키가 있는 별도 ‘참고 원문 그림 인용’ 구역이다. 각 그림 캡션에 **`참고 원문 재현·새 사업 수행/설치 증거 아님`**을 지속 표시한다. 이 고지는 제공 캡션의 길이나 문구로 제거되지 않는다. 원문 역할/소유 표기·source caption·문서 및 bitmap SHA·XPath·식별 셀을 연결하고, manifest와 meaning map에 정확한 입력 pointer/현재 부모/Q키/실제 그림·캡션 XML owner를 등록한다. 이 등록 자체는 독립 의미 검토의 합격 증거가 아니다.

원본 전체 bitmap과 실제 픽셀 종횡비를 보존한다. BMP는 decoded pixels를 대조한 PNG로 lossless 인코딩할 수 있으며 원본 SHA와 embedded SHA를 별도로 남긴다. 원문에서 관찰된 이미지 늘이기를 새 긍정 서식으로 복제하지 않는다.

`detail_regions`에는 최대6개의 `{ "label": "표시명", "box_pixels": [left, top, right, bottom] }`를 제공할 수 있다. 좌표는 검증한 원본 픽셀의 반열림 영역 `[left, top, right, bottom)`이다. 정수가 아닌 좌표, 빈 영역·경계 밖·동일 영역 중복·전체 원본 재지정은 거절한다. 전체 그림을 먼저 보존한 뒤 Q키의 하위 D키로 부분 보기를 추가하며 각 보기의 영구 고지·현재 부모 ID·역사적 소유자·원본 좌표·원문 근거를 연결한다. label과 좌표의 입력 pointer 및 실제 XML owner도 meaning map에 기록한다. 추가 보기는 기존 그림의 가독성 근거이며 쉬운 평가 단위를 추가하지 않는다.

이 경로는 `--raster-metadata-profile hancom-mac-12.30.0-png`를 명시해야 하며 BMP/PNG 원문만 지원한다. 전체 PNG payload를 매번 그대로 넣고 HWPX의 표시 영역만 조절한다. BMP는 전체 픽셀을 보존하는 PNG로 먼저 변환한다. 실제 좌표 모델과 버전 경계는 `docs/HWPX_COMPOSE.md` 및 `resources/picture-viewport-native-profile.json`을 따른다. 임의의 기존 그림을 이 좌표식으로 재작성하지 않는다. 그림의 글자를 AI로 다시 쓰거나 샤프닝하여 사실을 보완하지 않는다.

검증은 기존 입력의 전체 HWPX 바이트 불변, 기본 회귀, 여섯 인용의 실제 원본 대조와 새 variant 생성으로 나눈다. 원래 frozen 입력은 수정하지 않는다. 새 variant에는 별도의 실제 Hancom 열기·저장·재열기·PDF·원페이지 검토가 필요하며 G01/G02/G03과 최종 품질 점수는 그 전까지 unknown/pending이다. 이 지원으로 실제 성과 증적·필수 artifact 의무를 면제하지 않는다.
