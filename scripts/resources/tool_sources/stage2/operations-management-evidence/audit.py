import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from xml.etree import ElementTree as E
from zipfile import ZipFile
from datetime import date
import json,re,hashlib,collections
O=Path(__file__).resolve().parent
D={p.stem:json.loads(p.read_text()) for p in O.glob('*.json') if p.stem.startswith(('ref-','template-'))}
A={'scope':'Read-only audit of all six operations/management references and five role-matched templates','source_hashes':{k:v['sha256'] for k,v in D.items()},'numeric_checks':[],'issues':[],'weekly_register':[],'meeting_register':[],'change_register':[],'trace_links':[],'font_profiles':{}}
def table(key,s,t):return D[key]['sections'][s]['tables'][t-1]
def rows(t):return {r:[c for c in t['cells'] if c['row']==r] for r in range(1,int(t['attributes']['rowCnt'])+1)}
def cell(t,r,c):return next(q for q in t['cells'] if q['row']==r and q['cell']==c)
def issue(id,sev,key,evidence,observation,recommendation):A['issues'].append({'id':id,'severity':sev,'document':key,'evidence':evidence,'observation':observation,'generation_rule':recommendation,'classification':'reference_defect_or_unresolved_inconsistency'})
def number(s):return float(s.strip().replace(',','').replace('%','').replace('본','').strip()) if s.strip() not in ['','-'] else 0
# Operation monthly/weekly count table sums: '-' is explicitly treated as zero only for these tabulations.
for ti,start in [(6,2),(7,3)]:
 t=table('ref-os2',0,ti);rr=rows(t);last=max(rr)
 for r,cc in rr.items():
  if r<start:continue
  vals=[number(c['text']) for c in cc[1:]]
  if len(vals)!=5:continue
  ok=abs(sum(vals[:4])-vals[4])<0.01
  A['numeric_checks'].append({'document':'ref-os2','locator':t['locator']+f'/R{r}','kind':'row sum','components':vals[:4],'stated_total':vals[4],'computed_total':sum(vals[:4]),'passed':ok})
  if not ok:issue(f'OS2-T{ti}-R{r}-SUM','high','ref-os2',[c['locator'] for c in cc],'행 합계가 구성값 합과 다름: '+str(vals),'집계표는 원시 집계값에서 계산하고 행·열·총합을 모두 검산한다.')
 for cidx in range(1,6):
  actual=sum(number(rr[r][cidx]['text']) for r in range(start,last));stated=number(rr[last][cidx]['text']);ok=abs(actual-stated)<0.01
  A['numeric_checks'].append({'document':'ref-os2','locator':t['locator']+f'/totalcol{cidx+1}','kind':'column sum','computed':actual,'stated':stated,'passed':ok})
  if not ok:issue(f'OS2-T{ti}-C{cidx+1}-SUM','high','ref-os2',[t['locator'],rr[last][cidx]['locator']],f'열 합계 {stated:g}, 상세행 합 {actual:g}','집계표는 원시 집계값에서 계산하고 행·열·총합을 모두 검산한다.')
def mins(s):
 if s.strip() in ['','-']:return 0
 h=re.search(r'(\d+)시간',s);m=re.search(r'(\d+)분',s);return (int(h[1])*60 if h else 0)+(int(m[1]) if m else 0)
t=table('ref-os2',0,8);rr=rows(t);last=max(rr)
for r in range(3,last+1):
 cc=rr[r];vals=[mins(c['text']) for c in cc[1:]];ok=sum(vals[:4])==vals[4]
 A['numeric_checks'].append({'document':'ref-os2','locator':t['locator']+f'/R{r}','kind':'duration row sum minutes','components':vals[:4],'stated':vals[4],'computed':sum(vals[:4]),'passed':ok})
 if not ok:issue(f'OS2-T8-R{r}-SUM','high','ref-os2',[c['locator'] for c in cc],f'시간 행 합계 {vals[4]}분, 상세 합 {sum(vals[:4])}분','시간은 분/초 정규값에서 계산하여 표시에만 시간·분으로 변환한다.')
for ci in range(1,6):
 actual=sum(mins(rr[r][ci]['text']) for r in range(3,last));stated=mins(rr[last][ci]['text']);ok=actual==stated;A['numeric_checks'].append({'document':'ref-os2','locator':t['locator']+f'/totalcol{ci+1}','kind':'duration column sum minutes','computed':actual,'stated':stated,'passed':ok})
 if not ok:issue(f'OS2-T8-C{ci+1}-SUM','high','ref-os2',[t['locator'],rr[last][ci]['locator']],f'시간 열 합계 {stated}분, 상세 합 {actual}분','시간은 분/초 정규값에서 계산하여 행·열 합계를 모두 검산한다.')
# Weekly report: every report block and its two tables.
s=D['ref-pm2-weekly']['sections'][1];starts=[p for p in s['paragraphs'] if p['table'] is None and re.match(r'\d+년 \d+월 \d+주 주\s*간\s*보\s*고',p['text'])]
for i,p in enumerate(starts):
 end=starts[i+1]['id'] if i+1<len(starts) else len(s['paragraphs'])+1;ps=[q for q in s['paragraphs'] if p['id']<=q['id']<end and q['table'] is None];period=next(q for q in ps if '기  간' in q['text']);progress=next(q for q in ps if '진척율' in q['text']);written=next(q for q in ps if '작성일자' in q['text']);pr=[float(v) for v in re.findall(r'(\d+(?:\.\d+)?)%',progress['text'])]
 rec={'index':i+1,'title':p['text'],'locator':p['locator'],'period':{'text':period['text'],'locator':period['locator']},'progress':{'values':pr,'locator':progress['locator']},'written':{'text':written['text'],'locator':written['locator']},'work_table':2*i+1,'risk_table':2*i+2};A['weekly_register'].append(rec)
 if re.search(r'(?<!\d)024년',period['text']):issue(f'WEEKLY-DATE-{i+1}','medium','ref-pm2-weekly',[period['locator']],'기간 시작 연도가 024년으로 입력됨','기간은 ISO 날짜값으로 저장하고 연도 문자열을 손으로 재입력하지 않는다.')
 if i:
  prev=A['weekly_register'][i-1]['progress']['values'][2];delta=pr[2]-prev
  if abs(delta-pr[0])>0.011:issue(f'WEEKLY-PROGRESS-{i+1}','high','ref-pm2-weekly',[A['weekly_register'][i-1]['progress']['locator'],progress['locator']],f'전 누적계획 {prev:g}%→{pr[2]:g}% 증분 {delta:.2f}%가 금주계획 {pr[0]:g}%와 다름','고정 증분을 복사하지 말고 WBS 가중 실적과 전기 누적값에서 계획·실적을 계산한다.')
# Meeting dates: check calendar and create complete meeting/continuation register.
s=D['ref-pm4-meeting']['sections'][1];meet=[]
for t in s['tables']:
 if not t['cells'] or '일    시' not in t['cells'][0]['text']:continue
 c=cell(t,1,2);match=re.search(r'(\d+)년\s*(\d+)월\s*(\d+)일\s*\((.)요일\)',c['text']);dt=date(*map(int,match.groups()[:3]));actual='월화수목금토일'[dt.weekday()];stated=match[4]
 rec={'table':t['id'],'date':dt.isoformat(),'weekday_stated':stated,'weekday_actual':actual,'id':cell(t,1,4)['text'].strip(),'agenda':cell(t,4,2)['text'].strip(),'locator':t['locator'],'date_locator':c['locator']};meet.append(rec)
 if actual!=stated:issue(f'MEETING-WEEKDAY-{t["id"]}','medium','ref-pm4-meeting',[c['locator']],f'{dt} 원문 {stated}요일 / 실제 {actual}요일','요일은 날짜에서 자동 생성한다.')
for i,r in enumerate(meet):r['tables_in_record']=list(range(r['table'],meet[i+1]['table'] if i+1<len(meet) else len(s['tables'])+1))
A['meeting_register']=meet
# Change rows preserve exact metadata; source-verified image contents are annotated in report.
t=table('ref-pm5-change',0,2)
for r,cs in rows(t).items():
 if r==1:continue
 A['change_register'].append({'number':int(cs[0]['text']),'title':cs[1]['text'],'request_letter':cs[2]['text'],'request_date':cs[3]['text'],'requester':cs[4]['text'],'response_letter':cs[5]['text'],'response_type':cs[6]['text'],'response_date':cs[7]['text'],'locator':t['locator']+f'/R{r}'})
# KPI recomputation and metric definition.
t=table('ref-pm6-kpi',0,2)
for r in [2,3]:
 cs=rows(t)[r];cur,target,result=[number(cs[i]['text']) for i in [4,5,6]];attain=(result-cur)/(target-cur)*100;improve=(result-cur)/cur*100
 A['numeric_checks']+= [{'document':'ref-pm6-kpi','locator':cs[7]['locator'],'kind':'attainment percent','computed':attain,'stated':number(cs[7]['text']),'rounding_decimal_places':1,'passed':round(attain,1)==number(cs[7]['text'])},{'document':'ref-pm6-kpi','locator':cs[8]['locator'],'kind':'improvement percent','computed':improve,'stated':number(cs[8]['text']),'rounding_decimal_places':1,'passed':round(improve,1)==number(cs[8]['text'])}]
A['weighted_kpi_validation']={'status':'not_assessed','reason':'Requires an explicit source mapping for weights and stated weighted totals; no historical private metric values are bundled.'}
# Trace IDs: existence in correct source artifacts, only declaration label cells (not generic occurrence) for certainty.
RB=Path(os.environ.get("DOC_AUTOMATION_REFERENCES", str(Path.home()/"projects/gov-grants/_references")));codes=['AD2','TD3','TD4','CD1','TI1','TI4'];declarations={};cross={}
for code in codes:
 path=next(p for p in RB.rglob('*.hwpx') if f'SF-{code}_' in p.name);occ=[]
 with ZipFile(path) as z:
  for en in z.namelist():
   if not(en.startswith('Contents/section') and en.endswith('.xml')):continue
   rt=E.fromstring(z.read(en));par={c:p for p in rt.iter() for c in p};ps=[e for e in rt.iter() if e.tag.endswith('}p')];pid={id(e):i+1 for i,e in enumerate(ps)};tables=[e for e in rt.iter() if e.tag.endswith('}tbl')]
   for ti,tb in enumerate(tables,1):
    trs=[e for e in tb if e.tag.endswith('}tr')]
    for ri,tr in enumerate(trs,1):
     for ci,tc in enumerate([e for e in tr if e.tag.endswith('}tc')],1):
      text=''.join(e.text or '' for e in tc.iter() if e.tag.endswith('}t'))
      for match in re.finditer(r'MES-'+code+r'-\d{3}',text):occ.append({'id':match[0],'locator':f'{en}#T{ti}/R{ri}C{ci}','text':text[:500]})
 declarations[code]=set(o['id'] for o in occ);cross[code]={'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'occurrences':occ}
s=D['ref-pm7-trace']['sections'][1]
for t in s['tables']:
 for r,cs in rows(t).items():
  if r==1:continue
  for c in cs:
   for m in re.finditer(r'MES-(AD2|TD3|TD4|CD1|TI1|TI4)-\d{3}',c['text']):
    code=m[1];A['trace_links'].append({'id':m[0],'trace_locator':c['locator'],'target_artifact_code':code,'found_in_target_source':m[0] in declarations[code],'target_occurrences':[o for o in cross[code]['occurrences'] if o['id']==m[0]]})
A['trace_source_inventory']=cross
# Direct effective run formatting: actual run charPr/fontRef, not catalog of unused definitions.
for key,x in D.items():
 counts=collections.Counter();examples={};pages=[]
 for s in x['sections']:
  pages +=[{'entry':s['entry'],'pagePr':p} for p in s['page_properties'] if p['tag']=='pagePr']
  for p in s['paragraphs']:
   for r in p['runs']:
    if not r['text'].strip():continue
    val=(r['font_hangul'],r['height_source'],r['bold']);counts[val]+=len(r['text'].strip());examples.setdefault(val,p['locator'])
 A['font_profiles'][key]={'used_run_characters_by_format':[{'font':k[0],'height_source':k[1],'bold':k[2],'characters':v,'example':examples[k]} for k,v in counts.most_common()],'page_properties':pages}
A['summary']={'documents':6,'weekly_reports':len(A['weekly_register']),'meetings':len(meet),'changes':len(A['change_register']),'trace_id_links':len(A['trace_links']),'trace_links_found_in_correct_artifact':sum(q['found_in_target_source'] for q in A['trace_links']),'numeric_checks':len(A['numeric_checks']),'numeric_failures':sum(not q['passed'] for q in A['numeric_checks'])}
(O/'audit.json').write_text(json.dumps(A,ensure_ascii=False,indent=2));print(json.dumps(A['summary'],ensure_ascii=False));print(json.dumps(A['issues'],ensure_ascii=False,indent=2))
