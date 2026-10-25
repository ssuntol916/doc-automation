#!/usr/bin/env python3
"""Reproduce the nineteen synthetic v2.0 HWPX drafts."""

from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from doc_automation.renderers import generate_project


if __name__ == "__main__":
    result = generate_project(REPOSITORY / "examples/demo-suite.project.json", REPOSITORY / "generated/demo-suite")
    print(f"Generated {len(result['documents'])} synthetic HWPX drafts; native review pending.")
