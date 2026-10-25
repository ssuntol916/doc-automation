import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from xml.etree import ElementTree as E
import json,zipfile,hashlib
ROOT=Path(__file__).resolve().parent
out={'scope':'SF-AD1~AD3, SF-TD1~TD5 templates only','checks':[],'pass':True}
rules=[]
starts={'SF-AD1':('Contents/section1.xml',3),'SF-AD2':('Contents/section1.xml',3),'SF-AD3':('Contents/section0.xml',28),'SF-TD1':('Contents/section1.xml',3),'SF-TD2':('Contents/section1.xml',3),'SF-TD3':('Contents/section0.xml',59),'SF-TD4':('Contents/section0.xml',39),'SF-TD5':('Contents/section0.xml',39)}
for file in sorted(ROOT.glob('SF-*.json')):
 d=json.loads(file.read_text());checks=[]
 checks.append({'check':'source_hash_unchanged','pass':hashlib.sha256(Path(d['path']).read_bytes()).hexdigest()==d['sha256']})
 with zipfile.ZipFile(d['path']) as z:
  checks.append({'check':'zip_crc','pass':z.testzip() is None})
  for s in d['sections']:
   source=E.fromstring(z.read(s['xml']));native_paras=[p for p in source.iter() if p.tag.split('}')[-1]=='p'];native_tables=[p for p in source.iter() if p.tag.split('}')[-1]=='tbl']
   def local(e): return e.tag.split('}')[-1]
   owned_text=[]
   def visit_owned(n, origin):
    if n is not origin and local(n) in ('tbl','header','footer','p'): return
    if local(n)=='t':
     owned_text.append(n)
     return
    for child in n: visit_owned(child,origin)
   for p in native_paras: visit_owned(p,p)
   native_t=[x for x in source.iter() if local(x)=='t']
   inline_children=[c for t in native_t for c in t]
   checks.append({'check':'text_nodes_owned_by_one_paragraph_including_inline_tails','xml':s['xml'],'expected_text_nodes':len(native_t),'owned_text_nodes':len(owned_text),'unique_owned_text_nodes':len(set(id(n) for n in owned_text)),'inline_child_count':len(inline_children),'nonempty_inline_tail_count':sum(bool(x.tail) for x in inline_children),'pass':len(native_t)==len(owned_text)==len(set(id(n) for n in owned_text))})
   checks.append({'check':'paragraph_nodes_extracted_once','xml':s['xml'],'expected':len(native_paras),'actual':len(s['paragraphs']),'pass':len(native_paras)==len(s['paragraphs'])==len(set(p['xpath'] for p in s['paragraphs']))})
   checks.append({'check':'table_nodes_extracted_once','xml':s['xml'],'expected':len(native_tables),'actual':len(s['tables']),'pass':len(native_tables)==len(s['tables'])==len(set(t['xpath'] for t in s['tables']))})
   for t in s['tables']:
    rc=int(t['attributes']['rowCnt']);cc=int(t['attributes']['colCnt']);grid={};bad=[];cells=0
    for row in t['rows']:
     for c in row['cells']:
      cells+=1;r=int(c['address']['rowAddr']);col=int(c['address']['colAddr']);rs=int(c['span']['rowSpan']);cs=int(c['span']['colSpan'])
      if rs<1 or cs<1 or r<0 or col<0 or r+rs>rc or col+cs>cc:bad.append({'kind':'invalid_span','cell':c['address']})
      for r2 in range(r,r+rs):
       for c2 in range(col,col+cs):
        if (r2,c2) in grid:bad.append({'kind':'overlap','r':r2,'c':c2})
        grid[r2,c2]=c['xpath']
    missing=[(r,c) for r in range(rc) for c in range(cc) if (r,c) not in grid]
    checks.append({'check':'table_grid_coverage_and_nonoverlap','xml':s['xml'],'table_index':t['index'],'xpath':t['xpath'],'rows':rc,'cols':cc,'physical_cells':cells,'logical_grid_cells':len(grid),'missing':missing,'errors':bad,'pass':not missing and not bad})
   rule_sec,start=starts[d['code']]
   if s['xml']==rule_sec:
    for p in s['paragraphs']:
     if p['container']!='body' or not p['text'].strip() or not p['xpath'].startswith('/hs:sec/p['):continue
     topn=int(p['xpath'].split('/p[',1)[1].split(']',1)[0])
     if topn<=start:continue
     text=p['text'];kind='template_instruction'
     if text.strip()=='. 화면(보고서) 설계의':kind='instruction_fragment'
     if d['code']=='SF-AD2' and topn==15:kind='template_classification_example_not_general_definition'
     rules.append({'rule_id':f"{d['code']}-s{rule_sec.split('section')[1].split('.')[0]}-p{topn}",'document_code_from_filename':d['code'],'template_version_from_filename':'V2.0','source_file_sha256':d['sha256'],'source_xml':s['xml'],'source_xpath':p['xpath'],'source_text_verbatim':text,'evidence_type':kind,'is_current_regulatory_requirement_verified':False})
 out['checks'].append({'code':d['code'],'pass':all(x['pass'] for x in checks),'checks':checks})
out['pass']=all(d['pass'] for d in out['checks'])
(ROOT/'audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
(ROOT.parent/'analysis-design-rules.json').write_text(json.dumps({'scope':'Original template instructions only; no reference-derived observations or legal currency claims.','rules':rules},ensure_ascii=False,indent=2))
print(json.dumps({'pass':out['pass'],'documents':len(out['checks']),'rule_paragraphs':len(rules),'checks':sum(len(x['checks']) for x in out['checks'])},ensure_ascii=False))
