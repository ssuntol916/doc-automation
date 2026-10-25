"""Add exact source-backed semantic cover font targets to candidate profiles.
Retains v2 and preserves geometry/control policy. No native/editorial pass.
"""
import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json,shutil
R=Path(__file__).resolve().parents[2];B=Path(__file__).resolve().parent;P=B/'profiles'
def load(p):return json.loads(Path(p).read_text())
def h(p):return sha256(Path(p).read_bytes()).hexdigest()
def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
idx=load(P/'index.json');archive=P/'history/v2';archive.mkdir(parents=True,exist_ok=True)
for path in P.glob('*.json'):
 dest=archive/path.name
 if not dest.exists():shutil.copyfile(path,dest)
source_to_id={x['source_path']:x['id'] for x in load(R/'analysis/stage2/inventory.json')['documents']}
roles=['customer','program','title','date','supplier'];summary=[]
for entry in idx['profiles']:
 path=Path(entry['path']);p=load(path);refpath=p['reference_sources'][0]['path'];rid=source_to_id[refpath];reference=load(R/f'analysis/stage2/profiles/{rid}.json');template=load(R/f"analysis/stage1/profiles/template-{p['role'].lower()}.json")
 rr=[x for x in reference['sections'][0]['paragraphs'] if x['text'].strip() and x['role'] not in {'header','footer'}][:5];tt=[x for x in template['sections'][0]['paragraphs'] if x['text'].strip() and x['role'] not in {'header','footer'}][:5]
 if len(rr)!=5 or len(tt)!=5:raise ValueError('Cannot uniquely select five cover owners:'+p['role'])
 ev=load(entry['evidence_path']);raw=ev['reference'] or ev['adjacent_references'][0];formats={u['local_charPr_id']:u for u in raw['used_character_formats']};cover={};selectors={};observations=[]
 for role,r,t in zip(roles,rr,tt):
  nonempty=[x for x in r['runs'] if x['text'].strip()]
  if len(nonempty)!=1:raise ValueError('Mixed-format cover owner requires explicit per-run choice:'+p['role']+role)
  u=formats[nonempty[0]['attributes']['charPrIDRef']];target={'font_face':u['fonts']['hangul']['face'],'height_hwp':int(u['attributes']['height']),'bold':u['bold']};cover[role]=target
  selectors[role]={'template':{'source_sha256':p['source_template']['sha256'],'xml':template['sections'][0]['name'],'xpath':t['xpath'],'text_before_generation_verbatim':t['text']},'reference':{'source_sha256':reference['sha256'],'xml':reference['sections'][0]['name'],'xpath':r['xpath'],'text_verbatim':r['text'],'char_definition_xpath':u['definition_xpath']},'selector_policy':'Select exact template owner paragraph before/after supplied text substitution; preserve nontext objects/controls and geometry. Numeric IDs and actual exemplar business strings are not runtime replacement values.'}
  observations.append({'semantic_role':role,'reference_relationship':p['reference_relationship'] if p['reference_relationship']!='no_direct_reference' else 'adjacent_OS2_cover_design_basis','reference_paragraph':selectors[role]['reference'],'actual_used_character_definition':u,'chosen_target':target,'choice_category':'observed_convention_adopted_as_explicit_source_specific_choice_not_mandatory_template_rule','native_status':'pending_new_v3_bytes'})
 cev=P/(p['role']+'.cover-evidence.json');write(cev,{'schema_version':'cover-role-source-evidence-1','role':p['role'],'scope':'Exact source-used cover role font/height/bold definitions. Does not copy exemplar company/date/program facts and does not establish native output quality.','template_source':p['source_template'],'reference_source':{'path':refpath,'sha256':reference['sha256']},'roles':observations,'actual_score_percent':None})
 p['version']=3;p['profile_id']=f"reference-quality/{p['role']}/v3";p['targets']['cover_roles']=cover;p['cover_selectors']=selectors;p['cover_observed_evidence']={'path':str(cev),'sha256':h(cev)};p['selectors']['cover']='Only5named cover paragraph font/height/bold targets are editable; existing geometry, table/object/control, paragraph spacing and supplied fact text remain preserved.'
 p['allowed_changes'].append('derived_font_height_bold_on_five_exact_semantic_cover_owner_paragraphs_geometry_and_controls_preserved')
 p['implementation_choices'].append({'category':'implementation_choice','choice':'Adopt exact reference-used cover font/size/bold by customer/program/title/date/supplier role; OS1 uses explicitly adjacent OS2 cover and PM1 retains partial cadence mapping.','rationale':'Whole-document editorial review includes the cover; original BatangChe cover preservation alone did not match adopted reference typography. Geometry remains fixed, and long supplied program/date labels still need current native review.','native_status':'pending_new_v3_bytes'})
 p['iteration_refinement']['previous_profile_version']=2;p['iteration_refinement']['previous_bytes_preserved']='analysis/style-upgrade/profiles/history/v2';p['iteration_refinement']['native_status']='pending_new_v3_bytes'
 write(path,p);entry['sha256']=h(path);entry['status']=p['status'];summary.append({'role':p['role'],'targets':cover})
idx['recorded_at']=datetime.now(timezone.utc).isoformat();idx['scope']='19source-specific candidatev3 profiles including source-backed cover5roles; actual native/editorial scores remain unassigned.';write(P/'index.json',idx)
write(B/'cover-target-summary.json',{'recorded_at':datetime.now(timezone.utc).isoformat(),'profiles':summary,'scope':'Cover target/source evidence only. No actual output review or95% score.'})
print(json.dumps({'profiles':len(summary),'cover_role_targets':sum(len(x['targets']) for x in summary),'actual_scores_assigned':0},ensure_ascii=False,indent=2))
