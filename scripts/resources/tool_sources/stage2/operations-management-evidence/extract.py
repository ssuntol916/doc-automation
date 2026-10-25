import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as E
from collections import Counter
import json,unicodedata,hashlib,re
OUT=Path(__file__).resolve().parent
TB=Path(os.environ.get("DOC_AUTOMATION_TEMPLATES", str(Path.home()/"projects/gov-grants/_templates")));RB=Path(os.environ.get("DOC_AUTOMATION_REFERENCES", str(Path.home()/"projects/gov-grants/_references")))
REF={'15_':'ref-os2','17_':'ref-pm2-weekly','19_':'ref-pm4-meeting','20_':'ref-pm5-change','21_':'ref-pm6-kpi','22_':'ref-pm7-trace'}
TMP={f'SF-{c}':'template-'+c.lower() for c in ['OS2','PM1','PM2','PM3','PM4']}
def local(e):return e.tag.rsplit('}',1)[-1]
def tx(e):
 if local(e)=='tbl':return ''
 if local(e)=='t':return (e.text or '')+''.join({'lineBreak':'\n','tab':'\t','fwSpace':'　','nbSpace':' '}.get(local(c),tx(c))+(c.tail or '') for c in e)
 return ''.join(tx(c) for c in e)
def tree(e):return {'tag':local(e),'attributes':e.attrib,'text':e.text,'children':[tree(c) for c in e]}
def extract(p,key):
 x={'key':key,'source':str(p),'name':unicodedata.normalize('NFC',p.name),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'sections':[]}
 lines=[]
 with ZipFile(p) as z:
  h=E.fromstring(z.read('Contents/header.xml'));defs={tag:{e.get('id'):tree(e) for e in h.iter() if local(e)==tag} for tag in ['charPr','paraPr','style','borderFill']};fonts={e.get('lang'):{f.get('id'):f.get('face') for f in e if local(f)=='font'} for e in h.iter() if local(e)=='fontface'};x['definitions']=defs;x['fonts']=fonts
  manifest=E.fromstring(z.read('Contents/content.hpf'));items={e.get('id'):e.get('href') for e in manifest.iter() if local(e)=='item'}
  x['metadata']=[{'tag':local(e),'attributes':e.attrib,'text':e.text} for e in manifest.iter() if local(e) in ['meta','title','language']]
  for entry in z.namelist():
   if not(entry.startswith('Contents/section') and entry.endswith('.xml')):continue
   lines.append('\nSECTION '+entry)
   root=E.fromstring(z.read(entry));parent={c:p for p in root.iter() for c in p};ps=[e for e in root.iter() if local(e)=='p'];ts=[e for e in root.iter() if local(e)=='tbl'];pid={id(e):i+1 for i,e in enumerate(ps)};tid={id(e):i+1 for i,e in enumerate(ts)}
   def anc(e,tag):
    p=parent.get(e)
    while p is not None:
     if local(p)==tag:return p
     p=parent.get(p)
    return None
   sd={'entry':entry,'paragraphs':[],'tables':[],'images':[],'page_properties':[tree(e) for e in root.iter() if local(e) in ['pagePr','pageBorderFill']]};x['sections'].append(sd)
   for para in ps:
    pp=pid[id(para)];t=anc(para,'tbl');c=anc(para,'tc');runs=[]
    for run in (e for e in para if local(e)=='run'):
     cp=run.get('charPrIDRef');ch=defs['charPr'].get(cp,{});ca=ch.get('attributes',{});fr=next((v['attributes'] for v in ch.get('children',[]) if v['tag']=='fontRef'),{});bold=any(v['tag']=='bold' for v in ch.get('children',[]))
     runs.append({'charPrIDRef':cp,'text':tx(run),'height_source':ca.get('height'),'bold':bold,'font_hangul':fonts.get('HANGUL',{}).get(fr.get('hangul')),'fontref':fr})
    sd['paragraphs'].append({'id':pp,'locator':f'{entry}#P{pp}','text':tx(para),'attributes':para.attrib,'table':tid.get(id(t)) if t is not None else None,'runs':runs})
    if t is None and tx(para).strip():lines.append(f'P{pp}: '+tx(para).replace('\n',' / '))
   for t in ts:
    tt=tid[id(t)];pt=anc(t,'tbl');cells=[]
    for ri,row in enumerate([e for e in t if local(e)=='tr'],1):
     for ci,c in enumerate([e for e in row if local(e)=='tc'],1):
      pars=[pid[id(e)] for e in c.iter() if local(e)=='p' and anc(e,'tc') is c];content='\n'.join(tx(ps[q-1]) for q in pars)
      cells.append({'row':ri,'cell':ci,'locator':f'{entry}#T{tt}/R{ri}C{ci}','attributes':c.attrib,'properties':{local(e):e.attrib for e in c if local(e)!='subList'},'paragraphs':pars,'text':content})
    record={'id':tt,'locator':f'{entry}#T{tt}','attributes':t.attrib,'properties':{local(e):e.attrib for e in t if local(e)!='tr'},'parent_table':tid.get(id(pt)) if pt is not None else None,'cells':cells};sd['tables'].append(record)
    lines.append(f'\nTABLE {tt} {t.get("rowCnt")}x{t.get("colCnt")}')
    for c in cells:lines.append(f'  R{c["row"]}C{c["cell"]} P{",".join(map(str,c["paragraphs"]))}: '+c['text'].replace('\n',' / '))
   for im in root.iter():
    if local(im)!='img':continue
    p0=anc(im,'p');ref=im.get('binaryItemIDRef');item=items.get(ref);n=key+'-'+Path(item).name;dest=OUT/n;dest.write_bytes(z.read(item));sd['images'].append({'paragraph':pid[id(p0)] if p0 is not None else None,'binaryItemIDRef':ref,'package_entry':item,'extracted_file':str(dest),'sha256':hashlib.sha256(z.read(item)).hexdigest()})
 x['counts']={'paragraphs':sum(len(s['paragraphs']) for s in x['sections']),'tables':sum(len(s['tables']) for s in x['sections']),'images':sum(len(s['images']) for s in x['sections'])}
 (OUT/(key+'.json')).write_text(json.dumps(x,ensure_ascii=False,indent=2));(OUT/(key+'.txt')).write_text('\n'.join(lines));print(key,x['counts'])
for p in RB.rglob('*.hwpx'):
 for prefix,key in REF.items():
  if p.name.startswith(prefix):extract(p,key)
for p in TB.rglob('*.hwpx'):
 for prefix,key in TMP.items():
  if p.name.startswith(prefix+' '):extract(p,key)
