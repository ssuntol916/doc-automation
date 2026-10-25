import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")
from pathlib import Path
from xml.etree import ElementTree as E
import zipfile,json,hashlib,collections
ROOT=Path(__file__).resolve().parent
checks=[]
for f in sorted(ROOT.glob('SF-*.json')):
 d=json.loads(f.read_text());rootprofile=json.loads((ROOT.parent/'profiles'/('reference-'+d['code'].lower()+'.json')).read_text())
 checks.append({'code':d['code'],'check':'source_hash_unchanged','pass':hashlib.sha256(Path(d['path']).read_bytes()).hexdigest()==d['sha256']})
 checks.append({'code':d['code'],'check':'counts_match_independent_common_profile','pass':sum(len(s['paragraphs']) for s in d['sections'])==rootprofile['statistics']['paragraph_count'] and sum(len(s['tables']) for s in d['sections'])==rootprofile['statistics']['table_count']})
 with zipfile.ZipFile(d['path']) as z:
  checks.append({'code':d['code'],'check':'zip_crc','pass':z.testzip() is None})
 for sec in d['sections']:
  for t in sec['tables']:
   rc=int(t['attributes']['rowCnt']);cc=int(t['attributes']['colCnt']);grid=collections.Counter();errors=[]
   for r in t['rows']:
    for cell in r['cells']:
     a=cell['address'];sp=cell['span'];row,col=int(a['rowAddr']),int(a['colAddr']);rs,cs=int(sp['rowSpan']),int(sp['colSpan'])
     if not(0<=row<rc and 0<=col<cc and row+rs<=rc and col+cs<=cc and rs>0 and cs>0):errors.append(cell['xpath'])
     for rr in range(row,row+rs):
      for c in range(col,col+cs):grid[rr,c]+=1
   missing=[(r,c) for r in range(rc) for c in range(cc) if grid[r,c]!=1]
   checks.append({'code':d['code'],'check':'table_grid','xml':sec['xml'],'table':t['index'],'rows':rc,'cols':cc,'pass':not errors and not missing,'invalid_cells':errors,'missing_or_overlap':missing})
images=json.loads((ROOT/'images/manifest.json').read_text())
for im in images:
 d=json.loads((ROOT/(im['code']+'.json')).read_text())
 with zipfile.ZipFile(d['path']) as z:actual=hashlib.sha256(z.read(im['zip_path'])).hexdigest()
 checks.append({'code':im['code'],'check':'extracted_picture_original_bytes','binary_id':im['binary_id'],'xml':im['section'],'xpath':im['picture_xpath'],'pass':actual==im['sha256']==hashlib.sha256(Path(im['file']).read_bytes()).hexdigest()})
patterns=json.loads((ROOT.parent/'analysis-design-patterns.json').read_text());rules=json.loads((ROOT.parents[1]/'stage1/analysis-design-rules.json').read_text())['rules']
checks.append({'check':'all_stage1_instruction_paragraphs_assessed_once','pass':collections.Counter(x['rule_id'] for x in rules)==collections.Counter(x['rule_id'] for x in patterns['template_instruction_assessments'])})
checks.append({'check':'all_eight_roles_have_observation_recommendation_hold','pass':len(patterns['role_mapping'])==8 and all({p['classification'] for p in patterns['patterns'] if p['document_role']==m['document_role']}=={'expert_observation','generation_recommendation','hold'} for m in patterns['role_mapping'])})
native=json.loads((ROOT/'native-review.json').read_text())
checks.append({'check':'native_review_scope_all_16_documents_179_pages','pass':native['scope']['documents']==16 and native['scope']['template_pages']==23 and native['scope']['reference_pages']==156 and native['scope']['contact_sheets_viewed']==37})
checks.append({'check':'native_review_pdf_hashes_unchanged','pass':all(Path(r['pdf']).exists() and hashlib.sha256(Path(r['pdf']).read_bytes()).hexdigest()==r['pdf_sha256'] for r in native['records'])})
checks.append({'check':'native_review_contact_and_focused_artifacts_exist','pass':all(Path(c['path']).exists() for r in native['records'] for c in r['contact_sheets_viewed']) and all(Path(r['viewed_image']).exists() for r in native['focused_reviews'])})
result={'pass':all(c['pass'] for c in checks),'check_count':len(checks),'checks':checks,'scope':'Source preservation, independent extraction counts, table topology, original image bytes, and analysis coverage. No native PDF page layout claim.'}
(ROOT/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({'pass':result['pass'],'checks':len(checks),'failures':[c for c in checks if not c['pass']]},ensure_ascii=False))
