# 공개 코드와 비공개 자료의 경계

공개 저장소에는 재사용 코드·스키마·스킬·양식 식별용 해시·서식 프로필과 독립 합성 예제만 둔다. 실제 기업·인물·사업의 이름, 연락처, 업무 원문, 장비 일련번호, 운영값, 화면·설치 사진과 서명은 원본뿐 아니라 추출 JSON·관측 보고서·테스트 fixture에도 포함하지 않는다.

실제 자료에서 추출한 예제를 이름만 바꿔 합성으로 공개하지 않는다. 참고 추출과 같은 문안 비교 입력, 원사업의 구체적 오류·실적·관측, 과거 실제 한컴 출력과 검토 이력은 비공개 로컬 자료다. 공개 예제는 별도로 작성한 합성 사실과 그 사실에서 만든 설계 시안이며, 실제 수행·승인·서명·측정 증거가 아니다.

## 로컬 자료 연결

원본 양식은 읽기 전용이다. 생성 시 `--template-root PATH` 또는 `DOC_AUTOMATION_TEMPLATE_ROOT`로 로컬 폴더를 지정한다. `DOC_AUTOMATION_SOURCE_MAP`으로 비공개 JSON 파일을 지정할 수도 있다.

```json
{
  "schema_version": 1,
  "templates": {"SF-AD1": "/local/private/templates/form.hwpx"}
}
```

선택한 역할에 필요한 경로를 제공한다. 필요하면 `inventory` 객체에 공개 inventory ID별 로컬 경로도 지정한다. map의 상대경로는 map 파일의 부모 기준이다. 경로 설정은 원본 SHA·selector·서식 목표를 덮어쓸 수 없으며 실제 원본 bytes는 공개 핀과 대조한다. 개별 원본 파일명과 사용자 절대경로를 공개 자원에 넣지 않는다. map과 `.env`, 비공개 입력은 저장소 밖 또는 ignored `private/`에 둔다.

참고자료의 원문·그림 분석은 별도 로컬 폴더를 명시해 수행한다. `scripts/resources/run.py`는 새 ignored 작업공간에 코드를 준비하며 `--templates`, `--references`로 원본 위치를 받는다. 수동 관측·원문 선택·원사업 판정은 별도 비공개 JSON 입력으로 제공한다. 도구 실행만으로 과거 native/시각 판정을 새로 수행했다고 기록하지 않는다.

## 출력과 검증

원문 전체 추출, OCR, 참고 파생 입력, 모든 HWPX/PDF/페이지 PNG, 실행 manifest·해시·native 사건·검토 기록은 ignored `analysis/`, `outputs/`, `verification/`, `generated/` 또는 외부 비공개 작업공간에만 저장한다. 공개 `examples/`에는 독립 합성 입력과 합성 SVG/PNG만 둔다.

기본 테스트는 비공개 코퍼스를 요구하지 않는다. `corpus`/`native` 검사는 별도 로컬 자료를 명시적으로 준비해야 하며, 자료 부재를 통과로 바꾸지 않는다. 과거 한컴 출력 검토와 개별 서식 단위 판정은 로컬 이력이다. 공개 checkout의 새 실행·모든 문서 품질·실제 사업 제출 가능성 또는 95% 달성을 보증하지 않는다.

후보 공개 전에는 파일 내용, 경로, 이미지와 Git 추적 목록을 함께 점검한다. `.gitignore` 추가만으로 이미 추적된 개인정보가 제거되는 것은 아니다. 이전 공개 이력에 있던 내용의 정리는 현재 후보 정리와 별도 작업이다.

## 커밋 전 검사

`bash scripts/hooks/install.sh`로 이 저장소의 훅을 설치한다. `pre-commit`은 작업 파일뿐 아니라 실제 스테이징된 blob도 검사한다. 알려진 비공개 값 목록은 공개 소스에 넣지 않고 저장소 밖 JSON 문자열 배열로 둔다. 필요하면 로컬 Git 설정에 연결한다.

```sh
git config --local docAutomation.privateDenylist /local/private/forbidden-values.json
python3 scripts/audit_public_repository.py --staged --history \
  --forbidden-values /local/private/forbidden-values.json
```

문자열 검사는 이미지나 알지 못하는 민감정보의 부재를 보증하지 않으므로 새 자산의 출처와 내용을 별도로 검토한다. 로컬 설정과 비공개 값 목록은 Git으로 배포하지 않는다.

원래 참고자료의 인용 비교를 실행하는 선택된 코퍼스 검사는 `DOC_AUTOMATION_PRIVATE_FIXTURE_ROOT`로 기존 로컬 fixture 작업공간을 명시한다. 환경변수나 입력이 없으면 해당 검사는 실패하며, 기본 테스트에서는 코퍼스 마커로 제외한다. 과거 원문 파생 자료를 새 합성 데이터라고 다시 표시하지 않는다.
