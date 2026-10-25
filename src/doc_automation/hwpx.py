"""Read HWPX packages without changing the source or duplicating table text."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata
from zipfile import ZipFile

from lxml import etree as ET

NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "opf": "http://www.idpf.org/2007/opf/",
}


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def parse_xml(data: bytes) -> ET._Element:
    return ET.fromstring(data, parser=ET.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False))


def local(node: ET._Element) -> str:
    return ET.QName(node).localname


def element_data(node: ET._Element) -> dict:
    out = {"tag": local(node), "attributes": dict(node.attrib)}
    if node.text and node.text.strip():
        out["text"] = node.text
    if node.tail and node.tail.strip():
        out["tail"] = node.tail
    children = [element_data(c) for c in node if isinstance(c.tag, str)]
    if children:
        out["children"] = children
    return out


def nearest(node: ET._Element, tag: str):
    for ancestor in node.iterancestors():
        if ancestor.tag == tag:
            return ancestor
    return None


def inline_text(node: ET._Element) -> str:
    """Preserve text after inline controls; ``hp:t.text`` alone loses tails."""
    substitutions = {"lineBreak": "\n", "br": "\n", "tab": "\t", "fwSpace": "\u3000", "nbSpace": "\u00a0", "nbHyphen": "\u2011", "softHyphen": "\u00ad"}
    parts = [node.text or ""]
    for child in node:
        parts.append(substitutions.get(local(child), ""))
        parts.append(inline_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def own_text(paragraph: ET._Element) -> str:
    """Text owned by this paragraph; excludes descendant cell/footnote paragraphs."""
    parts = []
    for node in paragraph.iter(f"{{{NS['hp']}}}t"):
        if nearest(node, f"{{{NS['hp']}}}p") is not paragraph:
            continue
        parts.append(inline_text(node))
    return "".join(parts)


def paragraph_role(paragraph: ET._Element) -> str:
    names = [local(a) for a in paragraph.iterancestors()]
    for tag, role in (("header", "header"), ("footer", "footer"), ("footNote", "footnote"), ("endNote", "endnote"), ("drawText", "textbox"), ("tc", "table_cell")):
        if tag in names:
            return role
    return "body"


def section_order(z: ZipFile) -> list[str]:
    """Use OPF spine, not directory order, for reading order."""
    if "Contents/content.hpf" not in z.namelist():
        raise ValueError("Missing Contents/content.hpf")
    package = parse_xml(z.read("Contents/content.hpf"))
    items = {e.get("id"): e.get("href") for e in package.iter() if local(e) == "item"}
    sections = []
    for e in package.iter():
        if local(e) != "itemref":
            continue
        href = items.get(e.get("idref"), "") or ""
        if re.search(r"(^|/)section\d+\.xml$", href):
            name = href.lstrip("/")
            if name not in z.namelist():
                name = str(PurePosixPath("Contents") / href)
            if name not in z.namelist():
                raise ValueError(f"Spine section missing: {href}")
            sections.append(name)
    actual = {n for n in z.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)}
    if set(sections) != actual:
        raise ValueError(f"Spine/section mismatch: {set(sections) ^ actual}")
    return sections


def document_key(path: Path, kind: str) -> str:
    name = nfc(path.stem)
    code = re.search(r"SF-[A-Z]+\d+", name)
    if code:
        return f"{kind.lower()}-{code.group(0).lower()}"
    if "서식자료" in name:
        return f"{kind.lower()}-forms-2025"
    if "목록" in name:
        return f"{kind.lower()}-deliverables-v2"
    return f"{kind.lower()}-{sha256(name.encode()).hexdigest()[:12]}"


def profile(path: Path, kind: str, source_root: Path | None = None) -> dict:
    raw = path.read_bytes()
    result = {
        "id": document_key(path, kind), "kind": kind,
        "source_path": str(path.resolve()), "display_name": nfc(path.name),
        "relative_path": nfc(str(path.relative_to(source_root))) if source_root else nfc(path.name),
        "sha256": sha256(raw).hexdigest(), "size_bytes": len(raw),
        "analysis_scope": "package/XML; actual rendered layout requires native verification",
    }
    with ZipFile(path) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate ZIP entries in {path}")
        result["package"] = {
            "entries": [{"name": i.filename, "size": i.file_size, "compression": i.compress_type, "sha256": sha256(z.read(i)).hexdigest()} for i in z.infolist()],
            "mimetype": z.read("mimetype").decode("utf-8-sig").strip(),
            "first_entry": names[0],
            "crc_error": z.testzip(),
        }
        header = parse_xml(z.read("Contents/header.xml"))
        if ET.QName(header).namespace != NS["hh"]:
            raise ValueError("Unsupported header namespace; do not silently analyze as 2011 HWPX")
        result["header"] = element_data(header)
        maps = {}
        for collection, child in (("charProperties", "charPr"), ("paraProperties", "paraPr"), ("styles", "style"), ("borderFills", "borderFill"), ("numberings", "numbering"), ("bullets", "bullet")):
            maps[collection] = {e.get("id"): element_data(e) for e in header.iter() if local(e) == child}
        maps["fontfaces"] = [element_data(e) for e in header.iter() if local(e) == "fontface"]
        result["definitions"] = maps
        result["sections"] = []
        totals = Counter()
        all_text = []
        style_usage = Counter()
        char_usage = Counter()
        para_usage = Counter()
        for section_name in section_order(z):
            root = parse_xml(z.read(section_name))
            if ET.QName(root).namespace != NS["hs"]:
                raise ValueError(f"Unsupported section namespace in {section_name}")
            tree = root.getroottree()
            paragraphs = list(root.iter(f"{{{NS['hp']}}}p"))
            tables = list(root.iter(f"{{{NS['hp']}}}tbl"))
            pnums = {p: i + 1 for i, p in enumerate(paragraphs)}
            tnums = {t: i + 1 for i, t in enumerate(tables)}
            section = {"name": section_name, "paragraphs": [], "tables": [], "objects": [], "section_properties": []}
            counts = Counter(local(e) for e in root.iter() if isinstance(e.tag, str))
            totals.update(counts)
            section["element_counts"] = dict(counts)
            for p in paragraphs:
                text = own_text(p)
                style_usage[p.get("styleIDRef", "")] += 1
                para_usage[p.get("paraPrIDRef", "")] += 1
                runs = []
                for run in p.findall("hp:run", NS):
                    char_usage[run.get("charPrIDRef", "")] += 1
                    runs.append({"attributes": dict(run.attrib), "text": "".join(inline_text(t) for t in run.iter(f"{{{NS['hp']}}}t") if nearest(t, f"{{{NS['hp']}}}p") is p)})
                section["paragraphs"].append({"index": pnums[p], "evidence": f"{section_name}#P{pnums[p]}", "xpath": tree.getpath(p), "role": paragraph_role(p), "attributes": dict(p.attrib), "text": text, "runs": runs})
            for table in tables:
                index = tnums[table]
                cells = []
                for cell in table.iter(f"{{{NS['hp']}}}tc"):
                    if nearest(cell, f"{{{NS['hp']}}}tbl") is not table:
                        continue
                    address = cell.find("hp:cellAddr", NS)
                    addr = dict(address.attrib) if address is not None else {}
                    texts = [own_text(p) for p in cell.iter(f"{{{NS['hp']}}}p") if nearest(p, f"{{{NS['hp']}}}tc") is cell]
                    evidence = f"{section_name}#T{index}/R{addr.get('rowAddr','?')}C{addr.get('colAddr','?')}"
                    cells.append({"evidence": evidence, "address": addr, "attributes": dict(cell.attrib), "properties": [element_data(c) for c in cell if local(c) != "subList"], "paragraph_indices": [pnums[p] for p in cell.iter(f"{{{NS['hp']}}}p") if nearest(p, f"{{{NS['hp']}}}tc") is cell], "text": "\n".join(t for t in texts if t)})
                parent = nearest(table, f"{{{NS['hp']}}}tbl")
                section["tables"].append({"index": index, "evidence": f"{section_name}#T{index}", "xpath": tree.getpath(table), "parent_table": tnums.get(parent), "attributes": dict(table.attrib), "properties": [element_data(c) for c in table if local(c) != "tr"], "cells": cells})
            for e in root.iter():
                name = local(e)
                if name == "secPr":
                    section["section_properties"].append({"xpath": tree.getpath(e), "data": element_data(e)})
                if name in {"pic", "ole", "equation", "chart", "rect", "ellipse", "line", "container", "connectLine", "header", "footer", "footNote", "endNote"}:
                    section["objects"].append({"type": name, "xpath": tree.getpath(e), "data": element_data(e)})
            all_text.extend(inline_text(e) for e in root.iter(f"{{{NS['hp']}}}t"))
            result["sections"].append(section)
        result["statistics"] = {"section_count": len(result["sections"]), "table_count": totals["tbl"], "picture_count": totals["pic"], "paragraph_count": totals["p"], "element_counts": dict(totals), "style_usage": dict(style_usage), "char_property_usage": dict(char_usage), "para_property_usage": dict(para_usage)}
        result["ordered_text"] = "\n".join(t for t in all_text if t)
        for name in ("version.xml", "Contents/content.hpf", "settings.xml"):
            if name in names:
                result[name] = element_data(parse_xml(z.read(name)))
    return result


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def analyze_folder(source: Path, output: Path, kind: str) -> dict:
    files = sorted((p for p in source.rglob("*") if p.suffix.lower() in {".hwpx", ".hwp"}), key=lambda p: nfc(str(p)))
    inventory = {"source_root": str(source.resolve()), "kind": kind, "documents": [], "unsupported_inputs": []}
    used = set()
    for path in files:
        if path.suffix.lower() == ".hwp":
            inventory["unsupported_inputs"].append({"path": str(path), "reason": "Binary HWP requires a separately verified conversion path"})
            continue
        item = profile(path, kind, source)
        if item["id"] in used:
            raise ValueError(f"Ambiguous document key {item['id']}; add explicit source version mapping")
        used.add(item["id"])
        destination = output / "profiles" / f"{item['id']}.json"
        write_json(destination, item)
        text_path = output / "text" / f"{item['id']}.txt"
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text(item["ordered_text"] + "\n", encoding="utf-8")
        inventory["documents"].append({k: item[k] for k in ("id", "source_path", "relative_path", "display_name", "sha256", "size_bytes", "statistics")})
    write_json(output / "inventory.json", inventory)
    return inventory
