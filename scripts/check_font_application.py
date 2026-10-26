#!/usr/bin/env python3
"""Check explicit font expectations against current HWPX display-bearing runs.

This read-only declaration gate does not apply a profile or infer success from
its targets. It resolves each used run -> local charPr -> all seven fontRef
languages -> language-local font.face. It cannot prove an installed font,
native substitution, generated field glyph, picture lettering, or page layout.

Usage: python scripts/check_font_application.py CURRENT.hwpx --expect EXPECT.json
       --report REPORT.json

Expectation contract (reports belong in a private/ignored workspace):
  {"schema_version": 1, "require_all_text_runs": false, "scopes": [
    {"id": "body", "section": "*", "xpath": "//hp:p",
     "expected_face": "Fixture Sans"}
  ]}

section is an exact OPF-spine section member or '*'. XPath must select hp:p or
hp:run, never an enclosing table/control. Paragraph selection includes only
its own runs; nested cell, drawing, note and header paragraphs need their own
selection. expected_face may instead be a map containing every SCRIPTS key.
Every scope needs at least one display-bearing run (min_text_runs >= 1 is the
legacy option name). Stored hp:t text and directly owned hp:pageNum/hp:autoNum
are font usage, including automatic numbers without any hp:t. The legacy
require_all_text_runs option requires coverage of both kinds. Whitespace-only
runs, field markers, newNum/pageNumCtrl, pictures and formulas are not font
usage by themselves. Stored field-result hp:t is checked; other generated
field glyphs without stored text remain outside this gate. Inline tails retain
their ownership. Legacy *_text_runs report counts now include display controls;
the corresponding *_display_runs names state that counting boundary explicitly.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import posixpath
import re
import sys
from zipfile import BadZipFile, ZipFile

from lxml import etree as E

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
NS = {"hp": HP, "hh": HH, "hs": HS}
P, RUN, TEXT = (f"{{{HP}}}{name}" for name in ("p", "run", "t"))
SCRIPTS = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")
INLINE = {"lineBreak": "\n", "tab": "\t", "nbSpace": "\u00a0", "nbsp": "\u00a0", "fwSpace": "\u3000"}
DISPLAY_CONTROLS = {f"{{{HP}}}pageNum", f"{{{HP}}}autoNum"}
CONTROL_WRAPPERS = {f"{{{HP}}}{name}" for name in ("ctrl", "switch", "case", "default")}
SCHEMA = "font-application-check-2"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse(data):
    root = E.fromstring(data, E.XMLParser(resolve_entities=False, no_network=True, recover=False))
    require(not root.getroottree().docinfo.doctype, "DTD/entity-bearing XML is unsupported")
    return root


def nearest(node, tag):
    return next((a for a in node.iterancestors() if a.tag == tag), None)


def inline_text(node):
    text = node.text or ""
    for child in node:
        require(isinstance(child.tag, str), "Comments/processing instructions inside text are unsupported")
        name = E.QName(child).localname
        require(E.QName(child).namespace == HP and name in INLINE,
                f"Unsupported inline text control: {child.tag}")
        text += INLINE[name] + inline_text(child) + (child.tail or "")
    return text


def run_text(run):
    owner = nearest(run, P)
    require(owner is not None, "Text run has no paragraph owner")
    texts = [t for t in run.iter(TEXT) if nearest(t, RUN) is run and nearest(t, P) is owner]
    require(all(t.getparent() is run for t in texts), "Unsupported indirect hp:t ownership")
    return "".join(inline_text(t) for t in texts)


def run_display_controls(run):
    """Known glyph-producing controls owned by this run, never a nested object.

Only neutral control/switch wrappers may occur between control and run. A
picture/formula/field or nested paragraph cannot lend its content to an outer
run's font usage. This is a declaration inventory, not a rendered glyph count.
"""
    owner = nearest(run, P)
    controls = []
    for node in run.iter():
        if node.tag not in DISPLAY_CONTROLS or nearest(node, RUN) is not run or nearest(node, P) is not owner:
            continue
        parent = node.getparent()
        while parent is not run and parent is not None and parent.tag in CONTROL_WRAPPERS:
            parent = parent.getparent()
        if parent is run:
            controls.append({"type": E.QName(node).localname, "xpath": node.getroottree().getpath(node)})
    return controls


def expected_faces(value):
    if isinstance(value, str) and value.strip():
        return dict.fromkeys(SCRIPTS, value)
    require(isinstance(value, dict) and set(value) == set(SCRIPTS),
            "expected_face must be a nonempty string or a complete seven-language map")
    require(all(isinstance(x, str) and x.strip() for x in value.values()), "Expected font faces cannot be empty")
    return dict(value)


class Package:
    def __init__(self, path):
        self.path = Path(path)
        self.payload = self.path.read_bytes()
        with ZipFile(BytesIO(self.payload)) as archive:
            names = archive.namelist()
            require(len(names) == len(set(names)), "Duplicate ZIP members")
            self.members = {n: archive.read(n) for n in names}
        require(self.members.get("mimetype", b"").strip() == b"application/hwp+zip", "Not an HWPX package")
        require("Contents/content.hpf" in self.members and "Contents/header.xml" in self.members,
                "Missing OPF or header")
        opf = parse(self.members["Contents/content.hpf"])
        items = {}
        for item in opf.xpath('//*[local-name()="manifest"]/*[local-name()="item"]'):
            ident, href = item.get("id"), item.get("href")
            require(ident and ident not in items and href, "Invalid/duplicate OPF item")
            require(not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", href) and not any(x in href for x in ("?", "#", "\\")),
                    "External/qualified OPF href is unsupported")
            candidates = {posixpath.normpath(href.lstrip("/")), posixpath.normpath(posixpath.join("Contents", href))}
            matches = [x for x in candidates if not x.startswith("../") and x in self.members]
            require(len(matches) == 1, "Unresolved/ambiguous OPF member")
            items[ident] = matches[0]
        self.sections, spine = {}, []
        for ref in opf.xpath('//*[local-name()="spine"]/*[local-name()="itemref"]'):
            member = items.get(ref.get("idref"))
            require(member is not None and member not in spine, "Unresolved/duplicate OPF spine member")
            spine.append(member)
            root = parse(self.members[member])
            if root.tag == f"{{{HS}}}sec":
                self.sections[member] = root
            else:
                require(root.tag == f"{{{HH}}}head", "Unsupported OPF spine member")
        require(self.sections, "No sections in the OPF spine")
        undeclared = {n for n in self.members if re.fullmatch(r"Contents/section\d+\.xml", n)} - self.sections.keys()
        require(not undeclared, "Section members outside OPF spine")
        header = parse(self.members["Contents/header.xml"])
        self.chars, self.fonts = defaultdict(list), defaultdict(list)
        for char in header.iter(f"{{{HH}}}charPr"):
            self.chars[char.get("id")].append(char)
        for family in header.iter(f"{{{HH}}}fontface"):
            for font in family.findall(f"{{{HH}}}font"):
                self.fonts[(family.get("lang"), font.get("id"))].append(font)
        self.text_runs, self.excluded_runs = {}, []
        for member, root in self.sections.items():
            for run in root.iter(RUN):
                text = run_text(run)
                controls = run_display_controls(run)
                locator = {"section": member, "xpath": root.getroottree().getpath(run)}
                if text.strip() or controls:
                    self.text_runs[run] = {**locator, "text_sha256": sha(text.encode("utf-8")), "text_characters": len(text),
                                           "usage_kind": "text_and_display_control" if text.strip() and controls else "text" if text.strip() else "display_control",
                                           "display_controls": controls}
                else:
                    self.excluded_runs.append({**locator, "reason": "no_nonwhitespace_owned_hp_t_or_supported_display_control"})
        self.run_order = {run: index for index, run in enumerate(self.text_runs)}

    def resolve(self, run):
        ident = run.get("charPrIDRef")
        chars = self.chars.get(ident, [])
        require(len(chars) == 1, "Missing/ambiguous used charPr")
        refs = chars[0].findall(f"{{{HH}}}fontRef")
        require(len(refs) == 1, "Missing/ambiguous used fontRef")
        result = {}
        for script in SCRIPTS:
            font_id = refs[0].get(script)
            fonts = self.fonts.get((script.upper(), font_id), []) if font_id is not None else []
            if len(fonts) != 1 or not fonts[0].get("face"):
                result[script] = {"resolved": False, "local_font_id": font_id,
                                  "error": "missing_or_ambiguous_language_font"}
            else:
                font = fonts[0]
                result[script] = {"resolved": True, "local_font_id": font_id, "face": font.get("face"),
                                  "fallbacks": [dict(x.attrib) for x in font.findall(f"{{{HH}}}substFont")],
                                  "is_embedded": font.get("isEmbedded"), "binary_item_id_ref": font.get("binaryItemIDRef")}
        return ident, result


def check_font_application(path, expectations):
    require(isinstance(expectations, dict) and expectations.get("schema_version") == 1,
            "Expected schema_version=1")
    scopes = expectations.get("scopes")
    require(isinstance(scopes, list) and scopes, "At least one explicit font scope is required")
    require(isinstance(expectations.get("require_all_text_runs", False), bool), "require_all_text_runs must be boolean")
    package = Package(path)
    scope_ids, covered, results, failures = set(), set(), [], []
    for scope in scopes:
        require(isinstance(scope, dict), "Font scope must be an object")
        ident, section, xpath = scope.get("id"), scope.get("section"), scope.get("xpath")
        require(isinstance(ident, str) and ident and ident not in scope_ids, "Missing/duplicate scope id")
        scope_ids.add(ident)
        require(isinstance(section, str) and (section == "*" or section in package.sections),
                "Scope section is outside the OPF spine")
        require(isinstance(xpath, str) and xpath.strip(), "Scope XPath is required")
        expected = expected_faces(scope.get("expected_face"))
        minimum = scope.get("min_text_runs", 1)
        require(isinstance(minimum, int) and not isinstance(minimum, bool) and minimum >= 1,
                "min_text_runs must be a positive integer")
        selected, owners = set(), 0
        for member, root in package.sections.items():
            if section != "*" and member != section:
                continue
            matches = root.xpath(xpath, namespaces=NS)
            require(isinstance(matches, list) and all(isinstance(n, E._Element) and n.tag in {P, RUN} for n in matches),
                    "XPath must select hp:p or hp:run owners")
            owners += len(matches)
            for owner in matches:
                runs = [owner] if owner.tag == RUN else [r for r in owner.iter(RUN) if nearest(r, P) is owner]
                selected.update(r for r in runs if r in package.text_runs)
        if len(selected) < minimum:
            failures.append({"scope": ident, "code": "insufficient_text_runs", "expected_minimum": minimum,
                             "actual": len(selected)})
        # Preserve the OPF/paragraph/run order in the diagnostic, independent of XPath order.
        checks = []
        for run in sorted(selected, key=package.run_order.__getitem__):
            locator = package.text_runs[run]
            covered.add(run)
            check = {**locator, "local_charPr_id": run.get("charPrIDRef")}
            try:
                _, actual = package.resolve(run)
                check["font_faces"] = actual
                mismatch = [script for script in SCRIPTS if not actual[script]["resolved"] or actual[script]["face"] != expected[script]]
                check["passed"] = not mismatch
                for script in mismatch:
                    failures.append({"scope": ident, **locator, "code": "font_face_mismatch" if actual[script]["resolved"] else "unresolved_font",
                                     "script": script, "expected_face": expected[script], "actual": actual[script]})
            except ValueError as exc:
                check.update(passed=False, error=str(exc))
                failures.append({"scope": ident, **locator, "code": "unresolved_character_format", "error": str(exc)})
            checks.append(check)
        results.append({"id": ident, "section": section, "xpath": xpath, "expected_faces": expected,
                        "matched_owners": owners, "checked_text_runs": len(checks), "minimum_text_runs": minimum,
                        "checked_display_runs": len(checks),
                        "passed": len(checks) >= minimum and all(c["passed"] for c in checks), "runs": checks})
    uncovered = [locator for run, locator in package.text_runs.items() if run not in covered]
    if expectations.get("require_all_text_runs", False) and uncovered:
        failures.append({"code": "uncovered_text_runs", "count": len(uncovered)})
    return {"schema": SCHEMA, "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "tool_sha256": sha(Path(__file__).read_bytes()),
            "input": {"path": str(package.path.resolve()), "sha256": sha(package.payload)},
            "expectations_sha256": sha(json.dumps(expectations, ensure_ascii=False, sort_keys=True).encode("utf-8")),
            "passed": not failures, "opf_section_order": list(package.sections), "scopes": results, "failures": failures,
            "coverage": {"total_text_runs": len(package.text_runs), "checked_unique_text_runs": len(covered),
                         "total_display_runs": len(package.text_runs), "checked_unique_display_runs": len(covered),
                         "counting_basis": "Stored hp:t text plus directly owned pageNum/autoNum; legacy text-run counters and require_all_text_runs include both",
                         "require_all_text_runs": expectations.get("require_all_text_runs", False),
                         "uncovered_text_runs": uncovered, "excluded_empty_or_control_only_runs": package.excluded_runs},
            "policy": {"numeric_ids": "Local lookup only; success compares actual resolved face strings, never matching IDs or profile targets",
                       "languages": list(SCRIPTS), "matching": "Exact primary face for all seven script declarations on every checked text/control display-bearing run",
                       "ownership": "Own hp:t and inline tails of the selected paragraph/run; nested paragraphs are independent owners",
                       "display_controls": "Directly owned pageNum and autoNum through neutral control/switch wrappers included even with no hp:t; newNum/pageNumCtrl do not themselves produce inspected glyphs",
                       "fields": "Stored field-result hp:t included; field instructions/markers and other generated field glyphs without stored text excluded",
                       "semantic_objects": "Picture/formula objects do not imply font usage. No glyphs inferred from their attributes or nested controls; their independent hp:p text requires selection",
                       "native_limit": "Declaration check only; font installation/substitution, fallback rendering and current native page quality need independent QA"}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument("--expect", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report_path = args.report.resolve()
        require(all(report_path != source.resolve() and not (args.report.exists() and args.report.samefile(source))
                    for source in (args.input, args.expect)), "Report must not overwrite an input or expectations file")
        require(not any(p.name in {"_templates", "_references"} for p in report_path.parents),
                "Reports cannot be written inside a read-only template/reference corpus")
        expected_bytes = args.expect.read_bytes()
        expected = json.loads(expected_bytes.decode("utf-8"))
        report = check_font_application(args.input, expected)
        report["expectations_source"] = {"path": str(args.expect.resolve()), "sha256": sha(expected_bytes)}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, KeyError, BadZipFile, E.XMLSyntaxError, E.XPathError) as exc:
        print(f"Font application check could not run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"passed": report["passed"], "checked_text_runs": report["coverage"]["checked_unique_text_runs"],
                      "failures": len(report["failures"]), "report": str(args.report)}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
