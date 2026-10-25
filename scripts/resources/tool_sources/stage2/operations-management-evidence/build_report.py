"""Render a local report from private observations without bundled business data.

The supplied content is attributed to its input. This tool neither invents
source observations nor replays historical native/visual verdicts as current.
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
                        help='Private JSON containing title and sections[{heading, paragraphs}]')
    args = parser.parse_args()
    path = args.observations.expanduser().resolve()
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {'title', 'sections'} or not isinstance(data['title'], str) or not isinstance(data['sections'], list):
        parser.error('Expected exactly title and sections; there are no bundled historical observations')
    lines = ['# ' + data['title'], '', 'Private supplied observations; not a new execution, approval or native-review result.', '']
    for section in data['sections']:
        if (not isinstance(section, dict) or set(section) != {'heading', 'paragraphs'}
                or not isinstance(section['heading'], str) or not isinstance(section['paragraphs'], list)
                or any(not isinstance(p, str) for p in section['paragraphs'])):
            parser.error('Each section requires a heading and a list of supplied paragraph strings')
        lines.extend(['## ' + section['heading'], '', *[p + '\n' for p in section['paragraphs']]])
    out = Path(__file__).parent
    (out / 'report.md').write_text('\n'.join(lines) + '\n')
    (out / 'report-input.json').write_text(json.dumps({'input_sha256': sha256(path.read_bytes()).hexdigest(),
        'scope': 'Rendered supplied private observations only', 'actual_native_or_visual_review': False,
        'actual_quality_score_percent': None}, ensure_ascii=False, indent=2) + '\n')
    print('Wrote a local supplied-observation report; no historic business data is bundled.')


if __name__ == '__main__':
    main()
