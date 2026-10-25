"""Verify supplied native-output records against current local bytes.

This checks evidence integrity, not whether a person or application truly performed
the actions asserted in a record. Native execution and visual judgment need their
own observed evidence.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, BadZipFile

from jsonschema import Draft202012Validator, FormatChecker
from lxml import etree
from PIL import Image
import pymupdf

from .business import _schema
from .compose import validate_package
from .hwpx import section_order


def verify_quality_review(review_path: Path | str, *, input_path: Path | str, template_path: Path | str) -> dict:
    review_path = Path(review_path).resolve()
    errors: list[dict] = []
    files: list[dict] = []
    result = {
        "review": str(review_path), "passed": False, "errors": errors, "files": files,
        "limitations": [
            "Checks the supplied records and current local bytes; it does not establish the authenticity of application execution or visual judgment.",
            "A quality pass does not establish business facts, approval, execution results or submission readiness.",
        ],
    }

    def fail(code: str, message: str):
        errors.append({"code": code, "message": message})

    def checked(path: Path | str, expected: str, label: str) -> bytes | None:
        path = Path(path)
        if not path.is_absolute():
            path = review_path.parent / path
        path = path.resolve()
        try:
            payload = path.read_bytes()
        except OSError as exc:
            fail("FILE_UNREADABLE", f"{label}: {path}: {exc}")
            return None
        digest = sha256(payload).hexdigest()
        files.append({"label": label, "path": str(path), "sha256": digest, "matches": digest == expected})
        if digest != expected:
            fail("FILE_HASH_MISMATCH", f"{label}: {path}")
            return None
        return payload

    try:
        payload = review_path.read_bytes()
        record = json.loads(payload)
        result["review_sha256"] = sha256(payload).hexdigest()
    except (OSError, ValueError) as exc:
        fail("REVIEW_UNREADABLE", str(exc))
        return result
    invalid = list(Draft202012Validator(_schema("quality-review.schema.json"), format_checker=FormatChecker()).iter_errors(record))
    if invalid:
        for error in invalid:
            fail("REVIEW_SCHEMA", f"/{'/'.join(map(str, error.absolute_path))}: {error.message}")
        return result
    artifact, native, render, visual = [record[k] for k in ("artifact", "native_export", "render", "visual_review")]
    result["artifact"] = artifact
    result["pages"] = native["page_count"]
    checked(Path(input_path).resolve(), artifact["input_dataset_sha256"], "input_dataset")
    checked(Path(template_path).resolve(), artifact["template_sha256"], "template")
    hwpx = checked(artifact["path"], artifact["sha256"], "artifact")
    pdf = checked(native["pdf_path"], native["pdf_sha256"], "native_pdf")
    if native["source_sha256"] != artifact["sha256"]:
        fail("NATIVE_SOURCE_MISMATCH", "Native export is associated with different HWPX bytes.")
    if not any(x in native["application"].casefold() for x in ("hancom", "hanword", "hwp", "한글", "한컴")):
        fail("NATIVE_APPLICATION", "The record does not identify a Hancom application.")
    if not any(x in render["engine"].casefold() for x in ("poppler", "pdftoppm")):
        fail("RENDER_ENGINE", "The record does not identify Poppler page rendering.")
    if record["status"] != "passed" or any(not x["passed"] for x in record["checks"]):
        fail("CHECKS_INCOMPLETE", "The supplied quality checks have not all passed.")
    expected = list(range(1, native["page_count"] + 1))
    for label, pages in (("render", render["pages"]), ("visual_review", visual["pages"])):
        if sorted(x["page"] for x in pages) != expected:
            fail("PAGE_COVERAGE", f"{label}: every page must occur exactly once.")
    if any(x["status"] != "passed" for x in visual["pages"]):
        fail("VISUAL_REVIEW_INCOMPLETE", "One or more page reviews are pending or failed.")
    if hwpx is not None:
        try:
            with ZipFile(BytesIO(hwpx)) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)) or archive.testzip():
                    fail("HWPX_PACKAGE", "Duplicate members or invalid compressed payload.")
                if archive.read("mimetype").decode().strip() != "application/hwp+zip":
                    fail("HWPX_MIMETYPE", "Invalid HWPX media type.")
                section_order(archive)
                for name in names:
                    if name.endswith((".xml", ".hpf")):
                        etree.fromstring(archive.read(name), etree.XMLParser(resolve_entities=False, no_network=True))
        except (BadZipFile, KeyError, ValueError, etree.XMLSyntaxError, OSError) as exc:
            fail("HWPX_PACKAGE", str(exc))
        current_hwpx = Path(artifact["path"])
        if not current_hwpx.is_absolute():
            current_hwpx = review_path.parent / current_hwpx
        package_report = validate_package(current_hwpx, source_path=Path(template_path).resolve())
        result["package_validation"] = package_report
        if not package_report["valid"]:
            fail("HWPX_STRUCTURE", "; ".join(package_report["errors"]))
    if pdf is not None:
        try:
            with pymupdf.open(stream=pdf, filetype="pdf") as doc:
                if len(doc) != native["page_count"]:
                    fail("PDF_PAGE_COUNT", "The actual PDF and recorded page count differ.")
        except Exception as exc:
            fail("PDF_UNREADABLE", str(exc))
    for page in render["pages"]:
        png = checked(page["path"], page["sha256"], f"render_page_{page['page']}")
        if png is not None:
            try:
                with Image.open(BytesIO(png)) as im:
                    im.verify()
            except (OSError, ValueError) as exc:
                fail("PAGE_IMAGE_UNREADABLE", str(exc))
    result["passed"] = not errors
    return result
