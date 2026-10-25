"""Source-bound historical raster quotations, separate from execution evidence.

The initial allowlist contains six source ownership instances. It retains only
locators and digests; source literals and bitmaps remain user-supplied files.
"""

from __future__ import annotations

from hashlib import sha256
from importlib import resources
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import struct
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

from lxml import etree as ET
from PIL import Image, UnidentifiedImageError

from .hwpx import NS, own_text, parse_xml, section_order


DISCLOSURE = "참고 원문 재현·새 사업 수행/설치 증거 아님"
FIELDS = {"test_cases": "reference_result_quotations",
          "deployment_items": "reference_installation_quotations"}
_FREE_VALUES = {"data", "expected", "actual", "value", "default_value",
                "original_value", "proposed_value"}
_ARTIFACT_FIELDS = {
    "evidence_ids", "approval_evidence_ids", "verification_evidence_ids",
    "attachment_ids", "before_attachment_ids", "after_attachment_ids",
    "standard_attachment_ids", "module_flow_attachment_ids",
    "physical_export_attachment_ids", "flow_attachment_ids",
    "as_is_attachment_ids", "to_be_attachment_ids", "as_is_diagram_ids",
    "to_be_diagram_ids", "organization_chart_attachment_ids", "deliverable_ids",
    "artifact_id",
}
_PROFILE_KEYS = ("quotation_kind", "source_document_sha256", "source_xml",
                 "source_picture_xpath", "source_binary_item_id",
                 "source_binary_member", "source_binary_sha256",
                 "source_pixel_sha256")


class QuotationInputCollision(ValueError):
    """A planned mutation aliases a supplied read-only quotation file."""


def canonical_digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


def pixel_digest(raw):
    """Digest decoded dimensions and RGBA8 pixels, independent of file metadata."""
    with Image.open(BytesIO(raw)) as image:
        image.load()
        digest = sha256(struct.pack(">II", image.width, image.height)
                        + image.convert("RGBA").tobytes()).hexdigest()
        return digest, image.size, image.format


def entries(data):
    """Only the two schema-owned paths; raw test-data homonyms are not slots."""
    for domain, field in FIELDS.items():
        for index, parent in enumerate(data.get(domain, [])):
            for number, quote in enumerate(parent.get(field, [])):
                yield f"/{domain}/{index}/{field}/{number}", parent, quote


def _profiles():
    return json.loads(resources.files("doc_automation").joinpath(
        "quotation_sources.json").read_text(encoding="utf-8"))["entries"]


def role_for(domain, parent):
    if domain == "deployment_items":
        return "SF-TI2"
    return {"integration": "SF-TI1", "acceptance": "SF-TI4"}.get(parent.get("stage"))


def _local_path(record, base_dir):
    value = record.get("path")
    if not isinstance(value, str) or urlsplit(value).scheme:
        raise ValueError("Quotation requires a supplied local file path")
    path = Path(value).expanduser()
    return path if path.is_absolute() else base_dir / path


def _local_bytes(record, base_dir):
    return _local_path(record, base_dir).resolve().read_bytes()


def _member(href, names):
    """Resolve one local OPF member without accepting traversal or remote URIs."""
    if not href or urlsplit(href).scheme or ".." in PurePosixPath(href).parts:
        raise ValueError("Quotation OPF member is not local")
    candidates = [href.lstrip("/"), str(PurePosixPath("Contents") / href)]
    found = {name for name in candidates if name in names}
    if len(found) != 1:
        raise ValueError("Quotation OPF member must resolve uniquely")
    return found.pop()


def _one(root, xpath, tag):
    found = root.xpath(xpath, namespaces=NS)
    if len(found) != 1 or not isinstance(found[0], ET._Element) or found[0].tag != tag:
        raise ValueError("Quotation XPath has no unique expected source object")
    return found[0]


def _used_artifacts(data):
    # Submission gates treat a document_role attachment as a deliverable
    # artifact even without an evidence_ids or review link.
    used = {item["id"] for item in data.get("attachments", [])
            if item.get("document_role") is not None}

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _FREE_VALUES or key in FIELDS.values():
                    continue
                if key in _ARTIFACT_FIELDS:
                    used.update(x for x in (value if isinstance(value, list) else [value])
                                if isinstance(x, str))
                else:
                    walk(value)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(data)
    return used


def _detail_regions(quote, pixels):
    """Validate explicit half-open source pixels, without altering the source."""
    regions = quote.get("detail_regions", [])
    if not isinstance(regions, list) or len(regions) > 6:
        raise ValueError("Quotation detail_regions must be a list of at most six views")
    checked, boxes = [], set()
    for region in regions:
        if (not isinstance(region, dict) or set(region) != {"label", "box_pixels"}
                or not isinstance(region["label"], str) or not region["label"].strip()):
            raise ValueError("Quotation detail_regions requires only a nonempty label and box_pixels")
        box = region["box_pixels"]
        if (not isinstance(box, list) or len(box) != 4
                or any(type(value) is not int for value in box)):
            raise ValueError("Quotation detail_regions requires four integer box_pixels")
        left, top, right, bottom = box
        if not (0 <= left < right <= pixels[0] and 0 <= top < bottom <= pixels[1]):
            raise ValueError("Quotation detail_regions must stay inside the verified source pixels")
        if tuple(box) == (0, 0, *pixels):
            raise ValueError("Quotation detail_regions must select a detail; the whole view is already retained")
        if tuple(box) in boxes:
            raise ValueError("Quotation detail_regions must not duplicate the same source rectangle")
        boxes.add(tuple(box))
        checked.append({"label": region["label"], "box_pixels": list(box)})
    return checked


def verify_quotation(data, pointer, parent, quote, base_dir):
    """Return verified bytes/provenance; no business truth is inferred."""
    registry = _profiles()
    domain = pointer.split("/")[1]
    role = role_for(domain, parent)
    owner = quote["historical_owner"]
    if quote.get("scope") != "historical_reference_only":
        raise ValueError("Quotation scope must remain historical_reference_only")
    identity_sha = canonical_digest(owner)
    matches = [profile for profile in registry
               if all(profile[key] == quote[key] for key in _PROFILE_KEYS)
               and profile["historical_owner_sha256"] == identity_sha
               and profile["document_role"] == owner["document_role"] == role]
    if len(matches) != 1:
        raise ValueError("Quotation source/role/picture/historical owner is outside the six-instance registry")
    sources = {source["id"]: source for source in data["sources"]}
    attachments = {attachment["id"]: attachment for attachment in data["attachments"]}
    source = sources.get(quote["source_document_id"], {})
    attachment = attachments.get(quote["attachment_id"], {})
    if (source.get("kind") != "reference_document"
            or source.get("document_role") != role
            or source.get("sha256") != quote["source_document_sha256"]):
        raise ValueError("Quotation source must be the declared historical reference document and role")
    if (attachment.get("source_id") != source["id"]
            or attachment.get("purpose") != "historical_reference_quotation_only"
            or attachment.get("status") != "provided"
            or attachment.get("verification_status") != "provided"
            or attachment.get("sha256") != quote["source_binary_sha256"]):
        raise ValueError("Quotation attachment must be provided historical bytes, never verified execution evidence")
    source_raw = _local_bytes(source, base_dir)
    if sha256(source_raw).hexdigest() != quote["source_document_sha256"]:
        raise ValueError("Quotation source HWPX SHA mismatch")
    raw = _local_bytes(attachment, base_dir)
    if sha256(raw).hexdigest() != quote["source_binary_sha256"]:
        raise ValueError("Quotation bitmap SHA mismatch")
    with ZipFile(BytesIO(source_raw)) as package:
        names = package.namelist()
        if len(names) != len(set(names)) or package.testzip() is not None:
            raise ValueError("Quotation source has duplicate or corrupt ZIP members")
        spine = section_order(package)
        roots = {name: parse_xml(package.read(name)) for name in spine}
        # Read all own paragraphs in OPF order, including inline tails. Identity
        # cells are compared separately; enclosing paragraphs never own them.
        read_count = sum(1 for root in roots.values()
                         for paragraph in root.iter(f"{{{NS['hp']}}}p")
                         if own_text(paragraph) is not None)
        root = roots.get(quote["source_xml"])
        if root is None:
            raise ValueError("Quotation picture is outside the OPF spine")
        picture = _one(root, quote["source_picture_xpath"], f"{{{NS['hp']}}}pic")
        image = picture.find("hc:img", NS)
        if image is None or image.get("binaryItemIDRef") != quote["source_binary_item_id"]:
            raise ValueError("Quotation picture binary ID mismatch")
        opf = parse_xml(package.read("Contents/content.hpf"))
        items = [item for item in opf.findall("opf:manifest/opf:item", NS)
                 if item.get("id") == quote["source_binary_item_id"]]
        if len(items) != 1 or _member(items[0].get("href"), names) != quote["source_binary_member"]:
            raise ValueError("Quotation OPF binary mapping mismatch")
        if package.read(quote["source_binary_member"]) != raw:
            raise ValueError("Quotation attachment is not the exact source BinData payload")
        table = next(picture.iterancestors(f"{{{NS['hp']}}}tbl"), None)
        if table is None:
            raise ValueError("Quotation source picture has no historical table owner")
        for ref in owner["identity_refs"]:
            if ref["xml_member"] != quote["source_xml"]:
                raise ValueError("Quotation historical identity is in a different source section")
            cell = _one(root, ref["xpath"], f"{{{NS['hp']}}}tc")
            if next(cell.iterancestors(f"{{{NS['hp']}}}tbl"), None) is not table:
                raise ValueError("Quotation identity cell is outside its picture's historical table")
            paragraphs = [own_text(p) for p in cell.findall("hp:subList/hp:p", NS)]
            if (paragraphs != ref.get("paragraph_owned_texts")
                    or "\n".join(paragraphs) != ref["text_verbatim"]
                    or dict(cell.find("hp:cellAddr", NS).attrib) != ref.get("cell_address")):
                raise ValueError("Quotation historical owner literal/address mismatch")
        picture_sha = sha256(ET.tostring(picture, method="c14n")).hexdigest()
    pixel_sha, pixels, fmt = pixel_digest(raw)
    mime = {"BMP": {"image/bmp", "image/x-ms-bmp"}, "PNG": {"image/png"},
            "JPEG": {"image/jpeg"}}.get(fmt, set())
    if pixel_sha != quote["source_pixel_sha256"] or attachment.get("media_type") not in mime:
        raise ValueError("Quotation decoded pixels or MIME mismatch")
    regions = _detail_regions(quote, pixels)
    if regions and fmt not in {"BMP", "PNG"}:
        raise ValueError("Quotation detail_regions is verified only for lossless BMP/PNG sources")
    used = _used_artifacts(data)
    for aid in used:
        other = attachments.get(aid)
        if other is None:
            continue  # General reference validation reports the missing ID.
        if aid == attachment["id"] or other.get("sha256") == quote["source_binary_sha256"]:
            raise ValueError("Historical quotation payload cannot also occupy evidence/flow/artifact slots")
        # Evidence can be a TIFF/GIF raster or have an uninformative MIME such
        # as application/octet-stream. Sniff the actual local bytes rather
        # than using the rendering MIME allowlist as an exclusivity boundary.
        other_raw = _local_bytes(other, base_dir)
        try:
            other_pixels = pixel_digest(other_raw)[0]
        except UnidentifiedImageError:
            continue  # General artifact validation owns non-raster files.
        if other_pixels == pixel_sha:
            raise ValueError("Reencoded historical quotation pixels cannot be relabelled as evidence/flow")
    result = {"pointer": pointer, "role": role, "parent_id": parent["id"],
            "attachment_id": attachment["id"], "source_sha256": quote["source_document_sha256"],
            "source_picture_sha256": picture_sha, "source_spine": spine,
            "source_owned_paragraphs_read": read_count,
            "historical_owner_sha256": identity_sha, "pixel_sha256": pixel_sha,
            "pixels": pixels, "format": fmt, "source": source,
            "attachment": attachment, "bytes": raw}
    if regions:
        result["detail_regions"] = regions
    return result


def check_quotations(data, base_dir, *, verify_files=True):
    errors, checks = [], []
    for pointer, parent, quote in entries(data):
        try:
            if not verify_files:
                raise ValueError("Historical quotation provenance requires local file verification")
            checked = verify_quotation(data, pointer, parent, quote, base_dir)
            checks.append({key: value for key, value in checked.items()
                           if key not in {"bytes", "source", "attachment"}})
        except (ValueError, OSError, KeyError, TypeError, BadZipFile, ET.Error) as exc:
            errors.append({"path": pointer, "reason": str(exc)})
    return errors, checks


def append_reference_quotations(doc, role, data, ctx):
    """Append a named quotation register with exact parent/picture ownership.

    This is a separate register, never the actual-result cell or a flow slot.
    Its empty path performs no document mutation or style allocation.
    """
    from .narrative import readable_value, source_reference_text
    selected = [(pointer, parent, quote) for pointer, parent, quote in entries(data)
                if role_for(pointer.split("/")[1], parent) == role]
    if not selected:
        return
    from .compose import HANCOM_MAC_12_30_PNG_METADATA
    if (any(quote.get("detail_regions") for _, _, quote in selected)
            and ctx.get("raster_metadata_profile") != HANCOM_MAC_12_30_PNG_METADATA):
        raise ValueError("Quotation detail_regions requires the explicit Hancom Mac12.30 PNG profile")
    root = doc.root(len(doc.sections) - 1)
    prototype = next((p for p in reversed(list(root.iter(f"{{{NS['hp']}}}p")))
                      if own_text(p).strip()), None)
    if prototype is None:
        raise ValueError("Quotation register has no body paragraph prototype")

    def paragraph(text, *, heading=False, caption=False, picture=False, keep_next=False):
        p = doc.new_paragraph(text, prototype=prototype)
        doc.use_character_style(p, bold=heading, italic=False)
        doc.use_paragraph_style(p, align="LEFT", break_latin="KEEP_WORD")
        doc.use_paragraph_keep(p, keep_lines=not picture and len(text) <= 240,
                              keep_with_next=keep_next)
        root.append(p)
        if ctx.get("editorial"):
            owner_set = (doc._editorial_heading_paragraphs if heading else
                         doc._editorial_caption_paragraphs if caption else
                         doc._editorial_picture_paragraphs if picture else
                         doc._editorial_body_paragraphs)
            owner_set.add(p)
        return p

    paragraph("부록. 참고 원문 그림 인용", heading=True, keep_next=True)
    paragraph(DISCLOSURE + ". 아래 원문의 결과·사진은 역사적 비교자료이며 현재 항목의 결과·설치·승인 상태를 변경하지 않는다.")
    for number, (pointer, parent, quote) in enumerate(selected, 1):
        checked = verify_quotation(data, pointer, parent, quote, ctx["input_dir"])
        snapshots = ctx.setdefault("_quotation_file_snapshots", {})
        for record in (checked["source"], checked["attachment"]):
            path = str(_local_path(record, ctx["input_dir"]))
            if path in snapshots and snapshots[path] != record["sha256"]:
                raise ValueError("Quotation file has conflicting declared SHA snapshots")
            snapshots[path] = record["sha256"]
        key = f"Q{number}"
        owner = quote["historical_owner"]
        historical_label = (owner["group_id_literal"] + " / " + owner["case_label_literal"]
                            if quote["quotation_kind"] == "historical_test_result"
                            else owner["panel_heading_literal"])
        paragraphs = []
        paragraphs.append(paragraph(f"[{key}] 현재 항목: {parent['id']} — {readable_value(parent.get('name'))}; 원문: {role} / {historical_label}",
                                    heading=True, keep_next=True))
        caption = f"[{key}] {DISCLOSURE} · 현재 항목 {parent['id']} · 원문 {role} / {historical_label}"
        # This fixed disclosure is independent of supplied caption length. It
        # must never take the generic image-caption truncation/fallback path.
        caption_p = paragraph(caption, caption=True, keep_next=True)
        paragraphs.append(caption_p)
        picture_p = paragraph("", picture=True, keep_next=True)
        paragraphs.append(picture_p)
        attachment = checked["attachment"]
        source = checked["source"]
        given_caption = attachment.get("caption")
        if given_caption:
            paragraphs.append(paragraph(f"[{key}] 제공 캡션(원문 인용 용도): {given_caption}"))
        source_ref = {"source_id": source["id"],
                      "locator": quote["source_xml"] + "#" + quote["source_picture_xpath"]}
        ref_text = source_reference_text([source_ref]) or f"{source_ref['source_id']} {source_ref['locator']}"
        paragraphs.append(paragraph(f"[{key}] 출처: {source['id']} — {source['title']}; {ref_text}"))
        paragraphs.append(paragraph(f"[{key}] 원문 SHA-256: {quote['source_document_sha256']}"))
        paragraphs.append(paragraph(f"[{key}] 원문 그림 위치: {quote['source_xml']}#{quote['source_picture_xpath']}"))
        paragraphs.append(paragraph(f"[{key}] 첨부: {quote['attachment_id']}; 원문 binary ID: {quote['source_binary_item_id']}; 멤버: {quote['source_binary_member']}"))
        paragraphs.append(paragraph(f"[{key}] 원문 bitmap SHA-256: {quote['source_binary_sha256']}"))
        paragraphs.append(paragraph(f"[{key}] RGBA 픽셀 SHA-256: {quote['source_pixel_sha256']}; 크기: {checked['pixels'][0]}×{checked['pixels'][1]} px; 전체 그림·크롭 없음"))
        paragraphs.append(paragraph(f"[{key}] 인용 유형: {quote['quotation_kind']}; 범위: {quote['scope']}; 역사적 소유자: {owner['document_role']} / {owner['owner_kind']}"))
        if "group_id_literal" in owner:
            paragraphs.append(paragraph(f"[{key}] 원문 그룹: {owner['group_id_literal']} / {owner['group_name_literal']}; 원행 순서로 연결한 케이스 번호: {owner['case_number']}; 원문 케이스 표기: {owner['case_label_literal']}"))
        else:
            paragraphs.append(paragraph(f"[{key}] 원문 사진 패널: {owner['panel_heading_literal']}"))
        for index, identity in enumerate(owner["identity_refs"], 1):
            address = identity["cell_address"]
            paragraphs.append(paragraph(f"[{key}] 원문 소유 식별 {index}: {identity['xml_member']}#{identity['xpath']}; 셀 R{address['rowAddr']}C{address['colAddr']}"))
            # Exact paragraph-owned literals, with original inline tails and
            # paragraph boundaries; no ancestor-cell text duplication.
            for owned in identity["paragraph_owned_texts"]:
                paragraphs.append(paragraph(f"[{key}] 원문 소유 표기: {owned}"))
        raw = checked["bytes"]
        embedded, media = raw, attachment["media_type"]
        if checked["format"] == "BMP":
            with Image.open(BytesIO(raw)) as image:
                output = BytesIO()
                image.save(output, format="PNG")
                embedded, media = output.getvalue(), "image/png"
        if pixel_digest(embedded)[0] != checked["pixel_sha256"]:
            raise ValueError("Quotation raster preparation changed decoded pixels")
        binding = {"entity_id": parent["id"], "entity_name": parent.get("name"),
                   "entity_input_pointer": pointer.rsplit("/", 2)[0],
                   "slot": pointer.split("/")[-2], "slot_input_pointer": pointer.rsplit("/", 1)[0],
                   "quotation_input_pointer": pointer, "quotation_key": key,
                   "attachment_id": attachment["id"], "sha256": attachment["sha256"],
                   "embedded_sha256": sha256(embedded).hexdigest(),
                   "pixel_sha256": checked["pixel_sha256"],
                   "conversion": "bmp_to_png_lossless" if embedded != raw else "none",
                   "caption": caption, "provided_caption": given_caption, "crop": "none",
                   "historical_reference_only": True, "new_execution_evidence": False,
                   "historical_owner_sha256": checked["historical_owner_sha256"],
                   "placement": "dedicated_historical_quotation_register"}
        ctx.setdefault("image_bindings", []).append(binding)
        ctx.setdefault("_pending_images", []).append({"paragraph": picture_p,
            "bytes": embedded, "media_type": media, "pixels": checked["pixels"], "binding": binding})
        ctx.setdefault("_quotation_owners", []).append({"key": key,
            "input_pointer": pointer, "parent_id": parent["id"], "binding": binding,
            "_picture": picture_p, "_caption": caption_p})
        detail_fields = []
        for detail_number, region in enumerate(checked.get("detail_regions", []), 1):
            detail_key = f"{key}.D{detail_number}"
            detail_pointer = pointer + f"/detail_regions/{detail_number - 1}"
            label_p = paragraph(f"[{detail_key}] 원문 부분 확대: {region['label']}", keep_next=True)
            detail_caption = (f"[{detail_key}] {DISCLOSURE} · 현재 항목 {parent['id']} · "
                              f"원문 {role} / {historical_label} · 원본 픽셀 LTRB={region['box_pixels']} (오른쪽·아래쪽 경계 제외)")
            detail_caption_p = paragraph(detail_caption, caption=True, keep_next=True)
            detail_picture_p = paragraph("", picture=True, keep_next=True)
            proof_p = paragraph(f"[{detail_key}] 원문 근거: [{key}]의 문서/PIC/BinData와 동일. "
                                f"전체 원본 그림은 [{key}]에 보존하며 이 부분 보기는 추가 수행 증거가 아니다.")
            detail_paragraphs = [label_p, detail_caption_p, detail_picture_p, proof_p]
            paragraphs.extend(detail_paragraphs)
            detail_binding = {**binding, "caption": detail_caption,
                "crop": "declared_source_pixel_viewport", "quotation_parent_key": key,
                "quotation_detail_key": detail_key, "detail_input_pointer": detail_pointer,
                "viewport_pixels_ltrb": list(region["box_pixels"]),
                "source_document_sha256": quote["source_document_sha256"],
                "source_picture_xpath": quote["source_picture_xpath"],
                "source_binary_member": quote["source_binary_member"],
                "source_binary_sha256": quote["source_binary_sha256"],
                "whole_original_view_retained": True,
                "placement": "after_whole_historical_quotation_with_exact_pixel_coordinates"}
            ctx["image_bindings"].append(detail_binding)
            ctx["_pending_images"].append({"paragraph": detail_picture_p,
                "bytes": embedded, "media_type": media, "pixels": checked["pixels"],
                "binding": detail_binding, "viewport_pixels": list(region["box_pixels"])})
            ctx["_quotation_owners"].append({"key": detail_key,
                "input_pointer": detail_pointer, "parent_id": parent["id"],
                "binding": detail_binding, "_picture": detail_picture_p, "_caption": detail_caption_p})
            for field, value, owners in (("label", region["label"], [label_p]),
                                          ("box_pixels", region["box_pixels"], [detail_caption_p])):
                detail_fields.append({"input_pointer": detail_pointer + "/" + field,
                    "input_value": value, "input_type": type(value).__name__,
                    "content_review_status": "pending", "representation": "explicit_source_pixel_detail_view",
                    "quotation_key": key, "quotation_detail_key": detail_key,
                    "rendered_fragments": [own_text(p) for p in owners],
                    "_paragraph": owners[0], "_primary_paragraphs": owners})
        if ctx.get("editorial"):
            notes = ctx.setdefault("attachment_notes", {})
            if attachment["id"] not in notes:
                notes[attachment["id"]] = {"key": f"A{len(notes) + 1}",
                    "attachment": dict(attachment), "usages": []}
            notes[attachment["id"]]["usages"].append({"entity_id": parent["id"],
                "entity_name": parent.get("name"), "slot": binding["slot"],
                "slot_label": f"역사적 원문 그림 인용 [{key}] · {DISCLOSURE}"})
            fields = [{"input_pointer": pointer + "/" + field, "input_value": value,
                       "input_type": type(value).__name__, "content_review_status": "pending",
                       "representation": "source_verified_historical_quotation",
                       "quotation_key": key, "rendered_fragments": [own_text(p) for p in paragraphs],
                       "_paragraph": caption_p, "_primary_paragraphs": paragraphs}
                      for field, value in quote.items()]
            fields.extend(detail_fields)
            ctx.setdefault("meaning_map", []).append({"input_pointer": pointer,
                "entity_id": parent["id"], "entity_name": parent.get("name"),
                "quotation_key": key, "fields": fields})


def finalize_quotation_owners(doc, ctx):
    records = []
    for record in ctx.get("_quotation_owners", []):
        owners = {}
        for name in ("picture", "caption"):
            paragraph = record["_" + name]
            member = next(member for member in doc.sections
                          if doc.xml(member) in paragraph.iterancestors())
            owners[name] = {"section": member,
                            "xpath": doc.xml(member).getroottree().getpath(paragraph)}
        record["binding"]["owners"] = owners
        records.append({"key": record["key"], "input_pointer": record["input_pointer"],
                        "parent_id": record["parent_id"], "owners": owners,
                        "historical_reference_only": True, "native_QA_status": "pending"})
    return records


def assert_quotation_files_stable(ctx):
    """Check used local source/bitmap bytes again at the save boundary."""
    for path, expected in ctx.get("_quotation_file_snapshots", {}).items():
        try:
            actual = sha256(Path(path).read_bytes()).hexdigest()
        except OSError as exc:
            raise ValueError("Quotation source/bitmap became unavailable before commit: " + path) from exc
        if actual != expected:
            raise ValueError("Quotation source/bitmap changed before commit: " + path)


def reject_quotation_output_collisions(data, base_dir, planned_paths):
    """Reject write targets that alias supplied quotation inputs before writes."""
    selected = list(entries(data))
    if not selected:
        return
    sources = {item["id"]: item for item in data["sources"]}
    attachments = {item["id"]: item for item in data["attachments"]}
    inputs = {_local_path(record, base_dir)
              for _, _, quote in selected
              for record in (sources[quote["source_document_id"]], attachments[quote["attachment_id"]])}
    for source in inputs:
        for target in planned_paths:
            target = Path(target)
            if (source.absolute() == target.absolute()
                    or source.resolve() == target.resolve()
                    or source.exists() and target.exists() and source.samefile(target)):
                raise QuotationInputCollision("Quotation input aliases a planned output; no input may be overwritten: " + str(source))
