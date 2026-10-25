"""Freeze meaningful editorial observation units before viewing output.

This is task-local evaluation tooling, not a renderer or score generator. It writes
new files only under analysis/style-upgrade, refuses existing output paths, and
never grants a visual/native/semantic pass. After native export, use bind-pages to
freeze actual PDF pages before the first page inspection. Candidate literal
mapping is a search aid; ambiguous/missing locations remain unknown.
"""
from __future__ import annotations
import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import argparse,json,re,zipfile
from lxml import etree as E
import pymupdf
R=Path(__file__).resolve().parents[2];BASE=Path(__file__).resolve().parent
NS={'hp':'http://www.hancom.co.kr/hwpml/2011/paragraph'}
ROLE_PATHS={
'SF-AD1':['project/customer','project/business_profile','project/business_processes','project/systems'],
'SF-AD2':['requirements'], 'SF-AD3':['features'],
'SF-TD1':['project/business_processes','requirements'], 'SF-TD2':['project/systems','deployment_items','programs','database_tables'],
'SF-TD3':['screens','requirements','features','programs'], 'SF-TD4':['programs','database_tables'], 'SF-TD5':['database_tables'],
'SF-CD1':['test_cases','defects'], 'SF-TI1':['test_cases','defects'], 'SF-TI2':['deployment_items'],
'SF-TI3':['project/manual_sections','screens','project/systems'], 'SF-TI4':['test_cases','defects'],
'SF-OS1':['project/support_activities','project/staff_members','project/systems'],
'SF-OS2':['operation_periods','kpis','defects','deployment_items'],
'SF-PM1':['progress_reports','project/schedule_items','project/staff_members','project/budget_items'],
'SF-PM2':['meetings'], 'SF-PM3':['changes','meetings'],
'SF-PM4':['requirements','trace_links','features','screens','programs','database_tables','test_cases']}
CONTEXT=['project/id','project/name','project/program_name','project/program_year','project/template_version','project/customer','project/supplier','project/status','project/source_refs','project/start_date','project/end_date','project/implementation_scope','project/notes','synthetic_notice']
NO_PRINT={'sources':'Source registry/provenance file paths and hashes stay in linked machine input/annex; displayed source keys/locators remain mapped through source_refs.','attachments':'File path/SHA/media metadata remain in attachment register; supplied image/caption/meaning is separately required in figure inventory.','reviews':'Machine review links are retained in linked input and printed when the role uses their approval/review meaning; no approval is inferred.','extraction_issues':'Original issue register is preserved in linked input/QA annex; generation must not silently fix or turn it into new project facts.','schema_version':'Input schema metadata, not business prose.','dataset_kind':'Represented by in-document synthetic/reference/draft notice.','submission_ready':'Machine readiness flag remains false; not a signature/approval statement.','project/requested_deliverables':'Generation selection metadata, not claimed completed business outputs.','project/requested_forms':'Separate34form selection; not19role business content.'}
def digest(p):return sha256(Path(p).read_bytes()).hexdigest()
def canon(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def load(p):return json.loads(Path(p).read_text())
def now():return datetime.now(timezone.utc).isoformat()
def target(p):
 p=Path(p).resolve()
 if not p.is_relative_to(BASE):raise ValueError('Output must remain in analysis/style-upgrade')
 if p.exists():raise ValueError('Refusing to overwrite a frozen inventory/report: '+str(p))
 p.parent.mkdir(parents=True,exist_ok=True);return p
def write(p,d):p=target(p);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');return {'path':str(p),'sha256':digest(p)}
def pointer(s):return '/'+s.replace('~','~0').replace('/','/')
def value_at(d,path):
 for s in path.split('/'):
  if not isinstance(d,dict) or s not in d:return None,False
  d=d[s]
 return d,True
def semantic_fields(v,path):
 if path.endswith('/source_refs') or path.endswith('/field_states') or (isinstance(v,list) and not any(isinstance(i,dict) for i in v)):
  yield path,v
  return
 # Treat source_refs/ID arrays and prose lists as one meaningful field, not many easy glyph or metadata passes.
 if isinstance(v,dict):
  if not v:yield path,v
  for k,x in v.items():
   key=k.replace('~','~0').replace('/','~1')
   if k in {'source_refs','field_states'} or (isinstance(x,list) and not any(isinstance(i,dict) for i in x)):yield path+'/'+key,x
   else:yield from semantic_fields(x,path+'/'+key)
 elif isinstance(v,list):
  if not v:yield path,v
  for i,x in enumerate(v):yield from semantic_fields(x,path+'/'+str(i))
 else:yield path,v
REFERENCE_FIELDS={
 ('SF-TD1','requirements'):{'id','name'},
 ('SF-TD2','programs'):{'id','name','table_ids','screen_ids','requirement_ids'},('SF-TD2','database_tables'):{'id','name'},
 ('SF-TD3','features'):{'id','name','requirement_ids'},('SF-TD3','programs'):{'id','name'},
 ('SF-TD4','database_tables'):{'id','name'},
 ('SF-TI3','screens'):{'id','name','path','steps','checks','before_attachment_ids','after_attachment_ids'},
 ('SF-OS1','project/systems'):{'id','name','current_configuration','target_configuration'},
 ('SF-OS2','deployment_items'):{'id','name','installation_status','actual_specification','installed_quantity','installation_date','verification_result'},
 **{('SF-PM4',k):{'id','name','requirement_ids','stage','group_id'} for k in ['features','screens','programs','database_tables','test_cases']}}

# Each slot is reviewed independently. Reusing an attachment across roles or
# as-is/to-be slots does not merge their separate meaning/placement obligations.
SCREEN_SLOTS=('prototype_attachment_ids','current_capture_attachment_ids','changed_capture_attachment_ids','standard_attachment_ids','screenshot_attachment_ids','before_attachment_ids','after_attachment_ids')
FIGURE_PATHS={
 'SF-AD1':(('project/business_processes',('as_is_attachment_ids',)),('project/systems',('as_is_diagram_ids',))),
 'SF-TD1':(('project/business_processes',('as_is_attachment_ids','to_be_attachment_ids')),),
 'SF-TD2':(('project/systems',('as_is_diagram_ids','to_be_diagram_ids')),),
 'SF-TD3':(('screens',SCREEN_SLOTS),),
 'SF-TD4':(('programs',('module_flow_attachment_ids',)),),
 'SF-TI3':(('project/manual_sections',('attachment_ids',)),('screens',SCREEN_SLOTS)),
 'SF-CD1':(('test_cases',('flow_attachment_ids',)),),
 'SF-TI1':(('test_cases',('flow_attachment_ids',)),),
 'SF-TI4':(('test_cases',('flow_attachment_ids',)),),
}

def resolve_pointer(data,locator):
 """Resolve an explicit JSON Pointer; XML locators are never guessed."""
 if not locator.startswith('/'):raise ValueError('Not a JSON Pointer: '+locator)
 for token in locator[1:].split('/'):
  token=token.replace('~1','/').replace('~0','~')
  data=data[int(token)] if isinstance(data,list) else data[token]
 return data

def file_record(path):
 return {'path':str(Path(path).resolve()),'sha256':digest(path)}

def collect_figure_evidence(data,label_evidence=None,*,base_dir=None):
 """Load hash-bound source JSON and optional direct source-image observations.

 Loading a label freezes a future observation target. It does not establish that
 the label is readable in a generated/native document, or that its claim is true.
 """
 sources={x['id']:x for x in data.get('sources',[])}
 source_json={};source_records=[]
 for source_id,source in sources.items():
  path=Path(source.get('path',''))
  if not path.is_absolute():path=Path(base_dir or R)/path
  if path.suffix.lower()!='.json' or not path.is_file():continue
  actual=digest(path)
  if actual!=source.get('sha256'):raise ValueError('Source JSON SHA mismatch: '+source_id)
  source_json[source_id]=load(path)
  source_records.append({'source_id':source_id,**file_record(path)})
 manual={}
 if label_evidence:
  evidence=load(label_evidence)
  if evidence.get('schema_version')!='source-figure-label-observations-1':raise ValueError('Unsupported figure-label evidence schema')
  for record in [evidence.get(k) for k in ['source_document','source_image','lossless_preview']]+evidence.get('inspection_crops',[]):
   if record and (not Path(record['path']).is_file() or digest(record['path'])!=record['sha256']):raise ValueError('Manual label observation evidence SHA mismatch: '+record['path'])
  for item in evidence.get('figures',[]):
   key=(item['entity_id'],item['slot'],item['attachment_id'])
   if key in manual:raise ValueError('Duplicate manual figure-label evidence: '+str(key))
   if not item.get('essential_elements'):raise ValueError('Manual figure evidence has no essential elements')
   manual[key]=item
 return source_json,source_records,manual

def figure_inventory(data,role,source_json,source_records,manual,*,base_dir=None):
 attachments={x['id']:x for x in data.get('attachments',[])}
 source_records={x['source_id']:x for x in source_records};figures=[]
 for base,slots in FIGURE_PATHS.get(role,()):
  entities,exists=value_at(data,base)
  if not exists:continue
  for entity_index,entity in enumerate(entities):
   entity_pointer='/'+base+'/'+str(entity_index)
   stage={'SF-CD1':'unit','SF-TI1':'integration','SF-TI4':'acceptance'}.get(role)
   if base=='test_cases' and stage and entity.get('stage')!=stage:continue
   # Manual sections have no business ID in the schema. Their exact input
   # pointer is an evaluation owner key, never an invented printed identifier.
   owner_key=entity.get('id') or entity_pointer
   for slot in slots:
    for attachment_index,aid in enumerate(entity.get(slot,[]) or []):
     attachment=attachments.get(aid)
     figure_id='figure:'+owner_key+':'+slot+':'+aid
     figure={'unit_id':figure_id,'entity_id':owner_key,'entity_business_id':entity.get('id'),'entity_name':entity.get('name'),'entity_json_pointer':entity_pointer,'slot':slot,'slot_json_pointer':entity_pointer+'/'+slot+'/'+str(attachment_index),'attachment_id':aid,'source_path':attachment.get('path') if attachment else None,'source_sha256':attachment.get('sha256') if attachment else None,'caption':attachment.get('caption') if attachment else None,'state':attachment.get('verification_status') if attachment else 'missing','source_refs':attachment.get('source_refs',[]) if attachment else [],'essential_elements':[],'status':'unknown','scope':'Expected figure placement/caption/meaning and final printed legibility only; no implementation/execution/approval claim.'}
     if base=='screens':figure['screen_id']=entity['id']
     if figure['source_path'] and not Path(figure['source_path']).is_absolute():figure['source_path']=str((Path(base_dir or R)/figure['source_path']).resolve())
     if figure['source_path'] and Path(figure['source_path']).is_file() and digest(figure['source_path'])!=figure['source_sha256']:raise ValueError('Figure attachment SHA mismatch: '+figure_id)
     elements=[]
     # Screen-specific before/after figures retain the screen field/button
     # obligations. A shared main/login standard is a different semantic slot;
     # it needs explicit hash-bound source/manual labels, never unrelated form
     # fields. If no such labels exist it keeps the unresolved required unit.
     if base=='screens' and slot!='standard_attachment_ids':
      for key,kind in [('fields','field'),('buttons','button')]:
       for i,item in enumerate(entity.get(key,[])):
        label=item.get('name') or item.get('id')
        if label:elements.append({'label':label,'kind':kind,'label_basis':'input_screen_definition','json_pointer':entity_pointer+'/'+key+'/'+str(i),'source_refs':item.get('source_refs',[])})
     # Diagram labels must be bound to the same entity, slot, and image bytes.
     for ref in figure['source_refs']:
      source_id=ref.get('source_id');locator=ref.get('locator','')
      if source_id not in source_json or not locator.startswith('/'):continue
      try:source_item=resolve_pointer(source_json[source_id],locator)
      except (KeyError,IndexError,ValueError,TypeError):raise ValueError('Unresolved figure source pointer: '+str(ref))
      if not isinstance(source_item,dict) or 'essential_labels' not in source_item:continue
      bindings=source_item.get('bindings')
      if bindings is not None:
       if (not isinstance(bindings,list) or not bindings or not all(isinstance(binding,dict) for binding in bindings)
           or not any(binding.get('entity_id')==owner_key and binding.get('slot')==slot and binding.get('entity_json_pointer',entity_pointer)==entity_pointer for binding in bindings)):
        raise ValueError('Figure source explicit owner/slot bindings mismatch: '+figure_id)
      elif source_item.get('entity_id')!=owner_key or source_item.get('slot')!=slot:raise ValueError('Figure source entity/slot mismatch: '+figure_id)
      image_match=any(isinstance(source_item.get(k),dict) and source_item[k].get('sha256')==figure['source_sha256'] for k in ('png','bmp','jpeg','jpg','image'))
      if not image_match:raise ValueError('Figure source image SHA mismatch: '+figure_id)
      figure['diagram_relations']={'arrows_represent_supplied_step_order':source_item.get('arrows_represent_supplied_step_order'),'source_id':source_id,'locator':locator,'status':'unknown','scope':'Only an explicitly supplied step order may be reviewed as sequence; program function lists do not establish execution order.'}
      for i,label in enumerate(source_item['essential_labels']):
       if not isinstance(label,str) or not label.strip():raise ValueError('Empty/nontext essential diagram label: '+figure_id)
       elements.append({'label':label,'kind':'diagram_label','label_basis':'hash_bound_source_json','source':source_records[source_id],'source_id':source_id,'json_pointer':locator+'/essential_labels/'+str(i)})
     key=(owner_key,slot,aid)
     if key in manual:
      observed=manual[key]
      if observed['source_sha256']!=figure['source_sha256']:raise ValueError('Manual source image SHA mismatch: '+figure_id)
      figure['source_comparison_scope']=observed.get('comparison_scope')
      figure['source_limitations']=observed.get('source_limitations',[])
      for item in observed['essential_elements']:
       if not isinstance(item.get('label'),str) or not item['label'].strip():raise ValueError('Manual essential label is empty')
       elements.append({**item,'label_basis':'direct_source_image_observation'})
     # Supplied but unmapped figures cannot receive an empty/absence denominator.
     if not elements:elements=[{'label':None,'kind':'unresolved_essential_mapping','mapping_status':'required_before_legibility_review','reason':'Figure is supplied but its essential content has not been identified; this is not an absent-figure success.'}]
     # One visible essential label is one obligation even when both the screen
     # definition and the source figure list declare it. No double denominator.
     unique=[];seen_labels=set()
     for item in elements:
      label=item.get('label')
      if label is not None and label in seen_labels:continue
      if label is not None:seen_labels.add(label)
      unique.append(item)
     elements=unique
     for i,item in enumerate(elements):
      item.update({'unit_id':'essential:'+figure_id+':'+str(i),'figure_unit_id':figure_id,'status':'unknown','actual_output_location':None})
     figure['essential_elements']=elements
     figures.append(figure)
 return figures

def snapshot_figure_evidence(out,source_records,label_evidence):
 records=[]
 for index,source in enumerate(source_records):
  snapshot=target(out/'figure-sources'/(str(index)+'.snapshot.json'));snapshot.write_bytes(Path(source['path']).read_bytes())
  records.append({'source_id':source['source_id'],'source':{'path':source['path'],'sha256':source['sha256']},'snapshot':file_record(snapshot)})
 if label_evidence:
  snapshot=target(out/'source-figure-labels.snapshot.json');snapshot.write_bytes(Path(label_evidence).read_bytes())
  records.append({'source_id':'direct-source-image-label-observations','source':file_record(label_evidence),'snapshot':file_record(snapshot)})
 return records

def records(data,role):
 values=[]
 for base in CONTEXT+ROLE_PATHS[role]:
  v,exists=value_at(data,base)
  if not exists:continue
  if (role,base) in REFERENCE_FIELDS and isinstance(v,list):
   for i,x in enumerate(v):values.append(('/'+base+'/'+str(i),{k:y for k,y in x.items() if k in REFERENCE_FIELDS[(role,base)]}))
  elif base=='test_cases':
   stage={'SF-CD1':'unit','SF-TI1':'integration','SF-TI4':'acceptance'}.get(role)
   for i,x in enumerate(v):
    if stage is None or x.get('stage')==stage:values.append(('/'+base+'/'+str(i),x))
  else:values.append(('/'+base,v))
 return values
def make_inventory(args):
 inp=Path(args.input).resolve();data=load(inp);out=Path(args.output).resolve()
 if out.exists():raise ValueError('Frozen case directory already exists')
 source_json,source_records,manual=collect_figure_evidence(data,args.figure_label_evidence,base_dir=inp.parent)
 figure_sets={role:figure_inventory(data,role,source_json,source_records,manual,base_dir=inp.parent) for role in args.role or ROLE_PATHS}
 selected_manual_keys={(figure['entity_id'],figure['slot'],figure['attachment_id']) for figures in figure_sets.values() for figure in figures}
 if set(manual)-selected_manual_keys:raise ValueError('Unmatched manual figure-label evidence: '+str(sorted(set(manual)-selected_manual_keys)))
 input_snapshot=target(out/'input.snapshot.json');input_snapshot.write_bytes(inp.read_bytes());rubric_snapshot=target(out/'rubric.snapshot.json');rubric_snapshot.write_bytes((BASE/'rubric.json').read_bytes());tool_snapshot=target(out/'freeze-tool.snapshot.py');tool_snapshot.write_bytes(Path(__file__).read_bytes())
 figure_evidence_snapshots=snapshot_figure_evidence(out,source_records,args.figure_label_evidence)
 idx=load(BASE/'profiles/index.json');prof={x['role']:x for x in idx['profiles']};roles=args.role or list(ROLE_PATHS);rubric=load(BASE/'rubric.json');results=[];all_seen=set()
 for role in roles:
  p=load(prof[role]['path']);profile_snapshot=target(out/'profiles'/(role+'.json'));profile_snapshot.write_bytes(Path(prof[role]['path']).read_bytes());fields={}
  for path,v in records(data,role):
   for ptr,x in semantic_fields(v,path):fields[ptr]={'unit_id':'meaning:'+ptr,'json_pointer':ptr,'value':x,'json_type':'null' if x is None else type(x).__name__,'value_sha256':sha256(canon(x).encode()).hexdigest(),'required_location':'body_or_readable_appendix_or_explicit_reason','candidate_locations':[],'status':'unknown','reason':'Frozen expected meaning; no rendered position or semantic judgment yet.'};all_seen.add(ptr)
  figures=figure_sets[role]
  field_units=list(fields.values());ids=[x for x in field_units if x['json_pointer'].split('/')[-1] in {'id','screen_ids','program_ids','table_ids','requirement_ids','feature_ids'}];blocks=[]
  for base in ROLE_PATHS[role]:
   v,exists=value_at(data,base)
   if exists:
    if isinstance(v,list):
     stage={'SF-CD1':'unit','SF-TI1':'integration','SF-TI4':'acceptance'}.get(role) if base=='test_cases' else None
     blocks += [{'unit_id':'record:/'+base+'/'+str(i),'id':x.get('id') if isinstance(x,dict) else None} for i,x in enumerate(v) if stage is None or isinstance(x,dict) and x.get('stage')==stage]
    elif v is not None:blocks.append({'unit_id':'record:/'+base})
  semantic_roles=['cover_title','toc_or_section_heading','body','field_label','field_value','identifier','source_or_uncertainty_note']+(['figure_caption'] if figures else [])
  style_units=[{'unit_id':'style:'+x,'semantic_role':x,'status':'unknown'} for x in semantic_roles]
  rawtext=canon(data);scripts=[s for s,pat in [('hangul',r'[가-힣]'),('latin',r'[A-Za-z]'),('numeric',r'[0-9]'),('symbol',r'[^\w\s가-힣]'),('hanja',r'[\u4e00-\u9fff]'),('japanese',r'[\u3040-\u30ff]')] if re.search(pat,rawtext)]
  font_units=[{'unit_id':'font:'+r+':'+s,'semantic_role':r,'script':s,'status':'unknown'} for r in semantic_roles for s in scripts]
  criteria=[]
  for c in rubric['criteria']:
   cid=c['id']
   if cid=='F01':units=font_units
   elif cid in {'F02','S01','S02'}:units=style_units
   elif cid in {'C01','L04','L05'}:units=blocks or [{'unit_id':'empty-role-disclosure','status':'unknown'}]
   elif cid in {'C02','C03','C04','C05'}:units=field_units
   elif cid=='L03':units=ids
   elif cid=='L02':units=[x for x in field_units if any(k in x['json_pointer'] for k in ['database_tables','screens','test_cases','trace_links','requirements','features','progress_reports','meetings','changes'])] or field_units
   elif cid in {'G01','G03'}:units=figures or [{'unit_id':'absence:figure-slots','status':'unknown','scope':'Check no absent-required figure is invented or claimed complete. This is not a positive figure-legibility proof.'}]
   elif cid=='G02':units=[x for f in figures for x in f['essential_elements']] or [{'unit_id':'absence:essential-elements','status':'unknown','scope':'No actual figure supplied; any role needing figures remains pending until an appropriate frozen provided/synthetic test-image case exists.'}]
   elif cid=='L01':units=[{'unit_id':'section:cover-preserved','status':'unknown'},{'unit_id':'section:body-profile','status':'unknown'},{'unit_id':'tables:coherent-width-and-merged-cells','status':'unknown'}]
   elif cid in {'N01','N02'}:units=[{'unit_id':'native:current-final-artifact','status':'unknown'},{'unit_id':'native:all-current-pages-bind-after-export','status':'unknown','physical_page_count':None}]
   else:units=[{'unit_id':'comparison:same-content','status':'unknown'},{'unit_id':'comparison:unused-input','status':'unknown'}]
   # Freeze ID inventory without duplicating whole leaf values20times.
   criteria.append({'criterion_id':cid,'critical':c['critical'],'unit_ids':[x['unit_id'] for x in units],'required_observation_units':len(units),'status':'unknown','actual_passed_units':None,'actual_failed_units':None,'actual_unknown_units':None,'actual_pass_rate_percent':None})
  result={'schema_version':'frozen-editorial-observation-inventory-1','frozen_at':now(),'freeze_tool':{'path':str(Path(__file__).resolve()),'sha256':digest(__file__)},'prior_exploratory_observations':args.prior_exploration,'case_id':args.case_id,'case_kind':args.case_kind,'role':role,'source_input':{'path':str(inp),'sha256':digest(inp)},'input':{'path':str(input_snapshot),'sha256':digest(input_snapshot)},'profile_source':{'path':prof[role]['path'],'sha256':digest(prof[role]['path'])},'profile':{'path':str(profile_snapshot),'sha256':digest(profile_snapshot)},'rubric':{'path':str(rubric_snapshot),'sha256':digest(rubric_snapshot)},'selection_policy':{'paths':CONTEXT+ROLE_PATHS[role],'source_refs_and_prose_lists_are_grouped':True,'no_glyph_denominator':True,'reference_field_selection':{k[1]:sorted(v) for k,v in REFERENCE_FIELDS.items() if k[0]==role},'scope_limit':'Source metadata and unrelated role data are never silently treated as printed. Globalcoverage report lists assignments/nonprinting reasons. Mandatory paragraph instructions are additionally reviewed from profile.'},'semantic_fields':field_units,'record_blocks':blocks,'text_role_units':style_units,'font_script_units':font_units,'identifier_units':[x['unit_id'] for x in ids],'figure_units':figures,'figure_evidence_snapshots':figure_evidence_snapshots,'figure_selection_policy':{'paths':[{"entity_path":base,"independent_slots":list(slots)} for base,slots in FIGURE_PATHS.get(role,())],'essential_units':'Each figure owns its label units; supplied figures with unresolved label mapping retain an unknown mapping-required unit. Source defects never count as positive style evidence.'},'criteria':criteria,'actual_score_percent':None,'current_pdf_page_inventory':None,'page_policy':'Bind exact exported PDF and any PNG manifest to a new frozen page-inventory before page review. Do not guess page counts or overwrite this freeze.','actual_native_status':'not_recorded','actual_visual_status':'not_reviewed'}
  rr=write(out/(role+'.inventory.json'),result);results.append({'role':role,**rr,'semantic_fields':len(field_units),'figures':len(figures),'criterion_units':{x['criterion_id']:x['required_observation_units'] for x in criteria}})
 all_fields=list(semantic_fields(data,''));coverage=[]
 potential={role:{ptr for path,v in records(data,role) for ptr,val in semantic_fields(v,path)} for role in ROLE_PATHS}
 expected={x['role']:{f['json_pointer'] for f in load(x['path'])['semantic_fields']} for x in results}
 for ptr,val in all_fields:
  assigned=[role for role,paths in expected.items() if ptr in paths];owners=[role for role,paths in potential.items() if ptr in paths]
  clean=ptr.lstrip('/');reason=next((reason for pref,reason in NO_PRINT.items() if clean==pref or clean.startswith(pref+'/')),None)
  if not assigned and val==[] and not owners and not reason:reason='Empty unrequested domain array retained in linked typed input; not an assertion of actual absence or performed/not-performed business activity.'
  if not assigned and owners and not reason:reason='Owned by unrequested roles '+','.join(owners)+'; this controlled case does not claim those documents. Complete original typed input is retained.'
  coverage.append({'json_pointer':ptr,'assigned_roles':assigned,'document_printing_status':'expected_location_pending' if assigned else 'explicit_machine_register_or_notice' if reason else 'unassigned_requires_mapping_decision','nonprinting_reason':None if assigned else reason,'actual_output_location':None,'status':'unknown'})
 manifest={'schema_version':'frozen-editorial-case-manifest-1','frozen_at':now(),'freeze_tool':{'path':str(Path(__file__).resolve()),'sha256':digest(__file__)},'prior_exploratory_observations':args.prior_exploration,'case_id':args.case_id,'case_kind':args.case_kind,'input':{'path':str(inp),'sha256':digest(inp)},'source_input':{'path':str(inp),'sha256':digest(inp)},'input_snapshot':{'path':str(input_snapshot),'sha256':digest(input_snapshot)},'rubric_snapshot':{'path':str(rubric_snapshot),'sha256':digest(rubric_snapshot)},'tool_snapshot':{'path':str(tool_snapshot),'sha256':digest(tool_snapshot)},'figure_evidence_snapshots':figure_evidence_snapshots,'roles':results,'global_meaningful_field_coverage':coverage,'unassigned_without_reason':[x['json_pointer'] for x in coverage if x['document_printing_status']=='unassigned_requires_mapping_decision'],'actual_suite_score_percent':None,'not_a_review':'Expected units only. No actual font/native/visual/content pass exists in this record.'}
 write(out/'manifest.json',manifest);print(json.dumps({'roles':len(results),'case':args.case_id,'semantic_fields_global':len(coverage),'unassigned_without_reason':len(manifest['unassigned_without_reason']),'actual_score':None,'manifest':str(out/'manifest.json')},ensure_ascii=False,indent=2))
def bind_pages(args):
 inv=Path(args.inventory).resolve();d=load(inv);pdf=Path(args.pdf).resolve();doc=pymupdf.open(pdf)
 record={'schema_version':'frozen-editorial-page-inventory-1','frozen_at':now(),'base_inventory':{'path':str(inv),'sha256':digest(inv)},'input':d['input'],'profile':d['profile'],'pdf':{'path':str(pdf),'sha256':digest(pdf)},'page_count':len(doc),'pages':[{'unit_id':f'physical-page:{i+1}','physical_page':i+1,'page_rect':list(p.rect),'status':'unknown','observation':None,'reviewer':None,'reviewed_at':None} for i,p in enumerate(doc)],'actual_quality_score_percent':None,'scope':'Exact page inventory only, frozen before visual review; PDF parsing is not native execution or page-quality approval.'}
 if args.hwpx:record['current_native_hwpx']={'path':str(Path(args.hwpx).resolve()),'sha256':digest(args.hwpx)}
 print(json.dumps(write(Path(args.output),record),ensure_ascii=False))
def audit_mapping(args):
 inv=Path(args.inventory).resolve();d=load(inv);hp=Path(args.hwpx).resolve();paragraphs=[]
 with zipfile.ZipFile(hp) as z:
  opf=E.fromstring(z.read('Contents/content.hpf'));items={x.get('id'):x.get('href') for x in opf.xpath('//*[local-name()="manifest"]/*[local-name()="item"]')}
  for ref in opf.xpath('//*[local-name()="spine"]/*[local-name()="itemref"]'):
   name=items[ref.get('idref')];name=name if name in z.namelist() else 'Contents/'+name
   root=E.fromstring(z.read(name));tree=root.getroottree()
   for p in root.findall('.//hp:p',NS):
    ts=[t for t in p.findall('.//hp:t',NS) if next((a for a in t.iterancestors() if a.tag==p.tag),None) is p];text=''.join(''.join(t.itertext()) for t in ts)
    if text.strip():paragraphs.append({'xml':name,'xpath':tree.getpath(p),'text':text})
 rows=[]
 for f in d['semantic_fields']:
  v=f['value'];tokens=[]
  if isinstance(v,str) and v.strip():tokens=[v]
  elif isinstance(v,(int,float)) and not isinstance(v,bool):tokens=[str(v)]
  # null/boolean/arrays need explicit typed/owner review; generic0/unknown text cannot prove the right field.
  hits=[{'xml':p['xml'],'xpath':p['xpath'],'text':p['text'][:500]} for p in paragraphs if any(t in p['text'] for t in tokens)]
  rows.append({'unit_id':f['unit_id'],'json_pointer':f['json_pointer'],'candidate_locations':hits,'candidate_status':'literal_candidates_only_semantic_owner_review_required' if hits else 'no_literal_candidate_or_nonliteral_value_needs_mapping','semantic_status':'unknown','reason':'Literal presence is not proof of correct owner, preserved type/relation or final printed legibility.'})
 result={'schema_version':'editorial-semantic-location-candidate-audit-1','recorded_at':now(),'inventory':{'path':str(inv),'sha256':digest(inv)},'hwpx':{'path':str(hp),'sha256':digest(hp)},'role':d['role'],'fields':rows,'no_literal_candidates':[x['json_pointer'] for x in rows if not x['candidate_locations']],'actual_semantic_pass':False,'actual_quality_score_percent':None,'limits':['Search aid only; requires renderer field mapping or named human owner/meaning review. Null/false/0/empty arrays and translated enums must not be guessed from generic words.','Source metadata may legitimately be in linked annex with explicit nonprinting reason. Missing visible required meaning is not waived.']}
 print(json.dumps(write(Path(args.output),result),ensure_ascii=False))

def audit_freeze(args):
 """Check frozen manifests and observation-unit invariants; never score output."""
 manifest_path=Path(args.manifest).resolve();manifest=load(manifest_path);checks=[]
 def check(name,ok,detail=None):checks.append({'check':name,'ok':bool(ok),'detail':detail})
 def hash_check(name,record):
  path=Path(record['path']);check(name,path.is_file() and digest(path)==record['sha256'],record)
 for key in ['input_snapshot','rubric_snapshot','tool_snapshot']:
  hash_check(key,manifest[key])
 check('tool_snapshot_matches_recorded_tool',manifest['tool_snapshot']['sha256']==manifest['freeze_tool']['sha256'])
 check('suite_has_no_actual_score',manifest.get('actual_suite_score_percent') is None)
 for index,source in enumerate(manifest.get('figure_evidence_snapshots',[])):
  hash_check('figure_source_snapshot:'+str(index),source['snapshot'])
  check('figure_source_snapshot_matches_source:'+str(index),source['snapshot']['sha256']==source['source']['sha256'])
 for role_record in manifest['roles']:
  role=role_record['role'];hash_check(role+':inventory',role_record);inventory=load(role_record['path'])
  for key in ['input','profile','rubric']:hash_check(role+':'+key,inventory[key])
  check(role+':no_actual_score',inventory.get('actual_score_percent') is None)
  check(role+':no_native_or_visual_pass',inventory.get('actual_native_status')=='not_recorded' and inventory.get('actual_visual_status')=='not_reviewed')
  figures=inventory['figure_units'];essentials=[unit for figure in figures for unit in figure['essential_elements']]
  figure_ids=[figure['unit_id'] for figure in figures];essential_ids=[unit['unit_id'] for unit in essentials]
  check(role+':unique_figure_ids',len(figure_ids)==len(set(figure_ids)))
  check(role+':unique_essential_ids',len(essential_ids)==len(set(essential_ids)))
  for figure in figures:
   check(role+':nonempty_essential_mapping:'+figure['unit_id'],bool(figure['essential_elements']))
   check(role+':all_figure_observations_unknown:'+figure['unit_id'],figure['status']=='unknown' and all(x['status']=='unknown' for x in figure['essential_elements']))
   if figure['source_path'] and figure['source_sha256']:hash_check(role+':source_image:'+figure['unit_id'],{'path':figure['source_path'],'sha256':figure['source_sha256']})
  for criterion in inventory['criteria']:
   cid=criterion['criterion_id'];unit_ids=criterion['unit_ids']
   check(role+':criterion_count:'+cid,len(unit_ids)==len(set(unit_ids))==criterion['required_observation_units'])
   check(role+':criterion_unknown:'+cid,criterion['status']=='unknown' and all(criterion[k] is None for k in ['actual_passed_units','actual_failed_units','actual_unknown_units','actual_pass_rate_percent']))
   if figures and cid in {'G01','G03'}:check(role+':all_figures_in:'+cid,unit_ids==figure_ids)
   if figures and cid=='G02':check(role+':all_essentials_in:G02',unit_ids==essential_ids)
 report={'schema_version':'editorial-inventory-static-audit-1','recorded_at':now(),'manifest':file_record(manifest_path),'checks':checks,'static_invariants_ok':all(x['ok'] for x in checks),'actual_quality_score_percent':None,'actual_native_status':'not_recorded','actual_visual_status':'not_reviewed','scope':'Hash/count/selection/unknown-state checks only. No generated output or native page has been approved.'}
 record=write(Path(args.output),report);print(json.dumps({**record,'checks':len(checks),'static_invariants_ok':report['static_invariants_ok'],'actual_quality_score_percent':None},ensure_ascii=False))
 if not report['static_invariants_ok']:raise SystemExit(1)

def main():
 a=argparse.ArgumentParser(description=__doc__);sub=a.add_subparsers(dest='command',required=True)
 p=sub.add_parser('freeze');p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--case-id',required=True);p.add_argument('--case-kind',choices=['baseline_synthetic','same_content','heldout'],required=True);p.add_argument('--role',action='append');p.add_argument('--prior-exploration',default='none_declared');p.add_argument('--figure-label-evidence',help='Hash-bound direct source-image label observations; freezes future targets, never output passes.')
 p=sub.add_parser('bind-pages');p.add_argument('--inventory',required=True);p.add_argument('--pdf',required=True);p.add_argument('--hwpx');p.add_argument('--output',required=True)
 p=sub.add_parser('mapping-candidates');p.add_argument('--inventory',required=True);p.add_argument('--hwpx',required=True);p.add_argument('--output',required=True)
 p=sub.add_parser('audit-freeze');p.add_argument('--manifest',required=True);p.add_argument('--output',required=True)
 args=a.parse_args();{'freeze':make_inventory,'bind-pages':bind_pages,'mapping-candidates':audit_mapping,'audit-freeze':audit_freeze}[args.command](args)
if __name__=='__main__':main()
