#!/usr/bin/env python3
"""Restore only exact missing nonembedded HWPX font fallback declarations.

This package postprocess is not a native Save As. Its output still requires
actual native open/close/reopen/PDF export and page review. Font IDs are local:
matching uses language and the complete primary definition, excluding its ID
and substFont child, and requires uniqueness in both packages.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import copy, deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import posixpath
import re
from zipfile import BadZipFile, ZipFile

from lxml import etree as E

HH = "http://www.hancom.co.kr/hwpml/2011/head"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HEADER = "Contents/header.xml"
SUBST = f"{{{HH}}}substFont"
SCHEMA = "native-font-fallback-restoration-1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return sha256(data).hexdigest()


def file_ref(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": digest(path.read_bytes())}


def parse(data):
    root = E.fromstring(data, E.XMLParser(resolve_entities=False, no_network=True, recover=False))
    require(not root.getroottree().docinfo.doctype, "DTD/entity-bearing XML is unsupported")
    require(all(isinstance(n.tag, str) for n in root.iter()), "XML comments/processing instructions are unsupported")
    return root


def model(node, *, primary=False):
    """Expanded XML names; retain every attribute, child, text and child tail."""
    attrs = dict(node.attrib)
    if primary:
        attrs.pop("id", None)
    children = [c for c in node if not (primary and c.tag == SUBST)]
    return [node.tag, sorted(attrs.items()), node.text,
            [[model(c), c.tail] for c in children]]


def declarations(header):
    groups, keys = defaultdict(list), set()
    for face in header.iter(f"{{{HH}}}fontface"):
        lang = face.get("lang")
        require(bool(lang), "Font language is missing")
        for font in face.findall(f"{{{HH}}}font"):
            local_id = font.get("id")
            require(local_id is not None and (lang, local_id) not in keys,
                    "Duplicate/missing local font ID within a language")
            keys.add((lang, local_id))
            require(len(font.findall(SUBST)) <= 1, "Multiple fallback declarations are unsupported")
            key = (lang, json.dumps(model(font, primary=True), ensure_ascii=False, sort_keys=True))
            groups[key].append(font)
    require(keys, "No font declarations found")
    return groups


def safe_fallback(font):
    child = font.find(SUBST)
    if child is None:
        return None
    require(font.get("isEmbedded") == "0" and not font.get("binaryItemIDRef"),
            "Embedded/resource-backed primary fonts cannot be repaired")
    require(child.get("isEmbedded") == "0" and not child.get("binaryItemIDRef"),
            "Embedded/resource-backed fallback fonts cannot be repaired")
    require(child.get("face") and child.get("type") and not len(child) and not (child.text or "").strip(),
            "Unsupported or incomplete fallback declaration")
    return child


def read_package(path):
    with ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate ZIP member names are unsupported")
        require(HEADER in names, "Contents/header.xml is missing")
        return {name: archive.read(name) for name in names}, archive.infolist(), archive.comment


def used_fallbacks(entries, header, restored_keys):
    """Report source usage, without making a native or visual judgment."""
    require("Contents/content.hpf" in entries, "OPF manifest/spine is missing")
    opf = parse(entries["Contents/content.hpf"])
    manifest = {n.get("id"): n.get("href") for n in opf.iter()
                if E.QName(n).localname == "item"}
    paths = []
    for n in opf.iter():
        if E.QName(n).localname != "itemref":
            continue
        href = manifest.get(n.get("idref"))
        require(href is not None, "Unresolved OPF spine item")
        require(not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", href) and "?" not in href and "#" not in href,
                "External/qualified OPF spine paths are unsupported")
        candidates = {posixpath.normpath(href.lstrip("/")), posixpath.normpath(posixpath.join("Contents", href))}
        matches = [n for n in candidates if not n.startswith("../") and n in entries]
        require(len(matches) == 1, "Unresolved/ambiguous OPF spine path")
        name = matches[0]
        paths.append(name)
    require(paths and len(paths) == len(set(paths)), "Missing/duplicate OPF spine items")
    char_formats = {}
    for char in header.iter(f"{{{HH}}}charPr"):
        ref = char.find(f"{{{HH}}}fontRef")
        char_formats[char.get("id")] = set() if ref is None else {
            (lang.upper(), local_id) for lang, local_id in ref.attrib.items()}
    ptag, rtag, ttag = (f"{{{HP}}}{name}" for name in ("p", "run", "t"))
    def owner(node, tag):
        return next((a for a in node.iterancestors() if a.tag == tag), None)
    used, affected, char_ids = set(), [], set()
    index = 0
    for name in paths:
        root = parse(entries[name])
        for para in root.iter(ptag):
            own_text = "".join("".join(t.itertext()) for t in para.iter(ttag) if owner(t, ptag) is para)
            if not own_text.strip():
                continue
            paragraph_used = set()
            for run in para.iter(rtag):
                if owner(run, ptag) is not para:
                    continue
                run_text = "".join("".join(t.itertext()) for t in run.iter(ttag)
                                   if owner(t, ptag) is para and owner(t, rtag) is run)
                if run_text:
                    char_id = run.get("charPrIDRef")
                    require(char_id in char_formats, "Unresolved source character format")
                    refs = char_formats[char_id] & restored_keys
                    if refs:
                        paragraph_used |= refs
                        char_ids.add(char_id)
            if paragraph_used:
                affected.append({"spine_entry": name, "nonempty_owned_paragraph_index": index})
                used |= paragraph_used
            index += 1
    return {"source_nonempty_owned_paragraphs": index,
            "used_restored_font_declarations": len(used),
            "used_restored_fonts": [{"language": l, "source_local_font_id": i} for l, i in sorted(used)],
            "affected_character_format_ids": sorted(char_ids),
            "affected_nonempty_owned_paragraphs": affected}


def plan_restoration(reference_entries, native_entries):
    source, target = parse(reference_entries[HEADER]), parse(native_entries[HEADER])
    source_groups, target_groups = declarations(source), declarations(target)
    # Existing fallback declarations must also have one exact source meaning.
    for groups, other in ((source_groups, target_groups), (target_groups, source_groups)):
        for key, fonts in groups.items():
            for font in fonts:
                sub = safe_fallback(font)
                if sub is None:
                    continue
                require(len(fonts) == 1 and len(other.get(key, [])) == 1,
                        "Fallback primary definition has no unique matching language/definition")
                peer_sub = other[key][0].find(SUBST)
                if peer_sub is not None:
                    safe_fallback(other[key][0])
                    require(model(sub) == model(peer_sub), "Conflicting existing fallback declaration")
                elif groups is target_groups:
                    raise ValueError("Native fallback has no exact source fallback declaration")
    restorations, inserted, restored_keys = [], [], set()
    source_count = 0
    for key, fonts in source_groups.items():
        for source_font in fonts:
            expected = safe_fallback(source_font)
            if expected is None:
                continue
            source_count += 1
            target_font = target_groups[key][0]
            if target_font.find(SUBST) is not None:
                continue
            # Insert at the exact source child position. Other children are
            # already identical, and removing the inserted child must recover
            # every original native header attribute/text/tail/control.
            index = list(source_font).index(expected)
            child = deepcopy(expected)
            target_font.insert(index, child)
            inserted.append((target_font, child))
            restored_keys.add((key[0], source_font.get("id")))
            restorations.append({"language": key[0], "source_local_font_id": source_font.get("id"),
                                 "native_local_font_id": target_font.get("id"),
                                 "primary_definition_sha256": digest(key[1].encode()),
                                 "primary_attributes": {k: v for k, v in source_font.attrib.items() if k != "id"},
                                 "fallback_attributes": dict(expected.attrib), "source_child_index": index,
                                 "fallback_definition_sha256": digest(json.dumps(model(expected), ensure_ascii=False).encode())})
    require(restorations, "No missing exact fallback declarations to restore")
    output_header = E.tostring(target, encoding="UTF-8", xml_declaration=True)
    for parent, child in inserted:
        parent.remove(child)
    require(model(target) == model(parse(native_entries[HEADER])), "Unexpected non-fallback header mutation")
    return output_header, {"restorations": restorations,
                           "source_fallback_declarations": source_count,
                           "restored_fallback_declarations": len(restorations),
                           "source_usage": used_fallbacks(reference_entries, source, restored_keys)}


def preserved_entries(native_entries, output_entries):
    require(list(native_entries) == list(output_entries), "ZIP member order/set changed")
    entries = [{"name": name, "native_saved_sha256": digest(data), "output_sha256": digest(output_entries[name]),
                "unchanged": data == output_entries[name]} for name, data in native_entries.items()]
    changed = [e["name"] for e in entries if not e["unchanged"]]
    require(changed == [HEADER], "Only Contents/header.xml may change")
    return entries


def restore(reference_source, native_saved, output, report):
    reference_source, native_saved, output, report = map(lambda p: Path(p).resolve(),
                                                       (reference_source, native_saved, output, report))
    require(output != report and output not in (reference_source, native_saved) and report not in (reference_source, native_saved),
            "Output/report must not alias an input or each other")
    require(not output.exists() and not report.exists(), "Refusing to overwrite an existing output/report")
    source_ref, native_ref = file_ref(reference_source), file_ref(native_saved)
    source_entries, _, _ = read_package(reference_source)
    native_entries, infos, archive_comment = read_package(native_saved)
    header, details = plan_restoration(source_entries, native_entries)
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.comment = archive_comment
        for info in infos:
            archive.writestr(copy(info), header if info.filename == HEADER else native_entries[info.filename])
    result = buffer.getvalue()
    with ZipFile(BytesIO(result)) as archive:
        output_entries = {n: archive.read(n) for n in archive.namelist()}
    entries = preserved_entries(native_entries, output_entries)
    payload = {"schema_version": SCHEMA, "operation": "restore_native_font_fallbacks", "passed": True,
               "recorded_at": datetime.now(timezone.utc).isoformat(),
               "reference_source": source_ref, "native_saved": native_ref,
               "output": {"path": str(output), "sha256": digest(result)}, "tool": file_ref(__file__),
               "changed_entries": [HEADER], "entry_preservation": entries, **details,
               "native_status": "pending_actual_final_byte_open_close_reopen_pdf_and_full_page_review",
               "limitations": ["This output is a package postprocess of the recorded native Save As intermediate.",
                               "It is not claimed to be an unchanged native Save As result.",
                               "Another native Save As may remove fallback declarations again; no format-equivalence waiver is granted."]}
    require(file_ref(reference_source) == source_ref and file_ref(native_saved) == native_ref,
            "Input changed during restoration")
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    created_output = created_report = False
    try:
        with output.open("xb") as handle:
            created_output = True
            handle.write(result)
        with report.open("x") as handle:
            created_report = True
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    except Exception:
        # A failed report write must not leave an apparently complete candidate.
        if created_output:
            output.unlink(missing_ok=True)
        if created_report:
            report.unlink(missing_ok=True)
        raise
    return payload


def verify_report(report_path):
    """Recompute the limited repair and every member hash; distrust pass flags."""
    report_path = Path(report_path).resolve()
    report = json.loads(report_path.read_text())
    require(report.get("schema_version") == SCHEMA and report.get("operation") == "restore_native_font_fallbacks"
            and report.get("passed") is True, "Unsupported/incomplete restoration report")
    require(report.get("tool") == file_ref(__file__), "Restoration tool path/hash is stale or different")
    recorded = datetime.fromisoformat(report["recorded_at"].replace("Z", "+00:00"))
    require(recorded.tzinfo is not None, "Restoration time needs a timezone")
    bound = {}
    for name in ("reference_source", "native_saved", "output"):
        ref = report[name]
        path = Path(ref["path"])
        path = path.resolve() if path.is_absolute() else (report_path.parent / path).resolve()
        require(file_ref(path) == ref, f"Restoration {name} path/hash is stale or noncanonical")
        bound[name] = path
    require(len(set(bound.values())) == 3, "Restoration files must be distinct")
    source, _, _ = read_package(bound["reference_source"])
    native, _, _ = read_package(bound["native_saved"])
    output, _, _ = read_package(bound["output"])
    header, details = plan_restoration(source, native)
    require(output[HEADER] == header, "Output is not the exact permitted fallback restoration")
    entries = preserved_entries(native, output)
    require(report.get("changed_entries") == [HEADER] and report.get("entry_preservation") == entries,
            "Restoration entry preservation evidence differs from current bytes")
    for key, value in details.items():
        require(report.get(key) == value, f"Restoration {key} differs from recomputed evidence")
    require(report.get("native_status") == "pending_actual_final_byte_open_close_reopen_pdf_and_full_page_review",
            "Postprocess report cannot claim native validation")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-source", type=Path, required=True)
    parser.add_argument("--native-saved", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = restore(args.reference_source, args.native_saved, args.output, args.report)
        verify_report(args.report)
    except (OSError, ValueError, KeyError, TypeError, BadZipFile, E.XMLSyntaxError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"passed": True, "output": result["output"], "report": file_ref(args.report),
                      "restored_fallback_declarations": result["restored_fallback_declarations"],
                      "source_usage": result["source_usage"], "native_status": result["native_status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
