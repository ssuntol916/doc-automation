"""Stage a preserved analysis tool in a separate workspace before running it.

Historical local observations are optional inputs, not bundled output evidence.
This runner never executes tools in the canonical source or old analysis folder.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent / "tool_sources"
MARKER = ".doc-automation-resource-workspace.json"


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def workspace(path):
    target = Path(path).expanduser().resolve()
    if target == ROOT or (target.is_relative_to(ROOT) and target.relative_to(ROOT).parts[0] != "outputs"):
        raise ValueError("Use a new directory outside the checkout or below outputs/; canonical and historical analysis directories are protected")
    marker = target / MARKER
    if target.exists() and any(target.iterdir()) and not marker.is_file():
        raise ValueError("Workspace is not empty and has no resource-workspace marker; choose a new directory")
    target.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_text(json.dumps({"schema_version": "resource-rebuild-workspace-1",
            "source_checkout": str(ROOT), "purpose": "Separate execution workspace, not a native/visual review"}, indent=2) + "\n")
    return target


def stage(target):
    """Copy only source resources and tool code; never replace work already done."""
    seeded = []
    for source in TOOLS.rglob("*.py"):
        dest = target / "analysis" / source.relative_to(TOOLS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.read_bytes() != source.read_bytes():
            raise ValueError("Staged tool differs from source; preserve that workspace and choose a new one: " + str(dest))
        if not dest.exists():
            shutil.copyfile(source, dest)
    for directory in ("resources/stage1", "resources/stage2", "resources/style-upgrade", "examples", "schemas"):
        source_root = ROOT / directory
        dest_root = target / (directory.replace("resources/", "analysis/", 1) if directory.startswith("resources/") else directory)
        for source in source_root.rglob("*"):
            if not source.is_file() or "__pycache__" in source.parts:
                continue
            dest = dest_root / source.relative_to(source_root)
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            if directory.startswith("resources/") and dest.suffix == ".json":
                seeded.append(dest)
    # Canonical source-resource links are relocated to this workspace. Original
    # external source SHA and old native evidence locations are left untouched.
    def relocate(value):
        if isinstance(value, str) and value.startswith("resources/"):
            return str(target / value.replace("resources/", "analysis/", 1))
        if isinstance(value, list):
            return [relocate(item) for item in value]
        if isinstance(value, dict):
            return {key: relocate(item) for key, item in value.items()}
        return value
    for path in seeded:
        value = json.loads(path.read_text())
        revised = relocate(value)
        if revised != value:
            path.write_text(json.dumps(revised, ensure_ascii=False, indent=2) + "\n")
    def bind(value):
        if isinstance(value, list):
            for item in value:
                bind(item)
        elif isinstance(value, dict):
            for item in value.values():
                bind(item)
            for key in list(value):
                hashkey = "sha256" if key == "path" else key[:-5] + "_sha256" if key.endswith("_path") else None
                path = Path(value[key]) if isinstance(value[key], str) else None
                if hashkey in value and path is not None and path.is_relative_to(target / "analysis") and path.is_file():
                    value[hashkey] = digest(path)
    for _ in range(6):
        changed = False
        for path in seeded:
            value = json.loads(path.read_text())
            bind(value)
            revised = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
            if revised != path.read_bytes():
                path.write_bytes(revised)
                changed = True
        if not changed:
            break
    else:
        raise ValueError("Cyclic staged source-resource hash binding")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, help="New local output directory or a workspace previously created by this runner")
    parser.add_argument("--templates", type=Path, default=Path(os.environ.get("DOC_AUTOMATION_TEMPLATE_ROOT", Path.home() / "projects/gov-grants/_templates")))
    parser.add_argument("--references", type=Path, default=Path(os.environ.get("DOC_AUTOMATION_REFERENCE_ROOT", Path.home() / "projects/gov-grants/_references")))
    parser.add_argument("--prepare-only", action="store_true", help="Prepare a workspace without executing the selected analysis tool")
    parser.add_argument("task", nargs="?", help="list or a relative tool name, for example stage1/extract_root_forms.py")
    parser.add_argument("tool_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.task in (None, "list"):
        print("\n".join(str(p.relative_to(TOOLS)) for p in sorted(TOOLS.rglob("*.py"))))
        return 0
    if args.workspace is None:
        parser.error("--workspace is required; historical analysis output is never overwritten implicitly")
    source = (TOOLS / args.task).resolve()
    if not source.is_relative_to(TOOLS) or not source.is_file() or source.suffix != ".py":
        parser.error("Select a preserved tool from the list")
    try:
        target = workspace(args.workspace)
        stage(target)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    script = target / "analysis" / source.relative_to(TOOLS)
    if args.prepare_only:
        print(json.dumps({"workspace": str(target), "tool": str(script), "status": "prepared_only",
            "required_local_inputs": "Some tools additionally require fresh analyze output, original read-only sources or historical native observations placed in this separate workspace. Missing evidence never means a pass."}, ensure_ascii=False, indent=2))
        return 0
    env = dict(os.environ, DOC_AUTOMATION_REBUILD_STAGED="1",
               DOC_AUTOMATION_TEMPLATES=str(args.templates.expanduser().resolve()),
               DOC_AUTOMATION_REFERENCES=str(args.references.expanduser().resolve()))
    tool_args = args.tool_args[1:] if args.tool_args[:1] == ["--"] else args.tool_args
    result = subprocess.run([sys.executable, str(script), *tool_args], cwd=target, env=env, check=False)
    if result.returncode:
        print("Resource tool did not complete. Review its error and provide the required local source/extraction/native evidence in the separate workspace; no canonical resource or old output was replaced.", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
