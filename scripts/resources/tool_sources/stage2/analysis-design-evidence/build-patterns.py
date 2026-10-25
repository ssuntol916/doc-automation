"""Build a local source-linked comparison from private supplied observations.

Business values, exemplar findings and prior visual-review statements are private
inputs. This tool does not award a new native, factual or submission verdict.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path


def main():
    if os.environ.get('DOC_AUTOMATION_REBUILD_STAGED') != '1':
        raise SystemExit('Run through scripts/resources/run.py in a new ignored workspace.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observations', type=Path, required=True,
                        help='Private JSON with patterns and template_instruction_assessments')
    args = parser.parse_args()
    root = Path(__file__).parent
    private_path = args.observations.expanduser().resolve()
    supplied = json.loads(private_path.read_text())
    if not isinstance(supplied, dict) or set(supplied) != {'patterns', 'template_instruction_assessments'}:
        parser.error('Expected patterns and template_instruction_assessments; no historical defaults are bundled')
    documents = {p.stem: json.loads(p.read_text()) for p in root.glob('SF-*.json')}
    if not documents:
        raise ValueError('Provide fresh extracted source profiles in this private workspace')
    def evidence(selector):
        if not isinstance(selector, dict) or not {'role', 'section'} <= selector.keys():
            raise ValueError('An explicit source role/section selector is required')
        document = documents[selector['role']]
        source = Path(document['path'])
        if sha256(source.read_bytes()).hexdigest() != document['sha256']:
            raise ValueError('Read-only source no longer matches its extracted profile')
        section = document['sections'][selector['section']]
        obj = section
        if 'table' in selector:
            obj = section['tables'][selector['table'] - 1]
            if 'row' in selector:
                matches = [c for r in obj['rows'] for c in r['cells']
                           if int(c['address']['rowAddr']) == selector['row'] and int(c['address']['colAddr']) == selector['col']]
                if len(matches) != 1: raise ValueError('Ambiguous source cell')
                obj = matches[0]
        if 'paragraph' in selector:
            obj = next(p for p in section['paragraphs'] if p['xpath'] == selector['paragraph'])
        return {'source_file': str(source), 'sha256': document['sha256'], 'xml': section['xml'],
                'xpath': obj.get('xpath', '/hs:sec'), 'text_excerpt': obj.get('text', '')[:350]}
    output = {'schema_version': 1, 'scope': 'Private supplied observations linked to exact read-only source owners',
              'input_observations_sha256': sha256(private_path.read_bytes()).hexdigest(),
              'native_visual_review_performed_by_this_tool': False, 'actual_quality_score_percent': None}
    for key in ['patterns', 'template_instruction_assessments']:
        if not isinstance(supplied[key], list): parser.error(key + ' must be a list')
        output[key] = []
        for record in supplied[key]:
            if not isinstance(record, dict) or not isinstance(record.get('selectors'), list):
                parser.error('Every private observation must include selectors')
            output[key].append({**{k:v for k,v in record.items() if k != 'selectors'},
                                'reference_evidence': [evidence(s) for s in record['selectors']]})
    (root.parent / 'analysis-design-patterns.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print('Wrote source-linked private observations; no native/visual judgment was generated.')


if __name__ == '__main__':
    main()
