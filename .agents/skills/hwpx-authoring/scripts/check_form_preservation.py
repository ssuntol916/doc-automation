"""Compare HWPX page controls and table geometry without executing document content.

This is a structural gate, not permission to edit fixed labels or text owners.
It does not validate fonts, facts, signatures, every semantic object, or native layout.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET


HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
FORMAT_IDS = {"id", "instid", "charPrIDRef", "paraPrIDRef", "styleIDRef", "borderFillIDRef"}
LIMITATIONS = [
    "Text and fixed-label changes require a separate text-owner/allowlist check.",
    "Run, font and formatting-ID renumbering is outside this geometry comparison.",
    "Passing does not establish facts, signatures, approval, semantic-object preservation or native page layout.",
    "Tables are matched by section spine order and table traversal order; paragraph text anchors are not matched.",
]


def local(tag):
    return tag.rsplit("}", 1)[-1]


def children(node, name):
    return [child for child in node if local(child.tag) == name]


def attrs(node):
    return {key: value for key, value in sorted(node.attrib.items()) if local(key) not in FORMAT_IDS}


def tree_value(node):
    """No paragraph/run/text or local formatting identifiers in structural controls."""
    return {"tag": node.tag, "attributes": attrs(node),
            "children": [tree_value(child) for child in node
                         if local(child.tag) not in {"p", "run", "t"}]}


def direct_property(node, name):
    found = children(node, name)
    return [tree_value(child) for child in found]


def parse(raw, member):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError(f"DTD/entity declarations are not supported: {member}")
    return ET.fromstring(raw)


def section_members(archive):
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError("Duplicate ZIP members")
    package = parse(archive.read("Contents/content.hpf"), "Contents/content.hpf")
    items = {node.get("id"): node.get("href") for node in package.iter() if local(node.tag) == "item"}
    order = []
    for node in package.iter():
        if local(node.tag) != "itemref":
            continue
        href = items.get(node.get("idref"))
        if not href:
            raise ValueError("Unresolved OPF spine item")
        member = href.lstrip("/")
        if member not in names:
            member = str(PurePosixPath("Contents") / member)
        if member not in names:
            raise ValueError("Missing OPF spine member")
        root = parse(archive.read(member), member)
        if local(root.tag) == "sec":
            if member in order:
                raise ValueError("Duplicate section in OPF spine")
            order.append(member)
    actual = {name for name in names if re.fullmatch(r"Contents/section\d+\.xml", name)}
    if not order or not actual.issubset(set(order)):
        raise ValueError("OPF spine does not cover all document sections")
    return order


def snapshot(path):
    """Read every spine section. Geometry values stay in original HWP units."""
    raw = Path(path).read_bytes()
    sections = []
    with ZipFile(path) as archive:
        order = section_members(archive)
        for member in order:
            root = parse(archive.read(member), member)
            parents = {child: parent for parent in root.iter() for child in parent}
            tables = [node for node in root.iter() if local(node.tag) == "tbl"]
            table_indices = {node: index for index, node in enumerate(tables)}
            section = {"section_tag": root.tag,
                       "section_controls": [tree_value(node) for node in root.iter() if local(node.tag) == "secPr"],
                       "table_count": len(tables), "tables": []}
            for table in tables:
                owner = parents.get(table)
                parent_table = None
                paragraph_breaks = None
                while owner is not None:
                    if local(owner.tag) == "p" and paragraph_breaks is None:
                        paragraph_breaks = {key: owner.get(key, "0") for key in ("pageBreak", "columnBreak")}
                    if local(owner.tag) == "tbl":
                        parent_table = table_indices[owner]
                        break
                    owner = parents.get(owner)
                record = {"attributes": attrs(table), "parent_table": parent_table,
                          "owner_paragraph_breaks": paragraph_breaks,
                          "properties": {key: direct_property(table, key)
                                         for key in ("sz", "pos", "outMargin", "inMargin")},
                          "actual_row_count": len(children(table, "tr")), "rows": []}
                for row in children(table, "tr"):
                    cells = []
                    for cell in children(row, "tc"):
                        properties = {key: direct_property(cell, key)
                                      for key in ("cellAddr", "cellSpan", "cellSz", "cellMargin")}
                        for key in ("cellAddr", "cellSpan", "cellSz"):
                            if len(properties[key]) != 1:
                                raise ValueError(f"Cell requires exactly one {key}: {member}")
                        cells.append({"attributes": attrs(cell), "properties": properties,
                                      "sublist_attributes": [attrs(n) for n in children(cell, "subList")]})
                    record["rows"].append({"actual_cell_count": len(cells), "cells": cells})
                section["tables"].append(record)
            sections.append(section)
    # Member filenames and local object IDs may be rewritten on native Save As.
    return {"sha256": sha256(raw).hexdigest(), "spine_members": order,
            "structure": {"section_count": len(sections), "sections": sections}}


def differences(before, after, path=""):
    if type(before) is not type(after):
        return [{"path": path or "/", "baseline": before, "output": after}]
    found = []
    if isinstance(before, dict):
        for key in sorted(before.keys() | after.keys()):
            child = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in before or key not in after:
                found.append({"path": child, "baseline": before.get(key), "output": after.get(key)})
            else:
                found.extend(differences(before[key], after[key], child))
    elif isinstance(before, list):
        if len(before) != len(after):
            found.append({"path": path + "/length", "baseline": len(before), "output": len(after)})
        for index, (left, right) in enumerate(zip(before, after)):
            found.extend(differences(left, right, path + "/" + str(index)))
    elif before != after:
        found.append({"path": path or "/", "baseline": before, "output": after})
    return found


def compare(baseline, output):
    report = {"schema_version": 1, "preserved": False, "scope": "HWPX page controls and table geometry",
              "baseline_sha256": None, "output_sha256": None,
              "differences": [], "errors": [], "limitations": LIMITATIONS}
    try:
        left, right = snapshot(baseline), snapshot(output)
        report.update(baseline_sha256=left["sha256"], output_sha256=right["sha256"],
                      baseline_spine=left["spine_members"], output_spine=right["spine_members"])
        report["differences"] = differences(left["structure"], right["structure"])
        report["preserved"] = not report["differences"]
    except (OSError, ValueError, KeyError, ET.ParseError, BadZipFile) as error:
        report["errors"].append({"type": type(error).__name__, "message": str(error)})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    # A report must never overwrite either read-only document.
    target = args.report.expanduser().resolve()
    documents = [args.baseline.expanduser().resolve(), args.output.expanduser().resolve()]
    if target in documents or (target.exists() and any(
            document.exists() and os.path.samefile(target, document) for document in documents)):
        parser.error("Report path must differ from document paths")
    result = compare(args.baseline, args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"preserved": result["preserved"], "difference_count": len(result["differences"]),
                      "error_count": len(result["errors"])}, ensure_ascii=False))
    return 0 if result["preserved"] else 2


if __name__ == "__main__":
    sys.exit(main())
