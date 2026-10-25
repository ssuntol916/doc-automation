#!/usr/bin/env python3
"""Independent, conservative HWPX Save As audit; no product-code imports.

This compares supplied package bytes, not whether Hancom actually ran. A pass
is limited to the documented static invariants; current native visual QA is
always separate. Unrecognized controls and unresolved references cannot pass.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import posixpath
import re
from typing import Any
from zipfile import BadZipFile, ZipFile

from lxml import etree as E
from PIL import Image

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
P, RUN, TEXT, TABLE, CELL = (f"{{{HP}}}{n}" for n in ("p", "run", "t", "tbl", "tc"))
SEMANTIC = {
    "secPr", "colPr", "tbl", "pic", "ole", "equation", "fieldBegin", "fieldEnd",
    "header", "footer", "footNote", "endNote", "autoNum", "newNum", "pageNum",
    "pageNumCtrl", "pageHiding", "bookmark", "bookMark", "bookmarkStart", "bookmarkEnd",
    "hyperlink", "indexmark", "clickHere", "container", "line", "rect", "ellipse",
    "arc", "polygon", "curve", "connectLine", "textart", "video", "chart",
}
GROUP_OBJECTS = {"secPr", "header", "footer", "footNote", "endNote"}
INLINE = {"lineBreak": "\n", "tab": "\t", "nbSpace": "\u00a0", "nbsp": "\u00a0", "fwSpace": "\u3000"}
REF_TYPES = {"charPrIDRef": "charPr", "paraPrIDRef": "paraPr", "styleIDRef": "style",
             "nextStyleIDRef": "style", "borderFillIDRef": "borderFill", "tabPrIDRef": "tabPr",
             "numberingIDRef": "numbering", "bulletIDRef": "bullet"}
VOLATILE_MEMBERS = {"Contents/content.hpf", "Contents/header.xml", "version.xml", "settings.xml",
                    "META-INF/container.rdf", "META-INF/container.xml", "META-INF/manifest.xml"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def local(el: E._Element) -> str:
    return E.QName(el).localname


def parse(data: bytes) -> E._Element:
    root = E.fromstring(data, E.XMLParser(resolve_entities=False, no_network=True, recover=False))
    if root.getroottree().docinfo.doctype:
        raise ValueError("DTD/entity-bearing XML is unsupported")
    return root


def nearest(node: E._Element, tag: str) -> E._Element | None:
    return next((a for a in node.iterancestors() if a.tag == tag), None)


def inline_text(node: E._Element) -> str:
    value = node.text or ""
    for child in node:
        if not isinstance(child.tag, str):
            raise ValueError("Unsupported XML comment/processing instruction in text")
        name = local(child)
        if name not in INLINE or E.QName(child).namespace != HP:
            raise ValueError(f"Unsupported inline text control: {child.tag}")
        value += INLINE[name] + inline_text(child) + (child.tail or "")
    return value


def owned_text(p: E._Element, run: E._Element | None = None) -> str:
    return "".join(inline_text(t) for t in p.iter(TEXT)
                   if nearest(t, P) is p and (run is None or nearest(t, RUN) is run))


def differences(before: Any, after: Any, path: str = "", limit: int = 12) -> list[dict]:
    out: list[dict] = []
    def visit(a: Any, b: Any, where: str) -> None:
        if a == b or len(out) >= limit:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                if key not in a or key not in b:
                    out.append({"path": where + "/" + str(key), "before": a.get(key), "after": b.get(key)})
                else:
                    visit(a[key], b[key], where + "/" + str(key))
                if len(out) >= limit:
                    break
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                out.append({"path": where, "before_length": len(a), "after_length": len(b)})
            for index, (x, y) in enumerate(zip(a, b)):
                visit(x, y, where + "/" + str(index))
                if len(out) >= limit:
                    break
        else:
            def short(value: Any) -> Any:
                return {"prefix": value[:500], "length": len(value)} if isinstance(value, str) and len(value) > 500 else value
            out.append({"path": where or "/", "before": short(a), "after": short(b)})
    visit(before, after, path)
    return out[:limit]


class Package:
    def __init__(self, path: Path):
        self.path = path.resolve()
        payload = self.path.read_bytes()
        self.sha256 = sha(payload)
        with ZipFile(BytesIO(payload)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate ZIP member names")
            self.members = {n: archive.read(n) for n in names}
        if self.members.get("mimetype", b"").strip() != b"application/hwp+zip":
            raise ValueError("Not an HWPX mimetype")
        self.opf_member = "Contents/content.hpf"
        self.opf = parse(self.members[self.opf_member])
        self.items: dict[str, dict] = {}
        for item in self.opf.xpath('//*[local-name()="manifest"]/*[local-name()="item"]'):
            ident, href = item.get("id"), item.get("href")
            if not ident or ident in self.items or not href or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", href):
                raise ValueError("Invalid/duplicate OPF item or external href")
            candidates = (href.lstrip("/"), posixpath.normpath(posixpath.join(posixpath.dirname(self.opf_member), href)))
            member = next((c for c in candidates if c in self.members and not c.startswith("../")), None)
            if member is None:
                raise ValueError(f"Missing OPF member: {href}")
            self.items[ident] = {"member": member, "media_type": item.get("media-type")}
        self.sections: list[tuple[str, E._Element]] = []
        self.spine_types = []
        for ref in self.opf.xpath('//*[local-name()="spine"]/*[local-name()="itemref"]'):
            item = self.items.get(ref.get("idref"))
            if item is None:
                raise ValueError("Unresolved OPF spine itemref")
            node = parse(self.members[item["member"]])
            self.spine_types.append(node.tag)
            if node.tag == f"{{{HS}}}sec":
                if any(child.tag != P for child in node):
                    raise ValueError("Unsupported non-paragraph section child")
                self.sections.append((item["member"], node))
            elif node.tag != f"{{{HH}}}head":
                raise ValueError(f"Unsupported non-section spine item: {node.tag}")
        if not self.sections or len({p for p, _ in self.sections}) != len(self.sections):
            raise ValueError("Missing/duplicate section in OPF spine")
        undeclared = [n for n in self.members if re.fullmatch(r"Contents/section\d+\.xml", n)
                      and n not in {p for p, _ in self.sections}]
        if undeclared:
            raise ValueError(f"Sections outside the OPF spine: {undeclared}")
        self.header = parse(self.members["Contents/header.xml"])
        self.defs: dict[tuple[str, str], E._Element] = {}
        for node in self.header.iter():
            if isinstance(node.tag, str) and E.QName(node).namespace == HH and node.get("id") is not None and local(node) != "font":
                key = local(node), node.get("id")
                if key in self.defs:
                    raise ValueError(f"Duplicate header definition: {key}")
                self.defs[key] = node
        self.normalizations: Counter = Counter()
        self.resolved_formats: dict[str, Any] = {}
        self.field_labels: dict[str, str] = {}
        for section_index, (_, root) in enumerate(self.sections):
            for index, node in enumerate(root.iter(f"{{{HP}}}fieldBegin")):
                ident = node.get("id")
                if ident is None or ident in self.field_labels:
                    raise ValueError("Missing/duplicate fieldBegin id")
                self.field_labels[ident] = f"section{section_index}:field{index}"
        field_ends = Counter(n.get("beginIDRef") for _, root in self.sections
                             for n in root.iter(f"{{{HP}}}fieldEnd"))
        if set(field_ends) != set(self.field_labels) or any(n != 1 for n in field_ends.values()):
            raise ValueError("Unpaired/ambiguous fieldBegin/fieldEnd graph")

    def asset(self, ident: str) -> dict:
        item = self.items.get(ident)
        if item is None:
            raise ValueError(f"Unresolved binaryItemIDRef: {ident}")
        return {"sha256": sha(self.members[item["member"]]), "media_type": item["media_type"]}

    def definition(self, kind: str, ident: str, stack: tuple = ()) -> Any:
        key = kind, ident
        if key in stack:
            return {"definition_type": kind, "cycle_to_stack_index": stack.index(key)}
        if key not in self.defs:
            raise ValueError(f"Unresolved local definition: {key}")
        return self.node(self.defs[key], stack + (key,), definition_root=True)

    def node(self, node: E._Element, stack: tuple = (), *, definition_root: bool = False,
             object_root: bool = False, group: bool = False) -> Any:
        """Prefix-independent model; retain unknown properties, never blanket-delete IDRefs."""
        name = local(node)
        if name == "fontRef" and E.QName(node).namespace == HH:
            fonts = {}
            for language, ident in sorted(node.attrib.items()):
                found = self.header.xpath('.//*[local-name()="fontface" and @lang=$lang]/*[local-name()="font" and @id=$ident]', lang=language.upper(), ident=ident)
                if len(found) != 1:
                    raise ValueError(f"Unresolved font: {language}/{ident}")
                font = found[0]
                attrs = {k: (self.asset(v) if k == "binaryItemIDRef" and v else v)
                         for k, v in font.attrib.items() if k != "id"}
                children = []
                for child in font:
                    if local(child) == "typeInfo":
                        self.normalizations["font_typeInfo_metadata"] += 1
                    else:
                        children.append(self.node(child, stack))
                fonts[language] = {"attributes": attrs, "children": children}
            return {"font_faces": fonts}
        attrs: dict[str, Any] = {}
        for key, value in sorted(node.attrib.items()):
            if key == "id" and definition_root:
                continue
            if key in ("id", "instid", "instanceID") and object_root and name not in ("fieldBegin", "fieldEnd"):
                self.normalizations["native_object_instance_id"] += 1
                continue
            if name == "fieldBegin" and key == "id":
                attrs[key] = self.field_labels[value]
            elif name == "fieldEnd" and key == "beginIDRef":
                if value not in self.field_labels:
                    raise ValueError(f"Unresolved fieldEnd: {value}")
                attrs[key] = self.field_labels[value]
            elif key == "binaryItemIDRef":
                if not value and name in ("font", "substFont"):
                    attrs[key] = ""
                else:
                    attrs[key] = self.asset(value)
            elif name == "heading" and key == "idRef":
                kind = node.get("type")
                if kind == "NONE" and value == "0":
                    attrs[key] = "no_heading"
                elif kind in ("OUTLINE", "NUMBER", "NUMBERING", "BULLET"):
                    attrs[key] = self.definition("bullet" if kind == "BULLET" else "numbering", value, stack)
                else:
                    raise ValueError(f"Unsupported heading binding: {kind}/{value}")
            elif key in ("linkListIDRef", "linkListNextIDRef"):
                if value != "0":
                    raise ValueError(f"Nonzero linked-subList binding requires separate review: {key}/{value}")
                attrs[key] = value
            elif key == "charPrIDRef" and value == "4294967295" and name == "paraHead":
                attrs[key] = "inherit_current_character_format"
            elif key in REF_TYPES:
                attrs[key] = self.definition(REF_TYPES[key], value, stack)
            elif key == "outlineShapeIDRef":
                if ("numbering", value) not in self.defs:
                    raise ValueError(f"Unresolved default outline shape: {value}")
                # Actual outline paragraphs resolve heading/idRef above. Do not
                # treat unused default numbering fonts as displayed text.
                attrs[key] = "default_outline_shape_declared"
            elif key == "memoShapeIDRef" and value == "0":
                attrs[key] = "no_memo_shape"
            elif key.lower().endswith("idref"):
                raise ValueError(f"Unsupported reference binding requires review: {node.tag}/{key}={value}")
            elif name == "paraPr" and key == "textDir" and value == "AUTO":
                self.normalizations["explicit_default_textDir_AUTO"] += 1
            else:
                attrs[key] = value
        children = []
        for child in node:
            if not isinstance(child.tag, str):
                raise ValueError("Unsupported XML comment/processing instruction")
            child_name = local(child)
            if child_name == "linesegarray":
                self.normalizations["line_position_cache"] += 1
                continue
            if group and child.tag == P:
                continue  # These paragraphs and their controls are audited separately.
            if child_name == "switch":
                branches = [[self.node(x, stack) for x in branch] for branch in child]
                if branches and all(branch == branches[0] for branch in branches):
                    children.extend(branches[0])
                    self.normalizations["equivalent_switch_branches"] += 1
                    continue
            children.append(self.node(child, stack, object_root=child_name in SEMANTIC))
        return {"tag": node.tag, "attributes": attrs,
                "text": node.text if node.text and (not len(node) or node.text.strip()) else None,
                "tail": node.tail if node.tail and node.tail.strip() else None, "children": children}

    def format_key(self, kind: str, ident: str) -> str:
        model = self.definition(kind, ident)
        key = digest(model)
        self.resolved_formats[key] = model
        return key

    def model(self) -> dict:
        sections = []
        known_run = {"t", "ctrl"} | SEMANTIC
        for section_index, (member, root) in enumerate(self.sections):
            tables = list(root.iter(TABLE)); table_index = {t: i for i, t in enumerate(tables)}
            objects = [n for n in root.iter() if isinstance(n.tag, str) and E.QName(n).namespace == HP and local(n) in SEMANTIC]
            object_index = {node: i for i, node in enumerate(objects)}
            for node in root.iter():
                if node.tag == f"{{{HP}}}ctrl":
                    for child in node:
                        if local(child) not in SEMANTIC or E.QName(child).namespace != HP:
                            raise ValueError(f"Unsupported semantic control: {child.tag}")
                if node.tag == RUN:
                    for child in node:
                        if local(child) not in known_run or E.QName(child).namespace != HP:
                            raise ValueError(f"Unsupported run child: {child.tag}")
            def owner(node: E._Element) -> list:
                chain = []
                for ancestor in reversed(list(node.iterancestors())):
                    if ancestor.tag == CELL:
                        table = nearest(ancestor, TABLE); addr = ancestor.find(f"{{{HP}}}cellAddr")
                        if table is None or addr is None:
                            raise ValueError("Cell without table/address")
                        chain.append(["table_cell", table_index[table], dict(addr.attrib)])
                    elif local(ancestor) in GROUP_OBJECTS - {"secPr"}:
                        chain.append([local(ancestor), object_index[ancestor]])
                return chain
            paragraphs, paragraph_formats, locations = [], [], []
            pnodes = list(root.iter(P))
            for pi, p in enumerate(pnodes):
                text = owned_text(p); location = f"{member}#P{pi + 1}"
                attrs = {k: v for k, v in p.attrib.items() if k not in ("id", "paraPrIDRef", "styleIDRef")}
                pf = {"attributes": attrs, "paragraph_definition": self.format_key("paraPr", p.get("paraPrIDRef")),
                      "style_definition": self.format_key("style", p.get("styleIDRef"))}
                paragraph_formats.append(pf)
                if not text.strip():
                    continue
                segments = []
                for run in p.iter(RUN):
                    if nearest(run, P) is not p:
                        continue
                    value = owned_text(p, run)
                    if not value:
                        self.normalizations["empty_text_run_not_in_text_style_sequence"] += 1
                        continue
                    rattrs = {k: v for k, v in run.attrib.items() if k != "charPrIDRef"}
                    fmt = self.format_key("charPr", run.get("charPrIDRef"))
                    if segments and segments[-1]["format"] == fmt and segments[-1]["attributes"] == rattrs:
                        segments[-1]["text"] += value
                        self.normalizations["adjacent_equivalent_text_run_merge"] += 1
                    else:
                        segments.append({"text": value, "format": fmt, "attributes": rattrs})
                paragraphs.append({"owner": owner(p), "text": text, "text_styles": segments})
                locations.append(location)
            table_models, outer_heights = [], []
            for ti, table in enumerate(tables):
                table_attributes = {k: v for k, v in table.attrib.items() if k not in ("id", "instid", "instanceID")}
                attrs = self.node(E.Element(table.tag, attrib=table_attributes))["attributes"]
                properties = []
                for child in table:
                    if local(child) == "tr":
                        continue
                    clone = deepcopy(child)
                    if local(clone) == "sz":
                        outer_heights.append({"table": ti, "height": clone.attrib.pop("height", None)})
                    properties.append(self.node(clone))
                cells = []
                for cell in table.iter(CELL):
                    if nearest(cell, TABLE) is not table:
                        continue
                    sub = cell.find(f"{{{HP}}}subList")
                    props = [self.node(c) for c in cell if local(c) != "subList"]
                    # Cell format IDs are file-local, just like run/paragraph
                    # IDs. Resolve the shallow cell attributes through the same
                    # strict definition/reference resolver used for other nodes.
                    cell_attributes = self.node(E.Element(cell.tag, attrib=dict(cell.attrib)))["attributes"]
                    cells.append({"attributes": cell_attributes, "subList_attributes": dict(sub.attrib) if sub is not None else None,
                                  "properties": props})
                table_models.append({"owner": owner(table), "attributes": attrs, "properties": properties, "cells": cells})
            semantics = []
            for node in objects:
                name = local(node)
                if name == "tbl":
                    continue
                if name in ("pic", "ole") and not any(n.get("binaryItemIDRef") for n in node.iter()):
                    raise ValueError(f"Unbound {name} binary resource")
                if name == "equation" and not any(local(n) in ("script", "source") and (n.text or "").strip() for n in node.iter()):
                    raise ValueError("Equation without a supported nonempty script/source")
                semantics.append({"kind": name, "owner": owner(node),
                                  "value": self.node(node, object_root=True, group=name in GROUP_OBJECTS)})
            geometry = [self.node(n) for n in root.iter() if local(n) in ("pagePr", "pageBorderFill")]
            sections.append({"member": member, "paragraphs": paragraphs, "paragraph_locations": locations,
                             "paragraph_count_including_empty": len(pnodes), "paragraph_formats": paragraph_formats,
                             "tables": table_models, "semantic_counts": dict(Counter(local(n) for n in objects)),
                             "semantic_values": semantics, "page_geometry": geometry, "table_outer_heights": outer_heights})
        resources = []
        for name, payload in sorted(self.members.items()):
            if not name.startswith("BinData/"):
                continue
            entry = {"member": name, "sha256": sha(payload), "size_bytes": len(payload)}
            try:
                with Image.open(BytesIO(payload)) as picture:
                    picture.load()
                    entry["image"] = {"format": picture.format, "size": list(picture.size), "mode": picture.mode,
                                      "decoded_pixels_sha256": sha(picture.tobytes())}
            except (OSError, ValueError):
                entry["image"] = None
            resources.append(entry)
        return {"sections": sections, "spine_types": self.spine_types, "resources": resources,
                "normalizations_observed": dict(self.normalizations), "resolved_formats": self.resolved_formats}


def audit(before: Path, after: Path) -> dict:
    report = {"schema_version": "1.0", "tool": "independent_generated_roundtrip_audit",
              "tool_source_sha256": sha(Path(__file__).read_bytes()),
              "audited_at": datetime.now(timezone.utc).isoformat(), "passed": False,
              "native_visual_pass": False, "business_facts_verified": False,
              "normalization_policy": [
                  "Text: exact Unicode, inline lineBreak/tab/NBSP/full-width-space and tails retained; no whitespace collapse for pass.",
                  "Only text-empty/whitespace-only paragraphs are absent from the nonempty text sequence; all paragraph counts/formats are also compared.",
                  "Local format IDs resolve to definition content, actual font faces and referenced border/tab/style definitions; no blanket IDRef deletion.",
                  "Native paragraph/object instance IDs, equivalent adjacent text-run splits, empty text-only runs and line-position caches are not semantic text.",
                  "font typeInfo classification metadata and explicit paraPr textDir=AUTO omission are normalized; embedded/substitute font content is retained.",
                  "Equivalent switch branches flatten only if every branch has identical resolved content; differing branches remain in the model.",
                  "Unused section default outline shape IDs are validated as declarations; actual numbering/bullet paragraphs resolve their heading binding and payload.",
                  "Preview/version/app settings/OPF bookkeeping are reported as package changes, not compared as business text.",
                  "Table outer sz.height is retained as a separate native-layout delta; cell size/span/width/margins and every other table property remain strict.",
              ], "checks": [], "errors": [], "limits": [
                  "A pass establishes only these supplied-byte invariants, not actual Hancom execution, factual truth, approval/signature authenticity or submission readiness.",
                  "All current pages still require native PDF/PNG visual review, especially any table outer-height recomputation.",
                  "Unsupported controls, unresolved definitions/resources and unreviewed package changes cannot automatically pass.",
              ]}
    packages, models = [], []
    for label, path in (("before", before), ("after", after)):
        try:
            package = Package(path); model = package.model()
            packages.append(package); models.append(model)
            report[label] = {"path": str(package.path), "sha256": package.sha256,
                             "section_members_in_spine_order": [s["member"] for s in model["sections"]],
                             "nonempty_owned_paragraphs": sum(len(s["paragraphs"]) for s in model["sections"]),
                             "tables": sum(len(s["tables"]) for s in model["sections"]),
                             "resources": model["resources"], "normalizations_observed": model["normalizations_observed"]}
        except (OSError, ValueError, KeyError, TypeError, BadZipFile, E.XMLSyntaxError) as exc:
            report["errors"].append({"code": "PACKAGE_UNSUPPORTED_OR_INVALID", "side": label, "path": str(path), "reason": str(exc)})
    if report["errors"]:
        return report
    a, b = models
    def check(code: str, x: Any, y: Any) -> None:
        report["checks"].append({"id": code, "passed": x == y, "before_model_sha256": digest(x),
                                 "after_model_sha256": digest(y), "difference_examples": differences(x, y), "difference_examples_limit": 12})
    check("SPINE_SECTION_STRUCTURE", a["spine_types"], b["spine_types"])
    check("SECTION_COUNT", len(a["sections"]), len(b["sections"]))
    for key, code in (("paragraphs", "EXACT_OWNED_TEXT_OWNER_ORDER_AND_USED_CHARACTER_FORMATS"),
                      ("paragraph_count_including_empty", "ALL_PARAGRAPH_COUNTS"),
                      ("paragraph_formats", "RESOLVED_PARAGRAPH_AND_STYLE_DEFINITIONS"),
                      ("tables", "TABLE_CELL_OWNERSHIP_SPANS_AND_GEOMETRY"),
                      ("semantic_counts", "SEMANTIC_OBJECT_COUNTS"), ("semantic_values", "SEMANTIC_OBJECT_VALUES_AND_BINDINGS"),
                      ("page_geometry", "PAGE_GEOMETRY")):
        check(code, [s[key] for s in a["sections"]], [s[key] for s in b["sections"]])
    # Member renames alone are not image loss; every object's resource binding is also resolved above.
    check("BINDATA_PAYLOAD_MULTISET", sorted((r["sha256"], r["size_bytes"]) for r in a["resources"]),
          sorted((r["sha256"], r["size_bytes"]) for r in b["resources"]))
    pa, pb = packages
    section_names = {s[0] for p in packages for s in p.sections}
    def protected(p: Package) -> dict:
        return {n: sha(v) for n, v in p.members.items() if n not in VOLATILE_MEMBERS | section_names
                and not n.startswith(("Preview/", "BinData/"))}
    check("OTHER_PACKAGE_MEMBERS", protected(pa), protected(pb))
    names_a, names_b = set(pa.members), set(pb.members)
    report["package_changes"] = {"added": sorted(names_b - names_a), "removed": sorted(names_a - names_b),
                                 "changed": sorted(n for n in names_a & names_b if pa.members[n] != pb.members[n])}
    heights_a = [s["table_outer_heights"] for s in a["sections"]]
    heights_b = [s["table_outer_heights"] for s in b["sections"]]
    report["layout_delta"] = {"table_outer_heights_equal": heights_a == heights_b,
                              "differences": differences(heights_a, heights_b), "native_visual_review_required": True}
    report["text_diagnostics"] = {
        "whitespace_collapsed_text_sequence_equal": [[re.sub(r"\s+", " ", p["text"]).strip() for p in s["paragraphs"]] for s in a["sections"]]
        == [[re.sub(r"\s+", " ", p["text"]).strip() for p in s["paragraphs"]] for s in b["sections"]],
        "whitespace_collapse_is_not_used_for_pass": True}
    report["used_resolved_format_definitions"] = {"before": a["resolved_formats"], "after": b["resolved_formats"]}
    try:
        stable = [sha(p.path.read_bytes()) == p.sha256 for p in packages]
    except OSError:
        stable = [False, False]
    check("INPUT_BYTES_STABLE_DURING_AUDIT", stable, [True, True])
    report["passed"] = all(c["passed"] for c in report["checks"])
    report["summary"] = {"checks": len(report["checks"]), "failed": sum(not c["passed"] for c in report["checks"])}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() in (args.before.resolve(), args.after.resolve()):
        parser.error("Report path must not overwrite either HWPX input")
    result = audit(args.before, args.after)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "report": str(args.output.resolve()),
                      "summary": result.get("summary"), "errors": result["errors"]}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
