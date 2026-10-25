"""Inspect prospective Git files without initializing or staging this project."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = {'.agents', '.githooks', 'docs', 'examples', 'resources', 'schemas', 'scripts', 'src', 'tests'}
SOURCE_FILES = {'.gitignore', '.gitattributes', 'AGENTS.md', 'README.md', 'pyproject.toml', 'uv.lock', 'LICENSE'}
RESULT_DIRS = {'analysis', 'verification', 'outputs', 'generated', 'archives'}
RESULT_SUFFIXES = {'.hwpx', '.hwp', '.pdf', '.xlsx', '.log', '.zip', '.gz'}


def inventory(root=ROOT):
    root = Path(root).resolve()
    # An isolated metadata directory makes the project's actual ignore rules
    # authoritative while leaving its Git state and index completely untouched.
    with tempfile.TemporaryDirectory(prefix='doc-auto-git-scope-') as temporary:
        metadata = str(Path(temporary) / 'metadata.git')
        subprocess.run(['git', 'init', '--bare', '--quiet', metadata], check=True)
        prefix = ['git', '--git-dir=' + metadata, '--work-tree=' + str(root)]
        candidates = subprocess.check_output(prefix + ['ls-files', '--others', '--exclude-standard', '-z'])
        ignored = subprocess.check_output(prefix + ['ls-files', '--others', '--ignored', '--exclude-standard', '-z'])
    paths = sorted(p.decode() for p in candidates.split(b'\0') if p)
    ignored_paths = [p.decode() for p in ignored.split(b'\0') if p]
    violations = []
    files = []
    for value in paths:
        path = Path(value)
        if path.parts[0] not in SOURCE_DIRS and value not in SOURCE_FILES:
            violations.append({'path': value, 'reason': 'Not classified as maintained source'})
        if path.parts[0] in RESULT_DIRS:
            violations.append({'path': value, 'reason': 'Local work product entered candidate files'})
        if path.suffix.lower() in RESULT_SUFFIXES and not value.startswith('tests/fixtures/'):
            violations.append({'path': value, 'reason': 'Document, log or archive outside an explicit test fixture'})
        actual = root / path
        files.append({'path': value, 'bytes': actual.lstat().st_size})
    return {'recorded_at': datetime.now(timezone.utc).isoformat(), 'repository': str(root),
            'method': 'Git ignore evaluation with temporary external metadata; no project init, staging or commit',
            'candidate_files': files, 'candidate_count': len(files), 'candidate_bytes': sum(x['bytes'] for x in files),
            'ignored_count': len(ignored_paths),
            'excluded_local_work_files': sum(Path(p).parts[0] in RESULT_DIRS for p in ignored_paths),
            'violations': violations, 'passed': not violations}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, help='Optional new report in the ignored outputs directory')
    args = parser.parse_args()
    record = inventory()
    if args.report:
        report = args.report.expanduser().resolve()
        if not report.is_relative_to(ROOT / 'outputs'):
            parser.error('Report must be below the local outputs/ work directory')
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open('x', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: record[key] for key in ('candidate_count', 'candidate_bytes', 'excluded_local_work_files', 'violations', 'passed')}, ensure_ascii=False))
    return 0 if record['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
