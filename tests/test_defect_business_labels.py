"""Business labels must not rewrite literal JSON or other-domain records."""
import json
from pathlib import Path
import pytest
from doc_automation.compose import TemplateDocument
from doc_automation.hwpx import own_text
from doc_automation.narrative import SourceNotes, describe_fields, source_note_scope
from doc_automation.renderers import generate_project

ROOT = Path(__file__).resolve().parents[1]
LABELS = {'test_case_id': '연결 시험 ID', 'cause': '발생 원인', 'detected_date': '발견일자',
          'resolution': '조치 내용', 'resolved_date': '조치 완료일자(입력)', 'resolution_status': '조치 상태(입력)'}


def test_record_labels_leave_literal_json_and_other_domain_fields_unchanged():
    notes = SourceNotes()
    value = {'cause': None, 'resolution_status': 'unverified', 'data': {
        'cause': None, 'resolution_status': 'unverified',
        'source_refs': [{'source_id': 'literal-only', 'locator': '/not/provenance'}]}}
    original = json.dumps(value, ensure_ascii=False, sort_keys=True)
    with source_note_scope(notes):
        text = describe_fields(value, typed=True, field_labels=LABELS, code_fields={'resolution_status'})
        other = describe_fields({'resolution_status': 'open', 'resolution': '검토용 원문'}, typed=True)
    assert '발생 원인: 미확인(null)' in text and '조치 상태(입력): 미확인' in text
    assert '키: cause (문자열)' in text and '키: resolution_status (문자열)' in text
    assert '값: unverified (문자열)' in text and '키: source_refs (문자열)' in text
    assert notes.records == [] and notes.code_mappings == {'unverified': '미확인'}
    assert 'resolution_status: open (문자열)' in other and 'resolution: 검토용 원문 (문자열)' in other
    assert json.dumps(value, ensure_ascii=False, sort_keys=True) == original


@pytest.mark.corpus
def test_cd1_defect_business_terms_keep_input_types_sources_and_review_state(tmp_path):
    source = ROOT / 'examples/style-upgrade/illustrated-extended-v2/illustrated.project.json'
    data = json.loads(source.read_text())
    output = generate_project(source, tmp_path / 'defect-terms', roles=['SF-CD1'], style_profile='reference-v1')['documents'][0]
    doc = TemplateDocument(output['path'])
    paragraphs = [own_text(p) for member in doc.sections for p in doc.xml(member).iter('{http://www.hancom.co.kr/hwpml/2011/paragraph}p')]
    details = '\n'.join(text for text in paragraphs if text.startswith('[D1] '))
    for key, label in LABELS.items():
        assert label + ':' in details and f'[D1] {key}:' not in details
    assert '조치 상태(입력): 미확인' in details and '발생 원인: 미확인(null)' in details
    assert '입력만으로 조치 완료를 판정하지 않는다' in details
    meaning = json.loads(Path(output['meaning_map']['path']).read_text())
    record = next(item for item in meaning['entities'] if item['input_pointer'] == '/defects/0')
    for field in record['fields']:
        key = field['input_pointer'].rsplit('/', 1)[1]
        assert field['input_value'] == data['defects'][0][key]
        assert field['input_type'] == type(data['defects'][0][key]).__name__ and field['owners']
    notes = json.loads(Path(output['source_notes']['path']).read_text())
    assert notes['code_mappings']['unverified'] == '미확인'
