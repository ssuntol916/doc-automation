from __future__ import annotations

import argparse
import json
from pathlib import Path

from .hwpx import analyze_folder


def main():
    parser = argparse.ArgumentParser(description="Evidence-based HWPX automation")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="Extract complete package/XML profiles without modifying source files")
    analyze.add_argument("source", type=Path)
    analyze.add_argument("output", type=Path)
    analyze.add_argument("--kind", choices=["template", "reference"], required=True)
    validate = commands.add_parser("validate-project", help="Validate shared facts, references and evidence; schema success alone is not submission approval")
    validate.add_argument("input", type=Path)
    validate.add_argument("--report", type=Path, required=True)
    validate.add_argument("--skip-file-hashes", action="store_true", help="Check the model without verifying local source bytes; the report retains this limitation")
    validate.add_argument("--require-submission-ready", action="store_true")
    generate = commands.add_parser("generate", help="Generate requested HWPX drafts from the supported, fingerprinted templates")
    generate.add_argument("input", type=Path)
    generate.add_argument("output", type=Path)
    generate.add_argument("--role", action="append", dest="roles", help="Canonical role such as SF-AD2; repeat for multiple roles")
    generate.add_argument("--template-root", type=Path)
    generate.add_argument("--style-profile", choices=["reference-v1"], help="Apply the source-backed editorial profile; native output review remains required")
    generate.add_argument("--companion-verification", type=Path, help="Explicitly select a matching synthetic DB workbook verification report")
    generate.add_argument("--raster-metadata-profile", choices=["hancom-mac-12.30.0-png"], help="Explicit PNG metadata target observed in Hancom Mac12.30.0; preserve original bytes and displayed geometry; native review remains required")
    quality = commands.add_parser("verify-output", help="Verify supplied native-output evidence against current HWPX, PDF and page-image bytes")
    quality.add_argument("review", type=Path)
    quality.add_argument("--input", type=Path, required=True)
    quality.add_argument("--template", type=Path, required=True)
    quality.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "analyze":
        inventory = analyze_folder(args.source, args.output, args.kind)
        print(f"Analyzed {len(inventory['documents'])} documents; unsupported inputs: {len(inventory['unsupported_inputs'])}")
        if inventory["unsupported_inputs"]:
            raise SystemExit(1)
    elif args.command == "validate-project":
        from .business import validate_project
        from .hwpx import write_json
        data = json.loads(args.input.read_text(encoding="utf-8"))
        report = validate_project(data, verify_files=not args.skip_file_hashes, base_dir=args.input.resolve().parent)
        write_json(args.report, report)
        print(json.dumps({"errors": len(report["errors"]), "warnings": len(report["warnings"]), "submission_ready": report["submission_ready"], "report": str(args.report)}, ensure_ascii=False))
        if report["errors"]:
            raise SystemExit(1)
        if args.require_submission_ready and not report["submission_ready"]:
            raise SystemExit(2)
    elif args.command == "generate":
        from .renderers import generate_project
        try:
            result = generate_project(args.input, args.output, roles=args.roles, template_root=args.template_root, style_profile=args.style_profile, companion_verification=args.companion_verification, raster_metadata_profile=args.raster_metadata_profile)
        except (ValueError, OSError) as exc:
            parser.exit(1, f"Generation failed: {exc}\n")
        print(json.dumps({"documents": len(result["documents"]), "roles": [d["role"] for d in result["documents"]], "manifest": str(args.output.resolve() / "manifest.json"), "native_review_status": result["native_review_status"], "submission_ready": result["submission_ready"]}, ensure_ascii=False))
    elif args.command == "verify-output":
        from .quality import verify_quality_review
        from .hwpx import write_json
        result = verify_quality_review(args.review, input_path=args.input, template_path=args.template)
        write_json(args.report, result)
        print(json.dumps({"passed": result["passed"], "errors": len(result["errors"]), "report": str(args.report)}, ensure_ascii=False))
        if not result["passed"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
