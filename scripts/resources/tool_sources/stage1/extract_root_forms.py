import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import unicodedata,json,hashlib,re
BASE=Path(os.environ.get("DOC_AUTOMATION_TEMPLATES", str(Path.home()/"projects/gov-grants/_templates")));OUT=Path(__file__).resolve().parent
def ln(e):return e.tag.rsplit('}',1)[-1]
def tx(e):
 if ln(e)=='tbl':return ''
 if ln(e)=='t':
  control={'lineBreak':'\n','tab':'\t','fwSpace':'　','nbSpace':' '}
  return (e.text or '')+''.join(control.get(ln(c),tx(c))+(c.tail or '') for c in e)
 return ''.join(tx(c) for c in e)
for path in BASE.glob('*.hwpx'):
 name=unicodedata.normalize('NFC',path.name);kind='forms' if name.startswith('2025') else 'deliverables'
 data={'source':str(path),'filename_nfc':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'currency':'현행 여부 미확인','locator_convention':'P/T are 1-based preorder of all paragraph/table XML elements per section; R/C are physical serialized tr/tc positions, cellAddr is zero-based logical grid; ordinals are not XML IDs or rendered page numbers.','sections':[]};summ=[]
 with ZipFile(path) as z:
  for entry in z.namelist():
   if not(entry.startswith('Contents/section') and entry.endswith('.xml')):continue
   root=ET.fromstring(z.read(entry));parent={c:p for p in root.iter() for c in p};ps=[e for e in root.iter() if ln(e)=='p'];ts=[e for e in root.iter() if ln(e)=='tbl'];pid={id(e):i+1 for i,e in enumerate(ps)};tid={id(e):i+1 for i,e in enumerate(ts)}
   def ancestor(e,tag):
    p=parent.get(e)
    while p is not None:
     if ln(p)==tag:return p
     p=parent.get(p)
    return None
   sd={'entry':entry,'paragraph_count':len(ps),'table_count':len(ts),'blocks':[],'tables':[]};data['sections'].append(sd);current='front';form_names={};current_heading='';sd['images']=[]
   manifest=ET.fromstring(z.read('Contents/content.hpf'));items={x.get('id'):x.get('href') for x in manifest.iter() if ln(x)=='item'}
   for top_idx,e in enumerate(list(root),1):
    text=tx(e).strip();match=re.match(r'\[서식 ([\d-]+)\]',text)
    if match:current=match.group(1);summ.append('\nFORM '+current+' '+text)
    if text: current_heading=text
    tables=[tid[id(t)] for t in e.iter() if ln(t)=='tbl']
    for im in (x for x in e.iter() if ln(x)=='img'):
     ip=ancestor(im,'p');ref=im.get('binaryItemIDRef');sd['images'].append({'form':current,'paragraph':pid[id(ip)] if ip is not None else None,'binaryItemIDRef':ref,'package_entry':items.get(ref),'sha256':hashlib.sha256(z.read(items[ref])).hexdigest() if ref in items else None})
    sd['blocks'].append({'top_level_paragraph':top_idx,'paragraph':pid.get(id(e)),'text':text,'table_ids':tables,'form':current})
    for t in (x for x in e.iter() if ln(x)=='tbl'):
     cells=[]
     for ri,row in enumerate([x for x in t if ln(x)=='tr'],1):
      for ci,c in enumerate([x for x in row if ln(x)=='tc'],1):
       addr=next((x.attrib for x in c if ln(x)=='cellAddr'),{});span=next((x.attrib for x in c if ln(x)=='cellSpan'),{})
       cps=[{'paragraph':pid[id(x)],'text':tx(x)} for x in c.iter() if ln(x)=='p' and ancestor(x,'tc') is c]
       cells.append({'row':ri,'cell':ci,'addr':addr,'span':span,'attributes':c.attrib,'properties':{ln(v):v.attrib for v in c if ln(v)!='subList'},'paragraphs':cps,'text':'\n'.join(x['text'] for x in cps),'nested_tables':[tid[id(x)] for x in c.iter() if ln(x)=='tbl' and ancestor(x,'tc') is c]})
     pt=ancestor(t,'tbl');tb={'id':tid[id(t)],'locator':f'{entry}#T{tid[id(t)]}','form':current,'parent_table':tid[id(pt)] if pt is not None else None,'preceding_top_level_text':current_heading,'attributes':t.attrib,'properties':{ln(v):v.attrib for v in t if ln(v)!='tr'},'cells':cells};sd['tables'].append(tb)
     # compact all unique nonempty strings, select first 25 except huge ones
     vals=list(dict.fromkeys(c['text'].replace('\n',' / ').strip() for c in cells if c['text'].strip()))
     summ.append(f'T{tb["id"]} P{pid[id(e)]} parent={tb["parent_table"]} {t.get("rowCnt")}x{t.get("colCnt")} '+ ' | '.join(v[:160] for v in vals[:25]))
   recorded={q['paragraph'] for t in sd['tables'] for c in t['cells'] for q in c['paragraphs']}|{b['paragraph'] for b in sd['blocks']}
   sd['extra_paragraphs']=[{'paragraph':pid[id(p)],'attributes':p.attrib,'text':tx(p),'parent_type':ln(parent[p]) if p in parent else None} for p in ps if pid[id(p)] not in recorded]
   sd['mixed_content_tails']=[{'paragraph':pid[id(ancestor(c,'p'))] if ancestor(c,'p') is not None else None,'control':ln(c),'tail':c.tail} for t in root.iter() if ln(t)=='t' for c in t.iter() if c is not t and c.tail]
 (OUT/f'{kind}-structure.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
 Path(f'/tmp/{kind}-summary.txt').write_text('\n'.join(summ))
 print(kind, len(summ))
