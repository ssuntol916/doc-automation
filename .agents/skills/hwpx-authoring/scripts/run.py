"""Locate the canonical project and run its supported CLI in the uv environment.

Resolve this file before finding parents, so user-level symlinks work. The source
checkout is a declared dependency; no corpus or native Hancom engine is bundled.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REQUIRED = [
    "pyproject.toml", "src/doc_automation/cli.py", "docs/PLAN.md",
    "docs/FORMAT_SOURCES.md", "docs/DATA_MODEL.md", "docs/DATA_EXAMPLES.md",
    "docs/BUSINESS_VALIDATION.md", "docs/OUTPUT_QUALITY.md", "schemas/project.schema.json",
    "schemas/quality-review.schema.json", "resources/stage1/inventory.json",
    "resources/stage1/deliverables-catalog.json", "resources/stage1/forms-catalog.json",
    "resources/stage1/analysis-design-rules.json", "resources/stage1/test-management-requirements.json",
    "resources/stage2/mapping.json", "resources/stage2/analysis-design-patterns.json",
    "resources/stage2/test-transition-patterns.json", "resources/stage2/operations-management-patterns.json",
]
QA_PATHS = [
    "schemas/quality-review.schema.json", "docs/OUTPUT_QUALITY.md",
    "scripts/render_pdfs.py",
    "scripts/audit_native_baselines.py", "src/doc_automation/quality.py",
]


def repository() -> Path:
    override = os.environ.get("DOC_AUTOMATION_PROJECT")
    candidates = [Path(override).expanduser().resolve()] if override else list(Path(__file__).resolve().parents)
    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src/doc_automation/cli.py").is_file():
            return candidate
    raise SystemExit("The doc-automation checkout is unavailable. Keep this skill in its canonical .agents/skills directory or set DOC_AUTOMATION_PROJECT to the full checkout path.")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Usage: run.py locate | path REPO_RELATIVE_PATH ... | resources | qa-paths | analyze ... | validate-project ... | generate ... | verify-output ...")
        return 0
    repo = repository()
    if args == ["locate"]:
        print(repo)
        return 0
    if args[0] == "path":
        if len(args) == 1:
            raise SystemExit("path requires at least one repository-relative resource path")
        for value in args[1:]:
            path = (repo / value).resolve()
            if Path(value).is_absolute() or not path.is_relative_to(repo):
                raise SystemExit("Use a repository-relative path within the located checkout")
            if not path.exists():
                raise SystemExit("Required project resource is unavailable: " + str(path))
            print(path)
        return 0
    if args[0] in ("resources", "qa-paths"):
        paths = REQUIRED if args[0] == "resources" else QA_PATHS
        print(json.dumps({"repository": str(repo), "resources": [{"path": value, "absolute_path": str(repo / value), "exists": (repo / value).exists()} for value in paths], "uv_available": shutil.which("uv") is not None, "native_engine_bundled": False}, ensure_ascii=False, indent=2))
        return 0
    if args[0] not in ("analyze", "validate-project", "generate", "verify-output", "--help", "-h"):
        raise SystemExit("Unsupported helper command; use --help for the current project CLI or run.py with no arguments for resource helpers")
    if shutil.which("uv") is None:
        raise SystemExit("uv is required to run the project's declared dependency environment")
    # Keep caller cwd: relative input/output arguments are relative to that caller.
    return subprocess.run(["uv", "run", "--project", str(repo), "doc-automation", *args], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
