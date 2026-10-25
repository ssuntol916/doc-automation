"""Independently check source/cell accounting and source literal text coverage.

This is extraction QA, not a renderer or a source-policy currency check.
"""
import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as E
from collections import Counter
import json,hashlib,re
O=Path(__file__).resolve().parent
raw=json.loads((O/'forms-structure.json').read_text());cat=json.loads((O/'forms-catalog.json').read_text());dc=json.loads((O/'deliverables-catalog.json').read_text());dr=json.loads((O/'deliverables-structure.json').read_text())
checks=[]
def check(name,condition,details):
 if not condition:raise AssertionError((name,details))
 checks.append({'check':name,'passed':bool(condition),'details':details})
def local(e):return e.tag.rsplit('}',1)[-1]
def normalized(t):return re.sub(r'\s+','',t)
for src in [raw,dr]:
 h=hashlib.sha256(Path(src['source']).read_bytes()).hexdigest();check(src['filename_nfc']+' hash unchanged',h==src['sha256'],h)
 with ZipFile(src['source']) as z:
  for sd in src['sections']:
   rt=E.fromstring(z.read(sd['entry']));parents={c:p for p in rt.iter() for c in p};ps=[p for p in rt.iter() if local(p)=='p'];ts=[p for p in rt.iter() if local(p)=='tbl'];pi={id(p):i+1 for i,p in enumerate(ps)}
   check(src['filename_nfc']+' '+sd['entry']+' all tables',len(ts)==len(sd['tables']),len(ts))
   recorded={p['paragraph']:p['text'] for t in sd['tables'] for c in t['cells'] for p in c['paragraphs']};recorded.update({b['paragraph']:b['text'] for b in sd['blocks']});recorded.update({p['paragraph']:p['text'] for p in sd['extra_paragraphs']})
   check(src['filename_nfc']+' '+sd['entry']+' all paragraphs accounted',set(recorded)==set(range(1,len(ps)+1)),{'source':len(ps),'recorded':len(recorded)})
   tested=0;bad=[]
   for t in rt.iter():
    if local(t)!='t':continue
    literal=normalized(''.join(t.itertext()))
    if not literal:continue
    p=parents.get(t)
    while p is not None and local(p)!='p':p=parents.get(p)
    if p is None:bad.append({'reason':'no p ancestor','text':literal[:100]});continue
    idx=pi[id(p)];tested+=1
    if literal not in normalized(recorded[idx]):bad.append({'paragraph':idx,'text':literal[:100]})
   check(src['filename_nfc']+' '+sd['entry']+' independent source itertext coverage',not bad,{'nonempty_literal_t_elements_tested':tested,'omissions':bad})
   source_tails=[c.tail for t in rt.iter() if local(t)=='t' for c in t.iter() if c is not t and c.tail]
   check(src['filename_nfc']+' '+sd['entry']+' mixed-content tail accounting',len(source_tails)==len(sd['mixed_content_tails']),{'nonempty':len(source_tails),'nonwhitespace':sum(bool(v.strip()) for v in source_tails)})
   for i in sd.get('images',[]):
    check(src['filename_nfc']+' '+sd['entry']+' image '+i['binaryItemIDRef'],hashlib.sha256(z.read(i['package_entry'])).hexdigest()==i['sha256'],i['package_entry'])
check('34 TOC/body forms',len(cat['forms'])==34 and len({f['number'] for f in cat['forms']})==34,34)
check('table accounting',2+206==208 and sum(len(f['table_ids']) for f in cat['forms'])==205,{'front':2,'body_banner':1,'form_tables':205,'total':208})
check('unique body table assignment',set(t for f in cat['forms'] for t in f['table_ids'])==set(range(2,207)),'T2..T206, one form per table')
check('all table roles assigned',all(t.get('reviewed_role') for sec in raw['sections'] for t in sec['tables']),208)
check('image-only form10',len(next(f for f in cat['forms'] if f['number']=='10')['images'])==7 and next(f for f in cat['forms'] if f['number']=='10')['table_ids']==[],7)
check('deliverables count and requirement totals',len(dc['documents'])==19 and sum(d['required'] for d in dc['documents'])==17,{'required':17,'optional':2})
check('deliverable code uniqueness',len({d['form_code'] for d in dc['documents']})==19,19)
counts=dict(Counter(d['stage'] for d in dc['documents']));check('stage totals',sorted(counts.values())==[1,2,3,4,4,5],counts)
tails=[t for s in raw['sections'] for t in s['mixed_content_tails']]
check('forms source tail totals',len(tails)==47 and sum(bool(x['tail'].strip()) for x in tails)==45,{'nonempty':47,'nonwhitespace':45})
report={'analysis_date':'2026-10-24','status':'passed','scope':'Local read-only ZIP/XML completeness, independent literal mixed-content text extraction coverage, immutable source hashes, and catalog accounting. HWP page rendering, handwriting/seals, bitmap OCR correctness, current policy and legal applicability are outside this QA.','checks':checks}
(O/'forms-catalog-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'checks_passed':len(checks),'source_tail_fragments':len(tails),'stage_counts':counts},ensure_ascii=False))
