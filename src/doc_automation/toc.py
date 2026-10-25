"""Measure native-PDF TOC anchors and finalize a copy; re-export is mandatory."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata

from lxml import etree as ET
import pymupdf

from .compose import HP, NS, TemplateDocument
from .hwpx import inline_text, nearest, own_text
from .renderers import ROLES, _ad2_groups, _toc_entries

NO_TOC_ROLES = {"SF-AD3", "SF-PM1", "SF-PM2", "SF-PM3", "SF-PM4"}
PENDING = "쪽수: 네이티브 출력 후 확인 예정"
SECTION_ALIASES = {
    "SF-TD2": ["1. 시스템 구성도", "2. 하드웨어 구성도", "3. 소프트웨어 구성도",
               "4. 네트워크 구성도", "5. 장비 도입 및 설치 계획", "6. 클라우드 서비스 이용 내용"],
    "SF-TI2": ["1. 하드웨어 설치 결과", "2. 소프트웨어 설치 및 전환 결과",
               "3. 네트워크 설치 결과", "4. 초기데이터 전환 결과"],
    "SF-TI3": ["1. 사용자 매뉴얼", "2. 관리자(운영자) 매뉴얼"],
    "SF-OS1": ["1. 운영 지원 대상", "2. 운영 지원 기간", "3. 운영 지원 인력", "4. 운영 지원 내용"],
    "SF-OS2": ["1. 시스템 구축 현황", "2. 시스템 (시범)운영 현황", "3. KPI 계산 검토(실측 성과와 구별)"],
}
CARD_LABELS = {
    "SF-AD2": ("요구사항 ID", "요구사항명"),
    "SF-TD3": ("화면(보고서) ID", "화면(보고서)명"),
    "SF-TD4": ("프로그램 ID", "프로그램명"),
}


class TocError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.report = {"status": "failed", "code": code, "message": message, **details}


def _hash(raw):
    return sha256(raw).hexdigest()


def _compact(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def _flex(text, *, identifier=False, heading=False):
    value = _compact(text)
    pattern = r"\s*".join(re.escape(char) for char in value)
    if identifier:
        pattern = r"(?<![\w.-])" + pattern + r"(?![\w.-])"
    if heading:
        pattern = r"(?m)^\s*" + pattern + r"(?=\s|\(|$)"
    return re.compile(pattern)


def _dataset(value):
    if isinstance(value, dict):
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return value, {"path": None, "sha256": _hash(raw), "encoding": "canonical-json"}
    path = Path(value).expanduser().resolve()
    raw = path.read_bytes()
    return json.loads(raw), {"path": str(path), "sha256": _hash(raw), "encoding": "file-bytes"}


def _region(doc, specs):
    """Locate the generated profile's one logical TOC paragraph, never body prose.

    Physical PDF pages do not delimit XML ownership: a long TOC can wrap across
    pages, while notices before the first body table are separate paragraphs.
    """
    found, headings = [], 0
    for section_index in range(len(doc.sections)):
        children = list(doc.root(section_index))
        for index, p in enumerate(children):
            if _compact(own_text(p)) != "목차":
                continue
            headings += 1
            for child in children[index + 1:]:
                if (child.tag != HP + "p" or child.get("pageBreak") == "1"
                        or child.find(".//hp:tbl", NS) is not None):
                    break
                current = own_text(child).strip()
                if current:
                    found.append({"section": section_index, "heading": p,
                                  "first": child, "current_text": current})
                    break
    if headings != 1 or len(found) != 1:
        raise TocError("TOC_REGION", f"Expected one editable TOC region, found {len(found)}")
    region = found[0]
    labels = [_compact(spec["label"]) for spec in specs]
    current = _compact(region["current_text"])
    pending = "".join(labels) + _compact(PENDING)
    measured = "".join(re.escape(label) + r"\.\.\.(?:[0-9]+|PDF[0-9]+쪽)" for label in labels)
    if current != pending and re.fullmatch(measured, current) is None:
        raise TocError("TOC_CONTENT_MISMATCH",
                       "Expected one complete generated TOC paragraph with only expected labels and pending/page values")
    return region


def _specs(role, data):
    labels = _toc_entries(role, data)
    domain = {"SF-AD2": "requirements", "SF-TD4": "programs", "SF-TD5": "database_tables"}.get(role)
    if domain:
        items = ([item for _, group in _ad2_groups(data) for item in group]
                 if role == "SF-AD2" else data[domain])
        return [{"label": label, "kind": "table_column" if role == "SF-TD5" else "card",
                 "identifier": item["id"],
                 **({"row_column_ids": [column["id"] for column in item.get("columns", [])]}
                    if role == "SF-TD5" else {})} for label, item in zip(labels, items)]
    if role == "SF-TD3":
        return ([{"label": label, "kind": "heading", "anchor": label} for label in labels[:3]]
                + [{"label": label, "kind": "card", "identifier": item["id"]}
                   for label, item in zip(labels[3:-1], data["screens"])]
                + [{"label": labels[-1], "kind": "heading", "anchor": labels[-1]}])
    stage = {"SF-CD1": "unit", "SF-TI1": "integration", "SF-TI4": "acceptance"}.get(role)
    if stage:
        cases = [item for item in data["test_cases"] if item.get("stage") == stage]
        return ([{"label": label, "kind": "test_row", "identifier": item["id"]}
                 for label, item in zip(labels[:-1], cases)]
                + [{"label": labels[-1], "kind": "heading", "anchor": "2. 결함관리 내역"}])
    anchors = SECTION_ALIASES.get(role, labels)
    if len(anchors) != len(labels):
        raise TocError("ANCHOR_PROFILE", "TOC and section-anchor profile lengths differ")
    return [{"label": label, "kind": "heading", "anchor": anchor} for label, anchor in zip(labels, anchors)]


def _pdf_pages(raw):
    pages = []
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        if pdf.needs_pass:
            raise TocError("PDF_ENCRYPTED", "PDF requires a password")
        for number, page in enumerate(pdf, 1):
            lines, footers = [], []
            for block in page.get_text("rawdict")["blocks"]:
                for line in block.get("lines", []):
                    chars = [char for span in line["spans"] for char in span["chars"]]
                    text = "".join(char["c"] for char in chars)
                    box = list(map(float, line["bbox"]))
                    footer = re.fullmatch(r"\s*[-–—−]\s*(\d+)\s*[-–—−]\s*", text)
                    if footer and box[1] >= page.rect.height * .82:
                        footers.append({"number": int(footer[1]), "text": text, "bbox": box})
                        continue
                    plain = re.fullmatch(r"\s*(\d+)\s*", text)
                    centered = abs((box[0] + box[2]) / 2 - page.rect.width / 2) <= page.rect.width * .1
                    if plain and centered and box[1] >= page.rect.height * .93:
                        footers.append({"number": int(plain[1]), "text": text, "bbox": box})
                        continue
                    if text.strip():
                        lines.append({"text": text, "bbox": box, "chars": chars})
            offset = 0
            for line in lines:
                line["start"], line["end"] = offset, offset + len(line["text"])
                offset = line["end"] + 1
            pages.append({"pdf_page": number, "width": page.rect.width, "height": page.rect.height,
                          "lines": lines, "raw_text": "\n".join(line["text"] for line in lines),
                          "footers": footers})
    return pages


def _matches(page, text, *, identifier=False, heading=False):
    result = []
    for match in _flex(text, identifier=identifier, heading=heading).finditer(page["raw_text"]):
        lines = [line for line in page["lines"] if line["end"] > match.start() and line["start"] < match.end()]
        if not lines:
            continue
        pieces = []
        for line in lines:
            selected = line["chars"][max(0, match.start() - line["start"]):match.end() - line["start"]]
            if selected:
                pieces.append([min(char["bbox"][0] for char in selected), min(char["bbox"][1] for char in selected),
                               max(char["bbox"][2] for char in selected), max(char["bbox"][3] for char in selected)])
        bbox = [min(box[0] for box in pieces), min(box[1] for box in pieces),
                max(box[2] for box in pieces), max(box[3] for box in pieces)]
        # Glyph boxes allow IDs and labels to share one extracted PDF text line.
        if identifier and len(lines) > 1:
            lefts = [box[0] for box in pieces]
            if max(lefts) - min(lefts) > 18 or bbox[3] - bbox[1] > 80:
                continue
        result.append({"bbox": bbox, "text": "\n".join(line["text"] for line in lines),
                       "match_text": match.group(), "line_count": len(lines)})
    return result


def _toc_pages(pages, region, specs):
    compact, page_for_char = "", []
    starts = []
    for page in pages:
        for line in page["lines"]:
            value = _compact(line["text"])
            if value == "목차":
                starts.append((len(compact), page["pdf_page"]))
            compact += value
            page_for_char.extend([page["pdf_page"]] * len(value))
    if not starts:
        raise TocError("PDF_TOC_HEADING_MISSING", "No standalone 목차 heading in the native PDF")
    start, first_page = starts[0]
    current = region["current_text"]
    pending = _compact(PENDING)
    if pending in _compact(current):
        end_marker = pending
    else:
        if not specs:
            raise TocError("TOC_EMPTY", "No entries available to delimit the TOC")
        last = list(_flex(specs[-1]["label"]).finditer(current))
        if not last:
            raise TocError("TOC_CONTENT_MISMATCH", "Current HWPX does not contain its last expected TOC label")
        end_marker = _compact(current[last[-1].start():])
    end = compact.find(end_marker, start + 2)
    if end < 0:
        raise TocError("PDF_TOC_END_MISSING", "Current TOC end text is absent from the supplied PDF")
    end += len(end_marker)
    scope = compact[start:end]
    cursor = 0
    for spec in specs:
        found = scope.find(_compact(spec["label"]), cursor)
        if found < 0:
            raise TocError("PDF_TOC_ENTRY_MISSING", f"TOC label missing or out of order: {spec['label']}")
        cursor = found + len(_compact(spec["label"]))
    return list(range(first_page, page_for_char[end - 1] + 1))


def _same_band(value, labels):
    low = min(label["bbox"][1] for label in labels)
    high = max(label["bbox"][3] for label in labels)
    return value["bbox"][1] >= low - 7 and value["bbox"][3] <= high + 15


def _card_context(page, candidate, role):
    id_label, name_label = CARD_LABELS[role]
    for left in _matches(page, id_label):
        for right in _matches(page, name_label):
            a, b, value = left["bbox"], right["bbox"], candidate["bbox"]
            if (abs((a[1] + a[3] - b[1] - b[3]) / 2) <= 25
                    and value[0] >= a[2] - 4 and value[2] <= b[0] + 5
                    and _same_band(candidate, [left, right])):
                return {"kind": "detail_card_id_name_band", "labels": [left, right]}
    return None


def _grid_context(page, candidate, role, spec):
    if role == "SF-TD5":
        labels = ["테이블명", "테이블ID", "컬럼명", "컬럼ID"]
    elif role == "SF-CD1":
        labels = ["단위테스트ID", "단위테스트명", "테스트시나리오", "테스트데이터"]
    else:
        labels = ["테스트케이스", "데이터", "예상결과", "결과"]
    options = [_matches(page, label) for label in labels]
    if any(not values for values in options):
        return None
    for first in options[0]:
        band = [first]
        for values in options[1:]:
            matching = [value for value in values if abs((value["bbox"][1] + value["bbox"][3]
                        - first["bbox"][1] - first["bbox"][3]) / 2) <= 28]
            if not matching:
                break
            band.append(min(matching, key=lambda value: value["bbox"][0]))
        if len(band) != 4:
            continue
        centers = [(value["bbox"][0] + value["bbox"][2]) / 2 for value in band]
        if centers != sorted(centers):
            continue
        if candidate["bbox"][1] < max(value["bbox"][3] for value in band) - 2:
            continue
        if role == "SF-TD5":
            low, high = (centers[0] + centers[1]) / 2, (centers[1] + centers[2]) / 2
        else:
            low, high = first["bbox"][0] - 5, (centers[0] + centers[1]) / 2
        center = (candidate["bbox"][0] + candidate["bbox"][2]) / 2
        if low <= center <= high:
            row_evidence = []
            if role == "SF-TD5":
                # A notice after a table can fall below its old header. Require an actual
                # column identifier in the same data-row band and physical-column-ID lane.
                id_low = (centers[2] + centers[3]) / 2
                id_high = centers[3] + (centers[3] - centers[2]) / 2
                cy = (candidate["bbox"][1] + candidate["bbox"][3]) / 2
                for identifier in spec.get("row_column_ids", []):
                    for match in _matches(page, identifier, identifier=True):
                        box = match["bbox"]
                        if id_low <= (box[0] + box[2]) / 2 <= id_high and abs((box[1] + box[3]) / 2 - cy) <= 18:
                            row_evidence.append({"column_id": identifier, **match})
                if not row_evidence:
                    continue
            return {"kind": "table_id_column" if role == "SF-TD5" else "test_case_column",
                    "labels": band, "row_column_evidence": row_evidence}
    return None


def _measure(spec, pages, excluded, role):
    rejected, accepted = [], []
    for page in pages:
        if page["pdf_page"] <= max(excluded):
            continue  # Covers, TOC and TOC continuation pages cannot be body anchors.
        candidates = _matches(page, spec.get("identifier") or spec["anchor"],
                              identifier="identifier" in spec, heading=spec["kind"] == "heading")
        for candidate in candidates:
            context = {"kind": "exact_body_heading", "anchor": spec.get("anchor")}
            if spec["kind"] == "card":
                context = _card_context(page, candidate, role)
            elif spec["kind"] in {"table_column", "test_row"}:
                context = _grid_context(page, candidate, role, spec)
            if context is None:
                rejected.append({"pdf_page": page["pdf_page"], **candidate, "reason": "Detail table context not established"})
                continue
            footer_numbers = sorted({item["number"] for item in page["footers"]})
            if len(footer_numbers) > 1:
                raise TocError("AMBIGUOUS_PRINTED_PAGE", f"Several footer page numbers on PDF page {page['pdf_page']}",
                               footers=page["footers"])
            printed = footer_numbers[0] if footer_numbers else None
            accepted.append({**spec, "pdf_page": page["pdf_page"], "printed_page": printed,
                             "page_label": str(printed) if printed is not None else f"PDF {page['pdf_page']}쪽",
                             "page_basis": "printed_footer" if printed is not None else "explicit_pdf_page",
                             "anchor_evidence": candidate, "context": context, "footer_evidence": page["footers"]})
        if accepted:
            # The first valid detail card/table row, not the first incidental mention.
            return min(accepted, key=lambda value: (value["anchor_evidence"]["bbox"][1], value["anchor_evidence"]["bbox"][0]))
    raise TocError("BODY_ANCHOR_MISSING", f"No unambiguous detail anchor for {spec['label']}",
                   entry=spec, rejected_mentions=rejected)


def measure_toc(input_hwpx, pdf, input_dataset, role, native_source_sha256, *, native_pdf_sha256=None):
    """Measure current anchors without editing. Source/PDF association is caller attestation."""
    if role not in ROLES:
        raise TocError("UNKNOWN_ROLE", f"Unknown canonical role: {role}")
    input_path, pdf_path = Path(input_hwpx).expanduser().resolve(), Path(pdf).expanduser().resolve()
    hwpx_raw, pdf_raw = input_path.read_bytes(), pdf_path.read_bytes()
    source_hash, pdf_hash = _hash(hwpx_raw), _hash(pdf_raw)
    if native_source_sha256 != source_hash:
        raise TocError("STALE_NATIVE_SOURCE", "Native PDF is declared for different HWPX bytes",
                       actual_source_sha256=source_hash, declared_source_sha256=native_source_sha256)
    if native_pdf_sha256 is not None and native_pdf_sha256 != pdf_hash:
        raise TocError("STALE_NATIVE_PDF", "PDF bytes do not match the expected native export hash")
    data, dataset = _dataset(input_dataset)
    manifest = {"schema_version": "1.0", "role": role, "recorded_at": datetime.now(timezone.utc).isoformat(),
                "input_hwpx": str(input_path), "input_sha256": source_hash, "input_dataset": dataset,
                "native_pdf": str(pdf_path), "native_pdf_sha256": pdf_hash,
                "native_source_sha256": native_source_sha256,
                "association_basis": "caller_attested_native_export_hash_pair",
                "limitations": ["Checks supplied bytes and PDF text/geometry, not authenticity of native execution or visual quality."]}
    doc = TemplateDocument(input_path)
    if role in NO_TOC_ROLES:
        if any(_compact(own_text(p)) == "목차" for section in range(len(doc.sections)) for p in doc.root(section)):
            raise TocError("UNEXPECTED_TOC", "A no-TOC role contains a TOC; review its new profile")
        return {**manifest, "status": "not_applicable", "reason": "This v2 role has no TOC", "entries": []}
    try:
        specs = _specs(role, data)
    except (KeyError, TypeError) as exc:
        raise TocError("DATASET_PROFILE_MISMATCH", f"Fact data does not match this role's TOC profile: {exc}") from exc
    if not specs:
        raise TocError("TOC_EMPTY", "No TOC entries supplied")
    identifiers = [spec["identifier"] for spec in specs if "identifier" in spec]
    if len(identifiers) != len(set(identifiers)):
        raise TocError("DUPLICATE_TOC_IDENTIFIER", "Dataset has duplicate identifiers in this TOC domain")
    region = _region(doc, specs)
    try:
        pages = _pdf_pages(pdf_raw)
    except TocError:
        raise
    except Exception as exc:
        raise TocError("PDF_UNREADABLE", f"Cannot measure PDF text and geometry: {exc}") from exc
    excluded = _toc_pages(pages, region, specs)
    measurements = [_measure(spec, pages, excluded, role) for spec in specs]
    return {**manifest, "status": "measured", "pdf_page_count": len(pages), "toc_pdf_pages": excluded,
            "toc_locator": {"section": doc.sections[region["section"]],
                            "xpath": doc.root(region["section"]).getroottree().getpath(region["first"])},
            "entries": measurements}


def _blacken_owned(doc, paragraph):
    for run in paragraph.findall("hp:run", NS):
        texts = [t for t in run.iter(HP + "t") if nearest(t, HP + "p") is paragraph]
        if not any(inline_text(t) for t in texts):
            continue
        # Keep nested header/table runs outside the mutation scope.
        proxy = ET.Element(HP + "run", attrib=dict(run.attrib))
        for text in texts:
            proxy.append(deepcopy(text))
        doc.blacken_text_runs(proxy)
        run.set("charPrIDRef", proxy.get("charPrIDRef"))


def finalize_toc(input_hwpx, pdf, input_dataset, role, output_hwpx, native_source_sha256,
                 *, native_pdf_sha256=None, previous_manifest=None):
    """Write measured TOC values to a different HWPX; never approve the changed bytes."""
    output = Path(output_hwpx).expanduser().resolve()
    if output == Path(input_hwpx).expanduser().resolve():
        raise TocError("OUTPUT_IS_INPUT", "TOC finalization requires a separate output copy")
    measured = measure_toc(input_hwpx, pdf, input_dataset, role, native_source_sha256,
                           native_pdf_sha256=native_pdf_sha256)
    if measured["status"] == "not_applicable":
        return {**measured, "output_written": False, "native_status": "unchanged_not_applicable",
                "active_hwpx": measured["input_hwpx"], "active_sha256": measured["input_sha256"]}
    convergence = check_toc_convergence(previous_manifest, measured) if previous_manifest else None
    text = "\n".join(f"{entry['label']} ... {entry['page_label']}" for entry in measured["entries"])
    doc = TemplateDocument(input_hwpx)
    region = _region(doc, measured["entries"])
    changed = region["current_text"] != text
    if not changed:
        # Do not rewrite an unchanged ZIP merely to create a new byte identity.
        return {**measured, "status": "unchanged", "output_written": False,
                "native_status": "current_native_measurement", "convergence": convergence,
                "active_hwpx": measured["input_hwpx"], "active_sha256": measured["input_sha256"]}
    doc.set_paragraph_text(region["first"], text)
    _blacken_owned(doc, region["first"])
    report = doc.save(output)
    return {**measured, "status": "updated", "output_written": True,
            "output_hwpx": str(output), "output_sha256": report["sha256"], "composition": report,
            "active_hwpx": str(output), "active_sha256": report["sha256"],
            "native_status": "pending_reexport", "pdf_reuse_allowed": False,
            "next_action": "Export the current output bytes again in Hancom, then remeasure and compare convergence.",
            "convergence": convergence}


def check_toc_convergence(previous_manifest, current_measurement):
    """Compare second-pass measurements for the exact prior output HWPX bytes."""
    if not isinstance(previous_manifest, dict):
        previous_manifest = json.loads(Path(previous_manifest).read_text())
    previous, current = previous_manifest, current_measurement
    if previous.get("output_sha256") != current.get("input_sha256"):
        raise TocError("CONVERGENCE_SOURCE_MISMATCH", "Second native export does not belong to the prior TOC output")
    if previous.get("native_pdf_sha256") == current.get("native_pdf_sha256"):
        raise TocError("OLD_PDF_REUSED", "Changed TOC bytes require a fresh native PDF; old PDF bytes cannot establish convergence")
    if previous.get("role") != current.get("role") or previous.get("input_dataset", {}).get("sha256") != current.get("input_dataset", {}).get("sha256"):
        raise TocError("CONVERGENCE_SCOPE_MISMATCH", "Role or fact dataset changed between TOC passes")
    signature = lambda record: [(entry["label"], entry["page_label"], entry["page_basis"])
                                for entry in record.get("entries", [])]
    before, after = signature(previous), signature(current)
    return {"converged": before == after, "comparison": "same entries and printed/explicit TOC page labels",
            "previous_pdf_sha256": previous["native_pdf_sha256"], "current_pdf_sha256": current["native_pdf_sha256"],
            "physical_pdf_positions_changed": [entry["pdf_page"] for entry in previous.get("entries", [])]
                                              != [entry["pdf_page"] for entry in current.get("entries", [])],
            "native_visual_review_required": True, "changes": [] if before == after else {"before": before, "after": after}}
