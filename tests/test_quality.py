"""Fixtures are synthetic; these tests do not assert native application execution."""
import copy
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image
import pymupdf
import pytest

from doc_automation.quality import verify_quality_review


@pytest.fixture
def review_fixture(tmp_path):
    source = tmp_path / 'input.json'
    source.write_text('{"synthetic": true}')
    template = tmp_path / 'template.hwpx'
    artifact = tmp_path / 'draft.hwpx'
    with ZipFile(artifact, 'w') as z:
        z.writestr('mimetype', 'application/hwp+zip')
        z.writestr('Contents/header.xml', '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"><hh:charProperties><hh:charPr id="0"/></hh:charProperties><hh:paraProperties><hh:paraPr id="0"/></hh:paraProperties><hh:styles><hh:style id="0"/></hh:styles></hh:head>')
        z.writestr('Contents/section0.xml', '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p id="1" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:secPr/></hp:run></hp:p></hs:sec>')
        z.writestr('Contents/content.hpf', '<opf:package xmlns:opf="http://www.idpf.org/2007/opf"><opf:manifest><opf:item id="section0" href="section0.xml" media-type="application/xml"/></opf:manifest><opf:spine><opf:itemref idref="section0"/></opf:spine></opf:package>')
    template.write_bytes(artifact.read_bytes())
    pdf = tmp_path / 'native-fixture.pdf'
    with pymupdf.open() as doc:
        doc.new_page().insert_text((70, 70), 'SYNTHETIC EVIDENCE LINK TEST, not a native export')
        doc.save(pdf)
    page = tmp_path / 'page.png'
    Image.new('RGB', (20, 20), 'white').save(page)
    digest = lambda p: sha256(p.read_bytes()).hexdigest()
    record = {
        'schema_version': '1.0',
        'artifact': {'path': artifact.name, 'sha256': digest(artifact), 'input_dataset_sha256': digest(source), 'template_sha256': digest(template)},
        'native_export': {'application': 'Hancom (synthetic fixture claim only)', 'version': 'test', 'build': 'test', 'source_sha256': digest(artifact), 'pdf_path': pdf.name, 'pdf_sha256': digest(pdf), 'page_count': 1, 'compatibility_notices': []},
        'render': {'engine': 'Poppler (synthetic fixture claim only)', 'dpi': 96, 'pages': [{'page': 1, 'path': page.name, 'sha256': digest(page)}]},
        'checks': [{'id': 'fixture', 'passed': True, 'scope': 'bytes only', 'evidence': 'synthetic'}],
        'visual_review': {'reviewer': 'synthetic fixture', 'reviewed_at': '2026-10-24T02:00:00Z', 'pages': [{'page': 1, 'status': 'passed', 'observations': ['Synthetic record, not observed native execution.']}]},
        'status': 'passed', 'limitations': ['Test of records only; no native app or visual review was performed.'],
    }
    target = tmp_path / 'review.json'
    def run(changed=None):
        target.write_text(json.dumps(record if changed is None else changed))
        return verify_quality_review(target, input_path=source, template_path=template)
    return record, artifact, page, run


def test_current_evidence_bytes_and_complete_page_coverage(review_fixture):
    record, artifact, page, run = review_fixture
    result = run()
    assert result['passed'], result['errors']
    assert len(result['files']) == 5


@pytest.mark.parametrize('mutation,code', [('artifact', 'FILE_HASH_MISMATCH'), ('page', 'FILE_HASH_MISMATCH'), ('duplicate_page', 'PAGE_COVERAGE'), ('input_hash', 'FILE_HASH_MISMATCH'), ('pending_page', 'VISUAL_REVIEW_INCOMPLETE')])
def test_stale_or_incomplete_evidence_cannot_inherit_approval(review_fixture, mutation, code):
    record, artifact, page, run = review_fixture
    changed = copy.deepcopy(record)
    if mutation == 'artifact':
        artifact.write_bytes(artifact.read_bytes() + b'changed')
    elif mutation == 'page':
        Image.new('RGB', (20, 20), 'black').save(page)
    elif mutation == 'duplicate_page':
        changed['render']['pages'].append(copy.deepcopy(changed['render']['pages'][0]))
    elif mutation == 'input_hash':
        changed['artifact']['input_dataset_sha256'] = '0' * 64
    elif mutation == 'pending_page':
        changed['visual_review']['pages'][0]['status'] = 'pending'
    result = run(changed)
    assert not result['passed']
    assert code in {e['code'] for e in result['errors']}


@pytest.mark.parametrize('invalid', ['first_section_paragraph', 'empty_control'])
def test_supplied_pass_record_does_not_override_invalid_current_structure(review_fixture, invalid):
    record, artifact, page, run = review_fixture
    with ZipFile(artifact) as z:
        entries = {name: z.read(name) for name in z.namelist()}
    section = entries['Contents/section0.xml'].decode()
    if invalid == 'first_section_paragraph':
        section = section.replace('<hp:p id="1"', '<hp:p id="2" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>notice</hp:t></hp:run></hp:p><hp:p id="1"')
    else:
        section = section.replace('<hp:secPr/>', '<hp:secPr/><hp:ctrl/>')
    entries['Contents/section0.xml'] = section.encode()
    with ZipFile(artifact, 'w') as z:
        for name, payload in entries.items():
            z.writestr(name, payload)
    changed = copy.deepcopy(record)
    digest = sha256(artifact.read_bytes()).hexdigest()
    changed['artifact']['sha256'] = digest
    changed['native_export']['source_sha256'] = digest
    result = run(changed)
    assert not result['passed']
    assert 'HWPX_STRUCTURE' in {e['code'] for e in result['errors']}


def test_nonzip_artifact_returns_a_failure_report(review_fixture):
    record, artifact, page, run = review_fixture
    artifact.write_bytes(b'SYNTHETIC not a ZIP package')
    changed = copy.deepcopy(record)
    digest = sha256(artifact.read_bytes()).hexdigest()
    changed['artifact']['sha256'] = digest
    changed['native_export']['source_sha256'] = digest
    result = run(changed)
    assert not result['passed']
    assert {'HWPX_PACKAGE', 'HWPX_STRUCTURE'} <= {e['code'] for e in result['errors']}
