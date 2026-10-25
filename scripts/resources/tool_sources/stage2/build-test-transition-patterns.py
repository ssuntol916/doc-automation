"""Join private, explicitly supplied observations with fresh extracted sources.

No historic customer values, serials, findings or visual-review verdicts are
bundled. Running this report builder does not perform a native/visual review.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re


def main():
    if os.environ.get('DOC_AUTOMATION_REBUILD_STAGED') != '1':
        raise SystemExit('Run through scripts/resources/run.py in a new ignored workspace.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observations', type=Path, required=True,
                        help='Private JSON with issues, patterns and per-role compliance observations')
    args = parser.parse_args()
    out = Path(__file__).parent
    observation_path = args.observations.expanduser().resolve()
    supplied = json.loads(observation_path.read_text())
    required = {'issues', 'patterns', 'compliance'}
    if not isinstance(supplied, dict) or not required <= supplied.keys():
        parser.error('Private observations require issues, patterns and compliance; no historic defaults are available')
    codes = ['cd1', 'ti1', 'ti2', 'ti3', 'ti4']
    profiles = {c: json.loads((out / f'profiles/reference-sf-{c}.json').read_text()) for c in codes}
    inventory = {x['code']: x for x in json.loads((out / 'test-transition-evidence.json').read_text())}
    documents, references = [], {}
    for code, profile in profiles.items():
        source = Path(profile['source_path'])
        if sha256(source.read_bytes()).hexdigest() != profile['sha256']:
            raise ValueError('Read-only original source changed: ' + profile['id'])
        inv = inventory['SF-' + code.upper()]
        refs = {p['evidence'] for s in profile['sections'] for p in s['paragraphs']}
        refs |= {t['evidence'] for s in profile['sections'] for t in s['tables']}
        refs |= {c['evidence'] for s in profile['sections'] for t in s['tables'] for c in t['cells']}
        refs |= {p['ref'] for p in inv['picture_instances']}
        references[profile['id']] = refs
        doc = {'id': profile['id'], 'code': 'SF-' + code.upper(),
               'source': str(source), 'sha256': profile['sha256'],
               'statistics': profile['statistics'], 'object_counts': inv['object_counts'],
               'image_role_counts': dict(Counter(p['role'] for p in inv['picture_instances'])),
               'compliance': supplied['compliance'].get(code, []), 'tests': []}
        if code in ('cd1', 'ti1', 'ti4'):
            for table in profile['sections'][2]['tables'][:-1]:
                cells = {(int(c['address']['rowAddr']), int(c['address']['colAddr'])): c for c in table['cells']}
                row_indices = range(1 if code == 'cd1' else 3, int(table['attributes']['rowCnt']))
                cols = (2, 3, 4, 5) if code == 'cd1' else (0, 2, 3, 5)
                for row in row_indices:
                    owner = cells[(row, 0)] if code == 'cd1' else cells[(0, 1)]
                    doc['tests'].append({'test_id': re.sub(r'\s+', '', owner['text']),
                        'name': cells[(row, 1 if code == 'cd1' else 0)]['text'],
                        'row': row, 'table': table['evidence'],
                        **{key: cells[(row, col)]['evidence'] for key, col in zip(
                            ['scenario_ref', 'data_ref', 'expected_ref', 'result_ref'], cols)},
                        'result_text': cells[(row, cols[3])]['text']})
        documents.append(doc)
    errors = []
    def validate(value):
        if isinstance(value, dict):
            if 'document' in value and 'ref' in value and value['ref'] not in references.get(value['document'], set()):
                errors.append({'document': value['document'], 'ref': value['ref']})
            for item in value.values(): validate(item)
        elif isinstance(value, list):
            for item in value: validate(item)
    result = {'schema_version': 1, 'scope': 'Private source/observation join only; no new visual, execution or submission finding',
              'observation_source_sha256': sha256(observation_path.read_bytes()).hexdigest(),
              'documents': documents, 'patterns': supplied['patterns'], 'issues': supplied['issues'],
              'native_visual_review_performed_by_this_tool': False, 'actual_quality_score_percent': None}
    validate(result)
    result['validation'] = {'curated_reference_errors': errors, 'source_SHA_verified': True}
    if errors:
        raise ValueError('Private observations reference unavailable source owners')
    (out / 'test-transition-patterns.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('Wrote a local private-observation report; no native/visual verdict was generated.')


if __name__ == '__main__':
    main()
