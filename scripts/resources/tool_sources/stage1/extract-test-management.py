"""Read-only XML inventory for the assigned stage-1 templates. No source mutation."""
import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from collections import Counter
import json, re, unicodedata, hashlib
NS={'hp':'http://www.hancom.co.kr/hwpml/2011/paragraph','hc':'http://www.hancom.co.kr/hwpml/2011/core','hh':'http://www.hancom.co.kr/hwpml/2011/head'}
BASE=Path(os.environ.get("DOC_AUTOMATION_TEMPLATES", str(Path.home()/"projects/gov-grants/_templates")))
OUT=Path(__file__).parent
CODES=['SF-CD1','SF-TI1','SF-TI2','SF-TI3','SF-TI4','SF-OS1','SF-OS2','SF-PM1','SF-PM2','SF-PM3','SF-PM4']
def local(t): return t.rsplit('}',1)[-1]
def plain(e):
    return ''.join(''.join(x.itertext()) for x in e.iter() if local(x.tag)=='t')
def directtext(e):
    # Text belonging to this paragraph; exclude embedded table/header/footer contents.
    out=[]
    def walk(x):
        for c in x:
            if local(c.tag) in ('tbl','header','footer'): continue
            if local(c.tag)=='t': out.append(''.join(c.itertext()))
            else: walk(c)
    walk(e)
    return ''.join(out)
def extract(p):
    record={'source':str(p),'normalized_filename':unicodedata.normalize('NFC',p.name),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'sections':[]}
    with ZipFile(p) as z:
        record['zip_members']=z.namelist()
        h=ET.fromstring(z.read('Contents/header.xml'))
        record['header']={}
        for name in ('fontfaces','charProperties','paraProperties','styles','borderFills'):
            el=next((e for e in h.iter() if local(e.tag)==name),None)
            record['header'][name]=ET.tostring(el,encoding='unicode') if el is not None else None
        record['binary_items']=[n for n in z.namelist() if n.startswith('BinData/')]
        record['fonts']={e.get('lang'):{f.get('id'):f.get('face') for f in e} for e in h.iter() if local(e.tag)=='fontface'}
        record['char_properties']={e.get('id'):{'attributes':e.attrib,'font_ref': next((x.attrib for x in e if local(x.tag)=='fontRef'),{}),'bold':any(local(x.tag)=='bold' for x in e),'italic':any(local(x.tag)=='italic' for x in e),'details':{local(x.tag):x.attrib for x in e}} for e in h.iter() if local(e.tag)=='charPr'}
        record['para_properties']={e.get('id'):{'attributes':e.attrib,'xml':ET.tostring(e,encoding='unicode')} for e in h.iter() if local(e.tag)=='paraPr'}
        record['styles']=[e.attrib for e in h.iter() if local(e.tag)=='style']
        for n in sorted(z.namelist()):
            if not re.fullmatch(r'Contents/section\d+\.xml',n): continue
            r=ET.fromstring(z.read(n)); parents={c:a for a in r.iter() for c in a}
            ps=list(r.iter('{'+NS['hp']+'}p')); ts=list(r.iter('{'+NS['hp']+'}tbl'))
            pi={e:i+1 for i,e in enumerate(ps)}; ti={e:i+1 for i,e in enumerate(ts)}
            def ancestors(e):
                result=[]; a=parents.get(e)
                while a is not None:
                    result.append(local(a.tag)); a=parents.get(a)
                return result
            def table_parent(e):
                a=parents.get(e)
                while a is not None:
                    if a in ti: return ti[a]
                    a=parents.get(a)
                return None
            section={'member':n,'paragraph_count':len(ps),'table_count':len(ts),'page_settings':[ET.tostring(e,encoding='unicode') for e in r.iter() if local(e.tag)=='pagePr'],'paragraphs':[],'tables':[]}
            for e in ps:
                text=directtext(e)
                section['paragraphs'].append({'ref':f'{n}#P{pi[e]}','text':text,'attributes':e.attrib,'table':table_parent(e),'ancestors':ancestors(e),'pictures':[ET.tostring(x,encoding='unicode') for x in e.iter() if local(x.tag)=='pic'],'charPrIDRefs':[x.get('charPrIDRef') for x in e if local(x.tag)=='run'],'field_controls':[ET.tostring(x,encoding='unicode') for x in e.iter() if local(x.tag) in ('fieldBegin','fieldEnd','autoNum','pageNum','pageHiding','header','footer')]})
            for t in ts:
                tbl={'ref':f'{n}#T{ti[t]}','attributes':t.attrib,'parent_table':table_parent(t),'size':t.find('hp:sz',NS).attrib,'position':t.find('hp:pos',NS).attrib,'cells':[]}
                for tr in t.findall('hp:tr',NS):
                    for c in tr.findall('hp:tc',NS):
                        addr=c.find('hp:cellAddr',NS).attrib; span=c.find('hp:cellSpan',NS).attrib
                        tbl['cells'].append({'ref':f'{n}#T{ti[t]}/R{addr["rowAddr"]}C{addr["colAddr"]}','address':addr,'span':span,'attributes':c.attrib,'size':c.find('hp:cellSz',NS).attrib,'margin':c.find('hp:cellMargin',NS).attrib,'text':plain(c),'paragraph_refs':[f'{n}#P{pi[e]}' for e in c.iter('{'+NS['hp']+'}p')],'nested_tables':[f'{n}#T{ti[e]}' for e in c.iter('{'+NS['hp']+'}tbl')]})
                section['tables'].append(tbl)
            record['sections'].append(section)
    return record
records=[]
for code in CODES:
    p=next(p for p in BASE.rglob('*.hwpx') if p.name.startswith(code+' '))
    rec=extract(p); rec['code']=code; records.append(rec)
    lines=[rec['normalized_filename']]
    for s in rec['sections']:
        lines.append('\n'+s['member']+f" ({s['paragraph_count']} paragraphs, {s['table_count']} tables)")
        for p in s['paragraphs']:
            if p['table'] is None and p['text'].strip(): lines.append(p['ref']+' '+p['text'])
        for t in s['tables']:
            lines.append(f"\n{t['ref']} {t['attributes']} size={t['size']}")
            for c in t['cells']:
                lines.append(f"  {c['ref']} span={c['span']} p={','.join(r.split('#')[1] for r in c['paragraph_refs'])} text={c['text']}")
    (OUT/(code+'-xml-review.txt')).write_text('\n'.join(lines),encoding='utf8')
(OUT/'test-management-xml.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps([{'code':r['code'],'sections':len(r['sections']),'tables':sum(s['table_count'] for s in r['sections']),'paragraphs':sum(s['paragraph_count'] for s in r['sections'])} for r in records],ensure_ascii=False,indent=2))
