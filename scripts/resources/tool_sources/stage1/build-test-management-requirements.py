"""Curated stage-1 authoring catalogue with direct evidence references."""
import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from zipfile import ZipFile
from collections import Counter
import xml.etree.ElementTree as E
import json, hashlib, re, unicodedata
OUT=Path(__file__).parent
records=json.loads((OUT/'test-management-xml.json').read_text())
config={
'SF-CD1': dict(title='단위테스트결과서',row=9,status='필수',inputs=['단위테스트ID','단위테스트명','테스트시나리오','테스트데이터','예상결과','테스트결과와 증적','결함번호','연결 단위테스트ID','결함 현황과 원인','발생일자','조치 내용과 증적','완료일자'],repeat=['기능별 시험행','결함별 행'],rules=['s1:P109','s1:P111','s1:P112','s1:P113','s1:P114','s1:P115','s1:P116','s1:P117','s1:P119','s1:P120'],refs=['AD2 요구사항 요건·제약','TD3 화면 주요 체크사항','PM4 단위테스트ID'],pending=['CD2 ID 접두사와 SF-CD1 양식번호 관계','시험일·시험자·판정 기준의 추가 관리','결함 없음 표기']),
'SF-TI1': dict(title='통합테스트결과서',row=10,status='필수',inputs=['공정명','통합테스트ID','통합테스트명','업무흐름도','절차·조건별 테스트케이스','입력데이터','예상결과','실제 결과와 증적','결함번호','연결 통합테스트ID','결함 현황과 원인','발생일자','조치내용과 증적','완료일자'],repeat=['공정·통합시험ID별 상세표','시험케이스 행','결함 행'],rules=[f's1:P{n}' for n in [71,73,74,75,76,77,78,79,80,82,83]],refs=['주요 공정별 스마트化 추진 목표 달성 상황 외부 원문','PM4 통합테스트ID','목차/결함표 시험ID'],pending=['외부 인용 목표 문서의 정체와 버전','공정/시험 다중 관계','결함 없음/미해결 표기']),
'SF-TI2': dict(title='시스템전환결과서',row=11,status='필수',inputs=['계획·착수 장비 품명/규격/수량','실제 설치 품명/규격/수량/상태','모델명·시스템정보·라이선스·설치 증거','아키텍처 검증방안과 결과','필요한 장비의 도입기업 확인·서명','업무별 프로그램 개발 본수','물리DB 구축','소프트웨어 환경설정과 전환 증거','클라우드 제공내용·자원할당·전환 증거(해당시)','초기데이터 대상·유형별 전환건수','정합성·충분성 검사·도입기업 확인'],repeat=['장비/소프트웨어/네트워크별 결과와 증적 블록','데이터 유형별 전환/검증 블록'],rules=[f's0:P{n}' for n in [68,70,72,73,74,75,76,78,79,80,81]],refs=['사업계획서·착수계','TD2 아키텍처 검증방안','TD4 프로그램 목록','TD5 DB 설계','OS2 구축현황'],pending=['초기/기초 용어 정리','해당 없는 범위의 표기','검증 증적/실제 서명 확보']),
'SF-TI3': dict(title='메뉴얼',row=12,status='필수',inputs=['시스템 개요/구성도/메뉴구조도','공통 사용방법','화면명/설명/실행화면/순서/기능·이벤트/참고·제약','상용SW 설치·환경설정·실행·종료·패치','응용SW 설치·디렉터리·실행·종료·업그레이드','권한·프로그램 등록/삭제·버전관리','보안 적용/관리','장애유형·대응·백업/복구','담당자·긴급연락처','클라우드 접속 등 관리절차(해당시)'],repeat=['화면별 설명 블록','관리 대상SW·장애 유형·연락 담당자 항목'],rules=[f's0:P{n}' for n in [69,71,72,73,79,81,82,84,85,86,87,88,89,90]],refs=['TD3 화면/메뉴','AD3 변경/추가 기능','실제 운영/관리 시스템'],pending=['온라인 매뉴얼의 제출·접근·버전·보관 증거','메뉴얼/매뉴얼 명칭 정규화']),
'SF-TI4': dict(title='사용자테스트결과서',row=13,status='필수',inputs=['사용자테스트ID','사용자테스트명','공정별 업무흐름도','케이스·절차·조건·화면경로','입력데이터','예상결과','실제결과·증적','결함번호','연결 사용자시험ID','결함 현황·원인','발생일자','조치내용·증적','업무담당자','확인자','도입기업 시험담당자·운영환경'],repeat=['사용자시험ID별 상세표','케이스 행','결함 행'],rules=[f's1:P{n}' for n in [76,78,79,80,81,82,83,84,85,87,88]],refs=['공정별 추진목표 외부 원문','PM4 사용자테스트ID','목차/결함표 시험ID'],pending=['TI5 ID 접두사와 SF-TI4 양식번호 관계','공정명 독립 칸 부재시 공정 연결방법','결함 업무담당자 필드는 지침보다 표가 추가 요구']),
'SF-OS1': dict(title='운영지원계획서',row=14,status='선택',inputs=['H/W·S/W·N/W·시스템·초기데이터 지원대상','전환 이후~사업 종료 지원기간','실제 지원인력','헬프데스크 즉시 대응 방안','일일 로그인·평균시간·기능활용 분석 관리방안','운영미흡시 추가교육 계획','운영미흡시 활성화 이벤트 계획'],repeat=['지원대상·인력·활동별 항목'],rules=[f's0:P{n}' for n in [71,73,74,75,76,78,79,80,81]],refs=['TI2 전환시점','TI4 사용자시험 기간','사업기간 종료일','OS2 지원내역'],pending=['선택 산출물 포함여부','표지 공식 사업명','지표 산식·교육/활성화 발동조건']),
'SF-OS2': dict(title='운영현황보고서',row=15,status='필수',inputs=['H/W·S/W·N/W 설치·환경설정','클라우드 자원/설치/운영 증적(해당시)','주간 사용자·거래처·제품·생산계획/실적·거래 등록활용','일별 로그인수·사용자별 접속시간 분석·증적','주간 장애/오류·조치','주간 공급기업 지원내역'],repeat=['보고기간/주','일별·사용자별 활용 기록','데이터 유형·장애·지원 건'],rules=[f's0:P{n}' for n in [57,59,60,61,64,65,66,67]],refs=['TI2 설치/전환','OS1 지원계획','실제 로그·등록·거래 데이터'],pending=['목차/본문 구축(4) 누락 해소','운영/활용 장제목 통일','지표 산식과 기간','표지 공식 사업명']),
'SF-PM1': dict(title='월간보고서',row=16,status='필수',inputs=['보고월','과제명','보고기간','금월 계획/실적 진척률','누적 계획/실적 진척률','사업관리 실적·차월계획','단계·투입인력·작업별 개발실적/계획','위험/이슈번호·구분·내용·처리현황','작성일','공급기업PM·날인'],repeat=['월별 보고서','관리영역·단계·작업·인력 문단','위험/이슈 행'],rules=['s0:P29','s0:P31','s0:P32','s0:P33','s0:T2/R1C0','s0:T2/R1C1','s0:T3','s0:P115','s0:P116'],refs=['일정/인력 계획','실제 작업기록','PM3 변경','PM2 협의','전월 보고'],pending=['진척률 산식/가중치','지역 내역 문구의 의도','실제 날인 확보']),
'SF-PM2': dict(title='회의록',row=17,status='필수',inputs=['일시·요일','장소','주최자','안건','회의내용','합의사항','특이사항','도입기업/공급기업/기타 참석자'],repeat=['회의별 문서/블록','안건·논의·합의 항목','소속별 참석자'],rules=['s0:T2/R0C0','s0:T2/R1C0','s0:T2/R2C0','s0:T2/R3C0','s0:T2/R4C0','s0:T2/R5C0','s0:T2/R6C0','s0:T2/R7C0'],refs=['AD2 요구사항 근거','PM3 변경 사유·서명 회의록'],pending=['장문 pageBreak NONE 표 배치','변경 증빙 시 양 기업 서명 확보','잘못 남은 2019 일정계획서 머리말']),
'SF-PM3': dict(title='변경관리내역서',row=18,status='선택',inputs=['대장 번호·제목·발송공문번호·요청일·요청자','회신번호·회신내용·회신일','사업명·과제번호·도입/공급기업','변경사유·객관증거','변경전후 내용','영향/파급효과','양 기업 서명 회의록·관련증빙','전담/운영기관 승인 공문 또는 승인/확인 화면'],repeat=['변경건별 대장행+요청서+근거·승인 증적 묶음'],rules=[f's0:P{n}' for n in [111,113,117,122,123,124,125,126]],refs=['PM2 서명회의록','AD2/일정/인력/TD2 변경대상','PM4 추가/변경/삭제 근거'],pending=['선택 문서 적용여부와 변경시 처리기준','실제 승인상태','2019 일정계획서 머리말']),
'SF-PM4': dict(title='요구사항추적표',row=19,status='필수',inputs=['요구사항ID·명·설명','기능 요구별 실제 화면·프로그램·단위/통합/사용자시험ID','추가/변경/삭제 근거','비기능 실제 결과물명','비기능 이행현황(진행중/완료/미진행)'],repeat=['기능요구별 연결행','비기능요구별 이행행'],rules=[f's0:P{n}' for n in [136,137,139,140,141,143,144]],refs=['AD2 기능/비기능 원본','TD3/TD4/CD1/TI1/TI4 선언ID','PM3 변경근거'],pending=['다중ID/다중행 표기정책','해당 없는 설계/시험 칸 표기','CD2/TI5 접두사 충돌 해소','2019 일정계획서 머리말','상태판정 근거·기준일']),
}
def longref(ref):
 return re.sub(r'^s(\d+):',r'Contents/section\1.xml#',ref)
result=[]
for d in records:
 c=config[d['code']]
 c.update(code=d['code'],source=d['source'],source_sha256=d['sha256'],source_rules_are_local_templates_not_latest_regulations=True,field_requirement_semantics='Inputs are derived from labels/instructions; individual field mandatory flags are not present.',mandatory_evidence=f'목록 Contents/section0.xml#T1/R{c["row"]}C3',purpose_evidence=f'목록 Contents/section0.xml#T1/R{c["row"]}C4',code_evidence=f'목록 Contents/section0.xml#T1/R{c["row"]}C5',rules=[longref(r) for r in c['rules']],repeat_classification='implementation interpretation from template structure and enumerated placeholders',tables=[{'ref':t['ref'],'rows':t['attributes']['rowCnt'],'columns':t['attributes']['colCnt'],'pageBreak':t['attributes']['pageBreak'],'width':t['size']['width'],'merged_cells':[{'ref':x['ref'],'span':x['span']} for x in t['cells'] if x['span']!={'colSpan':'1','rowSpan':'1'}]} for s in d['sections'] for t in s['tables']])
 result.append(c)
(OUT/'test-management-requirements.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
# Verify current authoritative files and each curated evidence reference.
list_source=next(p for p in Path(os.environ.get("DOC_AUTOMATION_TEMPLATES", str(Path.home()/"projects/gov-grants/_templates"))).rglob('*.hwpx') if '목록' in unicodedata.normalize('NFC',p.name))
with ZipFile(list_source) as z:
 list_root=E.fromstring(z.read('Contents/section0.xml'))
 list_table=next(e for e in list_root.iter() if e.tag.endswith('}tbl'))
 list_cells={tuple(x.get(k) for k in ('rowAddr','colAddr')):''.join(''.join(t.itertext()) for t in c.iter() if t.tag.endswith('}t')) for c in list_table.iter() if c.tag.endswith('}tc') for x in c if x.tag.endswith('}cellAddr')}
list_checks=[{'code':code,'expected_status':c['status'],'actual_status':list_cells[(str(c['row']),'3')],'actual_code':list_cells[(str(c['row']),'5')],'passed':list_cells[(str(c['row']),'3')]==c['status'] and list_cells[(str(c['row']),'5')]==code} for code,c in config.items()]
validation={'list_source':{'path':str(list_source),'sha256':hashlib.sha256(list_source.read_bytes()).hexdigest(),'checks':list_checks},'source_files':[],'curated_reference_errors':[],'totals':{'documents':len(records),'sections':0,'paragraphs':0,'tables':0},'scope':'ZIP/XML integrity and local evidence coverage; not rendered Hancom output.'}
for d in records:
 issues=[]; grids=[]; tails=0
 with ZipFile(d['source']) as z:
  crc=z.testzip()
  if crc: issues.append('ZIP CRC failure: '+crc)
  for n in z.namelist():
   if n.endswith(('.xml','.hpf','.rdf')):
    try: E.fromstring(z.read(n))
    except E.ParseError as e: issues.append(f'{n}: {e}')
   if re.fullmatch(r'Contents/section\d+\.xml',n):
    r=E.fromstring(z.read(n))
    tails+=sum(1 for t in r.iter() if t.tag.endswith('}t') and ''.join(t.itertext())!=(t.text or ''))
 for s in d['sections']:
  validation['totals']['sections']+=1; validation['totals']['paragraphs']+=s['paragraph_count'];validation['totals']['tables']+=s['table_count']
  for t in s['tables']:
   grid=Counter(); rows=int(t['attributes']['rowCnt']);cols=int(t['attributes']['colCnt'])
   for c in t['cells']:
    rr=int(c['address']['rowAddr']);cc=int(c['address']['colAddr']);rs=int(c['span']['rowSpan']);cs=int(c['span']['colSpan'])
    for y in range(rr,rr+rs):
     for x in range(cc,cc+cs): grid[(y,x)]+=1
   holes=[(y,x) for y in range(rows) for x in range(cols) if grid[(y,x)]==0]
   overlaps=[p for p,n in grid.items() if n>1]
   outside=[p for p in grid if not (0<=p[0]<rows and 0<=p[1]<cols)]
   grids.append({'table':t['ref'],'holes':holes,'overlaps':overlaps,'outside':outside})
   if holes or overlaps or outside: issues.append('invalid grid '+t['ref'])
 refs={x['ref'] for s in d['sections'] for x in s['paragraphs']}|{t['ref'] for s in d['sections'] for t in s['tables']}|{c['ref'] for s in d['sections'] for t in s['tables'] for c in t['cells']}
 for ref in config[d['code']]['rules']:
  if ref not in refs: validation['curated_reference_errors'].append({'code':d['code'],'ref':ref})
 current_hash=hashlib.sha256(Path(d['source']).read_bytes()).hexdigest()
 validation['source_files'].append({'code':d['code'],'sha256_unchanged':current_hash==d['sha256'],'zip_crc_ok':crc is None,'issues':issues,'table_grid_checks':grids,'inline_tail_text_elements':tails,'all_styleIDRefs_zero':all(p['attributes']['styleIDRef']=='0' for s in d['sections'] for p in s['paragraphs']),'cell_header_values':sorted(set(c['attributes']['header'] for s in d['sections'] for t in s['tables'] for c in t['cells']))})
validation['passed']=all(c['passed'] for c in list_checks) and not validation['curated_reference_errors'] and all(f['sha256_unchanged'] and not f['issues'] for f in validation['source_files'])
(OUT/'test-management-validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2))
print(json.dumps({'totals':validation['totals'],'passed':validation['passed'],'reference_errors':validation['curated_reference_errors'],'inline_tails':sum(f['inline_tail_text_elements'] for f in validation['source_files'])},ensure_ascii=False,indent=2))
