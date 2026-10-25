"""Opt-in, source-guarded editorial profiles over the preserving compose core.

Selectors describe this verified v2 corpus. They are deliberately separate from
package mechanics and do not claim to understand arbitrary HWPX templates.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

from lxml import etree as ET

from .compose import ComposeError, HP, PROTECTED_CONTENT
from .hwpx import NS, nearest, own_text, parse_xml, inline_text


def _protected(node):
    return any(a.tag.rsplit("}", 1)[-1] in {"header", "footer", "footNote", "endNote"} for a in node.iterancestors())


def _top_paragraph(node):
    paragraph = nearest(node, HP + "p")
    while paragraph is not None and nearest(paragraph, HP + "p") is not None:
        paragraph = nearest(paragraph, HP + "p")
    return paragraph


def _columns(table):
    """Recover source logical widths using unmerged cells, then span constraints."""
    count = int(table.get("colCnt"))
    widths = [None] * count
    constraints = []
    for row in table.findall("hp:tr", NS):
        for cell in row.findall("hp:tc", NS):
            start = int(cell.find("hp:cellAddr", NS).get("colAddr"))
            span = int(cell.find("hp:cellSpan", NS).get("colSpan"))
            width = int(cell.find("hp:cellSz", NS).get("width"))
            constraints.append((start, span, width))
            if span == 1 and widths[start] is None:
                widths[start] = width
    for _ in range(count):
        for start, span, width in constraints:
            missing = [i for i in range(start, start + span) if widths[i] is None]
            if len(missing) == 1:
                widths[missing[0]] = width - sum(widths[i] or 0 for i in range(start, start + span))
    if any(value is None or value <= 0 for value in widths):
        raise ComposeError("Editorial profile needs explicit widths for ambiguous merged columns")
    return widths


def _scaled(widths, total):
    scaled = [round(value * total / sum(widths)) for value in widths]
    scaled[-1] += total - sum(scaled)
    return scaled


def _td3_profile_digest(profile):
    return sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


def register_td3_initial_chapters(doc, profile):
    """Bind the two original titles, independently of landscape geometry."""
    target = profile["targets"].get("td3_initial_chapters")
    if target is None:
        return {}
    contract = {"heading": "common_heading_targets", "body": "common_body_targets",
                "generated_prose_align": "LEFT", "generated_prose_intent_hwp": 0,
                "generated_prose_left_hwp": 0}
    if profile.get("role") != "SF-TD3" or target != contract:
        raise ComposeError("Unsupported TD3 initial-chapter typography contract")
    selectors = profile.get("td3_initial_chapter_sources", {})
    if set(selectors) != {"standards", "menu"}:
        raise ComposeError("TD3 initial chapters need exactly two source owners")
    registry = {}
    original = parse_xml(doc._entries[doc.sections[0]])
    header = parse_xml(doc._entries["Contents/header.xml"])
    for key, selector in selectors.items():
        if set(selector) != {"source_sha256", "xml", "xpath", "own_text", "paragraph_c14n_sha256",
                             "paragraph_definition_c14n_sha256", "section_page_c14n_sha256"}:
            raise ComposeError("Unsupported TD3 initial chapter source selector")
        location = selector.get("xml"), selector.get("xpath")
        matches = original.xpath(location[1], namespaces=NS)
        current = [p for p, saved in doc._source_paragraph_locations.items()
                   if saved == location and p.getparent() is doc.root(0)]
        if (selector.get("source_sha256") != doc.source_sha256
                or profile["source_template"]["sha256"] != doc.source_sha256
                or location[0] != doc.sections[0] or len(matches) != 1 or len(current) != 1
                or own_text(matches[0]) != selector.get("own_text")
                or own_text(current[0]) != selector.get("own_text")
                or doc._source_paragraph_text.get(current[0]) != selector.get("own_text")
                or sha256(ET.tostring(matches[0], method="c14n")).hexdigest() != selector.get("paragraph_c14n_sha256")
                or ET.tostring(current[0], method="c14n") != ET.tostring(matches[0], method="c14n")):
            raise ComposeError("TD3 initial chapter exact source/node mismatch")
        paragraph_definition = header.xpath(".//hh:paraPr[@id=$id]", namespaces=NS,
                                             id=matches[0].get("paraPrIDRef"))
        page = original.find("./hp:p/hp:run/hp:secPr/hp:pagePr", NS)
        live_page = doc.root(0).find("./hp:p/hp:run/hp:secPr/hp:pagePr", NS)
        if (len(paragraph_definition) != 1 or page is None or live_page is None
                or sha256(ET.tostring(paragraph_definition[0], method="c14n")).hexdigest() != selector.get("paragraph_definition_c14n_sha256")
                or sha256(ET.tostring(page, method="c14n")).hexdigest() != selector.get("section_page_c14n_sha256")
                or ET.tostring(live_page, method="c14n") != ET.tostring(page, method="c14n")):
            raise ComposeError("TD3 initial chapter source paragraph/page geometry mismatch")
        registry[key] = {"heading": current[0], "body": [], "expected_body_texts": [],
                         "expected_heading_text": own_text(current[0]), "source": selector,
                         "heading_geometry_attributes": {k: v for k, v in matches[0].attrib.items() if k != "paraPrIDRef"},
                         "page_geometry_sha256": selector["section_page_c14n_sha256"]}
    doc._editorial_td3_initial_chapters = registry
    doc._editorial_td3_initial_profile_digest = _td3_profile_digest(profile)
    return registry


def _prepare_td3_initial_typography(doc, profile):
    if profile["targets"].get("td3_initial_chapters") is None:
        return []
    registry = getattr(doc, "_editorial_td3_initial_chapters", None)
    if registry is None:
        # Raw-source layout callers can select the exact original titles only;
        # generated prose without its registry cannot pass the source-text guard.
        registry = register_td3_initial_chapters(doc, profile)
    if (set(registry) != {"standards", "menu"}
            or getattr(doc, "_editorial_td3_initial_profile_digest", None) != _td3_profile_digest(profile)):
        raise ComposeError("TD3 initial chapter registry/profile mismatch")
    prepared, seen = [], set()
    for key in ("standards", "menu"):
        record = registry[key]
        heading, body = record["heading"], record["body"]
        root = doc.root(0)
        page = root.find("./hp:p/hp:run/hp:secPr/hp:pagePr", NS)
        if (heading.getparent() is not root or own_text(heading) != record["expected_heading_text"]
                or doc._source_paragraph_locations.get(heading) != (record["source"]["xml"], record["source"]["xpath"])
                or doc._source_paragraph_text.get(heading) != record["source"]["own_text"]
                or {k: v for k, v in heading.attrib.items() if k != "paraPrIDRef"} != record["heading_geometry_attributes"]
                or len(body) != len(record["expected_body_texts"]) or page is None
                or sha256(ET.tostring(page, method="c14n")).hexdigest() != record["page_geometry_sha256"]):
            raise ComposeError("TD3 initial heading/paragraph geometry registry drift")
        previous = heading
        for paragraph, text in zip(body, record["expected_body_texts"]):
            if (paragraph in seen or paragraph.getparent() is not root or paragraph.getprevious() is not previous
                    or own_text(paragraph) != text
                    or any(node.tag.rsplit("}", 1)[-1] in PROTECTED_CONTENT
                           for node in paragraph.iter())
                    or paragraph not in getattr(doc, "_editorial_body_paragraphs", set())):
                raise ComposeError("TD3 initial prose has lost its exact registered owner")
            seen.add(paragraph)
            prepared.append((key, "body", paragraph))
            previous = paragraph
        prepared.append((key, "heading", heading))
    if root.index(registry["standards"]["heading"]) >= root.index(registry["menu"]["heading"]):
        raise ComposeError("TD3 initial chapter source order changed")
    return prepared


def _apply_td3_initial_typography(doc, targets, prepared):
    reports = []
    for chapter, role, paragraph in prepared:
        controls = [ET.tostring(c, method="c14n") for c in paragraph.findall(".//hp:ctrl", NS)]
        heading = role == "heading"
        doc.use_character_style(paragraph, font=targets["heading_font_face" if heading else "body_font_face"],
            size_pt=targets["heading_height_hwp" if heading else "body_height_hwp"] / 100,
            bold=targets["heading_bold"] if heading else False,
            spacing_percent=targets["character_spacing_percent"], ratio_percent=targets["character_ratio_percent"])
        doc.use_paragraph_style(paragraph, line_spacing_percent=targets["heading_line_spacing_percent" if heading else "body_line_spacing_percent"],
                                align=None if heading else "LEFT")
        if not heading:
            definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:paraPr", NS)}
            source_id = paragraph.get("paraPrIDRef")
            definition = deepcopy(definitions[source_id])
            for name in ("intent", "left"):
                values = definition.findall(".//hc:" + name, NS)
                if len(values) != 2 or any(v.get("unit") != "HWPUNIT" for v in values):
                    raise ComposeError("TD3 initial prose needs two resolved source margin branches")
                for value in values:
                    value.set("value", "0")
            paragraph.set("paraPrIDRef", doc._derived_definition("paraPr", source_id, definition))
            doc.invalidate_layout(paragraph)
        if controls != [ET.tostring(c, method="c14n") for c in paragraph.findall(".//hp:ctrl", NS)]:
            raise ComposeError("TD3 initial typography changed a protected control")
        reports.append({"chapter": chapter, "role": role, "section": doc.sections[0],
                        "xpath": paragraph.getroottree().getpath(paragraph), "text": own_text(paragraph),
                        "common_target_family": "heading" if heading else "body",
                        "target": {"font_face": targets["heading_font_face" if heading else "body_font_face"],
                            "height_hwp": targets["heading_height_hwp" if heading else "body_height_hwp"],
                            "line_spacing_percent": targets["heading_line_spacing_percent" if heading else "body_line_spacing_percent"],
                            "bold": targets["heading_bold"] if heading else False,
                            "spacing_percent": targets["character_spacing_percent"], "ratio_percent": targets["character_ratio_percent"],
                            **({} if heading else {"align": "LEFT", "left_hwp": 0, "intent_hwp": 0})},
                        "selection": "exact_source_title_and_registered_generated_prose_typography_only"})
    return reports


def _prepare_cover_roles(doc, profile):
    """Resolve all declared cover owners before any editorial mutation.

    Runtime identity comes from the renderer registry; the immutable source
    bytes, original owner text and exact XPath independently guard that identity.
    The exemplar's business strings are evidence, never replacement values.
    """
    targets = profile["targets"].get("cover_roles")
    if targets is None:
        return []
    roles = {"customer", "program", "title", "date", "supplier"}
    if not isinstance(targets, dict) or set(targets) != roles:
        raise ComposeError("Cover profile must declare exactly the five supported semantic roles")
    registry = getattr(doc, "_editorial_cover_paragraphs", {})
    selectors = profile.get("cover_selectors", {})
    prepared, selected = [], set()
    source_roots = {}
    for role in ("customer", "program", "title", "date", "supplier"):
        target = targets[role]
        if not isinstance(target, dict) or set(target) != {"font_face", "height_hwp", "bold"}:
            raise ComposeError("Cover target permits font_face/height_hwp/bold only")
        if not isinstance(target["font_face"], str) or not target["font_face"].strip() or not isinstance(target["bold"], bool):
            raise ComposeError("Invalid cover font/bold target")
        height = target["height_hwp"]
        if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
            raise ComposeError("Cover height_hwp must be a positive integer")
        selector = selectors.get(role, {}).get("template", {})
        member, xpath = selector.get("xml"), selector.get("xpath")
        if selector.get("source_sha256") != doc.source_sha256 or member != doc.sections[0]:
            raise ComposeError("Cover selector source fingerprint/member mismatch")
        if not isinstance(xpath, str) or not xpath.startswith("/hs:sec/"):
            raise ComposeError("Cover selector needs an exact source paragraph XPath")
        try:
            if member not in source_roots:
                source_roots[member] = parse_xml(doc._entries[member])
            original = source_roots[member].xpath(xpath, namespaces=NS)
            current = doc.xml(member).xpath(xpath, namespaces=NS)
        except Exception as exc:
            raise ComposeError("Invalid cover owner XPath") from exc
        paragraph = registry.get(role)
        expected = selector.get("text_before_generation_verbatim")
        if (not isinstance(expected, str) or len(original) != 1 or len(current) != 1
                or original[0].tag != HP + "p" or paragraph is not current[0]
                or own_text(original[0]) != expected
                or getattr(doc, "_source_paragraph_text", {}).get(paragraph) != expected
                or paragraph in selected or _protected(paragraph)):
            raise ComposeError("Cover role registry/source owner mismatch: " + role)
        selected.add(paragraph)
        prepared.append((role, paragraph, target, member, xpath))
    return prepared


def _apply_cover_roles(doc, prepared):
    reports = []
    for role, paragraph, target, member, xpath in prepared:
        changed = doc.use_character_style(paragraph, font=target["font_face"],
            size_pt=target["height_hwp"] / 100, bold=target["bold"])
        definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
        families = {f.get("lang").lower(): {font.get("id"): font.get("face") for font in f}
                    for f in doc.xml("Contents/header.xml").findall(".//hh:fontface", NS)}
        actual = []
        for run in paragraph.findall("hp:run", NS):
            if not any(inline_text(t) for t in run.findall("hp:t", NS)):
                continue
            definition = definitions[run.get("charPrIDRef")]
            font_refs = dict(definition.find("hh:fontRef", NS).attrib)
            actual.append({"charPrIDRef": run.get("charPrIDRef"), "height_hwp": int(definition.get("height")),
                           "bold": definition.find("hh:bold", NS) is not None,
                           "font_refs": font_refs,
                           "fonts": {script: families.get(script, {}).get(identifier) for script, identifier in font_refs.items()}})
        reports.append({"role": role, "member": member, "source_xpath": xpath,
                        "current_xpath": paragraph.getroottree().getpath(paragraph),
                        "target": dict(target), "changed_own_runs": changed, "actual_ids": actual})
    return reports


def _prepare_cover_program_paragraph(doc, profile, prepared_cover):
    """Guard the separately declared program-only paragraph property edit."""
    target = profile["targets"].get("cover_program_paragraph")
    if target is None:
        return None
    if target != {"break_non_latin": "BREAK_WORD"}:
        raise ComposeError("Cover program paragraph permits only declared BREAK_WORD")
    program = [record for record in prepared_cover if record[0] == "program"]
    if len(program) != 1:
        raise ComposeError("Cover program paragraph needs the five guarded cover owners")
    _, paragraph, _, member, xpath = program[0]
    guard = profile.get("cover_program_paragraph_source", {})
    if (not isinstance(guard, dict)
            or set(guard) != {"source_sha256", "xml", "xpath", "paragraph_c14n_sha256",
                      "paragraph_definition_c14n_sha256", "break_non_latin"}
            or guard["source_sha256"] != doc.source_sha256
            or (guard["xml"], guard["xpath"]) != (member, xpath)):
        raise ComposeError("Cover program paragraph source guard mismatch")
    original = parse_xml(doc._entries[member]).xpath(xpath, namespaces=NS)[0]
    source_header = parse_xml(doc._entries["Contents/header.xml"])
    original_definitions = source_header.xpath(".//hh:paraPr[@id=$i]", namespaces=NS,
                                               i=original.get("paraPrIDRef"))
    current_definitions = doc.xml("Contents/header.xml").xpath(".//hh:paraPr[@id=$i]", namespaces=NS,
                                                               i=paragraph.get("paraPrIDRef"))
    if len(original_definitions) != 1 or len(current_definitions) != 1:
        raise ComposeError("Cover program paragraph definition is ambiguous or missing")
    original_definition, current_definition = original_definitions[0], current_definitions[0]
    original_bytes = ET.tostring(original_definition, method="c14n", exclusive=True)
    current_bytes = ET.tostring(current_definition, method="c14n", exclusive=True)
    breaks = original_definition.findall("hh:breakSetting", NS)
    if (sha256(ET.tostring(original, method="c14n", exclusive=True)).hexdigest() != guard["paragraph_c14n_sha256"]
            or sha256(original_bytes).hexdigest() != guard["paragraph_definition_c14n_sha256"]
            or current_bytes != original_bytes or len(breaks) != 1
            or breaks[0].get("breakNonLatinWord") != guard["break_non_latin"]
            or guard["break_non_latin"] not in {"KEEP_WORD", "BREAK_WORD"}
            or any(node is not paragraph and node.tag.rsplit("}", 1)[-1] in PROTECTED_CONTENT
                   for node in paragraph.iter())):
        raise ComposeError("Cover program paragraph source owner/definition drift")
    return paragraph, member, xpath, guard["break_non_latin"], original_bytes


def _apply_cover_program_paragraph(doc, prepared):
    if prepared is None:
        return None
    paragraph, member, xpath, source_value, original_definition = prepared
    # A no-op must not deduplicate a different identical local definition or
    # invalidate line caches: already-BREAK_WORD owners retain exact bytes.
    before_id = paragraph.get("paraPrIDRef")
    changed = 0
    if source_value != "BREAK_WORD":
        changed = doc.use_paragraph_style(paragraph, break_non_latin="BREAK_WORD")
        if changed != 1:
            raise ComposeError("Cover program paragraph property did not derive one owner")
    actual, = doc.xml("Contents/header.xml").xpath(".//hh:paraPr[@id=$i]", namespaces=NS,
                                                  i=paragraph.get("paraPrIDRef"))
    # Reverse only the declared property and ID, then compare every other
    # paragraph attribute/branch against the independently guarded source.
    restored = deepcopy(actual)
    original = parse_xml(original_definition)
    restored.set("id", original.get("id"))
    restored.find("hh:breakSetting", NS).set("breakNonLatinWord", source_value)
    if ET.tostring(restored, method="c14n", exclusive=True) != original_definition:
        raise ComposeError("Cover program paragraph changed an undeclared property")
    return {"role": "program", "member": member, "source_xpath": xpath,
            "current_xpath": paragraph.getroottree().getpath(paragraph),
            "target": {"break_non_latin": "BREAK_WORD"},
            "source_break_non_latin": source_value, "actual_break_non_latin": "BREAK_WORD",
            "changed_paragraphs": changed, "before_paraPrIDRef": before_id,
            "after_paraPrIDRef": paragraph.get("paraPrIDRef"),
            "already_matching_owner_skipped_without_derivation": changed == 0,
            "all_other_paragraph_properties_preserved": True,
            "selection": "exact_source_program_owner_and_five_cover_role_registry"}


def _prepare_toc_roles(doc, profile):
    """Guard the two renderer-owned TOC paragraphs before any profile edit."""
    targets = profile["targets"].get("toc_roles")
    if targets is None:
        return []
    roles = {"title", "entries"}
    if not isinstance(targets, dict) or set(targets) != roles:
        raise ComposeError("TOC profile must declare exactly title/entries roles")
    registry = getattr(doc, "_editorial_toc_paragraphs", {})
    selectors = profile.get("toc_selectors", {})
    prepared, selected, source_roots = [], set(), {}
    for role in ("title", "entries"):
        target = targets[role]
        if (not isinstance(target, dict) or set(target) != {"font_face"}
                or not isinstance(target["font_face"], str) or not target["font_face"].strip()):
            raise ComposeError("TOC targets permit font_face only")
        selector = selectors.get(role, {}).get("template", {})
        member, xpath = selector.get("xml"), selector.get("xpath")
        if selector.get("source_sha256") != doc.source_sha256 or member not in doc.sections:
            raise ComposeError("TOC selector source fingerprint/member mismatch")
        if not isinstance(xpath, str) or not xpath.startswith("/hs:sec/"):
            raise ComposeError("TOC selector needs an exact source owner XPath")
        try:
            if member not in source_roots:
                source_roots[member] = parse_xml(doc._entries[member])
            original = source_roots[member].xpath(xpath, namespaces=NS)
            current = doc.xml(member).xpath(xpath, namespaces=NS)
        except Exception as exc:
            raise ComposeError("Invalid TOC owner XPath") from exc
        paragraph = registry.get(role)
        expected = selector.get("text_before_generation_verbatim")
        if (not isinstance(expected, str) or len(original) != 1 or len(current) != 1
                or original[0].tag != HP + "p" or paragraph is not current[0]
                or own_text(original[0]) != expected
                or getattr(doc, "_source_paragraph_text", {}).get(paragraph) != expected
                or paragraph in selected or _protected(paragraph)):
            raise ComposeError("TOC role registry/source owner mismatch: " + role)
        selected.add(paragraph)
        prepared.append((role, paragraph, target, member, xpath))
    return prepared


def _apply_toc_roles(doc, prepared):
    reports = []
    for role, paragraph, target, member, xpath in prepared:
        changed = doc.use_character_style(paragraph, font=target["font_face"])
        definitions = {p.get("id"): p for p in doc.xml("Contents/header.xml").findall(".//hh:charPr", NS)}
        families = {f.get("lang").lower(): {font.get("id"): font.get("face") for font in f}
                    for f in doc.xml("Contents/header.xml").findall(".//hh:fontface", NS)}
        actual = []
        for run in paragraph.findall("hp:run", NS):
            if not any(inline_text(t) for t in run.findall("hp:t", NS)):
                continue
            definition = definitions[run.get("charPrIDRef")]
            font_refs = dict(definition.find("hh:fontRef", NS).attrib)
            actual.append({"charPrIDRef": run.get("charPrIDRef"), "height_hwp": int(definition.get("height")),
                           "bold": definition.find("hh:bold", NS) is not None,
                           "fonts": {script: families.get(script, {}).get(identifier) for script, identifier in font_refs.items()}})
        reports.append({"role": role, "member": member, "source_xpath": xpath,
                        "current_xpath": paragraph.getroottree().getpath(paragraph), "target": dict(target),
                        "changed_own_runs": changed, "actual_ids": actual,
                        "size_bold_paragraph_geometry_controls": "preserved"})
    return reports


def _prepare_boundary_spacers(doc, profile, first_body):
    """Resolve only declared, originally empty suffix owners before splitting."""
    selectors = profile.get("section_boundary_spacer_selectors", [])
    if not selectors:
        return [], []
    root = first_body.getparent()
    originals = {}
    source_locations = {location: paragraph for paragraph, location in doc._source_paragraph_locations.items()}
    prepared, reports = [], []
    for selector in selectors:
        member, xpath = selector.get("xml"), selector.get("xpath")
        if (selector.get("source_sha256") != doc.source_sha256 or member not in doc.sections
                or selector.get("text_before_generation_verbatim") != ""):
            raise ComposeError("Boundary spacer source fingerprint/member/text mismatch")
        if member not in originals:
            originals[member] = parse_xml(doc._entries[member])
        try:
            original = originals[member].xpath(xpath, namespaces=NS)
        except Exception as exc:
            raise ComposeError("Invalid boundary spacer source XPath") from exc
        paragraph = source_locations.get((member, xpath))
        if (len(original) != 1 or original[0].tag != HP + "p" or own_text(original[0]) != ""
                or any(node.tag.rsplit("}", 1)[-1] not in {"p", "run", "t", "linesegarray", "lineseg"} for node in original[0].iter())
                or paragraph is None or doc._source_paragraph_text.get(paragraph) != ""):
            raise ComposeError("Boundary spacer original owner is not pure empty text")
        report = {"member": member, "source_xpath": xpath}
        if paragraph.getparent() is None:
            report["status"] = "absent_before_profile"
        elif paragraph.getparent() is root:
            prepared.append(paragraph)
            report.update(status="discarded_at_new_section_boundary", current_xpath=paragraph.getroottree().getpath(paragraph))
        else:
            raise ComposeError("Boundary spacer moved outside the declared split scope")
        reports.append(report)
    doc._check_boundary_spacers(first_body, prepared)
    return prepared, reports


def _select_declared_body_section(doc, profile, first_table_paragraph):
    """Select an exact source chapter and its small registered generated intro."""
    start = profile.get("body_section_start")
    if start is not None:
        if profile.get("role") not in {"SF-PM1", "SF-PM2", "SF-PM3"} or profile.get("body_section_selector") is not None:
            raise ComposeError("Unsupported declared management body start")
        locations = {location: paragraph for paragraph, location in doc._source_paragraph_locations.items()}
        roots = {}
        def owner(spec):
            member, xpath = spec.get("xml"), spec.get("xpath")
            if spec.get("source_sha256") != doc.source_sha256 or member not in doc.sections:
                raise ComposeError("Management body start source fingerprint/member mismatch")
            if member not in roots:
                roots[member] = parse_xml(doc._entries[member])
            try:
                original = roots[member].xpath(xpath, namespaces=NS)
            except Exception as exc:
                raise ComposeError("Invalid management body source XPath") from exc
            current = locations.get((member, xpath))
            expected = spec.get("text_before_generation_verbatim")
            if (len(original) != 1 or original[0].tag != HP + "p" or not isinstance(expected, str)
                    or own_text(original[0]) != expected or current is None
                    or doc._source_paragraph_text.get(current) != expected or _protected(current)):
                raise ComposeError("Management body source owner mismatch")
            return original[0], current
        original_heading, heading = owner(start)
        original_table, table = owner(start.get("first_table_carrier", {}))
        root = first_table_paragraph.getparent()
        if (table is not first_table_paragraph or heading is not getattr(doc, "_editorial_body_start_paragraph", None)
                or heading.getparent() is not root or table.getparent() is not root
                or root.index(heading) >= root.index(table) or not own_text(heading).strip()
                or original_heading.find(".//hp:tbl", NS) is not None):
            raise ComposeError("Management body start registry/boundary mismatch")
        bridge = [owner(spec) for spec in start.get("source_bridge", [])]
        source_root = original_heading.getparent()
        if (original_table.getparent() is not source_root
                or list(source_root)[source_root.index(original_heading)+1:source_root.index(original_table)] != [p for p, _ in bridge]):
            raise ComposeError("Management body source bridge differs from the declared finite owners")
        actual = list(root)[root.index(heading)+1:root.index(table)]
        known = [p for _, p in bridge]
        if [p for p in actual if p in doc._source_paragraph_locations] != known:
            raise ComposeError("Management body source bridge ownership/order changed")
        generated = [p for p in actual if p not in doc._source_paragraph_locations]
        allowed = {"p", "run", "t", "lineBreak", "tab", "fwSpace", "nbSpace", "linesegarray", "lineseg"}
        if (len(generated) != 1 or generated[0] not in getattr(doc, "_editorial_body_paragraphs", set())
                or not own_text(generated[0]).startswith(("검증용 합성 자료", "검토용 초안"))
                or any(node.tag.rsplit("}", 1)[-1] not in allowed for node in generated[0].iter())):
            raise ComposeError("Management body start requires its registered plain generated notice")
        # pageHiding and other source controls remain attached to their exact
        # owners. A body-boundary selection must never erase these controls.
        for original, current in [(original_heading, heading), *bridge]:
            if [ET.tostring(n, method="c14n") for n in original.findall("./hp:run/hp:ctrl", NS)] != [ET.tostring(n, method="c14n") for n in current.findall("./hp:run/hp:ctrl", NS)]:
                raise ComposeError("Management body intro source controls changed")
        return heading, {"selection": "exact_management_source_start_with_registered_generated_text",
                         "source_start": start, "current_heading_xpath": heading.getroottree().getpath(heading),
                         "current_table_xpath": table.getroottree().getpath(table),
                         "preserved_intro_xpaths": [p.getroottree().getpath(p) for p in [heading, *known]],
                         "generated_notice_xpath": generated[0].getroottree().getpath(generated[0])}
    selector = profile.get("body_section_selector")
    if selector is None:
        return first_table_paragraph, None
    locations = {location: paragraph for paragraph, location in doc._source_paragraph_locations.items()}
    prepared = {}
    for role in ("source_heading", "first_table_carrier"):
        source = selector.get(role, {})
        member, xpath = source.get("xml"), source.get("xpath")
        if source.get("source_sha256") != doc.source_sha256 or member not in doc.sections:
            raise ComposeError("Body section selector source fingerprint/member mismatch")
        try:
            nodes = parse_xml(doc._entries[member]).xpath(xpath, namespaces=NS)
        except Exception as exc:
            raise ComposeError("Invalid body section source owner XPath") from exc
        paragraph = locations.get((member, xpath))
        expected = source.get("text_before_generation_verbatim")
        if (len(nodes) != 1 or nodes[0].tag != HP + "p" or not isinstance(expected, str)
                or own_text(nodes[0]) != expected or paragraph is None
                or doc._source_paragraph_text.get(paragraph) != expected or _protected(paragraph)):
            raise ComposeError("Body section source owner mismatch: " + role)
        prepared[role] = paragraph
    heading, table_carrier = prepared["source_heading"], prepared["first_table_carrier"]
    root = first_table_paragraph.getparent()
    if (table_carrier is not first_table_paragraph or heading.getparent() is not root
            or table_carrier.getparent() is not root or root.index(heading) >= root.index(table_carrier)
            or own_text(heading) != selector["source_heading"]["text_before_generation_verbatim"]):
        raise ComposeError("Body section chapter/card boundary differs from its source owners")
    intro_policy = selector.get("generated_intro", {})
    if intro_policy != {"allowed_prefix": "과제: ", "maximum_paragraphs": 1,
                        "require_renderer_body_role": True, "plain_text_only": True}:
        raise ComposeError("Unsupported body section intro policy")
    plain_tags = {"p", "run", "t", "lineBreak", "tab", "fwSpace", "nbSpace", "linesegarray", "lineseg"}
    if any(node.tag.rsplit("}", 1)[-1] not in plain_tags for node in heading.iter()):
        raise ComposeError("Body section heading contains an undeclared object/control")
    intro = list(root)[root.index(heading) + 1:root.index(table_carrier)]
    if len(intro) > intro_policy["maximum_paragraphs"]:
        raise ComposeError("Body section has more than the declared finite intro")
    registered = getattr(doc, "_editorial_body_paragraphs", set())
    for paragraph in intro:
        if (paragraph not in registered or paragraph in doc._source_paragraph_locations
                or not own_text(paragraph).startswith(intro_policy["allowed_prefix"])
                or any(node.tag.rsplit("}", 1)[-1] not in plain_tags for node in paragraph.iter())):
            raise ComposeError("Body section intro is not the declared registered plain-text owner")
    return heading, {"selection": "exact_source_chapter_with_registered_finite_intro",
                     "source_heading": selector["source_heading"],
                     "first_table_carrier": selector["first_table_carrier"],
                     "current_heading_xpath": heading.getroottree().getpath(heading),
                     "current_table_xpath": table_carrier.getroottree().getpath(table_carrier),
                     "generated_intro": [{"xpath": p.getroottree().getpath(p), "text": own_text(p)} for p in intro]}


def apply_editorial_profile(doc, role, profile=None):
    """Apply one explicit profile; callers invoke this only for opt-in generation.

    Existing definitions and unrelated objects are retained. Five cover owner
    character styles and the separate program-only paragraph target require
    their explicit source-guarded declarations.
    The returned selector/change record belongs in the manifest.
    Native review of these exact new bytes remains a separate required stage.
    """
    if profile is None:
        path = Path(__file__).resolve().parents[2] / "resources/style-upgrade/profiles" / f"{role}.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
    if profile.get("schema_version") != "reference-editorial-profile-1" or profile.get("role") != role:
        raise ComposeError("Editorial profile schema/role mismatch")
    if profile.get("source_template", {}).get("sha256") != doc.source_sha256:
        raise ComposeError("Editorial profile source template fingerprint mismatch")
    targets = profile["targets"]
    prepared_td3_initial = _prepare_td3_initial_typography(doc, profile)
    prepared_cover = _prepare_cover_roles(doc, profile)
    prepared_cover_program = _prepare_cover_program_paragraph(doc, profile, prepared_cover)
    prepared_toc = _prepare_toc_roles(doc, profile)
    from .management_roles import prepare_overrides, prepare_preserved_titles
    prepared_management_roles = prepare_overrides(doc, profile)
    preserved_management_titles = prepare_preserved_titles(doc, profile)
    all_tables = [table for index in range(len(doc.sections)) for table in doc.tables(index)
                  if not _protected(table) and not any(a.tag == HP + "tbl" for a in table.iterancestors())]
    if len(all_tables) < 2:
        raise ComposeError("Editorial profile requires the verified cover/body table boundary")
    first_body = _top_paragraph(all_tables[1])
    first_body, declared_boundary = _select_declared_body_section(doc, profile, first_body)
    root = first_body.getparent()
    preserved_intro = []
    if declared_boundary is not None and declared_boundary["selection"] == "exact_management_source_start_with_registered_generated_text":
        for xpath in declared_boundary["preserved_intro_xpaths"]:
            paragraph = root.getroottree().xpath(xpath, namespaces=NS)[0]
            preserved_intro.append((paragraph, paragraph.get("paraPrIDRef"),
                                    [(run, run.get("charPrIDRef")) for run in paragraph.findall("hp:run", NS)]))
    boundary = root.index(first_body)
    # In single-section forms, include the nearby actual first heading (not
    # tab-separated TOC entries) and the notice preceding the body table.
    if root is doc.root(0) and declared_boundary is None:
        for index in range(max(1, boundary - 8), boundary):
            paragraph = root[index]
            # A newly written TOC entry can look exactly like a chapter title.
            # The immutable source-owned text distinguishes the observed source
            # body heading from original tab-separated TOC paragraphs.
            text = getattr(doc, "_source_paragraph_text", {}).get(paragraph, "").strip()
            if re.match(r"^1[.)]\s", text) and "\t" not in text:
                first_body, boundary = paragraph, index
                break
        while boundary > 1 and own_text(root[boundary - 1]).strip().startswith(("검증용 합성 자료", "검토용 초안")):
            boundary -= 1
            first_body = root[boundary]
    original_body_member = next(name for name in doc.sections if doc.xml(name) is root)
    original_boundary = boundary
    margins = targets.get("paper_margin_hwp")
    landscape = targets.get("landscape_body", False)
    split_requested = root is doc.root(0) and (landscape or margins is not None)
    boundary_spacers, boundary_reports = _prepare_boundary_spacers(doc, profile, first_body) if split_requested else ([], [])
    cover_reports = _apply_cover_roles(doc, prepared_cover)
    toc_reports = _apply_toc_roles(doc, prepared_toc)
    page_reports = []
    split = False
    # A dedicated body section keeps cover page geometry independent. Existing
    # multi-section forms already establish that boundary in their source.
    if split_requested:
        body_section = doc.split_section(first_body, landscape=landscape, margins_hwp=margins,
            discard_boundary_spacers=boundary_spacers)
        split = True
        body_scopes = [doc.root(index) for index in range(body_section, len(doc.sections))]
    else:
        start_section = doc.sections.index(original_body_member)
        body_scopes = [doc.root(index) for index in range(start_section, len(doc.sections))]
    for scope in body_scopes:
        section = next(i for i in range(len(doc.sections)) if doc.root(i) is scope)
        page_reports.append(doc.set_page_layout(section, landscape=landscape, margins_hwp=margins,
            sync_header_footer_frames=targets.get("sync_header_footer_frames", False)))
    changes = {"body_runs": 0, "body_paragraphs": 0, "headings": 0, "header_cells": 0, "captions": 0,
               "picture_paragraphs": 0}
    heading_selections = []
    caption_selections = []
    captions = []
    marked_headings = getattr(doc, "_editorial_heading_paragraphs", set())
    marked_captions = getattr(doc, "_editorial_caption_paragraphs", set())
    marked_pictures = getattr(doc, "_editorial_picture_paragraphs", set())
    for scope in body_scopes:
        changes["body_runs"] += doc.use_character_style(scope, font=targets.get("body_font_face"),
            size_pt=targets["body_height_hwp"] / 100 if "body_height_hwp" in targets else None,
            spacing_percent=targets.get("character_spacing_percent"), ratio_percent=targets.get("character_ratio_percent"))
        changes["body_paragraphs"] += doc.use_paragraph_style(scope, line_spacing_percent=targets.get("body_line_spacing_percent"))
        for paragraph in scope.iter(HP + "p"):
            if _protected(paragraph):
                continue
            text = own_text(paragraph).strip()
            if not text:
                continue
            # Section headings and the named appendix entries have a deliberate
            # short heading role; numbered procedure prose keeps body formatting.
            source_text = doc._source_paragraph_text.get(paragraph, "").strip()
            is_heading = paragraph in marked_headings or (paragraph.getparent() is scope
                and bool(re.match(r"^\d+\.\s", source_text)) and "\t" not in source_text and len(text) <= 90)
            if paragraph in marked_captions:
                captions.append((paragraph, "renderer_semantic_role"))
            elif is_heading:
                doc.use_character_style(paragraph, font=targets.get("heading_font_face"),
                    size_pt=targets.get("heading_height_hwp", targets.get("body_height_hwp", 1000)) / 100, bold=targets.get("heading_bold", True))
                doc.use_paragraph_style(paragraph, line_spacing_percent=targets.get("heading_line_spacing_percent"), keep_with_next=True)
                changes["headings"] += 1
                heading_selections.append({"text": text, "xpath": paragraph.getroottree().getpath(paragraph),
                                           "selection": "renderer_semantic_role" if paragraph in marked_headings else "source_guarded_heading_hint"})
    td3_initial_reports = _apply_td3_initial_typography(doc, targets, prepared_td3_initial)
    changes["initial_chapter_text_owners"] = len(td3_initial_reports)
    body_tables = [table for scope in body_scopes for table in scope.iter(HP + "tbl")
                   if not _protected(table) and not any(a.tag == HP + "tbl" for a in table.iterancestors())]
    table_reports = []
    repeat_widths = {}
    trace_tables = getattr(doc, "_editorial_trace_tables", set())
    for index, table in enumerate(body_tables):
        trace = table in trace_tables
        column_override = targets.get("trace_table_column_widths_hwp") if trace else targets.get("table_column_widths_hwp", {}).get(str(index))
        if trace and column_override is None:
            raise ComposeError("Registered trace table needs explicit role-specific column widths")
        total = targets.get("table_width_hwp")
        if column_override is not None or total is not None:
            original_widths = _columns(table)
            signature = (int(table.get("colCnt")), tuple(original_widths))
            if column_override is not None and not trace:
                repeat_widths[signature] = column_override
            if column_override is not None:
                widths = column_override
            elif signature in repeat_widths:
                widths = repeat_widths[signature]
            else:
                widths = _scaled(original_widths, int(total))
            report = doc.set_table_layout(table, column_widths_hwp=widths, cell_margins_hwp=targets.get("cell_margin_hwp"))
            report.update(body_table_index=index, instance_id=table.get("id"))
            if trace:
                report["selection"] = "renderer_trace_table_role"
            table_reports.append(report)
        rows = table.findall("hp:tr", NS)
        column_count = int(table.get("colCnt"))
        grouped_test = role in {"SF-TI1", "SF-TI4"} and column_count == 7 and len(rows[0].findall("hp:tc", NS)) < 7
        metadata_rows = 3 if role == "SF-TI1" else 2
        for row_index, row in enumerate(rows):
            for cell in row.findall("hp:tc", NS):
                address, span = cell.find("hp:cellAddr", NS), cell.find("hp:cellSpan", NS)
                column = int(address.get("colAddr"))
                count = int(span.get("colSpan"))
                card = role in {"SF-AD2", "SF-TD3", "SF-TD4"} or (role == "SF-PM3" and int(table.get("colCnt")) == 4)
                label = (column == 0 and count == 1) or (column == 2 and count == 1)
                meeting_label = role == "SF-PM2" and column == 0 and count == 1
                if column_count == 1:
                    # Narrative content lives in a one-cell frame. Its first
                    # row is the whole body, never a table column heading.
                    header = False
                elif grouped_test and row_index < metadata_rows:
                    header = column == 0 or (column == 4 and row_index == (1 if role == "SF-TI1" else 0))
                elif card:
                    header = label
                elif role == "SF-PM2":
                    header = meeting_label
                else:
                    header = cell.get("header") == "1" or row_index == 0
                if header:
                    doc.use_character_style(cell, font=targets.get("table_header_font_face"),
                        size_pt=targets.get("table_header_height_hwp", targets.get("body_height_hwp", 1000)) / 100, bold=targets.get("table_header_bold", True))
                    doc.use_paragraph_style(cell, line_spacing_percent=targets.get("table_header_line_spacing_percent"))
                    changes["header_cells"] += 1
    management_role_reports = []
    # These generated value identities must be styled after enclosing labels.
    # Only explicit bold/italic flags are allowed; font/size/spacing stay as
    # selected above. Source guides and table headers are separate owners.
    for record, target in prepared_management_roles:
        paragraph = record["paragraph"]
        if not any(scope in paragraph.iterancestors() for scope in body_scopes):
            raise ComposeError("Management label/value escaped its selected body section")
        doc.use_character_style(paragraph, **target)
        management_role_reports.append({"name": record["name"], "entity_id": record["entity_id"],
            "input_pointer": record["input_pointer"], "text": own_text(paragraph),
            "xpath": paragraph.getroottree().getpath(paragraph), "target": dict(target),
            "selection": "exact_source_role_with_generated_paragraph_cell_identity"})
    # Apply semantic captions after enclosing cell styles so a header-cell
    # override cannot silently turn a declared 9.5pt caption into 10pt text.
    for paragraph, selection in captions:
        doc.use_character_style(paragraph, font=targets.get("caption_font_face"),
            size_pt=targets.get("caption_height_hwp", targets.get("body_height_hwp", 1000)) / 100)
        doc.use_paragraph_style(paragraph, line_spacing_percent=targets.get("caption_line_spacing_percent"),
            keep_with_next=True)
        maximum = targets.get("after_picture_caption_keep_max_chars")
        if maximum is not None:
            if (profile.get("role") not in {"SF-TI1", "SF-TI4"}
                    or type(maximum) is not int or maximum != 240):
                raise ComposeError("Unsupported bounded after-picture caption policy")
            picture = getattr(doc, "_editorial_after_picture_captions", {}).get(paragraph)
            if picture is not None:
                if (picture not in marked_pictures or paragraph.getprevious() is not picture
                        or picture.getparent() is not paragraph.getparent()):
                    raise ComposeError("After-picture caption has lost its registered picture owner")
                doc.use_paragraph_keep(paragraph, keep_lines=len(own_text(paragraph)) <= maximum,
                                       keep_with_next=False)
        changes["captions"] += 1
        caption_selections.append({"text": own_text(paragraph), "xpath": paragraph.getroottree().getpath(paragraph),
                                   "selection": selection})
    for scope in body_scopes:
        for paragraph in scope.iter(HP + "p"):
            if paragraph in marked_pictures and not _protected(paragraph):
                changes["picture_paragraphs"] += doc.use_paragraph_style(paragraph, keep_with_next=True)
    # These title/period/summary owners previously preceded the body section.
    # Moving the boundary must not silently shrink them to ordinary body size
    # or change their direct formatting/spacing. Keep only the declared intro.
    for paragraph, paragraph_style, runs in preserved_intro:
        paragraph.set("paraPrIDRef", paragraph_style)
        for run, character_style in runs:
            run.set("charPrIDRef", character_style)
    preserved_title_reports = []
    for record in preserved_management_titles:
        paragraph = record["paragraph"]
        paragraph.set("paraPrIDRef", record["paraPrIDRef"])
        for run, character_style in record["runs"]:
            run.set("charPrIDRef", character_style)
        preserved_title_reports.append({"name": record["name"], "text": own_text(paragraph),
            "source": record["source"], "xpath": paragraph.getroottree().getpath(paragraph),
            "selection": "exact_source_title_with_renderer_element_identity",
            "source_typography_and_spacing_preserved": True})
    # Append/reuse this final definition after all other typography so adding
    # the program target cannot renumber unrelated body paragraph definitions.
    cover_program_report = _apply_cover_program_paragraph(doc, prepared_cover_program)
    return {"profile": "reference-v1", "role": role, "schema_version": profile["schema_version"],
            "source_template_sha256": doc.source_sha256, "profile_status": profile.get("status"),
            "selector": {"source_body_member": original_body_member, "source_top_level_paragraph_index": original_boundary,
                         "body_table_count": len(body_tables), "cover_table_excluded": True, "new_body_section": split,
                         "body_section_boundary": declared_boundary,
                         "header_footer_and_notes_excluded": not targets.get("sync_header_footer_frames", False),
                         "header_footer_and_notes_typography_excluded": True,
                         "header_footer_frame_extents_declared": targets.get("sync_header_footer_frames", False),
                         "heading_selections": heading_selections,
                         "caption_selections": caption_selections},
            "changes": changes, "pages": page_reports, "tables": table_reports, "cover_roles": cover_reports,
            "cover_program_paragraph": cover_program_report,
            "toc_roles": toc_reports,
            "management_character_roles": management_role_reports,
            "management_preserved_titles": preserved_title_reports,
            "td3_initial_chapter_typography": td3_initial_reports,
            "section_boundary_spacers": boundary_reports,
            "allowed_changes": profile.get("allowed_changes", []), "native_verified": False}
