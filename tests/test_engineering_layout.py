"""Regressions for exact native engineering-frame and continued-record defects."""
from corpus_sources import pinned_source_path
from hashlib import sha256
import json
from pathlib import Path

import pytest
from lxml import etree as ET

from doc_automation.compose import TemplateDocument, HANCOM_MAC_12_30_PNG_METADATA
from doc_automation.hwpx import own_text, NS
from doc_automation.renderers import generate_project, NOTICE

ROOT=Path(__file__).resolve().parents[1]
ROLES=['SF-AD1','SF-AD3','SF-TD1','SF-TD2','SF-TD4']


@pytest.fixture(scope='module')
def candidates(tmp_path_factory):
    source=ROOT/'examples/style-upgrade/illustrated-extended-v2/illustrated.project.json'
    result=generate_project(source,tmp_path_factory.mktemp('engineering-layout'),roles=ROLES,
        style_profile='reference-v1',raster_metadata_profile=HANCOM_MAC_12_30_PNG_METADATA)
    return json.loads(source.read_text()),{d['role']:d for d in result['documents']}


def definitions(doc):
    header=doc.xml('Contents/header.xml')
    return ({p.get('id'):p for p in header.findall('.//hh:charPr',NS)},
            {p.get('id'):p for p in header.findall('.//hh:paraPr',NS)})


@pytest.mark.corpus
@pytest.mark.parametrize('role',ROLES)
def test_engineering_profile_identity_sizes_and_source_contract_stay_declared(candidates,role):
    _,outputs=candidates;output=outputs[role]
    p=ROOT/'resources/style-upgrade/profiles'/(role+'.json');profile=json.loads(p.read_text())
    assert profile['version']==(9 if role=='SF-TD4' else 11 if role=='SF-TD2' else 10) and profile['assessment']['score_percent'] is None
    assert profile['cover_program_wordbreak_refinement']['previous_profile_version']==profile['version']-1
    assert profile['targets']['cover_program_paragraph']=={'break_non_latin':'BREAK_WORD'}
    guard=profile['cover_program_paragraph_source'];selector=profile['cover_selectors']['program']['template']
    assert (guard['source_sha256'],guard['xml'],guard['xpath'])==(output['source_template']['sha256'],selector['xml'],selector['xpath'])
    original=TemplateDocument(output['source_template']['path'])
    owner,=original.xml(guard['xml']).xpath(guard['xpath'],namespaces=NS)
    definition,=original.xml('Contents/header.xml').xpath('.//hh:paraPr[@id=$i]',namespaces=NS,i=owner.get('paraPrIDRef'))
    assert own_text(owner)==selector['text_before_generation_verbatim']
    assert sha256(ET.tostring(owner,method='c14n',exclusive=True)).hexdigest()==guard['paragraph_c14n_sha256']
    assert sha256(ET.tostring(definition,method='c14n',exclusive=True)).hexdigest()==guard['paragraph_definition_c14n_sha256']
    assert guard['break_non_latin']==definition.find('hh:breakSetting',NS).get('breakNonLatinWord')==('BREAK_WORD'if role=='SF-AD1'else'KEEP_WORD')
    actual=output['editorial_profile']['cover_program_paragraph']
    assert actual['changed_paragraphs']==int(role!='SF-AD1') and actual['already_matching_owner_skipped_without_derivation']is(role=='SF-AD1')
    assert actual['current_xpath']==guard['xpath'] and actual['actual_break_non_latin']=='BREAK_WORD' and actual['all_other_paragraph_properties_preserved']
    wrapping=profile['cover_program_wordbreak_evidence'];assert sha256((ROOT/wrapping['path']).read_bytes()).hexdigest()==wrapping['sha256']
    assert profile['source_template']['sha256']==output['source_template']['sha256']
    assert profile['targets']['body_height_hwp']==(1000 if role=='SF-AD3' else 1100)
    evidence=profile['engineering_layout_evidence'];assert sha256((ROOT/evidence['path']).read_bytes()).hexdigest()==evidence['sha256']
    idx=json.loads((ROOT/'resources/style-upgrade/profiles/index.json').read_text())
    assert next(r for r in idx['profiles'] if r['role']==role)['sha256']==sha256(p.read_bytes()).hexdigest()


@pytest.mark.corpus
@pytest.mark.parametrize('role',['SF-AD1','SF-TD1','SF-TD2'])
def test_engineering_frame_has_regular_owned_body_and_preserves_section_anchor(candidates,role):
    _,outputs=candidates;output=outputs[role];doc=TemplateDocument(output['path'])
    section=len(doc.sections)-1;table=doc.tables(section)[0]
    paragraphs=doc.cell(table,0,0).findall('hp:subList/hp:p',NS)
    assert own_text(paragraphs[0]).startswith(NOTICE)
    assert not any(own_text(p).startswith(NOTICE) for p in doc.root(section))
    assert table.get('pageBreak')=='CELL' and table.find('hp:pos',NS).get('treatAsChar')=='0'
    assert doc.root(section)[0].find('.//hp:secPr',NS) is not None
    chars,_=definitions(doc)
    headings={r['text'] for r in output['editorial_profile']['selector']['heading_selections']}
    captions={r['text'] for r in output['editorial_profile']['selector']['caption_selections']}
    for paragraph in paragraphs:
        value=own_text(paragraph)
        if not value or value in captions:continue
        values=[chars[r.get('charPrIDRef')].find('hh:bold',NS) is not None for r in paragraph.findall('hp:run',NS)]
        assert all(values) if value in headings else not any(values)


@pytest.mark.corpus
def test_feature_table_and_every_continued_detail_have_identifiers(candidates):
    data,outputs=candidates;output=outputs['SF-AD3'];doc=TemplateDocument(output['path']);table=doc.tables(len(doc.sections)-1)[0]
    assert table.get('pageBreak')=='TABLE'
    assert table.find('hp:pos',NS).get('treatAsChar')=='0'
    assert table.find('hp:pos',NS).get('vertOffset')=='2672'
    assert int(doc.cell(table,1,0).find('hp:cellSz',NS).get('width'))==7000
    assert int(doc.cell(table,1,2).find('hp:cellSz',NS).get('width'))==10500
    _,paras=definitions(doc)
    for index,feature in enumerate(data['features'],1):
        assert feature['id'] in ''.join(doc.cell(table,index,2).itertext())
        remarks=''.join(doc.cell(table,index,5).itertext())
        assert f'[F{index}]' in remarks and all(rid not in remarks for rid in feature.get('requirement_ids',[]))
    roots=list(doc.root(len(doc.sections)-1))
    title=next(i for i,p in enumerate(roots) if own_text(p)=='2. 기능별 근거·검토상태')
    detail=[]
    for p in roots[title+1:]:
        if own_text(p).startswith('부록.'):break
        if own_text(p):detail.append(p)
    assert detail and all(own_text(p).startswith('[F') for p in detail)
    for p in detail:
        if any(own_text(p).startswith(f'[F{i}] {f["id"]} ') for i,f in enumerate(data['features'],1)):
            assert paras[p.get('paraPrIDRef')].find('hh:breakSetting',NS).get('keepWithNext')=='1'
    mapping=json.loads(Path(output['meaning_map']['path']).read_text())
    records=[e for e in mapping['entities'] if e['input_pointer'].startswith('/features/')]
    for record in records:
        for field in record['fields']:
            assert field['owners']


@pytest.mark.corpus
def test_installation_plan_keeps_I_key_on_all_continued_paragraphs(candidates):
    data,outputs=candidates;output=outputs['SF-TD2'];doc=TemplateDocument(output['path'])
    table=doc.tables(len(doc.sections)-1)[0];paragraphs=doc.cell(table,0,0).findall('hp:subList/hp:p',NS)
    values=[own_text(p) for p in paragraphs];start=values.index('5. 장비 도입 및 설치 계획');end=values.index('6. 클라우드 서비스 이용 내용')
    assert all(value.startswith('[I') for value in values[start+1:end])
    for index,item in enumerate(data['deployment_items'],1):
        assert any(value.startswith(f'[I{index}] {item["id"]} ') for value in values)
        owners=[p for p in paragraphs if own_text(p).startswith(f'[I{index}] ')]
        _,definitions_by_id=definitions(doc)
        keeps=[definitions_by_id[p.get('paraPrIDRef')].find('hh:breakSetting',NS).get('keepWithNext') for p in owners]
        assert keeps[0]=='1' and keeps[1]=='0'
        assert all(value=='0' for value in keeps[1:]), 'The finite identity/first-plan link must not keep a whole deployment record together'
    mapping=json.loads(Path(output['meaning_map']['path']).read_text())
    for record in mapping['entities']:
        if not record['input_pointer'].startswith('/deployment_items/'):continue
        for field in record['fields']:
            if field['representation']=='role_main_specification':
                assert field['owners'] and all(p['rendered_text'].startswith('[I') for p in field['owners'])


@pytest.mark.corpus
def test_architecture_functions_are_an_input_list_without_invented_execution_arrows(candidates):
    data,outputs=candidates;doc=TemplateDocument(outputs['SF-TD2']['path'])
    paragraphs=doc.cell(doc.tables(len(doc.sections)-1)[0],0,0).findall('hp:subList/hp:p',NS)
    values=[own_text(p) for p in paragraphs]
    start=values.index('3. 소프트웨어 구성도');end=values.index('4. 네트워크 구성도')
    software=values[start+1:end]
    for program in data['programs']:
        expected='기능 목록(번호는 입력 배열 위치, 실행순서 미확정): '+'; '.join(f'{index}. {name}' for index,name in enumerate(program['functions'],1))
        assert expected in software
        assert '처리: '+' → '.join(program['functions']) not in software


@pytest.mark.corpus
def test_program_function_list_does_not_claim_a_directed_flow(candidates):
    data,outputs=candidates;doc=TemplateDocument(outputs['SF-TD4']['path'])
    cards=doc.tables(len(doc.sections)-1)
    assert len(cards)==len(data['programs'])
    for program,card in zip(data['programs'],cards):
        text='\n'.join(own_text(p) for p in doc.cell(card,2,1).findall('hp:subList/hp:p',NS))
        assert '기능 명세 항목(목록 배치는 실행 순서를 뜻하지 않음)' in text
        assert '\n'.join(f'{index}. {value}' for index,value in enumerate(program['functions'],1)) in text
        assert '설계상 데이터 흐름' not in text


@pytest.mark.corpus
def test_program_notice_joins_first_description_without_losing_PAGE_anchor(candidates):
    _,outputs=candidates;output=outputs['SF-TD4'];doc=TemplateDocument(output['path']);section=len(doc.sections)-1
    cards=doc.tables(section);first=cards[0];paragraphs=doc.cell(first,1,1).findall('hp:subList/hp:p',NS)
    assert own_text(paragraphs[0]).startswith(NOTICE)
    assert not any(own_text(p).startswith(NOTICE) for p in doc.root(section))
    anchor=next(a for a in first.iterancestors() if a.tag=='{'+NS['hp']+'}p')
    # The same source card becomes the first paragraph of its dedicated body
    # section, so the redundant per-paragraph page break is cleared by split.
    assert anchor is doc.root(section)[0] and anchor.get('pageBreak')=='0'
    assert anchor.find('./hp:run/hp:ctrl/hp:newNum[@numType="PAGE"]',NS).get('num')=='1'


@pytest.mark.corpus
@pytest.mark.parametrize('role',['SF-AD1','SF-TD1','SF-TD2','SF-TD4'])
def test_actual_engineering_captions_keep_keys_and_explicit_PNG_metadata_profile(candidates,role):
    _,outputs=candidates;output=outputs[role];doc=TemplateDocument(output['path']);_,paras=definitions(doc)
    for caption in output['editorial_profile']['selector']['caption_selections']:
        found=next(p for name in doc.sections for p in doc.xml(name).iter('{'+NS['hp']+'}p') if own_text(p)==caption['text'])
        definition=paras[found.get('paraPrIDRef')]
        assert definition.find('hh:align',NS).get('horizontal')=='LEFT'
        assert definition.find('hh:breakSetting',NS).get('breakLatinWord')=='KEEP_WORD'
    assert all(binding['raster_metadata_profile']==HANCOM_MAC_12_30_PNG_METADATA for binding in output['image_bindings'])


@pytest.mark.corpus
def test_unbounded_frame_contract_cannot_be_applied_to_feature_grid(candidates):
    from doc_automation.renderers import _testing_frame_flow
    _,outputs=candidates;doc=TemplateDocument(outputs['SF-AD3']['path'])
    with pytest.raises(ValueError,match='one-cell source shape'):
        _testing_frame_flow(doc,doc.tables(len(doc.sections)-1)[0],{'editorial':True})


@pytest.mark.corpus
@pytest.mark.parametrize('failure',['source_sha','source_xpath','source_own_text'])
def test_AD3_title_flow_fails_closed_for_wrong_original_owner(failure):
    from doc_automation.renderers import _render_ad3, _all_tables, _paragraph
    profile=json.loads((ROOT/'resources/style-upgrade/profiles/SF-AD3.json').read_text())
    doc=TemplateDocument(pinned_source_path(profile));tables=_all_tables(doc);owner=_paragraph(tables[-1])
    if failure=='source_sha':doc.source_sha256='0'*64
    elif failure=='source_xpath':doc._source_paragraph_locations[owner]=('Contents/section0.xml','/hs:sec/hp:p[999]')
    else:doc._source_paragraph_text[owner]='unexpected source text'
    with pytest.raises(ValueError,match='AD3 title/table source owner'):
        _render_ad3(doc,{'features':[]},tables,{'editorial':True,'warnings':[]})


@pytest.mark.corpus
def test_AD3_same_looking_business_value_does_not_become_source_heading(tmp_path):
    from copy import deepcopy
    source=ROOT/'examples/style-upgrade/illustrated-extended-v2/illustrated.project.json';data=json.loads(source.read_text())
    for collection in ('sources','attachments'):
        for item in data[collection]:
            if item.get('path') and not Path(item['path']).is_absolute():item['path']=str((source.parent/item['path']).resolve())
    data['features'][0]['major_category']='1. 000시스템'
    path=tmp_path/'input.json';path.write_text(json.dumps(data,ensure_ascii=False))
    output=generate_project(path,tmp_path/'out',roles=['SF-AD3'],style_profile='reference-v1')['documents'][0]
    doc=TemplateDocument(output['path']);table=doc.tables(len(doc.sections)-1)[0]
    assert own_text(doc.cell(table,1,0).find('hp:subList/hp:p',NS))=='1. 000시스템'
    owner=next(a for a in table.iterancestors() if a.tag=='{'+NS['hp']+'}p')
    assert own_text(owner)=='1. 시스템별 기능 대비(합성 설계 가정)'
    assert doc.root(len(doc.sections)-1)[0].find('./hp:run/hp:secPr',NS) is not None
