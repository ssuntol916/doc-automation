import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from xml.etree import ElementTree as E
import json,collections
ROOT=Path(__file__).resolve().parent
all=[]
def loc(n):return n.tag.split('}')[-1]
def summarize(d):
 fonts={f['id']:f['face'] for ff in d['fonts'] if ff['lang']=='HANGUL' for f in ff['fonts']};chars={c['attributes']['id']:c for c in d['char_properties']};paras={p['attributes']['id']:p for p in d['paragraph_properties']};cw=collections.Counter();pw=collections.Counter();samples={}
 for s in d['sections']:
  for p in s['paragraphs']:
   if p['container'] in ('header','footer') or not p['text'].strip():continue
   pid=p['attributes']['paraPrIDRef'];pw[pid]+=len(p['text']);samples.setdefault(('p',pid),{'xml':s['xml'],'xpath':p['xpath'],'sample':p['text'][:100]})
   for r in p['runs']:
    if not r['text'].strip():continue
    cid=r['attributes']['charPrIDRef'];cw[cid]+=len(r['text']);samples.setdefault(('c',cid),{'xml':s['xml'],'xpath':p['xpath'],'sample':r['text'][:100]})
 chars_used=[]
 for k,w in cw.most_common():
  ch=chars[k];children={k:v for child in ch['children'] for k,v in child.items()};fr=children.get('fontRef',{}).get('hangul');chars_used.append({'id':k,'characters':w,'font':fonts.get(fr),'pt':int(ch['attributes']['height'])/100,'color':ch['attributes'].get('textColor'),'bold':'bold' in children,'spacing':children.get('spacing'),'ratio':children.get('ratio'),'evidence':samples['c',k]})
 paras_used=[]
 for k,w in pw.most_common():
  pr=E.fromstring(paras[k]['xml']);paras_used.append({'id':k,'characters':w,'align':[x.attrib for x in pr.iter() if loc(x)=='align'],'lineSpacing':[x.attrib for x in pr.iter() if loc(x)=='lineSpacing'],'margin_xml':[E.tostring(x,encoding='unicode') for x in pr.iter() if loc(x)=='margin'],'evidence':samples['p',k]})
 tables=[]
 for s in d['sections']:
  for t in s['tables']:
   properties={k:v for child in t['table_properties'] for k,v in child.items()};tables.append({'xml':s['xml'],'index':t['index'],'xpath':t['xpath'],'rows':t['attributes']['rowCnt'],'cols':t['attributes']['colCnt'],'pageBreak':t['attributes']['pageBreak'],'repeatHeader':t['attributes']['repeatHeader'],'size':properties.get('sz'),'position':properties.get('pos'),'first_row_widths':[c['size'].get('width') for c in t['rows'][0]['cells']],'merged_cells':[{'address':c['address'],'span':c['span']} for r in t['rows'] for c in r['cells'] if int(c['span']['colSpan'])>1 or int(c['span']['rowSpan'])>1]})
 return {'char_styles_used_by_nonempty_text':chars_used,'para_styles_used_by_nonempty_text':paras_used,'tables':tables,'page_settings':[{'xml':s['xml'],'properties':[(p['tag'],p['attributes']) for p in s['section_properties'] if p['tag']=='pagePr']} for s in d['sections']]}
for ref in sorted(ROOT.glob('SF-*.json')):
 d=json.loads(ref.read_text());td=json.loads((ROOT.parents[1]/'stage1'/'analysis-design-evidence'/ref.name).read_text());r={'code':d['code'],'reference_sha256':d['sha256'],'template_sha256':td['sha256'],'template':summarize(td),'reference':summarize(d)};all.append(r)
(ROOT/'format-comparison.json').write_text(json.dumps(all,ensure_ascii=False,indent=2))
for d in all:
 print('\n'+d['code'])
 for kind in ('template','reference'):
  print(kind,[(x['id'],x['font'],x['pt'],x['color'],'B' if x['bold'] else '',x['characters']) for x in d[kind]['char_styles_used_by_nonempty_text'][:5]])
  print('paragraphs',[(x['id'],x['align'],x['lineSpacing'],x['characters']) for x in d[kind]['para_styles_used_by_nonempty_text'][:3]])
 print('reference sizes',[(t['xml'][-5],t['index'],t['rows'],t['cols'],t['pageBreak'],t['size']['width']) for t in d['reference']['tables']])
