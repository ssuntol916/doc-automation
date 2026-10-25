import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from zipfile import ZipFile
from collections import defaultdict,Counter
from io import BytesIO
import xml.etree.ElementTree as E
import json,hashlib,re
from PIL import Image,ImageDraw,ImageFont
OUT=Path(__file__).parent
IMG=OUT/'test-transition-images';IMG.mkdir(exist_ok=True)
NS={'hp':'http://www.hancom.co.kr/hwpml/2011/paragraph','hc':'http://www.hancom.co.kr/hwpml/2011/core'}
CODES=['cd1','ti1','ti2','ti3','ti4']
def local(e):return e.tag.rsplit('}',1)[-1]
def text(e):return ''.join(''.join(t.itertext()) for t in e.iter() if local(t)=='t')
def norm(s):return re.sub(r'\s+',' ',s).strip()
result=[];unique={}
for code in CODES:
 d=json.loads((OUT/f'profiles/reference-sf-{code}.json').read_text())
 pics=[];object_counts=Counter();cells=[]
 with ZipFile(d['source_path']) as z:
  manifest=E.fromstring(z.read('Contents/content.hpf'))
  items={i.get('id'):i.get('href') for i in manifest.iter() if local(i)=='item'}
  for s in d['sections']:
   root=E.fromstring(z.read(s['name']));parents={c:p for p in root.iter() for c in p}
   ps=[p for p in root.iter() if local(p)=='p'];pi={p:i+1 for i,p in enumerate(ps)}
   ts=[t for t in root.iter() if local(t)=='tbl'];ti={t:i+1 for i,t in enumerate(ts)}
   def nearest(e,tag):
    x=parents.get(e)
    while x is not None:
     if local(x)==tag:return x
     x=parents.get(x)
   def ref(e):
    t=nearest(e,'tbl');c=nearest(e,'tc');p=nearest(e,'p')
    r={'paragraph':f'{s["name"]}#P{pi[p]}' if p is not None else None}
    if t is not None:r['table']=f'{s["name"]}#T{ti[t]}'
    if c is not None:
     a=c.find('hp:cellAddr',NS);r['cell']=f'{s["name"]}#T{ti[t]}/R{a.get("rowAddr")}C{a.get("colAddr")}'
     r['cell_text']=norm(text(c));r['row']=int(a.get('rowAddr'));r['column']=int(a.get('colAddr'))
    return r
   for c in [c for c in root.iter() if local(c)=='tc']:
    t=nearest(c,'tbl');a=c.find('hp:cellAddr',NS)
    cells.append({'ref':f'{s["name"]}#T{ti[t]}/R{a.get("rowAddr")}C{a.get("colAddr")}','text':text(c),'normalized_text':norm(text(c)),'picture_count':sum(local(x)=='pic' for x in c.iter())})
   for o in s['objects']:object_counts[o['type']]+=1
   for n,pic in enumerate([p for p in root.iter() if local(p)=='pic'],1):
    img=pic.find('hc:img',NS);item=img.get('binaryItemIDRef');member=items[item];data=z.read(member);sha=hashlib.sha256(data).hexdigest()
    im=Image.open(BytesIO(data));im.load();out=IMG/(sha[:16]+'.png')
    if not out.exists():im.save(out)
    rec={'ref':f'{s["name"]}#Pic{n}','image_id':item,'member':member,'sha256':sha,'pixel_size':list(im.size),'local_path':str(out),'display_size':pic.find('hp:sz',NS).attrib,'position':pic.find('hp:pos',NS).attrib,**ref(pic)}
    pics.append(rec);unique[sha]=rec
  binaries=[{'member':n,'sha256':hashlib.sha256(z.read(n)).hexdigest()} for n in z.namelist() if n.startswith('BinData/')]
 unique_order=list(dict.fromkeys(p['sha256'] for p in pics))
 # Contact sheets preserve source assets; thumbnails exist solely for inspection.
 for start in range(0,len(unique_order),24):
  batch=unique_order[start:start+24];canvas=Image.new('RGB',(1200,((len(batch)+3)//4)*195),'#dddddd');draw=ImageDraw.Draw(canvas)
  for j,sha in enumerate(batch):
   rec=next(p for p in pics if p['sha256']==sha);im=Image.open(rec['local_path']).convert('RGB');im.thumbnail((290,163))
   x=(j%4)*300;y=(j//4)*195;canvas.paste(im,(x+(300-im.width)//2,y+25))
   draw.text((x+4,y+4),f'{code} {rec["image_id"]} {rec["ref"].split("#")[-1]} {sha[:6]}',fill='black')
  canvas.save(IMG/f'{code}-contact-{start//24+1}.jpg')
 # Annotate visual roles from source placement; no performance/authenticity inference.
 for p in pics:
  tn=int(p['table'].split('#T')[-1]) if p.get('table') else None
  pn=int(p['ref'].split('#Pic')[-1])
  if code=='cd1':p['role']='output_label' if p['image_id']=='image9' else 'test_result_screen'
  elif code in ('ti1','ti4'):
   p['role']='education_attendance_scan' if tn is None else ('business_flow_diagram' if p.get('row')==1 else ('output_label' if p['image_id'] in ('image29','image56') else 'test_result_screen'))
  elif code=='ti2':
   roles={4:'hardware_installation_photo',5:'hardware_identity_or_system_spec',6:'hardware_identity_or_system_spec',7:'hardware_identity_or_system_spec',8:'hardware_identity_or_system_spec',9:'transaction_statement_scan',11:'software_usage_certificate',12:'security_software_certificate',13:'transaction_statement_scan',15:'network_work_photo',16:'transaction_statement_scan',21:'application_start_screen',23:'operating_system_configuration',24:'operating_system_configuration'}
   p['role']=roles.get(tn,'initial_data_screen' if pn>=139 else ('database_deployment_screen' if pn in (127,128) else 'software_configuration_or_application_screen'))
  elif code=='ti3':
   p['role']=('system_architecture_diagram' if pn<=7 else 'common_screen_guide' if pn<=12 else 'external_attachment_filenames' if pn==13 else 'application_access_guide' if pn<=25 and pn!=19 else 'directory_architecture_diagram' if pn==19 else 'user_management_guide' if pn==26 else 'version_management_screen' if pn==27 else 'backup_restore_guide')
 object_inventory=[]
 for sec in d['sections']:
  for o in sec['objects']:
   def tt(x):return (x.get('text','') or '')+' '.join(tt(c) for c in x.get('children',[]))
   object_inventory.append({'section':sec['name'],'type':o['type'],'xpath':o['xpath'],'text':norm(tt(o['data'])) if o['type'] not in ('pic',) else None,'role': 'incident_management_flowchart' if o['type'] in ('container','rect','connectLine','line') else o['type']})
 result.append({'object_inventory':object_inventory,'code':'SF-'+code.upper(),'source':d['source_path'],'sha256':d['sha256'],'statistics':d['statistics'],'object_counts':dict(object_counts),'binary_members':binaries,'picture_instances':pics,'unique_picture_hashes':unique_order,'cells':cells})
(OUT/'test-transition-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
for r in result:
 print(r['code'],'pictures',len(r['picture_instances']),'unique',len(r['unique_picture_hashes']),'binaries',len(r['binary_members']),'objects',r['object_counts'])
for a in result:
 for b in result:
  if a['code']<b['code']:
   n=len(set(a['unique_picture_hashes'])&set(b['unique_picture_hashes']))
   if n:print('shared',a['code'],b['code'],n)
