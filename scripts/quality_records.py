"""Task-local evidence binder; performs no native export or visual review.

Build records only from explicit evidence supplied in a spec. Missing evidence,
stale bytes and contradictory pass judgments are rejected rather than inferred.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import tempfile

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from doc_automation.compose import validate_package
from doc_automation.quality import verify_quality_review

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "verification/generated"
STATUSES = {"pending", "passed", "failed"}
ACTIONS = ("open", "save_as", "close", "reopen", "export_pdf")
STANDARD_WORKFLOW = "native_save_close_reopen_export"
REPAIR_WORKFLOW = "native_save_repair_reopen"
REPAIR_ACTIONS = ("open", "save_as", "close_saved", "package_postprocess", "open_final", "close_final", "reopen", "export_pdf")
NO_TOC = {"SF-AD3", "SF-PM1", "SF-PM2", "SF-PM3", "SF-PM4"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def nonempty(value, label):
    require(isinstance(value, str) and value.strip(), f"{label}: explicit nonempty string required")
    return value


def strings(value, label, *, nonempty_list=False):
    require(isinstance(value, list), f"{label}: explicit list required")
    require(not nonempty_list or value, f"{label}: observations cannot be empty")
    for item in value:
        nonempty(item, label)
    return value


def status(value, label):
    require(value in STATUSES, f"{label}: use pending/passed/failed explicitly")
    return value


def timestamp(value, label):
    nonempty(value, label)
    require(FormatChecker().conforms(value, "date-time"), f"{label}: RFC3339 timestamp required")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def resolve(path, base):
    result = Path(nonempty(path, "path"))
    return (base / result).resolve() if not result.is_absolute() else result.resolve()


def evidence_text(ref):
    return json.dumps(ref, ensure_ascii=False, sort_keys=True)


def restoration_module():
    path = ROOT / "scripts/restore_native_font_fallbacks.py"
    spec = importlib.util.spec_from_file_location("quality_font_restoration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_native_events(native, workflow, files, same_ref, native_base, *, repair=None, repair_ref=None):
    """Bind the explicitly selected workflow; never infer missing UI events."""
    require(workflow in {STANDARD_WORKFLOW, REPAIR_WORKFLOW}, "unsupported native workflow")
    require(native.get("workflow", STANDARD_WORKFLOW) == workflow, "spec/native workflow differs")
    events = native["events"]
    actions = REPAIR_ACTIONS if workflow == REPAIR_WORKFLOW else ACTIONS
    require(isinstance(events, list), "native events must be an explicit list")
    require(len(events) == len(actions) and [e["action"] for e in events] == list(actions),
            "native events must explicitly record " + ",".join(actions) + " in order")
    event_times, native_states = [], []
    for event in events:
        native_states.append(status(event["status"], f"native {event['action']}"))
        nonempty(event["observation"], f"native {event['action']} observation")
        event_times.append(timestamp(event["observed_at"], f"native {event['action']} time"))
    require(event_times == sorted(event_times), "native action times are inconsistent")
    if workflow == REPAIR_WORKFLOW:
        require(repair is not None and repair_ref is not None, "repair workflow requires exact postprocess evidence")
        same_ref(native["native_saved"], files["native_saved"], native_base, "native observation intermediate Save As")
        same_ref(native["package_postprocess"], repair_ref, native_base, "native observation package postprocess")
        require(len({files[n]["path"] for n in ("native_before", "native_saved", "native_after")}) == 3,
                "source, native Save As intermediate and restored final must be distinct files")
        require(files["native_saved"]["sha256"] != files["native_after"]["sha256"],
                "repair workflow must distinguish native Save As bytes from repaired final bytes")
        targets = ("native_before", "native_saved", "native_saved", "native_after", "native_after", "native_after", "native_after", "pdf")
        for event, target in zip(events, targets):
            same_ref(event["artifact"], files[target], native_base, f"native {event['action']} artifact")
        same_ref(events[3]["report"], repair_ref, native_base, "package_postprocess event report")
        require(native_states[3] == "passed", "postprocess event must reflect the verified completed repair")
        repair_time = timestamp(repair["recorded_at"], "postprocess recorded_at")
        require(event_times[2] <= repair_time <= event_times[3] <= event_times[4],
                "repair must occur after closing the native-saved intermediate and before opening final bytes")
    else:
        require("native_saved" not in native and "package_postprocess" not in native,
                "postprocessed native evidence requires the explicit repair workflow")
    return native_states, event_times


def build_record(spec_path):
    """Return an in-memory record and exact-byte inventory, without writing it."""
    spec_path = Path(spec_path).resolve()
    spec = json.loads(spec_path.read_text())
    require(spec.get("schema_version") == "v4-quality-spec-1", "unsupported spec version")
    role = spec["role"]
    require(re.fullmatch(r"SF-(?:AD[1-3]|TD[1-5]|CD1|TI[1-4]|OS[1-2]|PM[1-4])", role), "unknown canonical role")
    record_id = spec["record_id"]
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", record_id), "unsafe record_id")
    inventory = {str(spec_path): digest(spec_path)}

    def file_ref(ref, base, label):
        require(isinstance(ref, dict), f"{label}: path/sha256 object required")
        path = resolve(ref["path"], base)
        expected = ref["sha256"]
        require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected), f"{label}: invalid SHA256")
        require(digest(path) == expected, f"{label}: current file SHA256 differs: {path}")
        require(str(path) not in inventory or inventory[str(path)] == expected, f"{label}: contradictory SHA256")
        inventory[str(path)] = expected
        return {"path": str(path), "sha256": expected}

    def same_ref(actual, wanted, base, label):
        got = file_ref(actual, base, label)
        require(got == wanted, f"{label}: path/SHA256 does not bind the declared file")

    def json_ref(name):
        source = spec[name]
        bound = file_ref(source, spec_path.parent, name)
        value = json.loads(Path(bound["path"]).read_text())
        pointer = source.get("pointer", "")
        require(isinstance(pointer, str) and (not pointer or pointer.startswith("/")), f"{name}: invalid JSON pointer")
        if pointer:
            for token in pointer[1:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                value = value[int(token)] if isinstance(value, list) else value[token]
        require(isinstance(value, dict), f"{name}: selected evidence must be an object")
        bound["pointer"] = pointer
        return value, Path(bound["path"]).parent, bound

    files = {name: file_ref(spec[name], spec_path.parent, name) for name in
             ("input", "template", "native_before", "native_after", "pdf")}
    before, after, pdf = (files[k] for k in ("native_before", "native_after", "pdf"))
    workflow = spec.get("workflow", STANDARD_WORKFLOW)
    require(workflow in {STANDARD_WORKFLOW, REPAIR_WORKFLOW}, "unsupported native workflow")
    repair = repair_ref = None
    if workflow == REPAIR_WORKFLOW:
        files["native_saved"] = file_ref(spec["native_saved"], spec_path.parent, "native_saved")
        repair, repair_base, repair_ref = json_ref("package_postprocess")
        require(repair_ref.pop("pointer") == "", "repair evidence must reference the entire report")
        # Recalculate the limited XML edit and every ZIP member hash, instead
        # of accepting a report's pass flag or declared preservation claims.
        verified = restoration_module().verify_report(repair_ref["path"])
        require(repair == verified, "selected repair evidence differs from the verified report")
        for key, target in (("reference_source", before), ("native_saved", files["native_saved"]), ("output", after)):
            same_ref(repair[key], target, repair_base, f"repair {key}")
        file_ref(repair["tool"], repair_base, "repair tool")
    else:
        require("native_saved" not in spec and "package_postprocess" not in spec,
                "postprocess specs require the explicit repair workflow")

    native, native_base, native_ref = json_ref("native_observation")
    require(native["role"] == role, "native observation role differs")
    for name in ("native_before", "native_after", "pdf"):
        same_ref(native[name], files[name], native_base, f"native observation {name}")
    app = native["application"]
    for key in ("name", "version", "build"):
        nonempty(app[key], f"actual application {key}")
    nonempty(native["observer"], "native observer")
    native_time = timestamp(native["observed_at"], "native observed_at")
    notices = strings(native["compatibility_notices"], "compatibility_notices")
    native_states, event_times = validate_native_events(native, workflow, files, same_ref, native_base,
                                                       repair=repair, repair_ref=repair_ref)
    require(native_time >= event_times[-1], "native action times are inconsistent")

    render, render_base, render_ref = json_ref("render_manifest")
    # This is the existing scripts/render_pdfs.py document contract. It records
    # image paths but no image hashes; reviewed image hashes below supply those.
    same_ref({"path": render["pdf"], "sha256": render["sha256"]}, pdf, render_base, "render PDF")
    page_count = render["pages"]
    require(type(page_count) is int and page_count > 0, "render page count must be positive")
    nonempty(render["renderer"], "render renderer")
    require(type(render["dpi"]) is int and render["dpi"] >= 72, "render dpi must be >=72")
    require(len(render["page_images"]) == page_count, "render page-image count differs")
    image_paths = [resolve(p, render_base) for p in render["page_images"]]
    require(len(set(image_paths)) == page_count, "render repeats image files")

    audit, audit_base, audit_ref = json_ref("roundtrip")
    require(audit.get("tool") == "independent_generated_roundtrip_audit", "unexpected roundtrip audit tool")
    same_ref(audit["before"], before, audit_base, "roundtrip before")
    same_ref(audit["after"], after, audit_base, "roundtrip after")
    tool_path = ROOT / "scripts/audit_generated_roundtrip.py"
    file_ref({"path": str(tool_path), "sha256": audit["tool_source_sha256"]}, ROOT, "roundtrip tool")
    require(type(audit["passed"]) is bool, "roundtrip explicit passed boolean required")
    require(isinstance(audit["checks"], list) and audit["checks"], "roundtrip checks missing")
    require(all(type(c["passed"]) is bool for c in audit["checks"]), "roundtrip checks need booleans")
    require(isinstance(audit["errors"], list), "roundtrip errors list missing")
    if audit["passed"]:
        require(all(c["passed"] for c in audit["checks"]) and not audit["errors"], "roundtrip pass contradicts failures")

    toc, toc_base, toc_ref = json_ref("toc_final")
    require(toc["role"] == role, "TOC role differs")
    same_ref({"path": toc["input_hwpx"], "sha256": toc["input_sha256"]}, after, toc_base, "TOC input")
    same_ref({"path": toc["active_hwpx"], "sha256": toc["active_sha256"]}, after, toc_base, "TOC active output")
    same_ref({"path": toc["native_pdf"], "sha256": toc["native_pdf_sha256"]}, pdf, toc_base, "TOC PDF")
    same_ref(toc["input_dataset"], files["input"], toc_base, "TOC dataset")
    require(toc["native_source_sha256"] == after["sha256"], "TOC native source differs")
    require(toc["status"] in {"unchanged", "not_applicable"}, "TOC is not a final unchanged/not_applicable measurement")
    require(toc["output_written"] is False, "TOC generated new bytes awaiting native reexport")
    require((toc["status"] == "not_applicable") == (role in NO_TOC), "TOC applicability disagrees with canonical role")
    if toc["status"] == "unchanged":
        require(toc["native_status"] == "current_native_measurement" and toc["pdf_page_count"] == page_count,
                "TOC is not the current PDF measurement")
        require(isinstance(toc["entries"], list) and toc["entries"], "final TOC entries missing")
    else:
        require(toc["entries"] == [] and toc["native_status"] == "unchanged_not_applicable", "unexpected no-TOC state")

    visual, visual_base, visual_ref = json_ref("visual_review")
    require(visual["role"] == role, "visual role differs")
    same_ref(visual["native_after"], after, visual_base, "visual HWPX")
    same_ref(visual["pdf"], pdf, visual_base, "visual PDF")
    require(visual["page_count"] == page_count, "visual page count differs")
    reviewer = nonempty(visual["reviewer"], "visual reviewer")
    visual_time = timestamp(visual["reviewed_at"], "visual reviewed_at")
    require(visual_time >= event_times[-1], "visual review predates native export")
    visual_status = status(visual["status"], "visual status")
    require(isinstance(visual["pages"], list) and [p["page"] for p in visual["pages"]] == list(range(1, page_count + 1)),
            "visual must cover every physical page exactly once in order")
    render_pages, visual_pages, visual_states = [], [], [visual_status]
    for p, image_path in zip(visual["pages"], image_paths):
        image = file_ref(p, visual_base, f"visual page {p['page']}")
        require(Path(image["path"]) == image_path, "visual image differs from render-manifest image")
        page_status = status(p["status"], "visual page status")
        require(type(p["full_original_image"]) is bool, "full_original_image must be explicit")
        if page_status == "passed":
            require(p["full_original_image"] is True, "a visual pass requires actual full original image review")
        observations = strings(p["observations"], "visual page observations", nonempty_list=True)
        render_pages.append({"page": p["page"], **image})
        visual_pages.append({"page": p["page"], "status": page_status, "observations": observations})
        visual_states.append(page_status)
    if visual_status == "passed":
        require(all(s == "passed" for s in visual_states), "visual pass contradicts page failures/pending")

    structural = validate_package(after["path"], source_path=files["template"]["path"])
    checks = [
        {"id": "native_open_save_close_reopen_export", "passed": all(s == "passed" for s in native_states),
         "scope": ("Explicit native Save As of intermediate, exact package repair, then final-byte open/close/reopen/export; no authenticity proof"
                   if repair else "Explicit observer's current before/after/PDF action record; no authenticity proof"), "evidence": evidence_text(native_ref)},
        {"id": "current_package", "passed": structural["valid"], "scope": "Current package structure and semantic controls",
         "evidence": json.dumps(structural, ensure_ascii=False, sort_keys=True)},
        {"id": "native_roundtrip_semantics", "passed": audit["passed"], "scope": "Exact supplied before/after bytes and current audit tool",
         "evidence": evidence_text(audit_ref)},
        {"id": "current_toc_fixedpoint", "passed": True, "scope": "Exact final source/PDF unchanged or inapplicable TOC; page sequence also needs visual review",
         "evidence": evidence_text(toc_ref)},
        {"id": "all_page_visual", "passed": all(s == "passed" for s in visual_states), "scope": "Explicit full original page-image observations for every current PDF page",
         "evidence": evidence_text(visual_ref)},
    ]
    if repair is not None:
        checks.append({"id": "exact_font_fallback_package_postprocess", "passed": True,
                       "scope": "Recomputed unique nonembedded fallback restoration; all other ZIP member bytes preserved; separate from native Save As",
                       "evidence": evidence_text(repair_ref)})
    judgment = spec["judgment"]
    nonempty(judgment["reviewer"], "judgment reviewer")
    judgment_time = timestamp(judgment["reviewed_at"], "judgment reviewed_at")
    require(judgment_time >= max(native_time, visual_time), "final judgment predates evidence review")
    judgment_status = status(judgment["status"], "judgment status")
    strings(judgment["observations"], "judgment observations", nonempty_list=True)
    if judgment_status == "passed":
        require(all(c["passed"] for c in checks), "passed judgment contradicts incomplete/failed evidence")
    if "failed" in native_states + visual_states or not audit["passed"] or not structural["valid"]:
        require(judgment_status == "failed", "known failure requires explicit failed final judgment")
    checks.append({"id": "reviewer_final_judgment", "passed": judgment_status == "passed", "scope": "Explicit reviewer/time/decision supplied in spec",
                   "evidence": evidence_text({"spec": str(spec_path), "spec_sha256": inventory[str(spec_path)], "judgment": judgment})})
    limitations = strings(spec["limitations"], "limitations", nonempty_list=True)
    if repair is not None:
        limitations = limitations + ["The final HWPX is an exact fallback package repair after the recorded native Save As intermediate; it is not an unchanged native Save As result."]
    record = {
        "schema_version": "1.0",
        "artifact": {"path": after["path"], "sha256": after["sha256"], "input_dataset_sha256": files["input"]["sha256"], "template_sha256": files["template"]["sha256"]},
        "native_export": {"application": app["name"], "version": app["version"], "build": app["build"], "source_sha256": after["sha256"],
                          "pdf_path": pdf["path"], "pdf_sha256": pdf["sha256"], "page_count": page_count, "compatibility_notices": notices},
        "render": {"engine": render["renderer"], "dpi": render["dpi"], "pages": render_pages},
        "checks": checks,
        "visual_review": {"reviewer": reviewer, "reviewed_at": visual["reviewed_at"], "pages": visual_pages},
        "status": judgment_status,
        "limitations": limitations + ["Hash consistency does not establish authenticity of application execution or reviewer judgment.",
                                       "This record does not establish business facts, execution results, signatures, approval or submission readiness."],
    }
    schema = json.loads((ROOT / "schemas/quality-review.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(record)
    binding = {"schema_version": "v4-quality-binding-1", "record_id": record_id, "role": role,
               "files": [{"path": p, "sha256": h} for p, h in sorted(inventory.items())],
               "evidence": {"native_observation": native_ref, "render_manifest": render_ref, "roundtrip": audit_ref, "toc_final": toc_ref, "visual_review": visual_ref},
               "judgment": judgment}
    if repair_ref is not None:
        binding["evidence"]["package_postprocess"] = repair_ref
        binding["workflow"] = workflow
    return record_id, record, binding, files


def recheck(binding):
    for item in binding["files"]:
        require(digest(item["path"]) == item["sha256"], f"evidence changed during binding: {item['path']}")


def run(spec_path, output_dir=None):
    record_id, record, binding, files = build_record(spec_path)
    # All paths in the record are absolute, so verification in a temporary
    # directory exercises the same quality.py checks without persistent approval.
    with tempfile.TemporaryDirectory(prefix="v4-quality-check-") as temp:
        review = Path(temp) / "review.json"
        review.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        verification = verify_quality_review(review, input_path=files["input"]["path"], template_path=files["template"]["path"])
    recheck(binding)
    if record["status"] == "passed":
        require(verification["passed"], "quality.py rejects passed record: " + evidence_text(verification["errors"]))
    if output_dir is not None:
        output_dir = Path(output_dir).resolve()
        require(output_dir.is_relative_to(BASE), "output directory must be project-local verification/generated")
        paths = {suffix: output_dir / f"{record_id}.{suffix}.json" for suffix in ("review", "verification", "binding")}
        require(not any(p.exists() for p in paths.values()), "refusing to overwrite an existing record/evidence file")
        require(not any(str(p) in {i['path'] for i in binding['files']} for p in paths.values()), "output aliases input evidence")
        output_dir.mkdir(parents=True, exist_ok=True)
        verification["review"] = str(paths["review"])
        binding["record_sha256"] = sha256((json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest()
        binding["bound_at"] = datetime.now(timezone.utc).isoformat()
        recheck(binding)
        for kind, payload in (("review", record), ("verification", verification), ("binding", binding)):
            with paths[kind].open("x") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return {"spec": str(Path(spec_path).resolve()), "record_id": record_id, "status": record["status"],
            "quality_passed": verification["passed"], "errors": verification["errors"], "written": output_dir is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, nargs="+")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check-only", action="store_true", help="verify in memory/temp; write no persistent approval records")
    group.add_argument("--output-dir", type=Path, help="new record filenames only, within verification/generated")
    args = parser.parse_args()
    results = []
    for spec in args.spec:
        try:
            results.append(run(spec, args.output_dir))
        except (OSError, ValueError, KeyError, TypeError, IndexError, ValidationError) as exc:
            results.append({"spec": str(spec), "rejected": True, "error": str(exc), "written": False})
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 2 if any(r.get("rejected") or not r.get("quality_passed") for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
