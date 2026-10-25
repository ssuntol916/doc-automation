"""Check publishable files and reachable Git objects without printing private values."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import unicodedata

PATTERNS = {
    "personal_home_path": re.compile(r"/(?:Users|home)/[^/\s\"'<>]+/"),
    "unmasked_phone": re.compile(r"\b0\d{1,2}[- ]\d{3,4}[- ]\d{4}\b"),
}


def normalized(value):
    return unicodedata.normalize("NFC", value).casefold()


def inspect_text(text, location, forbidden=()):
    findings = []
    for line, value in enumerate(text.splitlines(), 1):
        for kind, pattern in PATTERNS.items():
            if pattern.search(value):
                findings.append({"location": location, "line": line, "kind": kind})
        folded = normalized(value)
        for number, private in enumerate(forbidden):
            if private and normalized(private) in folded:
                findings.append({"location": location, "line": line,
                                 "kind": "private_value", "private_rule": number})
    return findings


def audit(root, *, forbidden=(), history=False, staged=False):
    root = Path(root).resolve()
    command = ["git", "-C", str(root)]
    raw = subprocess.check_output(command + ["ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    paths = sorted(set(p for p in raw.decode().split("\0") if p))
    findings, binary, text_count = [], [], 0
    for name in paths:
        path = root / name
        findings.extend(inspect_text(name, "filename:" + name, forbidden))
        try:
            value = path.read_text(encoding="utf-8")
        except UnicodeError:
            binary.append({"path": name, "sha256": sha256(path.read_bytes()).hexdigest()})
            continue
        text_count += 1
        findings.extend(inspect_text(value, name, forbidden))
    staged_objects = []
    if staged:
        entries = subprocess.check_output(command + ["ls-files", "--stage", "-z"]).decode().split("\0")
        for entry in entries:
            if not entry:
                continue
            metadata, name = entry.split("\t", 1)
            _, oid, stage = metadata.split()
            if stage != "0":
                findings.append({"location": name, "kind": "unmerged_index"})
                continue
            staged_objects.append(oid)
            data = subprocess.check_output(command + ["cat-file", "blob", oid])
            try:
                value = data.decode("utf-8")
            except UnicodeError:
                continue
            findings.extend(inspect_text(value, "index:" + name, forbidden))
    objects = []
    if history:
        listed = subprocess.check_output(command + ["rev-list", "--objects", "--all"]).decode().splitlines()
        for entry in listed:
            oid, _, name = entry.partition(" ")
            kind = subprocess.check_output(command + ["cat-file", "-t", oid]).decode().strip()
            if kind not in {"blob", "commit", "tag"}:
                continue
            data = subprocess.check_output(command + ["cat-file", kind, oid])
            objects.append({"object": oid, "type": kind})
            try:
                value = data.decode("utf-8")
            except UnicodeError:
                continue
            findings.extend(inspect_text(value, "git:" + oid + ":" + name, forbidden))
    return {"passed": not findings, "candidate_files": len(paths), "text_files": text_count,
            "binary_files": binary, "reachable_objects_scanned": len(objects),
            "staged_objects_scanned": len(staged_objects),
            "private_rule_count": len(forbidden), "findings": findings,
            "limits": "Known private-value and pattern scan; binary contents need a separate visual/provenance review. No private values are printed."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--forbidden-values", type=Path, help="Local private JSON list, never included in the publication tree")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--staged", action="store_true", help="Also inspect actual indexed blob bytes")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    forbidden = json.loads(args.forbidden_values.read_text()) if args.forbidden_values else []
    if not isinstance(forbidden, list) or any(not isinstance(v, str) for v in forbidden):
        parser.error("Private rules must be a JSON list of strings")
    if args.forbidden_values and args.forbidden_values.resolve().is_relative_to(args.root.resolve()):
        parser.error("Private rule file must remain outside the publication repository")
    result = audit(args.root, forbidden=forbidden, history=args.history, staged=args.staged)
    if args.report:
        if args.report.resolve().is_relative_to(args.root.resolve()) and "outputs" not in args.report.resolve().relative_to(args.root.resolve()).parts:
            parser.error("In-repository report must be under ignored outputs/")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    summary = {k: result[k] for k in ["passed", "candidate_files", "text_files", "reachable_objects_scanned", "private_rule_count"]}
    summary.update(findings_count=len(result["findings"]), first_findings=result["findings"][:20])
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
