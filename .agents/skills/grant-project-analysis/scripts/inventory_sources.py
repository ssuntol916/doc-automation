"""Hash and snapshot local project inputs into a fresh private workspace run.

This is intake mechanics only: it does not execute inputs, extract facts,
authenticate documents, or determine business completion.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

SKIP_DIRS = {'.git', '.hg', '.svn', 'node_modules', '.venv', 'venv', '__pycache__', '.pytest_cache'}
PRIVATE_AREAS = {'outputs', 'analysis', 'private', 'verification', 'generated'}
SENSITIVE_SUFFIXES = {'.pem', '.key', '.pfx', '.p12', '.jks', '.keystore'}
DOCUMENTS = {'.hwpx', '.hwp', '.pdf', '.pptx', '.ppt', '.docx', '.xlsx', '.xls', '.csv', '.tsv'}
CODE = {'.py', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.sql', '.sh', '.cs', '.java', '.ipynb'}


def digest(path):
    h = sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def is_link(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def sensitive(path):
    name = path.name.lower()
    return name.startswith('.env') or path.suffix.lower() in SENSITIVE_SUFFIXES or name in {'id_rsa', 'id_ed25519', 'credentials', '.netrc', '.npmrc', '.pypirc'}


def category(path):
    suffix = path.suffix.lower()
    if suffix in DOCUMENTS:
        return 'document'
    if suffix in {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp'}:
        return 'image'
    if suffix in CODE:
        return 'source_or_notebook'
    if suffix in {'.md', '.txt', '.rst', '.json', '.yaml', '.yml', '.toml', '.xml'}:
        return 'text_or_metadata'
    return 'other'


def run(source_root, output, workspace, groups=()):
    source_root, output, workspace = (Path(p).expanduser().resolve() for p in (source_root, output, workspace))
    if not source_root.is_dir():
        raise ValueError('Source root must be an existing directory')
    if output == source_root or output.is_relative_to(source_root) or source_root.is_relative_to(output):
        raise ValueError('Input and output trees must be disjoint')
    if not output.is_relative_to(workspace) or not output.relative_to(workspace).parts or output.relative_to(workspace).parts[0] not in PRIVATE_AREAS:
        raise ValueError('Output must be under an ignored private area of the explicit workspace')
    if output.exists():
        raise ValueError('Use a new run directory; existing evidence is never overwritten')
    if groups:
        roots = sorted([p for p in source_root.iterdir() if p.is_dir() and any(p.name.startswith(prefix) for prefix in groups)])
        if any(not any(p.name.startswith(prefix) for p in roots) for prefix in groups):
            raise ValueError('At least one requested group prefix has no matching directory')
    else:
        roots = [source_root]
    output.mkdir(parents=True)
    entries, skipped = [], []
    for selected in roots:
        if selected.name in SKIP_DIRS:
            skipped.append({'relative_path': selected.relative_to(source_root).as_posix(), 'reason': 'dependency_cache_or_vcs_directory'})
            continue
        if is_link(selected):
            skipped.append({'relative_path': selected.relative_to(source_root).as_posix(), 'reason': 'symlink_or_reparse_point'})
            continue
        for folder, dirs, files in os.walk(selected, followlinks=False):
            folder = Path(folder)
            kept = []
            for name in sorted(dirs):
                child = folder/name
                reason = 'dependency_cache_or_vcs_directory' if name in SKIP_DIRS else ('symlink_or_reparse_point' if is_link(child) else None)
                if reason:
                    skipped.append({'relative_path': child.relative_to(source_root).as_posix(), 'reason': reason})
                else:
                    kept.append(name)
            dirs[:] = kept
            for name in sorted(files):
                path = folder/name
                relative = path.relative_to(source_root).as_posix()
                if is_link(path) or not path.is_file():
                    skipped.append({'relative_path': relative, 'reason': 'symlink_reparse_or_nonregular_file'})
                    continue
                info = path.stat()
                fingerprint = digest(path)
                source_id = 'SRC-' + sha256(relative.encode('utf-8')).hexdigest()[:16]
                record = {'source_id': source_id, 'relative_path': relative, 'source_sha256': fingerprint,
                          'size_bytes': info.st_size, 'file_mtime_utc': datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                          'category': category(path), 'content_review': 'not_reviewed', 'business_attribution': 'unverified',
                          'file_hash_verified': False, 'snapshot_path': None}
                if sensitive(path):
                    record['handling'] = 'sensitive_configuration_deferred_no_copy_or_text_extraction'
                else:
                    target = output/'sources'/Path(relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with path.open('rb') as src, target.open('xb') as dst:
                        for block in iter(lambda: src.read(1024 * 1024), b''):
                            dst.write(block)
                    if digest(target) != fingerprint or digest(path) != fingerprint:
                        raise ValueError('Source changed during snapshot; run is incomplete')
                    record.update(snapshot_path=str(target.resolve()), snapshot_sha256=fingerprint,
                                  file_hash_verified=True, handling='copied_without_execution')
                entries.append(record)
    stable = all(digest(source_root/entry['relative_path']) == entry['source_sha256'] for entry in entries)
    if not stable:
        raise ValueError('A source changed before final inventory verification')
    manifest = {'schema_version': 'grant-project-source-inventory-1', 'created_at': datetime.now(timezone.utc).isoformat(),
                'source_root': str(source_root), 'selected_group_prefixes': list(groups),
                'groups': [{'relative_path': p.relative_to(source_root).as_posix(), 'file_count': sum(e['relative_path'].startswith(p.relative_to(source_root).as_posix()+'/') for e in entries)} for p in roots] if groups else [],
                'sources': entries, 'excluded_subtrees_or_files': skipped,
                'summary': {'files': len(entries), 'bytes': sum(e['size_bytes'] for e in entries),
                            'categories': dict(Counter(e['category'] for e in entries)),
                            'snapshots': sum(e['file_hash_verified'] for e in entries),
                            'deferred_sensitive_files': sum(sensitive(Path(e['relative_path'])) for e in entries)},
                'source_bytes_unchanged_at_end': stable, 'submission_ready': False,
                'tool': {'path': str(Path(__file__).resolve()), 'sha256': digest(Path(__file__))},
                'limits': ['File mtime is filesystem metadata, not execution, approval or report date.',
                           'Hash equality proves matching supplied bytes only; every content/business review starts as unverified.',
                           'Excluded dependency/cache/VCS subtrees are listed, not fully hashed.',
                           'No source code, macro, notebook, service, build or database was executed.']}
    (output/'source-inventory.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--group', action='append', default=[], help='Top-level directory prefix; repeat for selected groups only')
    args = parser.parse_args()
    try:
        result = run(args.source_root, args.output, args.workspace, args.group)
    except (ValueError, OSError) as error:
        parser.exit(1, f'Intake failed: {error}\n')
    print(json.dumps({'inventory': str((args.output/'source-inventory.json').resolve()), **result['summary'], 'source_bytes_unchanged': result['source_bytes_unchanged_at_end']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
