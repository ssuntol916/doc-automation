"""Small, source-preserving HWPX editing primitives, not a layout renderer."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import struct
import tempfile
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from lxml import etree as ET
from PIL import Image

from .hwpx import NS, inline_text, local, nearest, own_text, parse_xml, section_order
from .sourcebinding import profile_for_sha256

HP = "{" + NS["hp"] + "}"
HC = "{" + NS["hc"] + "}"
OPF = "{" + NS["opf"] + "}"
HH = "{" + NS["hh"] + "}"
SCOPE_CONTROLS = {"secPr", "colPr", "header", "footer", "pageNum", "newNum", "pageHiding"}
SHAPES = {"tbl", "pic", "ole", "equation", "chart", "rect", "ellipse", "arc", "polygon",
          "curve", "line", "connectLine", "container", "video", "textart"}
TEXT_INLINE = {"lineBreak", "br", "tab", "fwSpace", "nbSpace", "nbHyphen", "softHyphen"}
PROTECTED_CONTENT = SHAPES | SCOPE_CONTROLS | {"ctrl", "footNote", "endNote", "fieldBegin", "fieldEnd"}
SENTINEL_PARAGRAPH_IDS = {"0", "2147483648"}
HANCOM_MAC_12_30_PNG_METADATA = "hancom-mac-12.30.0-png"


class ComposeError(ValueError):
    """An edit cannot be performed without an explicit structural decision."""


def _tag(name):
    return HP + name


def _xml_bytes(root):
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


def _fingerprint(node):
    return sha256(ET.tostring(node)).digest()


def _load(path):
    with ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)):
            raise ComposeError("Duplicate ZIP member names")
        for name in names:
            posix = PurePosixPath(name)
            if posix.is_absolute() or ".." in posix.parts or "\\" in name:
                raise ComposeError(f"Unsafe ZIP member: {name}")
        if archive.testzip():
            raise ComposeError("ZIP CRC failure")
        if "mimetype" not in names or archive.read("mimetype").strip() != b"application/hwp+zip":
            raise ComposeError("Not an application/hwp+zip package")
        sections = section_order(archive)
        entries = {item.filename: archive.read(item) for item in infos}
        roots = {name: parse_xml(data) for name, data in entries.items()
                 if name.endswith((".xml", ".hpf"))}
    return infos, entries, roots, sections


def _identity_counts(roots, sections):
    counts = Counter()
    for section in sections:
        for node in roots[section].iter():
            name, value = local(node), node.get("id")
            if not value or name in {"secPr", "colPr", "subList"}:
                continue
            family = "object" if name in SHAPES else name
            counts[(family, value)] += 1
    return counts


def _resolve_href(href, entries):
    href = href.lstrip("/")
    if href in entries:
        return href
    relative = str(PurePosixPath("Contents") / href)
    return relative if relative in entries else None


def _check(entries, roots, sections, baseline_ids=None):
    errors, warnings = [], []
    package = roots.get("Contents/content.hpf")
    header = roots.get("Contents/header.xml")
    if package is None or header is None:
        return {"valid": False, "errors": ["Missing package/header XML"], "warnings": []}
    if ET.QName(header).namespace != NS["hh"]:
        errors.append("Unsupported header namespace")
    items = [node for node in package.iter() if local(node) == "item"]
    item_ids = [node.get("id") for node in items]
    if len(item_ids) != len(set(item_ids)):
        errors.append("Duplicate OPF manifest id")
    manifest = {node.get("id"): node for node in items}
    for item in items:
        if _resolve_href(item.get("href", ""), entries) is None:
            errors.append(f"Missing manifest resource: {item.get('href')}")
    for node in package.iter():
        if local(node) == "itemref" and node.get("idref") not in manifest:
            errors.append(f"Unresolved spine item: {node.get('idref')}")
    ordered_sections = []
    for node in package.iter():
        if local(node) == "itemref" and node.get("idref") in manifest:
            item = manifest[node.get("idref")]
            if re.search(r"(^|/)section\d+\.xml$", item.get("href", "")):
                ordered_sections.append(_resolve_href(item.get("href"), entries))
    if ordered_sections != list(sections):
        errors.append("Section order differs from the loaded OPF spine")
    definitions = {attr: {node.get("id") for node in header.iter() if local(node) == kind}
                   for attr, kind in (("paraPrIDRef", "paraPr"), ("charPrIDRef", "charPr"),
                                      ("styleIDRef", "style"), ("borderFillIDRef", "borderFill"))}
    for kind in ("paraPr", "charPr", "style", "borderFill"):
        ids = [node.get("id") for node in header.iter() if local(node) == kind]
        if len(ids) != len(set(ids)):
            errors.append(f"Duplicate local {kind} definition id")
    field_begins, field_ends = {}, []
    tables = pictures = paragraphs = 0
    for section in sections:
        root = roots[section]
        if ET.QName(root).namespace != NS["hs"]:
            errors.append(f"Unsupported section namespace: {section}")
        first_p = root.find("hp:p", NS)
        section_controls = list(root.iter(_tag("secPr")))
        if (len(section_controls) != 1 or first_p is None
                or nearest(section_controls[0], _tag("p")) is not first_p
                or section_controls[0].getparent().tag != _tag("run")):
            errors.append(f"secPr must remain in its section's first top-level paragraph: {section}")
        for node in root.iter():
            name = local(node)
            paragraphs += name == "p"
            if name == "ctrl" and not len(node):
                errors.append(f"Empty hp:ctrl is not a valid semantic control: {section}")
            required = {"p": {"id", "paraPrIDRef", "styleIDRef"}, "run": {"charPrIDRef"}}.get(name, set())
            if required - set(node.attrib):
                errors.append(f"Missing {name} attributes in {section}: {sorted(required - set(node.attrib))}")
            for attr, known in definitions.items():
                if attr in node.attrib and node.get(attr) not in known:
                    errors.append(f"Unresolved {attr}={node.get(attr)} in {section}")
            binary_id = node.get("binaryItemIDRef")
            if binary_id is not None and binary_id not in manifest:
                errors.append(f"Unresolved image resource: {binary_id}")
            if name == "pic":
                pictures += 1
            if name == "fieldBegin":
                field_begins[node.get("id")] = node.get("fieldid")
            if name == "fieldEnd":
                field_ends.append(node)
            if name != "tbl":
                continue
            tables += 1
            rows = node.findall("hp:tr", NS)
            try:
                nr, nc = int(node.get("rowCnt", "0")), int(node.get("colCnt", "0"))
                if nr != len(rows) or nr < 1 or nc < 1:
                    raise ComposeError("rowCnt/colCnt mismatch")
                occupied = set()
                for row_index, row in enumerate(rows):
                    for cell in row.findall("hp:tc", NS):
                        address, span = cell.find("hp:cellAddr", NS), cell.find("hp:cellSpan", NS)
                        if address is None or span is None:
                            raise ComposeError("Missing cellAddr/cellSpan")
                        r, c = int(address.get("rowAddr")), int(address.get("colAddr"))
                        rs, cs = int(span.get("rowSpan")), int(span.get("colSpan"))
                        if r != row_index or min(r, c) < 0 or min(rs, cs) < 1 or r + rs > nr or c + cs > nc:
                            raise ComposeError("Cell span/address outside table")
                        for rr in range(r, r + rs):
                            for cc in range(c, c + cs):
                                if (rr, cc) in occupied:
                                    raise ComposeError("Overlapping merged cells")
                                occupied.add((rr, cc))
                if len(occupied) != nr * nc:
                    raise ComposeError("Uncovered table grid cells")
            except (TypeError, ValueError) as exc:
                errors.append(f"Invalid table {node.get('id')} in {section}: {exc}")
    end_counts = Counter(end.get("beginIDRef") for end in field_ends)
    for end in field_ends:
        begin = end.get("beginIDRef")
        if begin not in field_begins or end.get("fieldid") != field_begins[begin]:
            errors.append(f"Unpaired fieldEnd: {begin}")
    for begin in field_begins:
        if end_counts[begin] != 1:
            errors.append(f"fieldBegin must have one matching fieldEnd: {begin}")
    counts = _identity_counts(roots, sections)
    for identity, count in counts.items():
        if count < 2:
            continue
        permitted = (baseline_ids or {}).get(identity, 1)
        if baseline_ids is None and identity[0] == "p" and identity[1] in SENTINEL_PARAGRAPH_IDS:
            permitted = count
        if count > permitted:
            errors.append(f"New duplicate instance id: {identity} count={count}")
        else:
            warnings.append(f"Preserved source duplicate id: {identity} count={count}")
    return {"valid": not errors, "errors": sorted(set(errors)), "warnings": warnings,
            "section_names": list(sections), "table_count": tables,
            "picture_count": pictures, "paragraph_count": paragraphs}


def validate_package(path, source_path=None):
    """Validate mechanics; pass the source to permit only its existing duplicate IDs."""
    try:
        infos, entries, roots, sections = _load(path)
        baseline = None
        if source_path is not None:
            _, _, original, original_sections = _load(source_path)
            baseline = _identity_counts(original, original_sections)
        report = _check(entries, roots, sections, baseline)
        if infos[0].filename != "mimetype" or infos[0].compress_type != ZIP_STORED:
            report["errors"].append("mimetype must be first and uncompressed")
            report["valid"] = False
        return report
    except (ValueError, KeyError, OSError, BadZipFile, ET.XMLSyntaxError) as exc:
        return {"valid": False, "errors": [str(exc)], "warnings": []}


class TemplateDocument:
    """Edit one source package while preserving unrelated ZIP entries and XML bytes."""

    def __init__(self, template_path, expected_sha256=None, *, profile_path=None):
        self.template_path = Path(template_path).expanduser().resolve()
        raw = self.template_path.read_bytes()
        self.source_sha256 = sha256(raw).hexdigest()
        self.source_profile = None
        if profile_path is not None:
            self.source_profile = json.loads(Path(profile_path).read_text())
        else:
            self.source_profile = profile_for_sha256(self.source_sha256)
        baseline_hash = expected_sha256 or (self.source_profile or {}).get("sha256")
        if baseline_hash and self.source_sha256 != baseline_hash:
            raise ComposeError("Template fingerprint does not match the approved source profile")
        self._infos, self._entries, self._roots, self.sections = _load(BytesIO(raw))
        self._initial_xml = {name: _fingerprint(root) for name, root in self._roots.items()}
        self._initial_p = {p: _fingerprint(p) for name in self.sections for p in self._roots[name].iter(_tag("p"))}
        # Retain source-owned text for source-specific selectors after a renderer
        # has replaced TOC contents or body headings. This is not saved in XML.
        self._source_paragraph_text = {p: own_text(p) for name in self.sections for p in self._roots[name].iter(_tag("p"))}
        self._source_paragraph_locations = {p: (name, p.getroottree().getpath(p))
                                            for name in self.sections for p in self._roots[name].iter(_tag("p"))}
        self._baseline_ids = _identity_counts(self._roots, self.sections)
        self._used_ids = {value for root in self._roots.values() for node in root.iter()
                          for attr, value in node.attrib.items() if attr in {"id", "instid", "fieldid"} and value}
        self._next_id = max((int(value) for value in self._used_ids if value.isdigit()), default=0) + 1
        self._new_entries = {}
        self._colour_cache = {}
        self._paragraph_keep_cache = {}
        self._inserted_picture_metadata = []

    @staticmethod
    def _units(value, *, positive=False):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ComposeError("A finite numeric layout value is required")
        if value < 0 or (positive and value <= 0):
            raise ComposeError("Layout dimensions must be positive" if positive else "Layout dimensions cannot be negative")
        result = round(value)
        if positive and result <= 0:
            raise ComposeError("Layout dimension rounds to zero")
        return result

    @classmethod
    def _mm_units(cls, value, *, positive=False):
        cls._units(value, positive=positive)
        return round(value * 7200 / 25.4)

    def _derived_definition(self, kind, source_id, definition):
        """Reuse exact local payloads; numeric IDs never cross package boundaries."""
        names = {"charPr": "charProperties", "paraPr": "paraProperties"}
        properties = self.xml("Contents/header.xml").find(".//hh:" + names[kind], NS)
        if properties is None:
            raise ComposeError("Missing local " + names[kind])
        definition.attrib.pop("id", None)
        payload = ET.tostring(definition, method="c14n", exclusive=True)
        for current in properties:
            copy = deepcopy(current)
            copy.attrib.pop("id", None)
            if ET.tostring(copy, method="c14n", exclusive=True) == payload:
                return current.get("id")
        new_id = str(max((int(p.get("id")) for p in properties if p.get("id", "").isdigit()), default=-1) + 1)
        definition.set("id", new_id)
        properties.append(definition)
        properties.set("itemCnt", str(len(properties)))
        return new_id

    def use_character_style(self, scope, *, font=None, size_pt=None, bold=None, italic=None, colour=None,
                            spacing_percent=None, ratio_percent=None, include_headers=False):
        """Derive only requested character attributes on text-owning runs.

        Other direct formatting and all inline semantic objects remain intact.
        A string font applies to all seven script families; a dict selects script
        names (hangul/latin/hanja/japanese/other/symbol/user) explicitly.
        """
        scripts = {name.lower(): name for name in ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")}
        fonts = {name: font for name in scripts} if isinstance(font, str) else (font or {})
        if not isinstance(fonts, dict) or any(k not in scripts or not isinstance(v, str) or not v.strip() for k, v in fonts.items()):
            raise ComposeError("Font must name a face or explicit supported script faces")
        height = self._units(size_pt * 100, positive=True) if size_pt is not None and not isinstance(size_pt, bool) else None
        if size_pt is not None and (isinstance(size_pt, bool) or height is None):
            raise ComposeError("Font size must be positive points")
        if any(v is not None and not isinstance(v, bool) for v in (bold, italic)):
            raise ComposeError("Bold and italic must be bool or None")
        if colour is not None and (not isinstance(colour, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", colour)):
            raise ComposeError("Text colour must be #RRGGBB")
        if spacing_percent is not None and (isinstance(spacing_percent, bool) or not isinstance(spacing_percent, (int, float)) or not math.isfinite(spacing_percent) or not -50 <= spacing_percent <= 50):
            raise ComposeError("Character spacing must be a percentage between -50 and 50")
        ratio = self._units(ratio_percent, positive=True) if ratio_percent is not None else None
        if ratio is not None and ratio > 200:
            raise ComposeError("Character width ratio must not exceed 200 percent")
        header = self.xml("Contents/header.xml")
        known = {p.get("id"): p for p in header.findall(".//hh:charPr", NS)}
        candidates = [scope] if scope.tag == _tag("run") else list(scope.iter(_tag("run")))
        if scope.tag == _tag("p"):
            candidates = [r for r in candidates if nearest(r, _tag("p")) is scope]
        if not include_headers:
            candidates = [r for r in candidates if not any(local(a) in {"header", "footer", "footNote", "endNote"} for a in r.iterancestors())]
        runs = [r for r in candidates if any(inline_text(t) for t in r.iter(_tag("t")) if nearest(t, _tag("run")) is r)]
        if any(r.get("charPrIDRef") not in known for r in runs):
            raise ComposeError("Missing local charPr definition")
        faces = {f.get("lang"): f for f in header.findall(".//hh:fontface", NS)}
        if any(scripts[k] not in faces for k in fonts):
            raise ComposeError("Source has no requested script fontface family")
        if fonts and any(known[r.get("charPrIDRef")].find("hh:fontRef", NS) is None for r in runs):
            raise ComposeError("Source charPr has no fontRef")
        for name, value in (("spacing", spacing_percent), ("ratio", ratio)):
            if value is not None and any(known[r.get("charPrIDRef")].find("hh:" + name, NS) is None for r in runs):
                raise ComposeError("Source charPr has no supported " + name)
        font_ids = {}
        for script, face_name in fonts.items():
            family = faces[scripts[script]]
            match = next((f for f in family if f.get("face") == face_name), None)
            if match is None:
                identifier = str(max((int(f.get("id")) for f in family if f.get("id", "").isdigit()), default=-1) + 1)
                match = ET.SubElement(family, HH + "font", id=identifier, face=face_name, type="TTF", isEmbedded="0")
                family.set("fontCnt", str(len(family)))
            font_ids[script] = match.get("id")
        changed = 0
        order = ["fontRef", "ratio", "spacing", "relSz", "offset", "bold", "italic", "underline", "strikeout", "outline", "shadow"]
        for run in runs:
            source_id = run.get("charPrIDRef")
            definition = deepcopy(known[source_id])
            if height is not None:
                definition.set("height", str(height))
            if colour is not None:
                definition.set("textColor", colour.upper())
            if fonts:
                definition.find("hh:fontRef", NS).attrib.update(font_ids)
            for name, value in (("spacing", spacing_percent), ("ratio", ratio)):
                if value is not None:
                    node = definition.find("hh:" + name, NS)
                    if node is None:
                        raise ComposeError("Source charPr has no supported " + name)
                    for script in scripts:
                        if script in node.attrib:
                            node.set(script, str(round(value)))
            for name, enabled in (("bold", bold), ("italic", italic)):
                if enabled is None:
                    continue
                existing = definition.find("hh:" + name, NS)
                if not enabled and existing is not None:
                    definition.remove(existing)
                elif enabled and existing is None:
                    insert = next((i for i, child in enumerate(definition) if local(child) in order and order.index(local(child)) > order.index(name)), len(definition))
                    definition.insert(insert, ET.Element(HH + name))
            target_id = self._derived_definition("charPr", source_id, definition)
            if target_id != source_id:
                run.set("charPrIDRef", target_id)
                changed += 1
                parent = nearest(run, _tag("p"))
                if parent is not None:
                    self.invalidate_layout(parent)
        return changed

    def use_paragraph_style(self, scope, *, line_spacing_percent=None, align=None, break_latin=None,
                            break_non_latin=None, keep_lines=None, keep_with_next=None, include_headers=False):
        """Derive requested paragraph properties, including both switch branches."""
        spacing = self._units(line_spacing_percent, positive=True) if line_spacing_percent is not None else None
        if align is not None and align not in {"LEFT", "RIGHT", "CENTER", "JUSTIFY", "DISTRIBUTE", "DISTRIBUTE_SPACE"}:
            raise ComposeError("Unsupported paragraph alignment")
        if any(value is not None and value not in {"KEEP_WORD", "BREAK_WORD"} for value in (break_latin, break_non_latin)):
            raise ComposeError("Unsupported word break policy")
        if any(v is not None and not isinstance(v, bool) for v in (keep_lines, keep_with_next)):
            raise ComposeError("Paragraph keep flags must be bool or None")
        known = {p.get("id"): p for p in self.xml("Contents/header.xml").findall(".//hh:paraPr", NS)}
        paragraphs = [scope] if scope.tag == _tag("p") else list(scope.iter(_tag("p")))
        if not include_headers:
            paragraphs = [p for p in paragraphs if not any(local(a) in {"header", "footer", "footNote", "endNote"} for a in p.iterancestors())]
        prepared = []
        for paragraph in paragraphs:
            source_id = paragraph.get("paraPrIDRef")
            if source_id not in known:
                raise ComposeError("Missing local paraPr definition")
            definition = deepcopy(known[source_id])
            if spacing is not None:
                nodes = definition.findall(".//hh:lineSpacing", NS)
                if not nodes:
                    raise ComposeError("Source paraPr has no supported lineSpacing")
                for node in nodes:
                    node.attrib.update({"type": "PERCENT", "value": str(spacing), "unit": "HWPUNIT"})
            if align is not None:
                node = definition.find("hh:align", NS)
                if node is None:
                    raise ComposeError("Source paraPr has no align")
                node.set("horizontal", align)
            requested = {k: v for k, v in (("breakLatinWord", break_latin), ("breakNonLatinWord", break_non_latin),
                ("keepLines", None if keep_lines is None else str(int(keep_lines))),
                ("keepWithNext", None if keep_with_next is None else str(int(keep_with_next)))) if v is not None}
            if requested:
                node = definition.find("hh:breakSetting", NS)
                if node is None or any(k not in node.attrib for k in requested):
                    raise ComposeError("Source paraPr has no supported breakSetting")
                node.attrib.update(requested)
            prepared.append((paragraph, source_id, definition))
        changed = 0
        for paragraph, source_id, definition in prepared:
            target_id = self._derived_definition("paraPr", source_id, definition)
            if target_id != source_id:
                paragraph.set("paraPrIDRef", target_id)
                self.invalidate_layout(paragraph)
                changed += 1
        return changed

    @property
    def source_profile_id(self):
        return (self.source_profile or {}).get("id")

    def root(self, section=0):
        return self._roots[self.sections[section]]

    def xml(self, member):
        return self._roots[member]

    def tables(self, section=0):
        return list(self.root(section).iter(_tag("tbl")))

    def paragraphs(self, section=0):
        return list(self.root(section).iter(_tag("p")))

    @staticmethod
    def cell(table, row, col, *, covered=False):
        for tr in table.findall("hp:tr", NS):
            for cell in tr.findall("hp:tc", NS):
                address, span = cell.find("hp:cellAddr", NS), cell.find("hp:cellSpan", NS)
                r, c = int(address.get("rowAddr")), int(address.get("colAddr"))
                if (r, c) == (row, col):
                    return cell
                if covered and r <= row < r + int(span.get("rowSpan")) and c <= col < c + int(span.get("colSpan")):
                    return cell
        raise ComposeError(f"No cell starts at logical R{row}C{col}; use covered=True for a merged coordinate")

    def _fresh_id(self):
        while str(self._next_id) in self._used_ids:
            self._next_id += 1
        result = str(self._next_id)
        if self._next_id > 4294967295:
            self._next_id = 1
            return self._fresh_id()
        self._used_ids.add(result)
        self._next_id += 1
        return result

    @staticmethod
    def invalidate_layout(paragraph):
        """Remove derived line caches, never page, table, shape or margin geometry."""
        for p in [paragraph, *[a for a in paragraph.iterancestors() if a.tag == _tag("p")]]:
            for cache in list(p):
                if local(cache) == "linesegarray":
                    p.remove(cache)

    @staticmethod
    def _write_text(t, text):
        if not isinstance(text, str):
            raise TypeError("Document text must be a string; render unknown values explicitly")
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", text):
            raise ComposeError("Text contains characters forbidden by XML 1.0")
        if any(local(child) not in TEXT_INLINE for child in t):
            raise ComposeError("Text node contains an unsupported semantic inline object")
        for child in list(t):
            t.remove(child)
        parts = re.split(r"([\n\t\u3000\u00a0])", text.replace("\r\n", "\n").replace("\r", "\n"))
        t.text = parts[0]
        controls = {"\n": "lineBreak", "\t": "tab", "\u3000": "fwSpace", "\u00a0": "nbSpace"}
        for index in range(1, len(parts), 2):
            child = ET.SubElement(t, _tag(controls[parts[index]]))
            if parts[index] == "\t":
                child.attrib.update({"width": "0", "leader": "0", "type": "0"})
            child.tail = parts[index + 1]

    def set_text_node(self, t, text):
        if t.tag != _tag("t"):
            raise ComposeError("Expected hp:t")
        self._write_text(t, text)
        p = nearest(t, _tag("p"))
        if p is not None:
            self.invalidate_layout(p)

    def set_paragraph_text(self, paragraph, text):
        """Replace only this paragraph's own text, retaining runs and semantic objects."""
        if paragraph.tag != _tag("p"):
            raise ComposeError("Expected hp:p")
        if not isinstance(text, str):
            raise TypeError("Document text must be a string; render unknown values explicitly")
        if any(local(node) in {"fieldBegin", "fieldEnd"} and nearest(node, _tag("p")) is paragraph
               for node in paragraph.iter()):
            raise ComposeError("Do not replace a field result as ordinary paragraph text")
        texts = [node for node in paragraph.iter(_tag("t")) if nearest(node, _tag("p")) is paragraph]
        if not texts:
            runs = paragraph.findall("hp:run", NS)
            run = runs[0] if runs else ET.SubElement(paragraph, _tag("run"), charPrIDRef="0")
            texts = [ET.SubElement(run, _tag("t"))]
        # Check before changing any nodes so unsupported inline content is non-destructive.
        if any(local(child) not in TEXT_INLINE for t in texts for child in t):
            raise ComposeError("Unsupported semantic inline object in paragraph text")
        self._write_text(texts[0], text)
        for t in texts[1:]:
            self._write_text(t, "")
        self.invalidate_layout(paragraph)
        return paragraph

    def set_cell_text(self, cell, text):
        """Fill a plain-text cell; refuse to discard drawings, tables or controls."""
        if cell.tag != _tag("tc"):
            raise ComposeError("Expected hp:tc")
        if not isinstance(text, str):
            raise TypeError("Document text must be a string; render unknown values explicitly")
        if any(local(node) in PROTECTED_CONTENT for node in cell.iter() if node is not cell):
            raise ComposeError("Cell contains semantic objects; edit its paragraphs/objects explicitly")
        sublist = cell.find("hp:subList", NS)
        if sublist is None:
            raise ComposeError("Cell has no hp:subList")
        paragraphs = sublist.findall("hp:p", NS)
        if not paragraphs:
            p = self.new_paragraph("")
            sublist.append(p)
            paragraphs = [p]
        self.set_paragraph_text(paragraphs[0], text)
        for p in paragraphs[1:]:
            sublist.remove(p)
        return cell

    def new_paragraph(self, text="", *, prototype=None):
        if prototype is None:
            prototype = next(self.root().iter(_tag("p")))
        p = ET.Element(_tag("p"), attrib=dict(prototype.attrib))
        p.set("id", self._fresh_id())
        p.set("pageBreak", "0")
        p.set("columnBreak", "0")
        source_run = prototype.find("hp:run", NS)
        attrs = dict(source_run.attrib) if source_run is not None else {"charPrIDRef": "0"}
        run = ET.SubElement(p, _tag("run"), attrib=attrs)
        t = ET.SubElement(run, _tag("t"))
        self._write_text(t, text)
        return p

    def append_text(self, container, text, *, prototype=None):
        p = self.new_paragraph(text, prototype=prototype)
        container.append(p)
        ancestor = nearest(container, _tag("p"))
        if ancestor is not None:
            self.invalidate_layout(ancestor)
        return p

    def use_text_colour(self, scope, colour="#000000"):
        """Change text colour through added local charPr definitions, never source styles."""
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
            raise ComposeError("Text colour must be #RRGGBB")
        colour = colour.upper()
        properties = self.xml("Contents/header.xml").find(".//hh:charProperties", NS)
        if properties is None:
            raise ComposeError("Missing local charProperties definitions")
        known = {node.get("id"): node for node in properties if local(node) == "charPr"}
        next_id = max((int(value) for value in known if value.isdigit()), default=-1) + 1
        changed = 0
        for run in scope.iter(_tag("run")):
            # A run enclosing a table does not own the text of nested cell runs.
            owned = [t for t in run.iter(_tag("t")) if nearest(t, _tag("run")) is run]
            if not any(inline_text(t) for t in owned):
                continue
            old_id = run.get("charPrIDRef")
            if old_id not in known:
                raise ComposeError(f"Missing local charPr definition: {old_id}")
            if known[old_id].get("textColor", "").upper() == colour:
                continue
            key = old_id, colour
            new_id = self._colour_cache.get(key)
            if new_id is None:
                definition = deepcopy(known[old_id])
                new_id = str(next_id)
                next_id += 1
                definition.set("id", new_id)
                definition.set("textColor", colour)
                properties.append(definition)
                known[new_id] = definition
                self._colour_cache[key] = new_id
            run.set("charPrIDRef", new_id)
            changed += 1
            p = nearest(run, _tag("p"))
            if p is not None:
                self.invalidate_layout(p)
        properties.set("itemCnt", str(len(known)))
        return changed

    def blacken_text_runs(self, scope):
        return self.use_text_colour(scope, "#000000")

    def use_table_pagination(self, table, *, break_mode=None, inline=None):
        """Change explicit table flow flags without changing cell geometry.

        CELL permits native cell contents to continue onto another page. An
        inline anchor keeps following body paragraphs after the table in text
        order. Neither flag proves that native layout has retained all text.
        """
        if table.tag != _tag("tbl"):
            raise ComposeError("Expected hp:tbl for table pagination")
        if break_mode not in {None, "NONE", "TABLE", "CELL"}:
            raise ComposeError("Unsupported table page break mode")
        if inline is not None and not isinstance(inline, bool):
            raise ComposeError("Table inline flag must be bool or None")
        position = table.find("hp:pos", NS)
        if break_mode is not None and "pageBreak" not in table.attrib:
            raise ComposeError("Source table does not define pageBreak")
        if inline is not None and (position is None or "treatAsChar" not in position.attrib):
            raise ComposeError("Source table does not define treatAsChar")
        if break_mode is not None:
            table.set("pageBreak", break_mode)
        if inline is not None:
            position.set("treatAsChar", "1" if inline else "0")
        paragraph = nearest(table, _tag("p"))
        if paragraph is not None:
            self.invalidate_layout(paragraph)
        return table

    def set_page_layout(self, section=0, *, landscape=None, margins_mm=None, margins_hwp=None,
                        sync_header_footer_frames=False):
        """Change explicit page geometry; landscape is an orientation, not a width swap.

        HWPX stores short/long paper edges and WIDELY/NARROWLY respectively for
        portrait/landscape. Header/footer are separate distances from paper edge.
        Opt-in frame synchronization changes only direct section header/footer
        subList textWidth/textHeight, retaining their text, IDs and formatting.
        """
        if landscape is not None and not isinstance(landscape, bool):
            raise ComposeError("landscape must be bool or None")
        if not isinstance(sync_header_footer_frames, bool):
            raise ComposeError("sync_header_footer_frames must be bool")
        if margins_mm is not None and margins_hwp is not None:
            raise ComposeError("Specify page margins in one unit only")
        margins = margins_hwp if margins_hwp is not None else margins_mm
        allowed = {"left", "right", "top", "bottom", "header", "footer", "gutter"}
        if margins is not None and (not isinstance(margins, dict) or set(margins) - allowed):
            raise ComposeError("Unsupported page margin")
        values = {k: self._units(v) if margins_hwp is not None else self._mm_units(v) for k, v in (margins or {}).items()}
        root = self.root(section)
        page = root.find(".//hp:secPr/hp:pagePr", NS)
        margin = page.find("hp:margin", NS) if page is not None else None
        if page is None or margin is None:
            raise ComposeError("Source section has no pagePr/margin")
        target = dict(margin.attrib)
        target.update({k: str(v) for k, v in values.items()})
        orientation = ("NARROWLY" if landscape else "WIDELY") if landscape is not None else page.get("landscape")
        width, height = int(page.get("width")), int(page.get("height"))
        paper_width, paper_height = (max(width, height), min(width, height)) if orientation == "NARROWLY" else (min(width, height), max(width, height))
        if int(target.get("left", 0)) + int(target.get("right", 0)) + int(target.get("gutter", 0)) >= paper_width or int(target.get("top", 0)) + int(target.get("bottom", 0)) >= paper_height:
            raise ComposeError("Page margins consume the paper")
        frames = []
        if sync_header_footer_frames:
            body_width = paper_width - sum(int(target.get(key, 0)) for key in ("left", "right", "gutter"))
            for kind in ("header", "footer"):
                for frame in root.findall(f"hp:p/hp:run/hp:ctrl/hp:{kind}/hp:subList", NS):
                    if not {"textWidth", "textHeight"} <= set(frame.attrib):
                        raise ComposeError("Header/footer frame has no declared textWidth/textHeight")
                    frames.append((frame, {"kind": kind, "xpath": frame.getroottree().getpath(frame),
                        "before": {key: frame.get(key) for key in ("textWidth", "textHeight")},
                        "after": {"textWidth": str(body_width), "textHeight": target.get(kind, "0")}}))
        page.set("landscape", orientation)
        margin.attrib.update(target)
        for frame, report in frames:
            frame.attrib.update(report["after"])
        for paragraph in root.iter(_tag("p")):
            self.invalidate_layout(paragraph)
        return {"section": section, "landscape": orientation == "NARROWLY", "paper_width_hwp": paper_width,
                "paper_height_hwp": paper_height, "margins_hwp": {k: int(v) for k, v in margin.attrib.items()},
                "header_footer_frames": [report for _, report in frames]}

    def _check_boundary_spacers(self, before_paragraph, spacers):
        """Validate an explicitly selected empty suffix; never discard controls."""
        parent = before_paragraph.getparent()
        values = list(spacers)
        boundary = parent.index(before_paragraph)
        if values and (len(set(values)) != len(values) or list(parent)[boundary-len(values):boundary] != values):
            raise ComposeError("Boundary spacers must be the contiguous suffix before the split")
        definitions = {p.get("id"): p for p in self.xml("Contents/header.xml").findall(".//hh:paraPr", NS)}
        for paragraph in values:
            definition = definitions.get(paragraph.get("paraPrIDRef"))
            heading = definition.find("hh:heading", NS) if definition is not None else None
            breaks = definition.find("hh:breakSetting", NS) if definition is not None else None
            if (paragraph.tag != _tag("p") or own_text(paragraph) != ""
                    or paragraph.get("pageBreak", "0") != "0" or paragraph.get("columnBreak", "0") != "0"
                    or paragraph.get("merged", "0") != "0" or definition is None
                    or heading is not None and heading.get("type", "NONE") != "NONE"
                    or breaks is not None and breaks.get("pageBreakBefore", "0") != "0"
                    or any(local(node) not in {"p", "run", "t", "linesegarray", "lineseg"} for node in paragraph.iter())):
                raise ComposeError("Boundary spacer must be pure empty text without objects, numbering or controls")
        return values

    def split_section(self, before_paragraph, *, landscape=None, margins_mm=None, margins_hwp=None,
                      discard_boundary_spacers=()):
        """Move a top-level suffix into a new OPF section, preserving its objects.

        A fresh carrier copies section/column settings and active header/footer
        controls. PAGE restart controls stay with their original text anchors;
        the new section itself continues numbering (startNum.page=0).
        """
        parent = before_paragraph.getparent()
        if before_paragraph.tag != _tag("p") or parent not in [self._roots[n] for n in self.sections]:
            raise ComposeError("Section boundary must be a top-level paragraph")
        original_name = next(n for n in self.sections if self._roots[n] is parent)
        boundary = parent.index(before_paragraph)
        if boundary == 0:
            raise ComposeError("Cannot split before the section properties carrier")
        spacers = self._check_boundary_spacers(before_paragraph, discard_boundary_spacers)
        section_properties = parent.find("hp:p/hp:run/hp:secPr", NS)
        if section_properties is None:
            raise ComposeError("Source section has no first-paragraph secPr")
        # Validate the requested geometry before moving any existing content.
        original_page = deepcopy(section_properties.find("hp:pagePr", NS))
        original_index = self.sections.index(original_name)
        try:
            self.set_page_layout(original_index, landscape=landscape, margins_mm=margins_mm, margins_hwp=margins_hwp)
            page = deepcopy(section_properties.find("hp:pagePr", NS))
        finally:
            current_page = section_properties.find("hp:pagePr", NS)
            if original_page is not None and current_page is not None:
                section_properties.replace(current_page, original_page)
        for spacer in spacers:
            parent.remove(spacer)
        boundary -= len(spacers)
        new_root = ET.Element(parent.tag, attrib=dict(parent.attrib), nsmap=parent.nsmap)
        first = parent.find("hp:p", NS)
        source_run = before_paragraph.find("hp:run", NS)
        if source_run is None:
            source_run = first.find("hp:run", NS)
        run = ET.Element(_tag("run"), charPrIDRef=source_run.get("charPrIDRef") if source_run is not None else "0")
        settings = deepcopy(section_properties)
        settings.replace(settings.find("hp:pagePr", NS), page)
        start = settings.find("hp:startNum", NS)
        if start is not None:
            start.set("page", "0")
        run.append(settings)
        column = first.find("hp:run/hp:ctrl/hp:colPr", NS)
        if column is not None:
            ET.SubElement(run, _tag("ctrl")).append(deepcopy(column))
        # Explicitly carry active headers/footers instead of dropping them at
        # the new section boundary. Clone preserves paired fields/resources.
        active = {}
        for prior in list(parent)[:boundary]:
            for control in prior.findall("hp:run/hp:ctrl", NS):
                for child in control:
                    if local(child) in {"header", "footer"}:
                        active[(local(child), child.get("applyPageType", "BOTH"))] = control
        for control in dict.fromkeys(active.values()):
            run.append(self._clone(control))
        for node in list(parent)[boundary:]:
            parent.remove(node)
            new_root.append(node)
        # Use the actual first body paragraph as the carrier. A separate empty
        # paragraph would consume a native line and shift floating table anchors.
        before_paragraph.insert(0, run)
        # The new section supplies this boundary's page transition already.
        before_paragraph.set("pageBreak", "0")
        package = self.xml("Contents/content.hpf")
        manifest = package.find("opf:manifest", NS)
        spine = package.find("opf:spine", NS)
        if manifest is None or spine is None:
            raise ComposeError("Missing OPF manifest/spine")
        existing_ids = {item.get("id") for item in manifest}
        number = 0
        while f"Contents/section{number}.xml" in self._roots or f"section{number}" in existing_ids:
            number += 1
        name, identifier = f"Contents/section{number}.xml", f"section{number}"
        ET.SubElement(manifest, OPF + "item", id=identifier, href=name, attrib={"media-type": "application/xml"})
        source_id = next(item.get("id") for item in manifest if _resolve_href(item.get("href", ""), self._entries | self._new_entries) == original_name)
        source_ref = next(item for item in spine if item.get("idref") == source_id)
        spine.insert(spine.index(source_ref) + 1, ET.Element(OPF + "itemref", idref=identifier, linear="yes"))
        self.sections.insert(original_index + 1, name)
        self._roots[name] = new_root
        self._new_entries[name] = _xml_bytes(new_root)
        self.xml("Contents/header.xml").set("secCnt", str(len(self.sections)))
        for paragraph in new_root.iter(_tag("p")):
            self.invalidate_layout(paragraph)
        return original_index + 1

    def set_table_layout(self, table, *, column_widths_mm=None, column_widths_hwp=None,
                         cell_margins_mm=None, cell_margins_hwp=None):
        """Resize a logical grid, including merged cells, with explicit padding.

        Heights and object anchors are preserved. This is a declared geometry
        edit and does not imply that native pagination has been checked.
        """
        if table.tag != _tag("tbl"):
            raise ComposeError("Expected hp:tbl")
        if (column_widths_mm is None) == (column_widths_hwp is None):
            raise ComposeError("Specify exactly one set of logical column widths")
        raw = column_widths_hwp if column_widths_hwp is not None else column_widths_mm
        if not isinstance(raw, (list, tuple)) or len(raw) != int(table.get("colCnt", "0")):
            raise ComposeError("Column widths must match the logical colCnt")
        widths = [self._units(v, positive=True) if column_widths_hwp is not None else self._mm_units(v, positive=True) for v in raw]
        if any(v <= 0 for v in widths):
            raise ComposeError("Column widths round to zero")
        if cell_margins_mm is not None and cell_margins_hwp is not None:
            raise ComposeError("Specify cell margins in one unit only")
        margins = cell_margins_hwp if cell_margins_hwp is not None else cell_margins_mm
        if margins is not None and (not isinstance(margins, dict) or set(margins) - {"left", "right", "top", "bottom"}):
            raise ComposeError("Unsupported cell margin")
        padding = {k: self._units(v) if cell_margins_hwp is not None else self._mm_units(v) for k, v in (margins or {}).items()}
        prepared = []
        for row in table.findall("hp:tr", NS):
            for cell in row.findall("hp:tc", NS):
                address, span, size = (cell.find("hp:" + n, NS) for n in ("cellAddr", "cellSpan", "cellSz"))
                if address is None or span is None or size is None:
                    raise ComposeError("Missing cell geometry")
                start, count = int(address.get("colAddr")), int(span.get("colSpan"))
                if start < 0 or count < 1 or start + count > len(widths):
                    raise ComposeError("Cell span outside the logical columns")
                width = sum(widths[start:start + count])
                margin = cell.find("hp:cellMargin", NS)
                inherited = table.find("hp:inMargin", NS)
                active = margin if cell.get("hasMargin") == "1" else inherited
                current = {k: int(v) for k, v in active.attrib.items()} if active is not None else {}
                current.update(padding)
                if current.get("left", 0) + current.get("right", 0) >= width:
                    raise ComposeError("Cell padding consumes the logical width")
                prepared.append((cell, size, width, current))
        size = table.find("hp:sz", NS)
        if size is None:
            raise ComposeError("Table has no hp:sz")
        size.set("width", str(sum(widths)))
        size.set("widthRelTo", "ABSOLUTE")
        for cell, cell_size, width, current in prepared:
            cell_size.set("width", str(width))
            if margins is not None:
                cell.set("hasMargin", "1")
                margin = cell.find("hp:cellMargin", NS)
                if margin is None:
                    margin = ET.SubElement(cell, _tag("cellMargin"))
                margin.attrib.update({k: str(v) for k, v in current.items()})
            for paragraph in cell.findall("hp:subList/hp:p", NS):
                self.invalidate_layout(paragraph)
        parent = nearest(table, _tag("p"))
        if parent is not None:
            self.invalidate_layout(parent)
        return {"table_width_hwp": sum(widths), "column_widths_hwp": widths, "cell_margins_hwp": padding}

    def move_page_numbering(self, source_paragraphs, target_paragraph):
        """Move explicitly selected identical PAGE numbering pairs to one anchor.

        Selection of the actual body boundary belongs to a source profile. This
        operation preserves all text, section properties and unrelated controls;
        only duplicate identical pageNum/newNum pairs are consolidated.
        """
        sources = list(source_paragraphs)
        if not sources or len(set(sources)) != len(sources) or target_paragraph in sources:
            raise ComposeError("Page numbering requires distinct source and target paragraphs")
        if any(p.tag != _tag("p") for p in [*sources, target_paragraph]):
            raise ComposeError("Expected hp:p for page numbering anchors")
        parent = target_paragraph.getparent()
        if parent is None or any(p.getparent() is not parent for p in sources):
            raise ComposeError("Page numbering anchors must share a section container")
        if target_paragraph.findall("./hp:run/hp:ctrl/hp:pageNum", NS) or target_paragraph.findall("./hp:run/hp:ctrl/hp:newNum", NS):
            raise ComposeError("Target already owns page numbering")
        pairs = []
        for paragraph in sources:
            controls = [control for control in paragraph.findall("./hp:run/hp:ctrl", NS)
                        if any(local(child) in {"pageNum", "newNum"} for child in control)]
            if len(controls) != 2 or any(len(control) != 1 for control in controls):
                raise ComposeError("Source does not own a simple page numbering pair")
            nodes = {local(control[0]): control[0] for control in controls}
            if set(nodes) != {"pageNum", "newNum"} or nodes["newNum"].get("numType") != "PAGE":
                raise ComposeError("Source does not own a PAGE numbering pair")
            pairs.append((paragraph, controls, {name: dict(node.attrib) for name, node in nodes.items()}))
        if any(pair[2] != pairs[0][2] for pair in pairs[1:]):
            raise ComposeError("Conflicting numbering pairs require an explicit profile decision")
        selected = pairs[-1][1]
        run = ET.Element(_tag("run"), attrib=dict(selected[0].getparent().attrib))
        for paragraph, controls, _ in pairs:
            for control in controls:
                control.getparent().remove(control)
            self.invalidate_layout(paragraph)
        for control in selected:
            run.append(control)
        target_paragraph.insert(0, run)
        self.invalidate_layout(target_paragraph)
        return {"moved_pairs": 1, "consolidated_duplicate_pairs": len(pairs) - 1}

    def use_paragraph_keep(self, paragraph, *, keep_lines=None, keep_with_next=None):
        """Derive a local paraPr changing only explicitly requested keep flags.

        None preserves the inherited source value. This method selects no
        paragraphs automatically and never edits source paragraph definitions.
        """
        if paragraph.tag != _tag("p"):
            raise ComposeError("Expected hp:p for paragraph keep policy")
        if any(value is not None and not isinstance(value, bool) for value in (keep_lines, keep_with_next)):
            raise ComposeError("Paragraph keep flags must be bool or None")
        properties = self.xml("Contents/header.xml").find(".//hh:paraProperties", NS)
        if properties is None:
            raise ComposeError("Missing local paraProperties definitions")
        known = {node.get("id"): node for node in properties if local(node) == "paraPr"}
        old_id = paragraph.get("paraPrIDRef")
        if old_id not in known:
            raise ComposeError(f"Missing local paraPr definition: {old_id}")
        source_break = known[old_id].find("hh:breakSetting", NS)
        if source_break is None:
            raise ComposeError("Source paraPr has no supported hh:breakSetting")
        requested = {name: "1" if value else "0" for name, value in (
            ("keepLines", keep_lines), ("keepWithNext", keep_with_next)) if value is not None}
        if any(name not in source_break.attrib for name in requested):
            raise ComposeError("Source breakSetting does not define the requested keep attribute")
        if all(source_break.get(name) == value for name, value in requested.items()):
            return paragraph
        key = old_id, tuple(sorted(requested.items()))
        new_id = self._paragraph_keep_cache.get(key)
        if new_id is None:
            definition = deepcopy(known[old_id])
            new_id = str(max((int(value) for value in known if value.isdigit()), default=-1) + 1)
            definition.set("id", new_id)
            target_break = definition.find("hh:breakSetting", NS)
            for name, value in requested.items():
                target_break.set(name, value)
            properties.append(definition)
            properties.set("itemCnt", str(len(known) + 1))
            self._paragraph_keep_cache[key] = new_id
        paragraph.set("paraPrIDRef", new_id)
        self.invalidate_layout(paragraph)
        return paragraph

    def _clone(self, node, *, strip_scope_controls=False):
        clone = deepcopy(node)
        if any(child.get(key) not in {None, "", "0"} for child in clone.iter()
               for key in ("linkListIDRef", "linkListNextIDRef")):
            raise ComposeError("Linked text lists require an explicit cross-block reference mapping")
        if strip_scope_controls:
            scope_runs = set()
            for child in list(clone.iter()):
                if child is not clone and local(child) in SCOPE_CONTROLS:
                    run = nearest(child, _tag("run"))
                    if run is not None:
                        scope_runs.add(run)
                    child.getparent().remove(child)
            for child in list(clone.iter(_tag("ctrl"))):
                if not len(child):
                    child.getparent().remove(child)
            for run in scope_runs:
                if not len(run) and run.getparent() is not None:
                    run.getparent().remove(run)
        field_map = {}
        for child in clone.iter():
            name = local(child)
            value = child.get("id")
            if name == "fieldBegin":
                if value in field_map:
                    raise ComposeError("Ambiguous fieldBegin id in cloned block")
                field_map[value] = (self._fresh_id(), self._fresh_id())
                child.set("id", field_map[value][0])
                child.set("fieldid", field_map[value][1])
            elif value and name not in {"secPr", "colPr", "subList"}:
                child.set("id", self._fresh_id())
            if "instid" in child.attrib:
                child.set("instid", self._fresh_id())
        ended = set()
        for child in clone.iter():
            if local(child) == "fieldEnd":
                original = child.get("beginIDRef")
                if original not in field_map:
                    raise ComposeError("Cloned block splits a field pair")
                child.set("beginIDRef", field_map[original][0])
                child.set("fieldid", field_map[original][1])
                ended.add(original)
        if set(field_map) != ended:
            raise ComposeError("Cloned block splits a field pair")
        for p in clone.iter(_tag("p")):
            self.invalidate_layout(p)
        return clone

    def clone_paragraph(self, paragraph, *, insert_after=False, strip_scope_controls=True):
        if paragraph.tag != _tag("p"):
            raise ComposeError("Expected hp:p")
        clone = self._clone(paragraph, strip_scope_controls=strip_scope_controls)
        if insert_after:
            paragraph.addnext(clone)
        return clone

    def clone_table(self, table, *, insert_after=False):
        if table.tag != _tag("tbl"):
            raise ComposeError("Expected hp:tbl")
        clone = self._clone(table)
        if insert_after:
            table.addnext(clone)
            parent = nearest(table, _tag("p"))
            if parent is not None:
                self.invalidate_layout(parent)
        return clone

    @staticmethod
    def _row_extent(row):
        """Source minimum/cache estimate only; native application determines final layout."""
        heights = []
        for cell in row.findall("hp:tc", NS):
            span = int(cell.find("hp:cellSpan", NS).get("rowSpan"))
            size = cell.find("hp:cellSz", NS)
            stored = int(size.get("height", "0")) if size is not None else 0
            margin = cell.find("hp:cellMargin", NS)
            padding = sum(int(margin.get(key, "0")) for key in ("top", "bottom")) if margin is not None else 0
            text_height = 0
            for p in cell.findall("hp:subList/hp:p", NS):
                lines = p.findall("hp:linesegarray/hp:lineseg", NS)
                if lines:
                    low = min(int(line.get("vertpos", "0")) for line in lines)
                    high = max(int(line.get("vertpos", "0")) + int(line.get("vertsize", "0")) for line in lines)
                    text_height += high - low
            heights.append(max(stored, text_height + padding) / span)
        return max(1, round(max(heights, default=1)))

    def replace_body_rows(self, table, prototype_row_index, rows_count, *, header_rows=1):
        """Keep the prefix, replace its body with safe copies of one row prototype."""
        rows = table.findall("hp:tr", NS)
        if not isinstance(rows_count, int) or isinstance(rows_count, bool) or rows_count < 0:
            raise ComposeError("rows_count must be a nonnegative integer")
        if not 1 <= header_rows <= len(rows) or not 0 <= prototype_row_index < len(rows):
            raise ComposeError("Invalid header/prototype row index")
        prototype = rows[prototype_row_index]
        for cell in prototype.findall("hp:tc", NS):
            if int(cell.find("hp:cellSpan", NS).get("rowSpan")) != 1:
                raise ComposeError("A repeated row prototype cannot have vertical merged cells")
        for row in rows[:header_rows]:
            for cell in row.findall("hp:tc", NS):
                addr, span = cell.find("hp:cellAddr", NS), cell.find("hp:cellSpan", NS)
                if int(addr.get("rowAddr")) + int(span.get("rowSpan")) > header_rows:
                    raise ComposeError("Header/body boundary crosses a vertical merged cell")
        extent = self._row_extent(prototype)
        removed_extent = sum(self._row_extent(row) for row in rows[header_rows:])
        size = table.find("hp:sz", NS)
        old_height = int(size.get("height", "0")) if size is not None else 0
        # Build all copies before changing the source table, including paired-field checks.
        replacements = [self._clone(prototype) for _ in range(rows_count)]
        for row in rows[header_rows:]:
            table.remove(row)
        for index, row in enumerate(replacements, header_rows):
            for cell in row.findall("hp:tc", NS):
                cell.find("hp:cellAddr", NS).set("rowAddr", str(index))
            table.append(row)
        table.set("rowCnt", str(header_rows + rows_count))
        if size is not None:
            size.set("height", str(max(1, old_height - removed_extent + rows_count * extent)))
        ancestor = nearest(table, _tag("p"))
        if ancestor is not None:
            self.invalidate_layout(ancestor)
        return replacements

    def repeat_header_rows(self, table, count=1):
        """Explicitly mark real title rows; repeatHeader alone is insufficient."""
        rows = table.findall("hp:tr", NS)
        if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= len(rows):
            raise ComposeError("Invalid repeated header count")
        for row in rows:
            for cell in row.findall("hp:tc", NS):
                address, span = cell.find("hp:cellAddr", NS), cell.find("hp:cellSpan", NS)
                start = int(address.get("rowAddr"))
                if start < count < start + int(span.get("rowSpan")):
                    raise ComposeError("Repeated-header boundary crosses a merged cell")
        table.set("repeatHeader", "1" if count else "0")
        for index, row in enumerate(rows):
            for cell in row.findall("hp:tc", NS):
                cell.set("header", "1" if index < count else "0")
        ancestor = nearest(table, _tag("p"))
        if ancestor is not None:
            self.invalidate_layout(ancestor)

    def remove(self, node, *, allow_scope_controls=False):
        if not allow_scope_controls and any(local(child) in SCOPE_CONTROLS for child in node.iter()):
            raise ComposeError("Removal would discard section/page/header controls")
        parent = node.getparent()
        if parent is None:
            raise ComposeError("Cannot remove a detached/root element")
        p = nearest(node, _tag("p"))
        parent.remove(node)
        if p is not None:
            self.invalidate_layout(p)

    def add_binary(self, data, media_type, extension):
        if not isinstance(data, bytes) or not data:
            raise ComposeError("A nonempty bytes resource is required")
        extension = extension.lower().lstrip(".")
        if not re.fullmatch(r"[a-z0-9]{1,12}", extension) or not re.fullmatch(r"[\w.+-]+/[\w.+-]+", media_type):
            raise ComposeError("Invalid resource extension/media type")
        package = self.xml("Contents/content.hpf")
        manifest = next((node for node in package if local(node) == "manifest"), None)
        if manifest is None:
            raise ComposeError("Missing OPF manifest")
        ids = {node.get("id") for node in manifest}
        index = 1
        while f"generated{index}" in ids or f"BinData/generated{index}.{extension}" in self._entries | self._new_entries:
            index += 1
        binary_id = f"generated{index}"
        name = f"BinData/{binary_id}.{extension}"
        ET.SubElement(manifest, OPF + "item", id=binary_id, href=name,
                      attrib={"media-type": media_type, "isEmbeded": "1"})
        self._new_entries[name] = data
        return binary_id

    def set_picture_image(self, picture, data, media_type, extension):
        if picture.tag != _tag("pic"):
            raise ComposeError("Expected hp:pic")
        images = list(picture.iter(HC + "img"))
        if len(images) != 1:
            raise ComposeError("Expected exactly one image reference in picture")
        binary_id = self.add_binary(data, media_type, extension)
        images[0].set("binaryItemIDRef", binary_id)
        p = nearest(picture, _tag("p"))
        if p is not None:
            self.invalidate_layout(p)
        return binary_id

    def insert_picture(self, paragraph, data, media_type, extension, *, width_mm,
                       height_mm=None, description="", prototype=None,
                       raster_metadata_profile=None, viewport_pixels=None):
        """Insert an inline raster, preserving the complete embedded payload.

        The caller owns the semantic slot, attachment provenance and caption.
        This primitive keeps all pre-existing paragraph text and objects. It
        supports verified PNG/JPEG/BMP bytes rather than guessing file contents.
        The optional PNG metadata profile anticipates the observed loaded-image
        serialization of Hancom for Mac 12.30.0, not a general HWPX rule. It
        changes full-raster clip/dimension metadata on this new picture.
        An explicit pixel viewport is a Mac12.30 PNG representation verified by
        native coordinate probes. It uses [left, top, right, bottom) source
        pixels, retains the whole raster and fits the visible region's aspect.
        Existing source pictures and the default whole-image path are untouched.
        """
        if paragraph.tag != _tag("p"):
            raise ComposeError("Picture target must be hp:p")
        if not isinstance(data, bytes) or not data:
            raise ComposeError("A nonempty bytes image is required")
        if not isinstance(description, str):
            raise ComposeError("Picture description must be text")
        if raster_metadata_profile not in (None, HANCOM_MAC_12_30_PNG_METADATA):
            raise ComposeError("Unknown raster metadata profile")
        max_width = self._mm_units(width_mm, positive=True)
        max_height = self._mm_units(height_mm, positive=True) if height_mm is not None else None
        try:
            with Image.open(BytesIO(data)) as raster:
                image_format, pixels = raster.format, raster.size
                raster.verify()
        except Exception as exc:
            raise ComposeError("Image bytes could not be decoded") from exc
        formats = {"PNG": ("image/png", {"png"}), "JPEG": ("image/jpeg", {"jpg", "jpeg"}), "BMP": ("image/bmp", {"bmp"})}
        if image_format not in formats or media_type != formats[image_format][0] or extension.lower().lstrip(".") not in formats[image_format][1]:
            raise ComposeError("Image media type/extension differs from decoded raster")
        if raster_metadata_profile is not None and image_format != "PNG":
            raise ComposeError("The selected raster metadata profile is verified only for PNG")
        visible_pixels = pixels
        if viewport_pixels is not None:
            if raster_metadata_profile != HANCOM_MAC_12_30_PNG_METADATA:
                raise ComposeError("Pixel viewport requires the explicit Hancom Mac12.30 PNG profile")
            if (not isinstance(viewport_pixels, (list, tuple)) or len(viewport_pixels) != 4
                    or any(type(value) is not int for value in viewport_pixels)):
                raise ComposeError("Pixel viewport must contain four integer source coordinates")
            left, top, right, bottom = viewport_pixels
            if not (0 <= left < right <= pixels[0] and 0 <= top < bottom <= pixels[1]):
                raise ComposeError("Pixel viewport must be a nonempty rectangle inside the source raster")
            if (left, top, right, bottom) == (0, 0, *pixels):
                raise ComposeError("Use the default whole-image path for the complete source raster")
            visible_pixels = right - left, bottom - top
        scale = min(max_width / visible_pixels[0], max_height / visible_pixels[1]) if max_height is not None else max_width / visible_pixels[0]
        width, height = max(1, round(visible_pixels[0] * scale)), max(1, round(visible_pixels[1] * scale))
        # Source pixel extents at 96 dpi. Explicit transforms, clipping and
        # display extents describe one complete image; no hidden crop is added.
        original_width, original_height = pixels[0] * 75, pixels[1] * 75
        image_width, image_height = original_width, original_height
        if raster_metadata_profile == HANCOM_MAC_12_30_PNG_METADATA:
            # Actual 12.30.0 build6544 SaveAs after viewport traversal gave a
            # 96-dpi basis rounded to the nearest 60 HWPUNIT, positive ties up.
            # A 14-case boundary probe distinguished this from source-DPI and
            # unrounded models. PNG pHYs is intentionally not used. Keep the
            # authored shape coordinates and displayed pixel aspect unchanged.
            image_width = ((original_width + 30) // 60) * 60
            image_height = ((original_height + 30) // 60) * 60
        # Newly authored transforms use the precision emitted by actual Hancom
        # SaveAs. Existing source picture matrices are never normalized here.
        def matrix_number(value):
            if viewport_pixels is not None:
                # Tiny-raster/high-scale probes distinguish native float32
                # storage from merely formatting Python float64 to six places.
                try:
                    value = struct.unpack("f", struct.pack("f", value))[0]
                except (OverflowError, struct.error) as exc:
                    raise ComposeError("Viewport transform exceeds native float32 precision") from exc
                if not math.isfinite(value):
                    raise ComposeError("Viewport transform must be finite")
            rendered = f"{value:.6f}".rstrip("0").rstrip(".")
            if value and float(rendered or "0") == 0:
                raise ComposeError("Picture scale is below native six-decimal precision")
            return rendered or "0"
        scale_x, scale_y = matrix_number(width / original_width), matrix_number(height / original_height)
        offset_x = offset_y = 0
        clip = (0, 0, image_width, image_height)
        if viewport_pixels is not None:
            # Native 13x9 and 509x313 internal/edge probes show that imgClip
            # uses the newly authored orgSz basis, not rounded imgDim ratios.
            # Right/bottom coordinates may exceed rounded imgDim by 15 units;
            # exact native SaveAs after loading all pictures preserves them.
            clip = tuple(value * 75 for value in viewport_pixels)
            offset_x = -round(clip[0] * width / (clip[2] - clip[0]))
            offset_y = -round(clip[1] * height / (clip[3] - clip[1]))
            if not all(-(2**31) <= value < 2**31 for value in (offset_x, offset_y)):
                raise ComposeError("Viewport offset exceeds the native signed coordinate range")
            if any(struct.unpack("f", struct.pack("f", value))[0] != value
                   for value in (offset_x, offset_y)):
                raise ComposeError("Viewport offset is not exactly representable by the native matrix")
        if prototype is not None and prototype.tag != _tag("pic"):
            raise ComposeError("Picture prototype must be hp:pic")
        picture = self._clone(prototype) if prototype is not None else ET.Element(_tag("pic"),
            id=self._fresh_id(), zOrder="0", numberingType="PICTURE", textWrap="TOP_AND_BOTTOM",
            textFlow="BOTH_SIDES", lock="0", dropcapstyle="None", href="", groupLevel="0", instid=self._fresh_id(), reverse="0")
        # A prototype supplies only shape-level attributes. Rebuild all raster
        # geometry so an earlier crop/rotation cannot silently obscure input.
        for child in list(picture):
            picture.remove(child)
        def child(name, **attrs):
            return ET.SubElement(picture, _tag(name), attrib={k: str(v) for k, v in attrs.items()})
        child("offset", x=offset_x & 0xffffffff, y=offset_y & 0xffffffff)
        child("orgSz", width=original_width, height=original_height)
        child("curSz", width=width, height=height)
        child("flip", horizontal=0, vertical=0)
        child("rotationInfo", angle=0, centerX=width // 2, centerY=height // 2, rotateimage=1)
        render = child("renderingInfo")
        for name, x, y in (("transMatrix", "1", "1"), ("scaMatrix", scale_x, scale_y), ("rotMatrix", "1", "1")):
            translation = (offset_x, offset_y) if name == "transMatrix" else (-offset_x, -offset_y) if name == "scaMatrix" else (0, 0)
            ET.SubElement(render, HC + name, e1=x, e2="0", e3=str(translation[0]), e4="0", e5=y, e6=str(translation[1]))
        binary_id = self.add_binary(data, media_type, extension)
        ET.SubElement(picture, HC + "img", binaryItemIDRef=binary_id, bright="0", contrast="0", effect="REAL_PIC", alpha="0")
        rectangle = child("imgRect")
        for number, (x, y) in enumerate(((0, 0), (original_width, 0), (original_width, original_height), (0, original_height))):
            ET.SubElement(rectangle, HC + f"pt{number}", x=str(x), y=str(y))
        child("imgClip", left=clip[0], right=clip[2], top=clip[1], bottom=clip[3])
        child("inMargin", left=0, right=0, top=0, bottom=0)
        child("imgDim", dimwidth=image_width, dimheight=image_height)
        child("effects")
        child("sz", width=width, widthRelTo="ABSOLUTE", height=height, heightRelTo="ABSOLUTE", protect=0)
        child("pos", treatAsChar=1, affectLSpacing=0, flowWithText=1, allowOverlap=0, holdAnchorAndSO=0,
              vertRelTo="PARA", horzRelTo="PARA", vertAlign="TOP", horzAlign="LEFT", vertOffset=0, horzOffset=0)
        child("outMargin", left=0, right=0, top=0, bottom=0)
        child("shapeComment").text = description
        source_run = paragraph.find("hp:run", NS)
        run = ET.SubElement(paragraph, _tag("run"), charPrIDRef=source_run.get("charPrIDRef") if source_run is not None else "0")
        run.append(picture)
        self._inserted_picture_metadata.append({
            "picture_id": picture.get("id"), "binary_id": binary_id,
            "raster_sha256": sha256(data).hexdigest(), "format": image_format,
            "raster_metadata_profile": raster_metadata_profile,
            "pixel_size": list(pixels),
            "shape_original_size_hwp": [original_width, original_height],
            "image_dimension_hwp": [image_width, image_height],
            "display_size_hwp": [width, height],
        })
        if viewport_pixels is not None:
            self._inserted_picture_metadata[-1].update({
                "viewport_pixels_ltrb": list(viewport_pixels),
                "viewport_clip_hwp_ltrb": list(clip),
                "whole_embedded_raster_preserved": True,
                "viewport_representation": "hancom-mac-12.30-png-org75-float32",
            })
        self.invalidate_layout(paragraph)
        return picture

    def set_metadata(self, *, title=None, creator=None, subject=None, description=None, clear_legacy=False):
        package = self.xml("Contents/content.hpf")
        metadata = next((node for node in package if local(node) == "metadata"), None)
        if metadata is None:
            metadata = ET.Element(OPF + "metadata")
            package.insert(0, metadata)
        if clear_legacy:
            for node in list(metadata):
                if local(node) != "language":
                    metadata.remove(node)
        if title is not None:
            node = next((node for node in metadata if local(node) == "title"), None)
            if node is None:
                node = ET.SubElement(metadata, OPF + "title")
            node.text = title
        for key, value in (("creator", creator), ("subject", subject), ("description", description)):
            if value is None:
                continue
            node = next((node for node in metadata if local(node) == "meta" and node.get("name") == key), None)
            if node is None:
                node = ET.SubElement(metadata, OPF + "meta", name=key, content="text")
            node.text = value

    def _materialize(self):
        # Raw root() edits are also detected; unchanged paragraphs keep their caches.
        for name in self.sections:
            for p in reversed(list(self._roots[name].iter(_tag("p")))):
                if self._initial_p.get(p) != _fingerprint(p):
                    self.invalidate_layout(p)
        entries = dict(self._entries)
        entries.update(self._new_entries)
        if any(self._initial_xml.get(name) != _fingerprint(self._roots[name]) for name in self.sections):
            if "Preview/PrvText.txt" in entries:
                preview = "\r\n".join(own_text(p) for name in self.sections
                                        for p in self._roots[name].iter(_tag("p")) if own_text(p))
                entries["Preview/PrvText.txt"] = preview.encode("utf-8")
            # An old page thumbnail would disclose obsolete facts and misrepresent this output.
            stale = {name for name in entries if re.fullmatch(r"Preview/PrvImage\.[^/]+", name)}
            package = self._roots["Contents/content.hpf"]
            stale_items = [item for item in package.iter() if local(item) == "item"
                           and _resolve_href(item.get("href", ""), entries) in stale]
            stale_ids = {item.get("id") for item in stale_items}
            if any(node.get("binaryItemIDRef") in stale_ids for name in self.sections
                   for node in self._roots[name].iter()):
                raise ComposeError("A preview image is also document content; resolve that reference explicitly")
            for root in self._roots.values():
                for node in list(root.iter()):
                    if node is root or node.getparent() is None:
                        continue
                    targets = {value.lstrip("/") for key, value in node.attrib.items()
                               if key in {"href", "full-path"} or key.endswith(("}resource", "}about", "}full-path"))}
                    if node in stale_items or targets & stale or (local(node) == "itemref" and node.get("idref") in stale_ids):
                        node.getparent().remove(node)
            for name in stale:
                del entries[name]
        for name, root in self._roots.items():
            if self._initial_xml.get(name) != _fingerprint(root):
                entries[name] = _xml_bytes(root)
        return entries

    def validate(self):
        return _check(self._materialize(), self._roots, self.sections, self._baseline_ids)

    def save(self, output_path):
        destination = Path(output_path).expanduser().resolve()
        if destination == self.template_path or (destination.exists() and os.path.samefile(destination, self.template_path)):
            raise ComposeError("Refusing to overwrite the source template")
        if any(parent.name in {"_templates", "_references"} for parent in [destination.parent, *destination.parents]):
            raise ComposeError("Refusing to write into a read-only source tree")
        if sha256(self.template_path.read_bytes()).hexdigest() != self.source_sha256:
            raise ComposeError("Source template changed during composition")
        entries = self._materialize()
        report = _check(entries, self._roots, self.sections, self._baseline_ids)
        if not report["valid"]:
            raise ComposeError("Invalid composed package: " + "; ".join(report["errors"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="." + destination.name + ".", suffix=".tmp", dir=destination.parent)
        os.close(fd)
        try:
            original_infos = {item.filename: item for item in self._infos}
            names = ["mimetype", *[item.filename for item in self._infos if item.filename != "mimetype" and item.filename in entries],
                     *[name for name in self._new_entries if name not in original_infos]]
            with ZipFile(temporary, "w") as archive:
                for name in names:
                    info = deepcopy(original_infos[name]) if name in original_infos else ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = ZIP_STORED if name == "mimetype" else (info.compress_type if name in original_infos else ZIP_DEFLATED)
                    archive.writestr(info, entries[name])
            final_report = validate_package(temporary, source_path=self.template_path)
            if not final_report["valid"]:
                raise ComposeError("Saved package failed validation: " + "; ".join(final_report["errors"]))
            with open(temporary, "rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {"output_path": str(destination), "sha256": sha256(destination.read_bytes()).hexdigest(),
                "source_path": str(self.template_path), "source_sha256": self.source_sha256,
                "source_profile_id": self.source_profile_id,
                "inserted_picture_metadata": deepcopy(self._inserted_picture_metadata),
                "modified_entries": [name for name in entries if self._entries.get(name) != entries[name]],
                "removed_entries": [name for name in self._entries if name not in entries],
                "source_unchanged": sha256(self.template_path.read_bytes()).hexdigest() == self.source_sha256,
                "package_validation": final_report,
                "native_verified": False}
