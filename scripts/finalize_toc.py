#!/usr/bin/env python3
"""Finalize a HWPX TOC from a caller-confirmed native PDF, or measure a second pass."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from doc_automation.toc import TocError, check_toc_convergence, finalize_toc, measure_toc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_hwpx", type=Path)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--output", type=Path, help="Different HWPX output; required except with --measure-only")
    parser.add_argument("--native-source-sha256", required=True)
    parser.add_argument("--native-pdf-sha256", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--previous-manifest", type=Path)
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.measure_only and args.output is None:
        parser.error("--output is required unless --measure-only is specified")
    protected = {path.resolve() for path in (args.input_hwpx, args.pdf, args.dataset, args.output, args.previous_manifest) if path}
    report_path = args.manifest.expanduser().resolve()
    if report_path in protected or any(parent.name in {"_templates", "_references"} for parent in report_path.parents):
        parser.error("--manifest must not overwrite an input/output artifact or the read-only source trees")
    try:
        if args.measure_only:
            report = measure_toc(args.input_hwpx, args.pdf, args.dataset, args.role, args.native_source_sha256,
                                 native_pdf_sha256=args.native_pdf_sha256)
            if args.previous_manifest:
                report["convergence"] = check_toc_convergence(args.previous_manifest, report)
        else:
            report = finalize_toc(args.input_hwpx, args.pdf, args.dataset, args.role, args.output,
                                  args.native_source_sha256, native_pdf_sha256=args.native_pdf_sha256,
                                  previous_manifest=args.previous_manifest)
    except TocError as exc:
        report = exc.report
    except (OSError, ValueError, KeyError) as exc:
        report = {"status": "failed", "code": "INPUT_OR_COMPOSITION_ERROR", "message": str(exc)}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "manifest": str(report_path),
                      "entries": len(report.get("entries", [])), "native_status": report.get("native_status"),
                      "converged": report.get("convergence", {}).get("converged") if report.get("convergence") else None},
                     ensure_ascii=False))
    return 2 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
