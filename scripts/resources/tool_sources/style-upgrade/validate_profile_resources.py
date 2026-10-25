"""Task-local source/profile/inventory contract checks; no native or editorial pass."""
import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json,zipfile
from lxml import etree as E
from doc_automation.hwpx import own_text,inline_text,section_order
B=Path(__file__).resolve().parent;R=B.parents[1]
NS={'hs':'http://www.hancom.co.kr/hwpml/2011/section','hp':'http://www.hancom.co.kr/hwpml/2011/paragraph','hh':'http://www.hancom.co.kr/hwpml/2011/head'}
def load(p):return json.loads(Path(p).read_text())
def h(p):return sha256(Path(p).read_bytes()).hexdigest()
checks=[]
def ck(n,b,d=None):checks.append({'check':n,'passed':bool(b),'detail':d})
idx=load(B/'profiles/index.json');ck('19current source-specific profiles',len(idx['profiles'])==19)
source_seen={};mcount=0;fcount=0
for i in idx['profiles']:
 p=load(i['path']);ck('current profile SHA matches index',h(i['path'])==i['sha256'],p['role']);ck('candidatev7 actual score not assigned',p['version']==7 and p['status']=='candidate_unvalidated' and p['assessment']['score_percent'] is None,p['role'])
 e=load(i['evidence_path']);ck('current raw format evidence SHA matches',h(i['evidence_path'])==i['evidence_sha256'],p['role'])
 for source in [e['template']]+([e['reference']] if e['reference'] else e['adjacent_references']):
  if source['path'] not in source_seen:source_seen[source['path']]=h(source['path']);ck('source original current SHA',source_seen[source['path']]==source['sha256'],source['path'])
  with zipfile.ZipFile(source['path']) as z:
   header=E.fromstring(z.read('Contents/header.xml'))
   for u in source['used_character_formats']:
    definition=header.xpath(u['definition_xpath'],namespaces=NS);ck('used char definition locator resolves',len(definition)==1,{'role':p['role'],'path':u['definition_xpath']})
    s=u['run_evidence'];sec=E.fromstring(z.read(s['xml']));run=sec.xpath(s['xpath'],namespaces=NS);ck('actual used run char definition matches',len(run)==1 and run[0].get('charPrIDRef')==u['local_charPr_id'],p['role'])
    for font in u['fonts'].values():ck('resolved font definition exists with actual face',len(header.xpath(font['font_definition_xpath'],namespaces=NS))==1 and header.xpath(font['font_definition_xpath'],namespaces=NS)[0].get('face')==font['face'],p['role'])
 for entry in p['mandatory_template_instructions']+p['template_field_observations']:
  with zipfile.ZipFile(p['source_template']['path']) as z:sec=E.fromstring(z.read(entry['xml']));loc=sec.xpath(entry['xpath'],namespaces=NS);ck('template instruction/field canonical XML locator resolves',len(loc)==1,{'role':p['role'],'xpath':entry['xpath']})
 mcount+=len(p['mandatory_template_instructions']);fcount+=len(p['template_field_observations'])
 t=p['targets'];ck('page/table units and stable width are explicit',t['table_width_hwp']==(75000 if t['landscape_body'] else 48500) and t['body_height_hwp'] in {1000,1100},p['role'])
 ck('five source-backed cover semantic targets',set(t['cover_roles'])=={'customer','program','title','date','supplier'},p['role'])
 ck('cover evidence exact current SHA',h(p['cover_observed_evidence']['path'])==p['cover_observed_evidence']['sha256'],p['role'])
 for key,selector in p['cover_selectors'].items():
  with zipfile.ZipFile(p['source_template']['path']) as z:sec=E.fromstring(z.read(selector['template']['xml']));ck('exact template semantic cover owner resolves',len(sec.xpath(selector['template']['xpath'],namespaces=NS))==1,{'role':p['role'],'cover_role':key})
  with zipfile.ZipFile(p['reference_sources'][0]['path']) as z:
   sec=E.fromstring(z.read(selector['reference']['xml']));header=E.fromstring(z.read('Contents/header.xml'));char=header.xpath(selector['reference']['char_definition_xpath'],namespaces=NS)[0]
   ck('exact reference cover owner and chosen height/bold match',len(sec.xpath(selector['reference']['xpath'],namespaces=NS))==1 and int(char.get('height'))==t['cover_roles'][key]['height_hwp'] and (char.find('hh:bold',NS) is not None)==t['cover_roles'][key]['bold'],{'role':p['role'],'cover_role':key})
 for key,widths in t.get('table_column_widths_hwp',{}).items():ck('column widths positive and exact table width sum',all(x>0 for x in widths) and sum(widths)==t['table_width_hwp'],{'role':p['role'],'table':key,'sum':sum(widths)})
 ck('body header/footer frame synchronization explicitly selected',t.get('sync_header_footer_frames') is True,p['role'])
 ck('native layout refinement evidence exact SHA',h(p['native_layout_evidence']['path'])==p['native_layout_evidence']['sha256'],p['role'])
 ck('section boundary refinement evidence exact SHA',h(p['section_boundary_evidence']['path'])==p['section_boundary_evidence']['sha256'],p['role'])
 ck('section/heading owner refinement evidence exact SHA',h(p['section_heading_owner_evidence']['path'])==p['section_heading_owner_evidence']['sha256'],p['role'])
 if p['role']=='SF-TD3':
  selector=p['body_section_selector']
  with zipfile.ZipFile(p['source_template']['path']) as z:
   for semantic_role in ('source_heading','first_table_carrier'):
    s=selector[semantic_role];root=E.fromstring(z.read(s['xml']));nodes=root.xpath(s['xpath'],namespaces=NS)
    ck('TD3 exact original chapter/card owner binds source SHA and own text',len(nodes)==1 and s['source_sha256']==p['source_template']['sha256'] and own_text(nodes[0])==s['text_before_generation_verbatim'],semantic_role)
   ck('TD3 generated finite intro policy is registered/plain/one paragraph',selector['generated_intro']=={'allowed_prefix':'과제: ','maximum_paragraphs':1,'require_renderer_body_role':True,'plain_text_only':True})
 else:ck('exact TD3 chapter/card selector not generalized to other roles','body_section_selector' not in p,p['role'])
 for selector in p['section_boundary_spacer_selectors']:
  with zipfile.ZipFile(p['source_template']['path']) as z:
   root=E.fromstring(z.read(selector['xml']));owners=root.xpath(selector['xpath'],namespaces=NS)
   ck('declared boundary spacer is exact originally empty control-free owner',len(owners)==1 and own_text(owners[0])=='' and selector['source_sha256']==p['source_template']['sha256'] and selector['text_before_generation_verbatim']=='' and all(E.QName(n).localname in {'p','run','t','linesegarray','lineseg'} for n in owners[0].iter()) and owners[0].get('pageBreak','0')=='0' and owners[0].get('columnBreak','0')=='0',p['role'])
 if p['role']=='SF-PM4':
  widths=t['trace_table_column_widths_hwp'];ck('separate registered trace grid positive7columns and75000total',len(widths)==7 and min(widths)>0 and sum(widths)==75000,p['role'])
  ck('PM4 test IDs have at least measured8815HWP width including padding',all(width>=8815 for width in t['table_column_widths_hwp']['0'][6:9]),p['role'])
  ck('PM4 trace ID has at least measured9575HWP width including padding',widths[0]>=9575,p['role'])
  ck('PM4 nonfunctional prefix+test ID fits measured13616HWP including padding',t['table_column_widths_hwp']['1'][4]>=13616,p['role'])
 toc_roles={'SF-AD1','SF-AD2',*[f'SF-TD{n}' for n in range(1,6)],'SF-CD1',*[f'SF-TI{n}' for n in range(1,5)],'SF-OS1','SF-OS2'}
 selected=p['role'] in toc_roles
 ck('TOC target exists only in14source-backed roles',bool(t.get('toc_roles'))==selected and bool(p.get('toc_selectors'))==selected,p['role'])
 ck('source TOC presence explicitly recorded',p['toc_scope']['present_in_selected_template_and_reference']==selected,p['role'])
 if selected:
  ck('two TOC roles permit font face only',t['toc_roles']=={role:{'font_face':'함초롬바탕'} for role in ('title','entries')},p['role'])
  toc=load(p['toc_observed_evidence']['path']);ck('TOC evidence current SHA matches',h(p['toc_observed_evidence']['path'])==p['toc_observed_evidence']['sha256'],p['role'])
  for kind in ('template','reference'):
   source=toc[kind+'_source'];ck('TOC source original SHA',h(source['path'])==source['sha256'],{'role':p['role'],'kind':kind})
   with zipfile.ZipFile(source['path']) as z:
    ck('TOC evidence covers actual OPF spine order',source['spine_sections']==section_order(z),{'role':p['role'],'kind':kind})
    # Read all sections before resolving the exact TOC owners.
    sections={name:E.fromstring(z.read(name)) for name in source['spine_sections']};header=E.fromstring(z.read('Contents/header.xml'))
    for semantic_role,paragraphs in source['roles'].items():
     for paragraph in paragraphs:
      owner=sections[paragraph['xml']].xpath(paragraph['xpath'],namespaces=NS)
      ck('TOC exact owner text and source SHA match',len(owner)==1 and own_text(owner[0])==paragraph['text_verbatim'] and paragraph['source_sha256']==source['sha256'],{'role':p['role'],'kind':kind,'owner':paragraph['xpath']})
      for used in paragraph['actual_used_character_definitions']:
       run=sections[paragraph['xml']].xpath(used['run_xpath'],namespaces=NS);definition=header.xpath(used['definition_xpath'],namespaces=NS)
       ck('TOC actually used run and local character definition resolve',len(run)==1 and len(definition)==1 and run[0].get('charPrIDRef')==used['local_charPr_id']==definition[0].get('id') and ''.join(inline_text(t) for t in run[0].findall('hp:t',NS))==used['text_verbatim'],p['role'])
       if len(definition)!=1:continue
       char=definition[0];ck('TOC actual character size/bold/attributes evidence exact',dict(char.attrib)==used['attributes'] and (char.find('hh:bold',NS) is not None)==used['bold'],p['role'])
       ck('TOC all seven script font references resolved',set(used['fonts'])=={'hangul','latin','hanja','japanese','other','symbol','user'},p['role'])
       for script,font in used['fonts'].items():
        actual=header.xpath(font['font_definition_xpath'],namespaces=NS);refs=char.find('hh:fontRef',NS)
        ck('TOC actual script font declaration matches used local reference',len(actual)==1 and actual[0].get('id')==refs.get(script)==font['local_font_id'] and actual[0].get('face')==font['face'],{'role':p['role'],'kind':kind,'script':script})
        if kind=='reference':ck('reference TOC seven-script HCR observation',font['face']=='함초롬바탕',{'role':p['role'],'script':script})
    for control in source['protected_region_controls']:
     nodes=sections[control['xml']].xpath(control['xpath'],namespaces=NS)
     ck('TOC protected source control exact locator and attributes',len(nodes)==1 and E.QName(nodes[0]).localname==control['kind'] and dict(nodes[0].attrib)==control['attributes'],{'role':p['role'],'kind':kind,'control':control['kind']})
  for semantic_role,selector in p['toc_selectors'].items():
   first=toc['template_source']['roles'][semantic_role][0];s=selector['template']
   ck('TOC selector binds exact original first owner',s=={'source_sha256':toc['template_source']['sha256'],'xml':first['xml'],'xpath':first['xpath'],'text_before_generation_verbatim':first['text_verbatim']},{'role':p['role'],'owner':semantic_role})
 else:ck('TOC-absent roles contain no invented TOC evidence',not p.get('toc_observed_evidence'),p['role'])
for version in range(1,7):
 history=B/f'profiles/history/v{version}';old_index=load(history/'index.json')
 ck('previous profile history retains19entries',len(old_index['profiles'])==19,version)
 for old in old_index['profiles']:
  frozen=history/Path(old['path']).name;ck('previous profile bytes match historical index SHA',h(frozen)==old['sha256'],{'version':version,'role':old['role']})
  for path_key,hash_key in (('evidence_path','evidence_sha256'),):
   ck('previous raw evidence bytes match historical index SHA',h(history/Path(old[path_key]).name)==old[hash_key],{'version':version,'role':old['role']})
  prior=load(frozen)
  for key in ('cover_observed_evidence','native_layout_evidence','toc_observed_evidence','section_boundary_evidence','section_heading_owner_evidence'):
   if key in prior:ck('previous declared evidence bytes match frozen profile SHA',h(history/Path(prior[key]['path']).name)==prior[key]['sha256'],{'version':version,'role':old['role'],'kind':key})
ck('OS1no direct reference explicitly separate',load(B/'profiles/SF-OS1.json')['reference_relationship']=='no_direct_reference');ck('PM1partial cadence explicitly separate',load(B/'profiles/SF-PM1.json')['reference_relationship']=='partial_role')
active=[entry['case_id'] for entry in load(B/'active-freezes.json')['cases']]
for case in active:
 d=load(B/'frozen-inventory'/case/'manifest.json');ck('frozen case has no unassigned semantic fields',not d['unassigned_without_reason'],case);ck('frozen case score remains null',d['actual_suite_score_percent'] is None,case)
 for k in ['input_snapshot','rubric_snapshot','tool_snapshot']:
  f=d[k];ck('frozen immutable resource exact SHA',h(f['path'])==f['sha256'],{'case':case,'kind':k})
 for item in d['roles']:
  ck('frozen role inventory exact SHA',h(item['path'])==item['sha256'],item['role']);v=load(item['path'])
  for k in ['input','profile','rubric']:ck('frozen role immutable snapshot exact SHA',h(v[k]['path'])==v[k]['sha256'],{'case':case,'role':item['role'],'kind':k})
  ck('20criterion expected units only no fabricated pass',len(v['criteria'])==20 and v['actual_score_percent'] is None and all(c['status']=='unknown' and c['actual_pass_rate_percent'] is None for c in v['criteria']),{'case':case,'role':item['role']})
result={'recorded_at':datetime.now(timezone.utc).isoformat(),'tool_source_sha256':h(__file__),'scope':'Static v7 source-specific candidate profile, exact TD3 chapter/finite-intro boundary and heading-owner selection, declared empty boundary targets, measured PM4 normal/trace grids,14source-backed font-only TOC targets and frozen v1-v6 history/resource validation only. Active frozen inventories retain their own declared earlier profile snapshots; no pass is transferred. No Hancom action, page review, actual quality score or implementation regression claimed.','checks':checks,'failed':sum(not x['passed'] for x in checks),'summary':{'profiles':19,'profile_version':7,'toc_profile_roles':14,'toc_owner_targets':28,'toc_absent_roles':5,'previous_history_versions_checked':[1,2,3,4,5,6],'unique_source_hwpx':len(source_seen),'local_template_instructions':mcount,'template_field_observations_not_mandatory':fcount,'active_frozen_cases':active,'actual_quality_scores_assigned':0},'sources_current_sha256':source_seen}
report=B/'resource-validation-v7.json';report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'report':str(report),'checks':len(checks),'failed':result['failed'],'summary':result['summary'],'failures':[x for x in checks if not x['passed']][:15]},ensure_ascii=False,indent=2))
raise SystemExit(bool(result['failed']))
