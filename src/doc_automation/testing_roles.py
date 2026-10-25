"""Source-bound case-card flow for the two verified testing forms."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree as ET

from .compose import ComposeError, HP
from .hwpx import NS, nearest, own_text, parse_xml


def _profile(role):
    if role not in {"SF-TI1", "SF-TI4"}:
        raise ComposeError("Unsupported source-bound testing role")
    return json.loads((Path(__file__).resolve().parents[2] / "resources/style-upgrade/profiles" /
                       (role + ".json")).read_text(encoding="utf-8"))


def prepare_case_cards(doc, role, table):
    """Check immutable source and live table identity before its data is filled."""
    profile = _profile(role)
    source = profile.get("testing_case_card_source", {})
    location = source.get("xml"), source.get("paragraph_xpath")
    paragraph = nearest(table, HP + "p")
    if (profile["source_template"]["sha256"] != doc.source_sha256
            or source.get("source_sha256") != doc.source_sha256
            or location[0] not in doc.sections
            or doc._source_paragraph_locations.get(paragraph) != location
            or doc._source_paragraph_text.get(paragraph) != source.get("paragraph_own_text")):
        raise ComposeError("Testing case-card source fingerprint/paragraph identity mismatch")
    root = parse_xml(doc._entries[location[0]])
    found = root.xpath(source.get("table_xpath", ""), namespaces=NS)
    if (len(found) != 1 or found[0].tag != HP + "tbl"
            or sha256(ET.tostring(found[0], method="c14n")).hexdigest() != source.get("table_c14n_sha256")
            or own_text(found[0].getparent().getparent()) != source.get("paragraph_own_text")
            or table.getparent().getparent() is not paragraph
            or table.get("colCnt") != str(source.get("column_count"))
            or ET.tostring(table, method="c14n") != ET.tostring(found[0], method="c14n")):
        raise ComposeError("Testing case-card exact source table shape mismatch")
    expected = {"per_case": True, "inline": False, "page_break": "CELL",
                "repeat_header_rows": 4 if role == "SF-TI1" else 3}
    if profile["targets"].get("testing_case_cards") != expected:
        raise ComposeError("Unsupported testing case-card flow declaration")
    return expected


def stale_guide_restart(doc, role, paragraph):
    """Remove only the declared TI1 guide restart, never a body/page control."""
    if role != "SF-TI1":
        return False
    profile = _profile(role)
    source = profile.get("stale_guide_page_restart", {})
    location = source.get("xml"), source.get("xpath")
    if doc._source_paragraph_locations.get(paragraph) != location:
        return False
    if (source.get("source_sha256") != doc.source_sha256
            or location[0] not in doc.sections
            or doc._source_paragraph_text.get(paragraph) != source.get("own_text")
            or own_text(paragraph) != source.get("own_text")):
        raise ComposeError("Testing guide restart source owner mismatch")
    original = parse_xml(doc._entries[location[0]]).xpath(location[1], namespaces=NS)
    if (len(original) != 1
            or sha256(ET.tostring(original[0], method="c14n")).hexdigest() != source.get("c14n_sha256")
            or ET.tostring(paragraph, method="c14n") != ET.tostring(original[0], method="c14n")):
        raise ComposeError("Testing guide restart exact source shape mismatch")
    numbers = paragraph.findall(".//hp:newNum", NS)
    controls = [node for control in paragraph.findall(".//hp:ctrl", NS) for node in control]
    if (len(numbers) != 1 or dict(numbers[0].attrib) != {"num": "1", "numType": "PAGE"}
            or controls != numbers):
        raise ComposeError("Testing guide restart may contain only one PAGE=1 control")
    return True
