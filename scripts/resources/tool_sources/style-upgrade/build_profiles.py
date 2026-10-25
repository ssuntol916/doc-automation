"""Build candidate source-specific editorial profiles and raw used-format evidence.
Reads original files without modification; writes only analysis/style-upgrade.
"""
import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from hashlib import sha256
from collections import Counter,defaultdict
from datetime import datetime,timezone
import json,re,zipfile,sys,shutil,math
from lxml import etree as E
import pymupdf
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
NS={'hs':'http://www.hancom.co.kr/hwpml/2011/section','hp':'http://www.hancom.co.kr/hwpml/2011/paragraph','hh':'http://www.hancom.co.kr/hwpml/2011/head','opf':'http://www.idpf.org/2007/opf'}
def load(p):return json.loads((R/p).read_text())
def h(p):return sha256(Path(p).read_bytes()).hexdigest()
def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def refine_native_layout():
 """Advance existing cover-v3 profiles without rebuilding or changing history.

 The observed native mutation is a generator coherence defect. Its values are
 declared editorial targets here; the native strict checker is not relaxed.
 """
 folder=O/'profiles';idx=load(folder/'index.json')
 profiles=[(entry,Path(entry['path']),load(entry['path'])) for entry in idx['profiles']]
 if all(p['version']==4 for _,_,p in profiles):
  print(json.dumps({'profiles':len(profiles),'version':4,'changed':False,'native_status':'pending_new_v4_bytes'}));return
 if any(p['version']!=3 for _,_,p in profiles):raise ValueError('Native layout refinement requires all19cover-v3 profiles')
 events_path=R/'verification/style-upgrade/iteration-02/TD5-native-events.json';events=load(events_path)
 for key in ('native_before','native_after','pdf'):
  if h(events[key]['path'])!=events[key]['sha256']:raise ValueError('Historical native evidence SHA changed:'+key)
 roundtrip=R/'verification/style-upgrade/iteration-02/TD5-roundtrip.json'
 frame_observations=[]
 for key in ('native_before','native_after'):
  with zipfile.ZipFile(events[key]['path']) as z:
   root=E.fromstring(z.read('Contents/section1.xml'));tree=root.getroottree();page=root.find('.//hp:pagePr',NS)
   frames=[{'xpath':tree.getpath(f),'attributes':dict(f.attrib)} for f in root.findall('hp:p/hp:run/hp:ctrl/hp:header/hp:subList',NS)]
   frame_observations.append({'artifact':key,'member':'Contents/section1.xml','page_xpath':tree.getpath(page),'page_attributes':dict(page.attrib),'margin':dict(page.find('hp:margin',NS).attrib),'frames':frames})
 font_path=Path('/Applications/Hancom Office HWP.app/Contents/Resources/Hnc/Shared/TTF/Install/HANBatang.ttf')
 font=pymupdf.Font(fontfile=str(font_path));padding=566;old_width=16000;new_width=17000
 advances=[{'exact_identifier':text,'advance_hwp_at_11pt':font.text_length(text,fontsize=11)*100,
            'required_cell_width_hwp_ceiling':math.ceil(font.text_length(text,fontsize=11)*100+padding)}
           for text in ('DEMO_PRODUCTION_RESULT','DEMO_QUALITY_INSPECTION')]
 if max(x['required_cell_width_hwp_ceiling'] for x in advances)>new_width:raise ValueError('Declared identifier width does not fit measured advances')
 evidence_path=folder/'native-layout-refinement-evidence.json'
 evidence={'schema_version':'native-layout-refinement-evidence-1','category':'observed_native_behavior_and_implementation_choice',
  'application':events['application'],'native_event_record':{'path':str(events_path),'sha256':h(events_path)},
  'strict_roundtrip_record':{'path':str(roundtrip),'sha256':h(roundtrip),'passed':load(roundtrip)['passed']},
  'observations':frame_observations,'frame_target_choice':'Direct section header/footer subList width = oriented paper width minus left/right/gutter; height = declared header/footer margin. This changes only frame extents, preserving text/IDs/character and paragraph definitions.',
  'identifier_width_choice':{'font_path':str(font_path),'font_sha256':h(font_path),'resolved_font_name':font.name,'font_size_pt':11,
   'measurement_engine':'PyMuPDF Font.text_length; glyph advances are supporting evidence, not native pagination proof','padding_left_right_hwp':padding,
   'old_table_id_column_width_hwp':old_width,'new_table_id_column_width_hwp':new_width,'identifiers':advances,
   'width_donor':'Remarks column7000→6000; its compact constraint reference keys retain full meaning in the linked constraint details. Other columns and whole75000HWP table width remain unchanged.',
   'choice_category':'implementation_choice_not_template_requirement','native_status':'pending_new_v4_bytes'},
  'limits':['The historical TD5 SaveAs changed the body header frame; this is not a universal source convention.','The new targets require actual SaveAs/reopen/PDF/all-page review. No current native pass or95% score assigned.']}
 # Freeze every existing v3 profile/evidence/index byte once. Existing history
 # must already be identical; never silently replace a prior frozen resource.
 archive=folder/'history/v3';archive.mkdir(parents=True,exist_ok=True)
 for path in folder.glob('*.json'):
  dest=archive/path.name
  if dest.exists() and dest.read_bytes()!=path.read_bytes():raise ValueError('Frozen v3 resource differs:'+str(dest))
  if not dest.exists():shutil.copyfile(path,dest)
 write(evidence_path,evidence)
 for entry,path,p in profiles:
  p['version']=4;p['profile_id']=f"reference-quality/{p['role']}/v4"
  p['targets']['sync_header_footer_frames']=True
  if p['role']=='SF-TD5':p['targets']['table_column_widths_hwp']['0']=[8500,17000,9000,14500,10000,2500,2500,5000,6000]
  p['allowed_changes'].append('declared_body_section_header_footer_frame_extents_only_text_ids_and_styles_preserved')
  p['selectors']['captions']='Renderer-registered caption owner paragraphs first, then limited textual caption hints; apply after enclosing cell styles. Picture/caption/detail keepWithNext changes preserve text and picture geometry.'
  p['native_layout_evidence']={'path':str(evidence_path),'sha256':h(evidence_path)}
  p['implementation_choices'].append({'category':'implementation_choice','choice':'Synchronize only body-section header/footer frame extents to declared page geometry; preserve cover-section frames and all text/IDs/character/paragraph definitions.','rationale':'Historical Hancom12.30.0build6544 TD5 SaveAs changed stale portrait header49324×4252 to landscape75684×2268. The generator must create coherent frames before strict native comparison.','native_status':'pending_new_v4_bytes'})
  if p['role']=='SF-TD5':p['implementation_choices'].append({'category':'implementation_choice','choice':'Table ID column17000HWP and remarks6000HWP within unchanged75000HWP whole table; preserve11pt HCR font and exact IDs.','rationale':'Measured HCR11pt advances15945.60/15899.40HWP plus566HWP cell padding exceed old16000column and fit17000. Remarks contain compact keys linked to full constraint detail.','native_status':'pending_new_v4_bytes'})
  p['iteration_refinement']={'previous_profile_version':3,'previous_bytes_preserved':'analysis/style-upgrade/profiles/history/v3','basis':'Historical strict native frame mismatch and measured TD5 glyph advances; exact evidence and implementation choices are linked in native_layout_evidence. Caption owner selection also uses explicit renderer roles to realize existing caption targets.','native_status':'pending_new_v4_bytes'}
  write(path,p);entry['sha256']=h(path)
 idx['recorded_at']=datetime.now(timezone.utc).isoformat();idx['scope']='19source-specific candidatev4 profiles: source-backed cover5roles, coherent body header/footer frames and measured TD5 ID width. No current native/editorial pass or actual95% score.'
 idx['native_status']='pending_new_v4_bytes';write(folder/'index.json',idx)
 print(json.dumps({'profiles':len(profiles),'version':4,'history_preserved':str(archive),'layout_evidence_sha256':h(evidence_path),'native_status':'pending_new_v4_bytes'},ensure_ascii=False,indent=2))

if '--refine-native-layout' in sys.argv:
 refine_native_layout();raise SystemExit
def own(x):
 # Only hp:t belongs to owner text; nested paragraph/cell/control text stays with its owner.
 def inline(t):
  special={'lineBreak':'\n','tab':'\t','nbSpace':'\u00a0','fwSpace':'\u3000'}
  tag=E.QName(t).localname
  return special.get(tag,t.text or '')+''.join(inline(c)+(c.tail or '') for c in t)
 if x.tag==f"{{{NS['hp']}}}p":return ''
 if x.tag==f"{{{NS['hp']}}}t":return inline(x)
 return ''.join(own(c) for c in x)
def raw(doc,kind):
 path=Path(doc['source_path']);actual=h(path)
 if actual!=doc['sha256']:raise ValueError('source SHA mismatch:'+str(path))
 with zipfile.ZipFile(path) as z:
  hd=E.fromstring(z.read('Contents/header.xml'));ht=hd.getroottree();opf=E.fromstring(z.read('Contents/content.hpf'))
  items={x.get('id'):x.get('href') for x in opf.xpath('//*[local-name()="manifest"]/*[local-name()="item"]')}
  section=[]
  for x in opf.xpath('//*[local-name()="spine"]/*[local-name()="itemref"]'):
   href=items[x.get('idref')];name=href if href in z.namelist() else 'Contents/'+href
   if name.endswith('.xml'):section.append(name)
  faces={f.get('lang'):{x.get('id'):x for x in f} for f in hd.findall('.//hh:fontface',NS)}
  chars={x.get('id'):x for x in hd.findall('.//hh:charPr',NS)};paras={x.get('id'):x for x in hd.findall('.//hh:paraPr',NS)}
  cc=Counter();pc=Counter();samples={};psamples={};secpr=[];tables=[]
  for name in section:
   root=E.fromstring(z.read(name));tree=root.getroottree()
   for p in root.findall('.//hp:p',NS):
    runs=[]
    for run in p.findall('hp:run',NS):
     text=own(run)
     if text.strip():
      cid=run.get('charPrIDRef');cc[cid]+=len(text);samples.setdefault(cid,{'xml':name,'xpath':tree.getpath(run),'paragraph_xpath':tree.getpath(p),'text':text[:160]});runs.append(text)
    if runs:
     pid=p.get('paraPrIDRef');pc[pid]+=sum(map(len,runs));psamples.setdefault(pid,{'xml':name,'xpath':tree.getpath(p),'text':''.join(runs)[:160]})
   for pg in root.findall('.//hp:secPr/hp:pagePr',NS):secpr.append({'xml':name,'xpath':tree.getpath(pg),'attributes':dict(pg.attrib),'margin':dict(pg.find('hp:margin',NS).attrib)})
   for tbl in root.findall('.//hp:tbl',NS):
    sz=tbl.find('hp:sz',NS);cells=tbl.findall('hp:tr/hp:tc',NS)
    tables.append({'xml':name,'xpath':tree.getpath(tbl),'attributes':dict(tbl.attrib),'size':dict(sz.attrib) if sz is not None else {},'first_row_cells':[{'address':dict(c.find('hp:cellAddr',NS).attrib),'span':dict(c.find('hp:cellSpan',NS).attrib),'size':dict(c.find('hp:cellSz',NS).attrib)} for c in cells if c.find('hp:cellAddr',NS).get('rowAddr')=='0']})
  used=[]
  for cid,count in cc.most_common():
   c=chars[cid];fr=c.find('hh:fontRef',NS);resolved={}
   for script,lang in [('hangul','HANGUL'),('latin','LATIN'),('hanja','HANJA'),('japanese','JAPANESE'),('other','OTHER'),('symbol','SYMBOL'),('user','USER')]:
    f=faces[lang][fr.get(script)];sub=f.find('hh:substFont',NS);resolved[script]={'face':f.get('face'),'font_definition_xpath':ht.getpath(f),'local_font_id':f.get('id'),'fallback':dict(sub.attrib) if sub is not None else None}
   used.append({'local_charPr_id':cid,'characters':count,'attributes':dict(c.attrib),'height_pt':int(c.get('height'))/100,'fonts':resolved,'bold':c.find('hh:bold',NS) is not None,'definition_xpath':ht.getpath(c),'run_evidence':samples[cid]})
  pp=[]
  for pid,count in pc.most_common():
   p=paras[pid];spacing=p.findall('.//hh:lineSpacing',NS);margin=p.findall('.//hh:margin',NS)
   pp.append({'local_paraPr_id':pid,'characters':count,'definition_xpath':ht.getpath(p),'line_spacing':[dict(x.attrib) for x in spacing],'margins':[E.tostring(x,encoding='unicode') for x in margin],'paragraph_evidence':psamples[pid]})
  # PDF text candidate pages localize samples, not a claim of fresh visual review.
  pdf=R/'verification/baselines'/('templates' if kind=='template' else 'references')/(doc['id']+'.pdf')
  if pdf.exists():
   pdftexts=[''.join(p.get_text().split()) for p in pymupdf.open(pdf)]
   for u in used[:8]:
    needle=''.join(u['run_evidence']['text'].split())[:60];u['run_evidence']['baseline_pdf_candidate_pages']=[i+1 for i,t in enumerate(pdftexts) if needle and needle in t]
  return {'path':str(path),'sha256':actual,'analysis_profile':str(R/f"analysis/stage{1 if kind=='template' else 2}/profiles/{doc['id']}.json"),'spine_sections':section,'used_character_formats':used,'used_paragraph_formats':pp,'section_page_properties':secpr,'tables':tables,'baseline_pdf':{'path':str(pdf),'sha256':h(pdf)} if pdf.exists() else None,'limits':['Actual used run/paragraph definitions resolved within this file; numeric IDs are evidence only and are never cross-file selectors.','Baseline PDF candidate pages use text search only; absence/ambiguity is not visual proof or a source-layout failure.']}
def toc_source_evidence(source):
 """Read every spine section, then resolve actual TOC owner runs locally."""
 from doc_automation.hwpx import own_text,inline_text
 path=Path(source['path'])
 if h(path)!=source['sha256']:raise ValueError('TOC source SHA mismatch:'+str(path))
 with zipfile.ZipFile(path) as z:
  package=E.fromstring(z.read('Contents/content.hpf'));items={x.get('id'):x.get('href') for x in package.xpath('//*[local-name()="manifest"]/*[local-name()="item"]')}
  names=[]
  for x in package.xpath('//*[local-name()="spine"]/*[local-name()="itemref"]'):
   href=items[x.get('idref')];name=href if href in z.namelist() else 'Contents/'+href
   if re.search(r'(^|/)section\d+\.xml$',name):names.append(name)
  roots=[(name,E.fromstring(z.read(name))) for name in names]
  header=E.fromstring(z.read('Contents/header.xml'));ht=header.getroottree()
  chars={x.get('id'):x for x in header.findall('.//hh:charPr',NS)}
  faces={f.get('lang').lower():{x.get('id'):x for x in f} for f in header.findall('.//hh:fontface',NS)}
  regions=[]
  for name,root in roots:
   children=list(root)
   for index,paragraph in enumerate(children):
    if own_text(paragraph).strip()!='목 차':continue
    region=[]
    for following in children[index+1:]:
     if following.get('pageBreak')=='1' or following.find('.//hp:tbl',NS) is not None:break
     region.append(following)
    entries=[p for p in region if own_text(p).strip()]
    if not entries:raise ValueError('TOC title has no source entries:'+str(path))
    regions.append((name,root,paragraph,region,entries))
  if not regions:return {'path':str(path),'sha256':source['sha256'],'spine_sections':names,'present':False}
  if len(regions)!=1:raise ValueError('TOC owner not unique:'+str(path))
  name,root,title,region,entries=regions[0];tree=root.getroottree()
  def paragraph_record(paragraph):
   used=[]
   for run in paragraph.findall('hp:run',NS):
    text=''.join(inline_text(t) for t in run.findall('hp:t',NS))
    if not text:continue
    char=chars[run.get('charPrIDRef')];refs=char.find('hh:fontRef',NS);resolved={}
    for script,identifier in refs.attrib.items():
     font=faces[script][identifier];fallback=font.find('hh:substFont',NS)
     resolved[script]={'face':font.get('face'),'local_font_id':identifier,'font_definition_xpath':ht.getpath(font),'fallback':dict(fallback.attrib) if fallback is not None else None}
    used.append({'run_xpath':tree.getpath(run),'text_verbatim':text,'local_charPr_id':run.get('charPrIDRef'),
     'definition_xpath':ht.getpath(char),'attributes':dict(char.attrib),'bold':char.find('hh:bold',NS) is not None,'fonts':resolved})
   return {'source_sha256':source['sha256'],'xml':name,'xpath':tree.getpath(paragraph),'text_verbatim':own_text(paragraph),
           'paragraph_attributes':dict(paragraph.attrib),'actual_used_character_definitions':used}
  controls=[{'xml':name,'xpath':tree.getpath(node),'kind':E.QName(node).localname,'attributes':dict(node.attrib)}
            for p in [title,*region] for node in p.iter() if E.QName(node).localname in {'secPr','colPr','header','footer','pageNum','newNum','pageHiding','fieldBegin','fieldEnd','pic','tbl','equation'}]
  return {'path':str(path),'sha256':source['sha256'],'spine_sections':names,'present':True,
          'roles':{'title':[paragraph_record(title)],'entries':[paragraph_record(p) for p in entries]},'protected_region_controls':controls}

def refine_toc_fonts():
 folder=O/'profiles';idx=load(folder/'index.json');profiles=[(entry,Path(entry['path']),load(entry['path'])) for entry in idx['profiles']]
 refresh=all(p['version']==5 for _,_,p in profiles)
 if not refresh and any(p['version']!=4 for _,_,p in profiles):raise ValueError('TOC refinement requires all19v4 profiles or all19currentv5 profiles')
 prepared=[];expected={'SF-AD1','SF-AD2',*[f'SF-TD{i}' for i in range(1,6)],'SF-CD1',*[f'SF-TI{i}' for i in range(1,5)],'SF-OS1','SF-OS2'}
 for entry,path,p in profiles:
  template=toc_source_evidence(p['source_template']);reference=toc_source_evidence(p['reference_sources'][0])
  if template['present']!=reference['present'] or template['present']!=(p['role'] in expected):raise ValueError('TOC scope differs from14role evidence:'+p['role'])
  if template['present']:
   for paragraphs in reference['roles'].values():
    for paragraph in paragraphs:
     for char in paragraph['actual_used_character_definitions']:
      if set(char['fonts'])!={'hangul','latin','hanja','japanese','other','symbol','user'} or any(v['face']!='함초롬바탕' for v in char['fonts'].values()):raise ValueError('Reference TOC seven-script font evidence differs:'+p['role'])
  prepared.append((entry,path,p,template,reference))
 archive=folder/'history/v4';archive.mkdir(parents=True,exist_ok=True)
 if not refresh:
  for path in folder.glob('*.json'):
   dest=archive/path.name
   if dest.exists() and dest.read_bytes()!=path.read_bytes():raise ValueError('Frozen v4 resource differs:'+str(dest))
   if not dest.exists():shutil.copyfile(path,dest)
 for entry,path,p,template,reference in prepared:
  p['version']=5;p['profile_id']=f"reference-quality/{p['role']}/v5"
  p['selectors']['captions']='Only renderer-registered actual caption owner paragraphs; source captions require a separately verified exact owner declaration. Text prefixes such as 그림/표/화면/출처 never imply caption role. Unselected body instructions and source notes keep body typography.'
  caption_choice='Apply caption typography only to renderer-registered actual captions; body instructions and source notes retain body typography.'
  if not any(choice.get('choice')==caption_choice for choice in p['implementation_choices']):p['implementation_choices'].append({'category':'implementation_choice','choice':caption_choice,'rationale':'A generic 화면/그림/표 prefix can describe business content or an image-location instruction. Caption identity must come from the actual attachment owner registry; a source-specific caption would need separate exact source evidence.','native_status':'pending_new_v5_bytes'})
  p['toc_scope']={'present_in_selected_template_and_reference':template['present'],'relationship':p['reference_relationship'],'reference_is_adjacent':p['role']=='SF-OS1'}
  if template['present']:
   ep=folder/(p['role']+'.toc-evidence.json')
   evidence={'schema_version':'toc-owner-source-evidence-1','role':p['role'],'category':'observed_expert_font_convention_and_declared_font_only_choice',
    'template_source':template,'reference_source':reference,'reference_relationship':p['reference_relationship'],
    'choice':{'adopted':'함초롬바탕 for all seven scripts of the two renderer-registered TOC owner paragraphs only',
      'preserved':'Source owner character height/bold/other direct formatting, paragraph style/geometry, all controls and text. Reference11/12/13pt entry sizes and mixed bold are observations, not uniform targets.',
      'scope':'The renderer merges entries into the first source entry owner; other original TOC region paragraphs are not typography selectors.',
      'unresolved':'Current Hancom SaveAs/PDF/all-page review and TOC finalization remain required. No native pass or95% score.'},'actual_score_percent':None}
   write(ep,evidence);p['toc_observed_evidence']={'path':str(ep),'sha256':h(ep)}
   p['targets']['toc_roles']={role:{'font_face':'함초롬바탕'} for role in ('title','entries')}
   p['toc_selectors']={role:{'template':{'source_sha256':template['sha256'],'xml':template['roles'][role][0]['xml'],'xpath':template['roles'][role][0]['xpath'],'text_before_generation_verbatim':template['roles'][role][0]['text_verbatim']}} for role in ('title','entries')}
   if not refresh:p['allowed_changes'].append('derived_font_face_only_on_two_exact_source_guarded_toc_owner_paragraphs_other_character_and_paragraph_properties_preserved')
   p['selectors']['toc']='Only renderer-registered title and merged-entry owner paragraphs, guarded by immutable source SHA/XML/exact XPath/own text; typography changes only font face in each own run.'
   if not refresh:p['implementation_choices'].append({'category':'implementation_choice','choice':'Adopt observed seven-script HCR font face for source-guarded TOC title/entries; preserve original owner sizes/bold and all paragraph geometry/controls.','rationale':'Selected reference TOC uses HCR in14roles; entry sizes/bold vary by role and hierarchy. Font-only choice does not copy reference business text or establish mandatory typography. OS1 remains an explicit adjacent OS2 design basis.','native_status':'pending_new_v5_bytes'})
  p['iteration_refinement']={'previous_profile_version':4,'previous_bytes_preserved':'analysis/style-upgrade/profiles/history/v4','basis':'14source-exact TOC font-only targets backed by every actual source/reference TOC owner run and seven-script font resolution; five roles have no source TOC and no target. Actual caption selection uses registered owners only. Header-frame and TD5-width refinements are retained.','native_status':'pending_new_v5_bytes'}
  write(path,p);entry['sha256']=h(path);entry['toc_target_owner_count']=2 if template['present'] else 0
 idx['recorded_at']=datetime.now(timezone.utc).isoformat();idx['scope']='19source-specific candidatev5 profiles;14roles declare source-backed font-only TOC owner targets. Earlier cover/frame/TD5width targets retained. No current native/editorial pass or actual95% score.'
 idx['native_status']='pending_new_v5_bytes';write(folder/'index.json',idx)
 print(json.dumps({'profiles':len(profiles),'version':5,'toc_roles':len(expected),'toc_owner_targets':len(expected)*2,'history_preserved':str(archive),'native_status':'pending_new_v5_bytes'},ensure_ascii=False,indent=2))

if '--refine-toc-fonts' in sys.argv:
 refine_toc_fonts();raise SystemExit

def refine_pm4_boundary():
 from doc_automation.compose import TemplateDocument,HP
 from doc_automation.hwpx import own_text,nearest,local
 folder=O/'profiles';idx=load(folder/'index.json');profiles=[(entry,Path(entry['path']),load(entry['path'])) for entry in idx['profiles']]
 if all(p['version']==6 for _,_,p in profiles):
  print(json.dumps({'profiles':19,'version':6,'changed':False,'native_status':'pending_new_v6_bytes'}));return
 if any(p['version']!=5 for _,_,p in profiles):raise ValueError('PM4 boundary refinement requires all19v5 profiles')
 observations={};selectors={}
 for _,_,p in profiles:
  d=TemplateDocument(p['source_template']['path'],expected_sha256=p['source_template']['sha256']);role=p['role'];selected=[]
  item={'source':p['source_template'],'spine_sections':d.sections,'source_section_count':len(d.sections),'category':'source_structure_observation_not_universal_template_requirement'}
  if len(d.sections)==1:
   root=d.root();table=d.tables()[1];first=nearest(table,HP+'p')
   while nearest(first,HP+'p') is not None:first=nearest(first,HP+'p')
   boundary=root.index(first)
   for number in range(max(1,boundary-8),boundary):
    text=own_text(root[number]).strip()
    if re.match(r'^1[.)]\s',text) and '\t' not in text:first=root[number];boundary=number;break
   for paragraph in reversed(list(root)[:boundary]):
    if own_text(paragraph)!='' or any(local(node) not in {'p','run','t','linesegarray','lineseg'} for node in paragraph.iter()):break
    try:d._check_boundary_spacers(root[boundary],[paragraph,*reversed(selected)])
    except ValueError:break
    selected.append(paragraph)
   selected.reverse()
   item.update(body_member=d.sections[0],body_source_xpath=root.getroottree().getpath(first),body_source_own_text=own_text(first),
     pure_empty_suffix=[{'source_sha256':d.source_sha256,'xml':d.sections[0],'xpath':root.getroottree().getpath(paragraph),'text_before_generation_verbatim':'','paragraph_attributes':dict(paragraph.attrib)} for paragraph in selected])
  else:item['pure_empty_suffix']=[]
  observations[role]=item
  selectors[role]=[{key:spacer[key] for key in ('source_sha256','xml','xpath','text_before_generation_verbatim')} for spacer in item['pure_empty_suffix']]
 font_path=Path('/Applications/Hancom Office HWP.app/Contents/Resources/Hnc/Shared/TTF/Install/HANBatang.ttf');font=pymupdf.Font(fontfile=str(font_path))
 metrics=[{'text_verbatim':text,'advance_hwp_at_10pt':font.text_length(text,fontsize=10)*100,'required_width_hwp_ceiling':math.ceil(font.text_length(text,fontsize=10)*100+566)} for text in ('DEMO-TEST-001','DEMO-TD3-001','DEMO-TD4-001','DEMO-AD2-001','DEMO-TRACE-001','T1')]
 native_pdf=R/'verification/style-upgrade/iteration-03/native/SF-PM4.pdf';candidate=R/'verification/semantic-v5/generated/SF-PM4_요구사항추적표_검증용.hwpx'
 pdf=pymupdf.open(native_pdf)
 evidence={'schema_version':'pm4-boundary-and-width-refinement-evidence-1','source_observations':observations,
  'native_observation':{'pdf':{'path':str(native_pdf),'sha256':h(native_pdf)},'candidate':{'path':str(candidate),'sha256':h(candidate)},'page_count':len(pdf),'page2_paper_pt':list(pdf[1].rect),'page2_text_verbatim':pdf[1].get_text(),
    'observed':'Portrait page2 contains the running header only; landscape body begins onpage3. Candidate cover suffix has three pure empty text paragraphs; no page/column break, object or control is present in those owners.',
    'inference':'Trailing empty flow after the cover can spill to a blank portrait page before a new section starts. Remove only exact declared pure-empty suffix owners; actual new native output must verify the diagnosis.'},
  'width_choice':{'font_path':str(font_path),'font_sha256':h(font_path),'resolved_font_name':font.name,'declared_font_size_pt':10,'horizontal_padding_hwp':566,'measurement_engine':'PyMuPDF Font.text_length; support for width selection, not native pagination proof','metrics':metrics,
    'functional_grid_columns_hwp':[2500,9000,9000,8500,8500,8500,9000,9000,9000,2000],
    'trace_grid_columns_hwp':[10000,16000,16000,7000,9000,8000,9000],
    'tradeoff':'Functional description/name columns become narrower to preserve complete screen/program/test IDs at10pt within75000HWP. Long body text and status values may continue across lines/pages; no character shrinking, truncation or ID mutation.'},
  'actual_quality_score_percent':None,'native_status':'pending_new_v6_bytes'}
 archive=folder/'history/v5';archive.mkdir(parents=True,exist_ok=True)
 for path in folder.glob('*.json'):
  dest=archive/path.name
  if dest.exists() and dest.read_bytes()!=path.read_bytes():raise ValueError('Frozen v5 resource differs:'+str(dest))
  if not dest.exists():shutil.copyfile(path,dest)
 ep=folder/'pm4-boundary-refinement-evidence.json';write(ep,evidence)
 for entry,path,p in profiles:
  role=p['role'];p['version']=6;p['profile_id']=f'reference-quality/{role}/v6';p['section_boundary_spacer_selectors']=selectors[role]
  p['section_boundary_evidence']={'path':str(ep),'sha256':h(ep)}
  if selectors[role]:
   p['allowed_changes'].append('discard_only_exact_declared_pure_empty_paragraph_suffix_at_new_body_section_boundary_no_objects_controls_or_numbering')
   p['implementation_choices'].append({'category':'implementation_choice','choice':'Discard only declared originally empty suffix paragraphs immediately before a new body section; preserve all preceding visible text geometry and every semantic control.','rationale':'A new section already supplies the page transition. Empty trailing flow can create a portrait header-only page. Source-exact guards and pure-empty/control-free validation prevent deleting a meaningful spacer owner.','native_status':'pending_new_v6_bytes'})
  if role=='SF-PM4':
   p['targets']['table_column_widths_hwp']['0']=evidence['width_choice']['functional_grid_columns_hwp'];p['targets']['trace_table_column_widths_hwp']=evidence['width_choice']['trace_grid_columns_hwp']
   p['allowed_changes'].append('renderer_registered_trace_comparison_table_role_specific_grid_widths_within75000HWP')
   p['selectors']['trace_table']='Only element identities in renderer _editorial_trace_tables; seven explicit columns, separate from normal table ordinals and repeated prototype widths.'
   p['implementation_choices'].append({'category':'implementation_choice','choice':'Use measured screen/program/test-ID widths in the functional grid and independent renderer-registered trace comparison widths, both75000HWP total at unchanged10pt.','rationale':'DEMO-TEST-001 requires8815HWP including padding and DEMO-TRACE-0019575HWP. Complete IDs take priority over wider narrative columns; field values remain full and native row continuation/readability still need verification.','native_status':'pending_new_v6_bytes'})
  p['iteration_refinement']={'previous_profile_version':5,'previous_bytes_preserved':'analysis/style-upgrade/profiles/history/v5','basis':'Exact original pure-empty section-boundary suffix targets and PM4 glyph-advance-based functional/trace grids; earlier source-backed cover/TOC and header/TD5 refinements retained.','native_status':'pending_new_v6_bytes'}
  write(path,p);entry['sha256']=h(path)
 idx['recorded_at']=datetime.now(timezone.utc).isoformat();idx['scope']='19candidatev6 profiles retain source-backed cover/TOC, header-frame and TD5 rules; add declared empty boundary suffix handling and measured PM4 normal/trace grids. No current native/editorial pass or95% score.';idx['native_status']='pending_new_v6_bytes';write(folder/'index.json',idx)
 print(json.dumps({'profiles':19,'version':6,'empty_boundary_roles':{role:len(value) for role,value in selectors.items() if value},'native_status':'pending_new_v6_bytes'},ensure_ascii=False,indent=2))

if '--refine-pm4-boundary' in sys.argv:
 refine_pm4_boundary();raise SystemExit

def refine_td3_section():
 from doc_automation.compose import TemplateDocument
 from doc_automation.hwpx import own_text
 folder=O/'profiles';idx=load(folder/'index.json');profiles=[(entry,Path(entry['path']),load(entry['path'])) for entry in idx['profiles']]
 if all(p['version']==7 for _,_,p in profiles):
  print(json.dumps({'profiles':19,'version':7,'changed':False,'native_status':'pending_new_v7_bytes'}));return
 if any(p['version']!=6 for _,_,p in profiles):raise ValueError('TD3 section refinement requires all19v6 profiles')
 td3=next(p for _,_,p in profiles if p['role']=='SF-TD3');doc=TemplateDocument(td3['source_template']['path'],expected_sha256=td3['source_template']['sha256'])
 selector={}
 for role,xpath,expected in [('source_heading','/hs:sec/hp:p[54]','3. 화면(보고서) 설계'),('first_table_carrier','/hs:sec/hp:p[55]','')]:
  nodes=doc.root().xpath(xpath,namespaces=NS)
  if len(nodes)!=1 or own_text(nodes[0])!=expected:raise ValueError('TD3 original section owner differs:'+role)
  selector[role]={'source_sha256':doc.source_sha256,'xml':doc.sections[0],'xpath':xpath,'text_before_generation_verbatim':expected}
 if len(doc.root().xpath('/hs:sec/hp:p[55]//hp:tbl[@colCnt="4"]',namespaces=NS))!=1:raise ValueError('TD3 original first card differs')
 selector['generated_intro']={'allowed_prefix':'과제: ','maximum_paragraphs':1,'require_renderer_body_role':True,'plain_text_only':True}
 native_pdf=R/'verification/style-upgrade/iteration-05/native/SF-TD3.pdf';candidate=R/'verification/semantic-v7/generated/SF-TD3_화면설계서_검증용.hwpx';audit=R/'verification/style-upgrade/iteration-05/TD3-roundtrip.json';pdf=pymupdf.open(native_pdf)
 font_path=Path('/Applications/Hancom Office HWP.app/Contents/Resources/Hnc/Shared/TTF/Install/HANBatang.ttf');font=pymupdf.Font(fontfile=str(font_path))
 nonfunctional=[2500,9000,14000,20000,17000,9000,3500]
 evidence={'schema_version':'td3-section-and-heading-owner-refinement-evidence-1','td3_source':td3['source_template'],'source_spine_sections':doc.sections,'declared_body_section_selector':selector,
  'previous_output':{'candidate':{'path':str(candidate),'sha256':h(candidate)},'strict_roundtrip':{'path':str(audit),'sha256':h(audit),'passed':load(audit)['passed']},'pdf':{'path':str(native_pdf),'sha256':h(native_pdf)},'page_count':len(pdf),
    'physical_page4':{'rect_pt':list(pdf[3].rect),'text_verbatim':pdf[3].get_text()},'physical_page5':{'rect_pt':list(pdf[4].rect)},
    'observation':'Previous generated section0 retains the3rd chapter title and one project intro; section1 starts at the first card. Native page4 is portrait with chapter title/intro while the first landscape card begins onpage5. Strict preservation passes but does not establish appropriate section placement.'},
  'implementation_choices':[{'category':'implementation_choice','choice':'Start TD3 landscape section at the exact original3rd-chapter owner, carry only up to one new renderer-registered plain project intro before the exact first card owner, and keep source1st/2nd chapters in portrait.','limits':'No broad text search, scope-control removal, card-wide keep or font shrinking. Current new native output remains required.'},
    {'category':'implementation_choice','choice':'Use explicit renderer heading identities and genuine numbered section headings; context keys [Tn]/[Cn]/[Fn] alone never imply a title or keepWithNext chain.','limits':'True T/C/F titles must be renderer-registered; body value bold/keep flags remain as authored.'}],
  'pm4_nonfunctional_width_choice':{'font_path':str(font_path),'font_sha256':h(font_path),'font_name':font.name,'size_pt':10,'horizontal_padding_hwp':566,'exact_text':'연결 시험: DEMO-TEST-004','advance_hwp':font.text_length('연결 시험: DEMO-TEST-004',fontsize=10)*100,'required_width_hwp_ceiling':math.ceil(font.text_length('연결 시험: DEMO-TEST-004',fontsize=10)*100+566),'column_widths_hwp':nonfunctional,'whole_width_hwp':sum(nonfunctional),'rationale':'17000HWP deliverable/test-link column fits the complete prefix and supplied ID at unchanged10pt. Normal functional and registry-selected trace widths are retained independently.'},
  'actual_quality_score_percent':None,'native_status':'pending_new_v7_bytes'}
 archive=folder/'history/v6';archive.mkdir(parents=True,exist_ok=True)
 for path in folder.glob('*.json'):
  dest=archive/path.name
  if dest.exists() and dest.read_bytes()!=path.read_bytes():raise ValueError('Frozen v6 resource differs:'+str(dest))
  if not dest.exists():shutil.copyfile(path,dest)
 ep=folder/'td3-section-and-heading-refinement-evidence.json';write(ep,evidence)
 for entry,path,p in profiles:
  role=p['role'];p['version']=7;p['profile_id']=f'reference-quality/{role}/v7';p['section_heading_owner_evidence']={'path':str(ep),'sha256':h(ep)}
  p['selectors']['headings']='Explicit renderer semantic heading identities or genuine numbered top-level section titles only; context keys [Tn]/[Cn]/[Fn] do not establish heading status.'
  p['implementation_choices'].append({'category':'implementation_choice','choice':'Preserve body value typography/keeps when a paragraph merely carries a T/C/F context key; genuine key headings require explicit renderer registration.','rationale':'Previous prefix inference made PM4 context values bold and keepWithNext despite the renderer declaring them body text. Removing that inference preserves the intended role.','native_status':'pending_new_v7_bytes'})
  if role=='SF-TD3':
   p['body_section_selector']=selector;p['allowed_changes'].append('exact_source_third_chapter_and_finite_registered_intro_move_with_first_card_to_body_section')
   p['implementation_choices'].append({'category':'implementation_choice','choice':'Start the TD3 landscape section at exact original chapter3 owner; include only the registered one-paragraph project intro before its source-exact first card.','rationale':'The previous table-only split stranded chapter3/intro on a nearly empty portrait page. Original chapter1/2 remain portrait and the new section supplies the sole transition.','native_status':'pending_new_v7_bytes'})
  if role=='SF-PM4':
   p['targets']['table_column_widths_hwp']['1']=nonfunctional
   p['implementation_choices'].append({'category':'implementation_choice','choice':'Rebalance nonfunctional7column grid to2500/9000/14000/20000/17000/9000/3500HWP; retain independent functional and trace grids.','rationale':'Full 연결 시험: DEMO-TEST-004 needs13616HWP including padding at10pt;17000HWP preserves the prefix/ID without font reduction and keeps total75000HWP.','native_status':'pending_new_v7_bytes'})
  p['iteration_refinement']={'previous_profile_version':6,'previous_bytes_preserved':'analysis/style-upgrade/profiles/history/v6','basis':'Exact TD3 chapter/first-card section boundary, registered finite intro and heading-owner selection; measured PM4 nonfunctional prefix+ID width. Earlier refinements retained.','native_status':'pending_new_v7_bytes'}
  write(path,p);entry['sha256']=h(path)
 idx['recorded_at']=datetime.now(timezone.utc).isoformat();idx['scope']='19candidatev7 profiles retain prior rules; exact TD3 chapter+intro section boundary, explicit heading roles and measured PM4 nonfunctional grid. No current native/editorial pass or95% score.';idx['native_status']='pending_new_v7_bytes';write(folder/'index.json',idx)
 print(json.dumps({'profiles':19,'version':7,'TD3_source_heading_xpath':selector['source_heading']['xpath'],'PM4_nonfunctional_total_hwp':sum(nonfunctional),'native_status':'pending_new_v7_bytes'},ensure_ascii=False,indent=2))

if '--refine-td3-section' in sys.argv:
 refine_td3_section();raise SystemExit

T={x['id']:x for x in load('analysis/stage1/inventory.json')['documents']};F={x['id']:x for x in load('analysis/stage2/inventory.json')['documents']};M=load('analysis/stage2/mapping.json')['mappings'];catalog=load('analysis/stage1/deliverables-catalog.json')['documents'];rules=load('analysis/stage1/analysis-design-rules.json')['rules'];reqs={x['code']:x for x in load('analysis/stage1/test-management-requirements.json')};baseline=load('generated/reviewed-suite/manifest.json')
references={x['template_id']:x for x in M if x.get('template_id')}
evidence={};index=[]
narrative={'SF-AD1','SF-TD1','SF-TD2','SF-TI2','SF-TI3','SF-OS1','SF-OS2'}
landscape={'SF-TD3','SF-TD5','SF-PM4'}
widths={'SF-TD5':{'0':[8500,16000,9000,14500,10000,2500,2500,5000,7000]},'SF-PM4':{'0':[3000,10000,12000,15000,6500,6500,6500,6500,6500,2500],'1':[4000,11500,15000,18000,8500,10000,8000]},'SF-TD3':{'0':[13000,24500,13000,24500]}}
for item in catalog:
 role=item['form_code'];tid='template-'+role.lower();template=raw(T[tid],'template');mapping=references.get(tid);refdoc=F.get(mapping['reference_id']) if mapping else None;reference=raw(refdoc,'reference') if refdoc else None
 relation=mapping['relationship'] if mapping else 'no_direct_reference';rawrefs=[reference] if reference else []
 if role=='SF-OS1':rawrefs=[raw(F['reference-sf-os2'],'reference')]
 e={'schema_version':'source-style-evidence-1','role':role,'template':template,'reference':reference,'adjacent_references':rawrefs if reference is None else [],'relationship':relation,'evidence_kind':'observed_expert_convention_not_universal_requirement','native_editorial_judgment':'not_performed_for_new_profile'}
 evidence[role]=e;ep=O/'profiles'/f'{role}.evidence.json';write(ep,e)
 mandatory=[];field_observations=[]
 for r in rules:
  if r['document_code_from_filename']==role:mandatory.append({'category':'template_instruction','source_sha256':r['source_file_sha256'],'xml':r['source_xml'],'xpath':'/'.join(('hp:'+v if v and ':' not in v else v) for v in r['source_xpath'].split('/')),'legacy_source_xpath':r['source_xpath'],'text_verbatim':r['source_text_verbatim'],'current_regulatory_requirement_verified':False})
 if role in reqs:
  profile=load(f'analysis/stage1/profiles/{tid}.json');paragraphs={p['evidence']:p for sec in profile['sections'] for p in sec['paragraphs']}
  for loc in reqs[role]['rules']:
   p=paragraphs.get(loc)
   if p is None:
    for sec in profile['sections']:
     for table in sec['tables']:
      if table['evidence']==loc:p={'text':'\n'.join(c['text'] for c in table['cells']),'xpath':table['xpath']}
      for cell in table['cells']:
       if cell['evidence']==loc:
        a=cell['address'];p={'text':cell['text'],'xpath':table['xpath']+"/hp:tr/hp:tc[hp:cellAddr/@rowAddr='"+a['rowAddr']+"' and hp:cellAddr/@colAddr='"+a['colAddr']+"']"}
   if p is None:raise ValueError('Unresolved template instruction:'+loc)
   entry={'category':'template_instruction' if '#P' in loc and re.search('작성|기재|기술|기입|명시|제출|확인|포함|반영|정의',p['text']) else 'template_structure_or_field_observation','source_sha256':template['sha256'],'xml':loc.split('#')[0],'xpath':p['xpath'],'text_verbatim':p['text'],'current_regulatory_requirement_verified':False,'field_label_does_not_establish_individual_mandatory_status':True}
   (mandatory if entry['category']=='template_instruction' else field_observations).append(entry)
 # Intentional targets are chosen candidates informed by role-specific observations, not claimed native-verified styles.
 bodypt=11 if role in narrative or role in {'SF-TD3','SF-TD4','SF-TD5','SF-PM2','SF-PM3'} else 10;line=160 if role in {'SF-AD1','SF-OS2'} else 140 if role in {'SF-PM2','SF-PM3'} else 150 if role in narrative else 130;portrait_width=48500;w=75000 if role in landscape else portrait_width
 target={'body_font_face':'함초롬바탕','body_height_hwp':bodypt*100,'body_line_spacing_percent':line,'heading_font_face':'함초롬바탕','heading_height_hwp':1200,'heading_line_spacing_percent':150,'heading_bold':True,'table_header_font_face':'함초롬바탕','table_header_height_hwp':1000,'table_header_line_spacing_percent':130,'table_header_bold':True,'caption_font_face':'함초롬바탕','caption_height_hwp':950,'caption_line_spacing_percent':130,'landscape_body':role in landscape,'paper_margin_hwp':{'left':4252 if role in landscape else 5102,'right':4252 if role in landscape else 5102,'top':4252,'bottom':4252,'header':2268,'footer':2268,'gutter':0},'table_width_hwp':w,'cell_margin_hwp':{'left':283,'right':283,'top':141,'bottom':141},'identifier_wrap':'natural_no_mutation','character_spacing_percent':0,'character_ratio_percent':100}
 if role in widths:target['table_column_widths_hwp']=widths[role]
 exclusions=['Do not copy extreme source right margins, crowded line spacing, missing continuation headers, incomplete sentences or reference facts/signatures.','Do not use source paragraph/character numeric IDs as runtime style selectors.','Do not turn null/unknown into performed/not_applicable/optional/nonfunctional or create absent captures/approvals.']
 if role=='SF-AD1':exclusions+=['Exclude unexplained large yellow X overlays over diagrams; preserve as unresolved source observation.']
 if role=='SF-TD5':exclusions+=['Exclude physical/logical-column transposition and duplicate IDs observed in reference; keep supplied field identity/type and composite constraints.']
 if role in {'SF-CD1','SF-TI1','SF-TI4','SF-PM4'}:exclusions+=['Source continuation header absence is a defect; new output must retain field/ID context across pages.']
 if role=='SF-PM1':exclusions+=['Weekly reference is a partial cadence match only; never relabel provided weekly actuals as monthly.']
 if role=='SF-OS1':exclusions+=['No direct expert reference exists; these targets are adjacent-reference-informed design choices, not a demonstrated same-role reproduction.']
 if role=='SF-PM3':exclusions+=['Native SaveAs fallback loss is a compatibility defect, not an accepted formatting delta; restore only exact declarations and review final bytes.']
 notices={x['role']:x for x in baseline['documents']}
 p={'schema_version':'reference-editorial-profile-1','profile_id':f'reference-quality/{role}/v2','version':2,'role':role,'status':'candidate_unvalidated','source_template':{'path':template['path'],'sha256':template['sha256']},'reference_relationship':relation,'reference_sources':[{'path':x['path'],'sha256':x['sha256'],'relationship':relation if reference else 'adjacent_role_design_basis'} for x in rawrefs],'targets':target,'target_units':{'*_height_hwp':'charPr height: point size multiplied by100, not page HWPUNIT','paper_margin_hwp/table_width_hwp/table_column_widths_hwp/cell_margin_hwp':'HWPUNIT:1inch=7200;1mm=7200/25.4','*_line_spacing_percent':'percent; must remain PERCENT type'},'selectors':{'cover':'preserve existing cover/control-owned paragraphs and cover table','body':'role-aware first actual body table/card or body section after cover/TOC; never arbitrary first nonempty paragraph','headings':'semantic chapter/section/card titles, not regex alone or font ID','table_header':'header cells in selected body tables; continue page field/ID context','captions':'explicit figure/table caption paragraphs only','notes':'source/uncertainty appendices; no shrink of required data to make page fit'},'allowed_changes':['derived_character_font_face_and_size_on_declared_body_targets','derived_character_spacing_ratio_on_declared_body_targets','derived_paragraph_line_spacing_on_declared_targets','body_section_orientation_and_margins_only_where_profile_declares','body_table_whole_width_cell_width_margin_coherent_change','semantic_caption_style_and_keep_with_figure','declared_body_header_bold_and_spacing'],'preservation_contract':{'content_boundary':'input_field/type/ID/relation/status/source_refs to rendered meaning/position mapping; intentional prose and table transformations logged','editorial_boundary':'exact text, field meaning and object references retained outside explicit semantic relocations; definitions derived, cover and controls protected','native_boundary':'strict current styled-byte before/after preservation; fallback loss remains failure until exact repair and new actual final-byte QA'},'mandatory_template_instructions':mandatory,'template_field_observations':field_observations,'local_catalog_document_requirement':{'required':item['required'],'evidence':item['evidence'],'scope':'Only the selected localv2catalog document-presence rule; not every field mandatory or current universal submission law'},'observed_convention_evidence':{'path':str(ep),'sha256':h(ep),'used_format_scope':'all actual nonempty owner run usage, resolved fonts and paragraph definitions; source values retained separately from targets'},'implementation_choices':[{'category':'implementation_choice','choice':'role-specific10/11pt body and130/140/150/160% line spacing with12pt headings','rationale':'table roles need compact stable field comparison; narrative roles need paragraph rhythm. Candidate values are within observed families but not copied as universal rules.','native_status':'pending'},{'category':'implementation_choice','choice':'TD3/TD5/PM4 landscape body; cover remains portrait','rationale':'support long IDs and wide multi-column specifications while retaining original fields and declared layout transition; declared75000HWP wide table allows outer margin/offset within75684HWP body' ,'applies':role in landscape,'native_status':'pending'},{'category':'implementation_choice','choice':'safe15/18mm side margins,1mm horizontal cell padding and0.5mm vertical padding','rationale':'exclude extreme exemplar margins and preserve legibility; final native wrapping decides suitability','native_status':'pending'}],'excluded_or_unresolved':exclusions,'iteration_refinement':{'previous_profile_version':1,'previous_bytes_preserved':'analysis/style-upgrade/profiles/history/v1','basis':'Compose agent measured actualTD5 native available75684HWP, outer566+offset66;75000content+632=75632 fits. Wide75000/portrait48500 are explicit candidate width choices, not silent clamping. TD5 nullable column5000HWP follows actualNOT NULL wrap failure; current native re-export/review is still required.','native_status':'pending_new_v2_bytes'},'project_fact_policy':'This profile contains no project execution/approval/signature/measurement facts. Supplied fact values/status/source_refs remain separate.','baseline_output':notices[role],'assessment':{'rubric_id':'reference-quality-observed-rubric/v1','score_percent':None,'status':'not_assessed','evidence_required':['current_native_hwpx_pdf_png_hashes','actual_native_actions_and_app_version','font_and_spacing_observations','all_original_page_editorial_observations','same_content_reproduction','heldout_input_evaluation']}}
 write(O/'profiles'/f'{role}.json',p);index.append({'role':role,'path':str(O/'profiles'/f'{role}.json'),'sha256':h(O/'profiles'/f'{role}.json'),'source_template_sha256':template['sha256'],'reference_relationship':relation,'mandatory_instruction_count':len(mandatory),'evidence_path':str(ep),'evidence_sha256':h(ep),'status':p['status']})
write(O/'profiles/index.json',{'schema_version':'reference-editorial-profile-index-1','recorded_at':datetime.now(timezone.utc).isoformat(),'scope':'19source-specific candidate profiles; observed source formatting and chosen targets are distinct. No actual95% score/native pass asserted.','profiles':index,'generation_scope':'v2.0 development deliverables19; independent34forms remain analysis/typed-facts scope','actual_score_percent':None,'native_status':'pending'})
print(json.dumps({'profiles':len(index),'sources_read_only':True,'actual_scores_assigned':0,'mandatory_instructions':sum(x['mandatory_instruction_count'] for x in index),'landscape_roles':sorted(landscape)},ensure_ascii=False,indent=2))
