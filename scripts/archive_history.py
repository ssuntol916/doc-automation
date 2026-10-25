#!/usr/bin/env python3
"""Archive project history with per-file verification and reversible restoration.

Only explicitly listed analysis/, verification/ and generated/ regular files
can be removed. All archives are verified before any original is removed.
This utility grants no document-quality or native-execution acceptance.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tempfile
import warnings


ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"analysis", "verification", "generated"}
SCHEMA = "history-archive-manifest-1"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative(value, *, prefix=False):
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise ValueError("Invalid relative path")
    if prefix and value == "":
        return ""
    value = value.removesuffix("/") if prefix else value
    p = PurePosixPath(value)
    if p.is_absolute() or not p.parts or any(x in {"", ".", ".."} for x in value.split("/")) or str(p) != value:
        raise ValueError("Path must be canonical and relative: " + value)
    return value


def safe_path(root, name, *, top=None):
    name = relative(name)
    parts = PurePosixPath(name).parts
    if top is not None and parts[0] not in top:
        raise ValueError("Path is outside permitted trees: " + name)
    if any(x in {"_templates", "_references"} for x in parts):
        raise ValueError("Read-only source tree is protected: " + name)
    p = root
    for part in parts:
        p = p / part
        if p.is_symlink():
            raise ValueError("Symlink paths are not accepted: " + name)
    if not p.resolve().is_relative_to(root):
        raise ValueError("Path escapes project: " + name)
    return p


def archive_path(root, value):
    p = Path(value)
    name = str(p.relative_to(root)) if p.is_absolute() else p.as_posix()
    result = safe_path(root, name, top={"archives"})
    if len(PurePosixPath(name).parts) < 2:
        raise ValueError("Use a named directory inside archives/")
    return result


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        try:
            os.fsync(fd)
        except OSError as error:
            if error.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
                raise
            warnings.warn("Directory fsync is unsupported on this filesystem: " + str(path), RuntimeWarning)
    finally:
        os.close(fd)


def write_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def check_retained(records, plan):
    declarations = {}
    for field in ("keep_files", "keep_subtrees"):
        values = plan.get(field, [])
        if not isinstance(values, list):
            raise ValueError(field + " must be a list")
        names = [x.get("path") if isinstance(x, dict) else x for x in values]
        declarations[field] = {relative(x) for x in names}
    conflicts = [x["path"] for x in records if x["path"] in declarations["keep_files"]
                 or any(x["path"] == tree or x["path"].startswith(tree + "/")
                        for tree in declarations["keep_subtrees"])]
    if conflicts:
        raise ValueError("Archive selection intersects retained paths: " + ", ".join(conflicts[:10]))


def validate_records(records, root):
    seen = set()
    for record in records:
        name = relative(record["path"])
        if name in seen:
            raise ValueError("Duplicate manifest path: " + name)
        seen.add(name)
        safe_path(root, name, top=ALLOWED)
        if not re.fullmatch(r"[a-f0-9]{64}", record["sha256"]):
            raise ValueError("Invalid SHA-256: " + name)
        if type(record["bytes"]) is not int or record["bytes"] < 0:
            raise ValueError("Invalid byte count: " + name)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", record["group"]):
            raise ValueError("Invalid group name")
        if "mode" in record and (type(record["mode"]) is not int or record["mode"] < 0 or record["mode"] > 0o777):
            raise ValueError("Special permission bits are not supported")
        if "mtime_ns" in record and type(record["mtime_ns"]) is not int:
            raise ValueError("Invalid modification timestamp")
    return seen


def check_sources(records, root):
    for record in records:
        p = safe_path(root, record["path"], top=ALLOWED)
        if not p.is_file() or not stat.S_ISREG(p.stat().st_mode):
            raise ValueError("Source is not a regular file: " + record["path"])
        if p.stat().st_size != record["bytes"] or digest(p) != record["sha256"]:
            raise ValueError("Source bytes changed: " + record["path"])


def load_manifest(directory, root):
    directory = archive_path(root, directory)
    manifest_path = safe_path(root, (directory / "manifest.json").relative_to(root).as_posix(), top={"archives"})
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported archive manifest")
    validate_records(manifest["files"], root)
    groups = {r["group"] for r in manifest["files"]}
    if groups != set(manifest["archives"]):
        raise ValueError("Archive group inventory mismatch")
    for group, info in manifest["archives"].items():
        if info["path"] != group + ".tar.gz":
            raise ValueError("Noncanonical archive filename")
        safe_path(root, (directory / info["path"]).relative_to(root).as_posix(), top={"archives"})
    return directory, manifest


def verify_archive(directory, *, root=None):
    root = Path(root or ROOT).resolve()
    directory, manifest = load_manifest(directory, root)
    grouped = defaultdict(dict)
    for record in manifest["files"]:
        grouped[record["group"]][record["path"]] = record
    total = 0
    for group, expected in grouped.items():
        info = manifest["archives"][group]
        archive = directory / info["path"]
        if archive.stat().st_size != info["bytes"] or digest(archive) != info["sha256"]:
            raise ValueError("Compressed archive bytes changed: " + info["path"])
        found = set()
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle:
                name = relative(member.name)
                if not member.isfile() or name not in expected or name in found:
                    raise ValueError("Unexpected, duplicate or nonregular archive member: " + name)
                record = expected[name]
                stream = bundle.extractfile(member)
                if (stream is None or member.size != record["bytes"] or member.mode != record["mode"]
                        or abs(member.mtime * 1e9 - record["mtime_ns"]) > 1000):
                    raise ValueError("Archive member metadata differs: " + name)
                with stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if actual != record["sha256"]:
                    raise ValueError("Archive member bytes differ: " + name)
                found.add(name)
                total += member.size
        if found != set(expected):
            raise ValueError("Missing archive members: " + group)
    return {"status": "verified", "files": len(manifest["files"]), "original_bytes": total,
            "archive_bytes": sum(x["bytes"] for x in manifest["archives"].values())}


def apply_plan(plan_path, directory, *, root=None):
    root = Path(root or ROOT).resolve()
    plan_path = Path(plan_path)
    plan = json.loads(plan_path.read_text())
    if plan.get("schema_version") != "history-retention-plan-1" or Path(plan["root"]).resolve() != root:
        raise ValueError("Plan schema/project mismatch")
    records = [dict(x) for x in plan["files"]]
    if not records:
        raise ValueError("Empty archive plan")
    validate_records(records, root)
    check_retained(records, plan)
    check_sources(records, root)
    directory = archive_path(root, directory)
    if directory.exists():
        raise ValueError("Refusing existing archive directory")
    directory.mkdir(parents=True)
    sync_directory(directory.parent)
    sync_directory(root)
    groups = defaultdict(list)
    for record in records:
        s = safe_path(root, record["path"], top=ALLOWED).stat()
        record.update(mode=stat.S_IMODE(s.st_mode), mtime_ns=s.st_mtime_ns)
        groups[record["group"]].append(record)
    archives = {}
    for group, items in sorted(groups.items()):
        dest = directory / (group + ".tar.gz")
        with tarfile.open(dest, "w:gz", compresslevel=6) as bundle:
            for record in items:
                p = safe_path(root, record["path"], top=ALLOWED)
                bundle.add(p, arcname=record["path"], recursive=False)
        with dest.open("rb") as stream:
            os.fsync(stream.fileno())
        archives[group] = {"path": dest.name, "sha256": digest(dest), "bytes": dest.stat().st_size}
    manifest = {"schema_version": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
                "source_root_reference": str(root), "plan_sha256": digest(plan_path),
                "status": "packed_originals_present", "files": records, "archives": archives}
    write_json(directory / "manifest.json", manifest)
    result = verify_archive(directory, root=root)
    # The complete inventory is checked again before the first removal.
    check_sources(records, root)
    manifest["status"] = "verified_removal_pending"
    write_json(directory / "manifest.json", manifest)
    parents = set()
    for record in records:
        p = safe_path(root, record["path"], top=ALLOWED)
        p.unlink()
        parents.update(parent for parent in p.parents if parent != root and parent.is_relative_to(root))
    for parent in sorted(parents, key=lambda x: len(x.parts), reverse=True):
        if parent == root / parent.relative_to(root).parts[0]:
            continue
        try:
            parent.rmdir()
        except OSError:
            pass
    manifest["status"] = "archived_originals_removed"
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(directory / "manifest.json", manifest)
    return {**result, "status": manifest["status"], "archive_dir": str(directory)}


def select_records(manifest, prefix):
    prefix = relative(prefix, prefix=True)
    return [x for x in manifest["files"] if not prefix or x["path"] == prefix or x["path"].startswith(prefix + "/")]


def restore_archive(directory, prefix="", *, root=None):
    root = Path(root or ROOT).resolve()
    verify_archive(directory, root=root)
    directory, manifest = load_manifest(directory, root)
    selected = select_records(manifest, prefix)
    if not selected:
        raise ValueError("No archived path matches prefix")
    missing = {}
    skipped = 0
    for record in selected:
        dest = safe_path(root, record["path"], top=ALLOWED)
        if dest.exists():
            if not dest.is_file() or digest(dest) != record["sha256"]:
                raise ValueError("Refusing to overwrite different file: " + record["path"])
            skipped += 1
        else:
            missing[record["path"]] = record
    restored = 0
    for group in {x["group"] for x in missing.values()}:
        with tarfile.open(directory / manifest["archives"][group]["path"], "r:gz") as bundle:
            for member in bundle:
                if member.name not in missing:
                    continue
                record = missing[member.name]
                dest = safe_path(root, member.name, top=ALLOWED)
                dest.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix=".restore-", dir=dest.parent)
                try:
                    with os.fdopen(fd, "wb") as output, bundle.extractfile(member) as source:
                        while block := source.read(1024 * 1024):
                            output.write(block)
                    if digest(temporary) != record["sha256"]:
                        raise ValueError("Restoration hash mismatch")
                    # A concurrent existing file must not be overwritten.
                    safe_path(root, member.name, top=ALLOWED)
                    os.chmod(temporary, record["mode"])
                    os.utime(temporary, ns=(record["mtime_ns"], record["mtime_ns"]))
                    os.link(temporary, dest)
                    restored += 1
                finally:
                    Path(temporary).unlink(missing_ok=True)
    return {"status": "restored", "restored": restored, "already_present": skipped, "prefix": prefix}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("plan", type=Path)
    apply.add_argument("--archive-dir", required=True)
    for command in ("verify", "list", "restore"):
        sub = commands.add_parser(command)
        sub.add_argument("directory")
        if command != "verify":
            sub.add_argument("--prefix", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "apply":
            result = apply_plan(args.plan, args.archive_dir)
        elif args.command == "verify":
            result = verify_archive(args.directory)
        elif args.command == "restore":
            result = restore_archive(args.directory, args.prefix)
        else:
            _, manifest = load_manifest(args.directory, ROOT)
            result = {"paths": [x["path"] for x in select_records(manifest, args.prefix)]}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, tarfile.TarError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
