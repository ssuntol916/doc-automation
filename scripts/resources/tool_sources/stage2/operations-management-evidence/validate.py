import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as E
from collections import Counter
import json,hashlib,re
O=Path(__file__).resolve().parent;P=O.parent
D={p.stem:json.loads(p.read_text()) for p in O.glob('*.json') if p.stem.startswith(('ref-','template-'))};A=json.loads((O/'audit.json').read_text());R=json.loads((P/'operations-management-patterns.json').read_text())
checks=[]
def test(name,ok,details):
 if not ok:raise AssertionError((name,details))
 checks.append({'check':name,'passed':True,'details':details})
def local(e):return e.tag.rsplit('}',1)[-1]
def norm(s):return re.sub(r'\s+','',s)
for key,x in D.items():
 test(key+' unchanged source',hashlib.sha256(Path(x['source']).read_bytes()).hexdigest()==x['sha256'],x['sha256'])
 with ZipFile(x['source']) as z:
  test(key+' ZIP integrity',z.testzip() is None,len(z.namelist()))
  for s in x['sections']:
   root=E.fromstring(z.read(s['entry']));parents={c:p for p in root.iter() for c in p};ps=[e for e in root.iter() if local(e)=='p'];ts=[e for e in root.iter() if local(e)=='tbl'];pid={id(e):i+1 for i,e in enumerate(ps)}
   test(key+' '+s['entry']+' paragraph/table counts',len(ps)==len(s['paragraphs']) and len(ts)==len(s['tables']),{'paragraphs':len(ps),'tables':len(ts)})
   missing=[];n=0
   for t in root.iter():
    if local(t)!='t':continue
    literal=norm(''.join(t.itertext()))
    if not literal:continue
    p=parents.get(t)
    while p is not None and local(p)!='p':p=parents.get(p)
    if p is None:missing.append('no paragraph');continue
    n+=1;pp=pid[id(p)]
    if literal not in norm(s['paragraphs'][pp-1]['text']):missing.append(pp)
   test(key+' '+s['entry']+' independent literal mixed-content coverage',not missing,{'tested_nonempty_t_nodes':n,'missing':missing})
   for image in s['images']:
    test(key+' '+s['entry']+' asset at P'+str(image['paragraph']),hashlib.sha256(z.read(image['package_entry'])).hexdigest()==image['sha256'],image['package_entry'])
test('all six references',len([k for k in D if k.startswith('ref-')])==6,6)
test('five matched templates',len([k for k in D if k.startswith('template-')])==5,5)
test('48 weekly blocks and 96 body tables',len(A['weekly_register'])==48 and len(D['ref-pm2-weekly']['sections'][1]['tables'])==96,48)
test('10 meeting records cover all 33 body tables',len(A['meeting_register'])==10 and set(t for m in A['meeting_register'] for t in m['tables_in_record'])==set(range(1,34)),10)
test('6 change units',len(A['change_register'])==6 and len(D['ref-pm5-change']['sections'][0]['tables'])==14,6)
test('74 trace ID links found in proper target source',len(A['trace_links'])==74 and all(t['found_in_target_source'] for t in A['trace_links']),74)
test('105 numeric checks with 9 observed source defects',len(A['numeric_checks'])==105 and sum(not q['passed'] for q in A['numeric_checks'])==9,{'checks':105,'source_defects':9})
test('KPI six numerical checks pass',all(q['passed'] for q in A['numeric_checks'] if q['document']=='ref-pm6-kpi'),6)
test('role/cadence mappings',len(R['mappings'])==6 and next(m for m in R['mappings'] if m['reference']=='ref-pm2-weekly')['relation']=='partial_cadence_match' and next(m for m in R['mappings'] if m['reference']=='ref-pm6-kpi')['template'] is None,'weekly/monthly partial; no dedicated KPI template')
test('criteria have required statuses',len(R['all_compliance_criteria'])==36 and all(c['status'] in ['충족','미충족','판정불가'] for c in R['all_compliance_criteria']),dict(Counter(c['status'] for c in R['all_compliance_criteria'])))
test('taxonomy separates observations/instructions/facts/recommendations',set(p['category'] for p in R['reusable_patterns'])=={'expert_observation','official_template_instruction','business_specific_fact','generation_recommendation'},len(R['reusable_patterns']))
imgs=[i for k,x in D.items() if k.startswith('ref-') for s in x['sections'] for i in s['images']]
test('31 unique reference images / 83 occurrences',len(imgs)==83 and len({i['sha256'] for i in imgs})==31,{'occurrences':len(imgs),'unique':len({i['sha256'] for i in imgs})})
test('31 reviewed issue entries',len(R['all_reference_defects'])==31,len(R['all_reference_defects']))
report={'status':'passed','analysis_date':'2026-10-24','scope':'Evidence extraction completeness and report accounting; source-document numerical defects are intentionally retained/reported. No legal currency, document authenticity or native page quality claim.','checks':checks}
(O/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'checks_passed':len(checks),'criteria_statuses':dict(Counter(c['status'] for c in R['all_compliance_criteria']))},ensure_ascii=False))
