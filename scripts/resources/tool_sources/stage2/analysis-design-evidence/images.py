import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from xml.etree import ElementTree as E
from PIL import Image, ImageOps, ImageDraw
import json,zipfile,hashlib
OUT=Path(__file__).resolve().parent/'images';OUT.mkdir(exist_ok=True)
def tag(e):return e.tag.split('}')[-1]
manifest=[]
for f in sorted(OUT.parent.glob('SF-*.json')):
 d=json.loads(f.read_text());code=d['code'];imgs=[]
 with zipfile.ZipFile(d['path']) as z:
  hpf=E.fromstring(z.read('Contents/content.hpf'));items={e.attrib.get('id'):e.attrib.get('href') for e in hpf.iter() if tag(e)=='item'}
  for sec in d['sections']:
   root=E.fromstring(z.read(sec['xml']));paths={root:'/hs:sec'}
   for n in root.iter():
    counter={}
    for c in n:
     t=tag(c);counter[t]=counter.get(t,0)+1;paths[c]=paths[n]+f'/{t}[{counter[t]}]'
   for n in root.iter():
    if tag(n)!='pic':continue
    im=next((c for c in n.iter() if tag(c)=='img'),None)
    if im is None:continue
    key=im.attrib.get('binaryItemIDRef');href=items.get(key)
    if href not in z.namelist() and 'Contents/'+str(href) in z.namelist():href='Contents/'+href
    data=z.read(href);target=OUT/f'{code}-{key}{Path(href).suffix}';target.write_bytes(data)
    record={'code':code,'section':sec['xml'],'picture_xpath':paths[n],'binary_id':key,'zip_path':href,'file':str(target),'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)}
    try:
     with Image.open(target) as img:record['pixel_size']=img.size;record['format']=img.format
    except Exception as e:record['error']=str(e)
    imgs.append(record);manifest.append(record)
  for i in range(0,len(imgs),6):
   sheet=Image.new('RGB',(1800,1300),'#eeeeee');draw=ImageDraw.Draw(sheet)
   for j,rec in enumerate(imgs[i:i+6]):
    x=(j%3)*600;y=(j//3)*650;draw.text((x+12,y+8),f"{code} {rec['binary_id']} {rec.get('pixel_size')}",fill='black')
    try:
     im=Image.open(rec['file']).convert('RGB');im.thumbnail((576,610));sheet.paste(im,(x+(600-im.width)//2,y+34+(610-im.height)//2))
    except Exception:draw.text((x+12,y+40),'Cannot rasterize; inspect native PDF',fill='red')
   sheet.save(OUT/f'{code}-contact-{i//6+1}.jpg',quality=90)
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print('pictures',len(manifest),'sheets',len(list(OUT.glob('*contact*'))))
