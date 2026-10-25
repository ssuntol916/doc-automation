# 구현 근거와 지원 범위

확인일: 2026-10-24. 사용자 자료 원본의 XML이 구체적인 생성·비교의 기준이다.

- [한컴 HWPX 구조 설명](https://tech.hancom.com/hwpxformat/): ZIP/XML 패키지, content.hpf manifest와 spine, header.xml의 서식 정의, section의 본문 및 BinData의 관계. 본문 순서는 spine을 따른다.
- [한컴 HWP/OWPML 형식 공개](https://www.hancom.com/support/downloadCenter/hwpOwpml): 형식 명세의 공식 배포처. 명세의 버전·적용 네임스페이스를 확인하고 사용한다.
- [한컴 공식 OWPML 모델](https://github.com/hancom-io/hwpx-owpml-model): 패키지와 요소 모델의 일차 자료. 이 저장소의 Windows C++ 예제를 현재 macOS에서 실행한 것으로 간주하지 않는다.
- [한컴의 HWPX 파싱 설명](https://tech.hancom.com/python-hwpx-parsing-2/): 본문 스키마 해석 참고. 소개된 2021 네임스페이스와 현재 입력 파일의 2011 네임스페이스는 구분한다.

현재 분석기는 실제 입력에서 확인한 2011 HWPX 네임스페이스를 지원하며 다른 본문 네임스페이스는 명시적으로 거절한다. 원문 텍스트는 hp:t의 자식 제어문자 뒤 tail까지 추출하고, 표를 담는 문단과 셀의 문단을 별도로 처리해 중복 추출을 방지한다.

XML 파싱·참조 검사와 네이티브 한글 출력 검증은 별개다. 전체 XSD 적합성 검사나 모든 한글 버전 호환성을 검증했다고 주장하지 않는다. 최종 출력은 설치된 한글 앱에서 열고 PDF를 생성해 별도로 검토한다.

합성 AD2 한 문서는 macOS 한글 12.30.0 build6544에서 HWPX 재저장, HWP 바이너리 저장·재열기, HWPX 역변환·재열기를 실행했다. 왕복 대조 (로컬 자료: `verification/generation-pilot/roundtrip-audit.json`)에서 5쪽 PDF의 텍스트와 72dpi 픽셀이 같았고, HWPX 전후 비어 있지 않은 소유 문단74개의 순서·내용도 같았다. 이 실증은 텍스트·표 중심 한 예시의 변환 경로이며 임의 HWP의 그림·수식·OLE·배포용/암호 문서·모든 버전 지원을 뜻하지 않는다. 바이너리 HWP를 XML 분석기에 직접 넣으면 명시적으로 미지원으로 보고한다.
