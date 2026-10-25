import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from xml.etree import ElementTree as E
import zipfile,json,hashlib,unicodedata,re
BASE=Path(os.environ.get("DOC_AUTOMATION_TEMPLATES", str(Path.home()/"projects/gov-grants/_templates")))
OUT=Path(__file__).resolve().parent
CODES=['SF-AD1','SF-AD2','SF-AD3','SF-TD1','SF-TD2','SF-TD3','SF-TD4','SF-TD5']
def tag(e): return e.tag.split('}')[-1]
def textown(e):
 out=[]
 def walk(n):
  if n is not e and tag(n) in ('tbl','header','footer','p'): return
  if tag(n)=='t': out.append(''.join(n.itertext()))
  elif tag(n)=='lineBreak': out.append('\n')
  elif tag(n)=='tab': out.append('\t')
  else:
   for c in n: walk(c)
 walk(e)
 return ''.join(out)
def fulltext(e): return '\n'.join(textown(p) for p in e.iter() if tag(p)=='p' and textown(p))
all_docs=[]
for code in CODES:
 p=next(BASE.rglob(code+' *.hwpx'))
 with zipfile.ZipFile(p) as z:
  h=E.fromstring(z.read('Contents/header.xml'))
  fonts=[];charPr=[];paraPr=[];styles=[]
  for el in h.iter():
   if tag(el)=='fontface': fonts.append({'lang':el.attrib.get('lang'),'fonts':[dict(x.attrib) for x in el if tag(x)=='font']})
   elif tag(el)=='charPr': charPr.append({'attributes':dict(el.attrib),'children':[{tag(x):dict(x.attrib)} for x in el]})
   elif tag(el)=='paraPr': paraPr.append({'attributes':dict(el.attrib),'xml':E.tostring(el,encoding='unicode')})
   elif tag(el)=='style': styles.append(dict(el.attrib))
  doc={'code':code,'path':str(p),'filename_nfc':unicodedata.normalize('NFC',p.name),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'zip_entries':z.namelist(),'fonts':fonts,'border_fills':[{'attributes':dict(e.attrib),'xml':E.tostring(e,encoding='unicode')} for e in h.iter() if tag(e)=='borderFill'],'char_properties':charPr,'paragraph_properties':paraPr,'styles':styles,'sections':[]}
  for name in sorted(z.namelist()):
   if not re.fullmatch(r'Contents/section\d+.xml',name): continue
   root=E.fromstring(z.read(name));parents={c:n for n in root.iter() for c in n};paths={root:'/hs:sec'}
   for n in root.iter():
    counter={}
    for c in n:
     t=tag(c);counter[t]=counter.get(t,0)+1;paths[c]=paths[n]+f'/{t}[{counter[t]}]'
   def ancestors(n):
    result=[]
    while n in parents: n=parents[n];result.append(n)
    return result
   sec={'xml':name,'section_properties':[],'paragraphs':[],'tables':[],'headers_footers':[],'controls':[]}
   for n in root.iter():
    t=tag(n)
    if t in ('secPr','pagePr','pageBorderFill','footNotePr','endNotePr'): sec['section_properties'].append({'xpath':paths[n],'tag':t,'attributes':dict(n.attrib),'xml':E.tostring(n,encoding='unicode')})
    if t in ('pagePr','pageNum','pageNumCtrl','hide','newNum','autoNum','colPr','pageHiding'): sec['controls'].append({'xpath':paths[n],'tag':t,'attributes':dict(n.attrib)})
    if t=='p':
     anc=ancestors(n);container=next((tag(a) for a in anc if tag(a) in ('tc','header','footer')), 'body')
     sec['paragraphs'].append({'xpath':paths[n],'text':textown(n),'container':container,'attributes':dict(n.attrib),'runs':[{'attributes':dict(x.attrib),'text':textown(x)} for x in n if tag(x)=='run']})
    elif t in ('header','footer'): sec['headers_footers'].append({'type':t,'xpath':paths[n],'attributes':dict(n.attrib),'text':fulltext(n)})
    elif t=='tbl':
     tab={'index':len(sec['tables'])+1,'xpath':paths[n],'attributes':dict(n.attrib),'nested':any(tag(a)=='tbl' for a in ancestors(n)),'table_properties':[{tag(x):dict(x.attrib)} for x in n if tag(x)!='tr'],'rows':[]}
     for ri,tr in enumerate(x for x in n if tag(x)=='tr'):
      cells=[]
      for ci,tc in enumerate(x for x in tr if tag(x)=='tc'):
       cps=[x for x in tc.iter() if tag(x)=='p' and not any(tag(a)=='tbl' for a in ancestors(x)[:ancestors(x).index(tc)])]
       cells.append({'xml_cell_index':ci,'xpath':paths[tc],'attributes':dict(tc.attrib),'address':next((dict(x.attrib) for x in tc if tag(x)=='cellAddr'),{}),'span':next((dict(x.attrib) for x in tc if tag(x)=='cellSpan'),{}),'size':next((dict(x.attrib) for x in tc if tag(x)=='cellSz'),{}),'margins':next((dict(x.attrib) for x in tc if tag(x)=='cellMargin'),{}),'text':'\n'.join(textown(x) for x in cps if textown(x)),'paragraphs':[paths[x] for x in cps]})
      tab['rows'].append({'xml_row_index':ri,'cells':cells})
     sec['tables'].append(tab)
   doc['sections'].append(sec)
  (OUT/(code+'.json')).write_text(json.dumps(doc,ensure_ascii=False,indent=2))
  lines=[f'# {code} {doc["filename_nfc"]}',f'SHA256 {doc["sha256"]}']
  for sec in doc['sections']:
   lines.append(f'XML {sec["xml"]}')
   for para in sec['paragraphs']:
    if para['container']=='body' and para['text']:lines.append(f'P {para["xpath"]} [{para["attributes"]}] {para["text"]}')
   for tab in sec['tables']:
    lines.append(f'T{tab["index"]} {tab["xpath"]} {tab["attributes"]}')
    for row in tab['rows']:
     for cell in row['cells']:
      lines.append(f'  R{cell["address"].get("rowAddr")}C{cell["address"].get("colAddr")} span={cell["span"]}: {cell["text"]!r}')
   for hf in sec['headers_footers']: lines.append(f'{hf["type"].upper()} {hf["xpath"]}: {hf["text"]!r}')
  (OUT/(code+'.txt')).write_text('\n'.join(lines))
  all_docs.append({k:doc[k] for k in ('code','path','sha256')})
(OUT/'manifest.json').write_text(json.dumps(all_docs,ensure_ascii=False,indent=2))
