"""Two source-bound management label/value roles; no generic style inference."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from .compose import ComposeError, PROTECTED_CONTENT
from .hwpx import NS, nearest, own_text, parse_xml


HP = "{" + NS["hp"] + "}"
_NAMES = {
    "SF-PM2": {f"meeting_{field}_{kind}" for field in ("discussions", "decisions", "special_notes", "attendees")
               for kind in ("label", "value")},
    "SF-PM3": {"change_request_number_value"},
}


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


def source_paragraph(doc, selector):
    """Resolve the immutable source, not a generated paragraph's local IDs."""
    if selector["source_sha256"] != doc.source_sha256 or selector["xml"] not in doc._entries:
        raise ComposeError("Management role source fingerprint/member mismatch")
    root = parse_xml(doc._entries[selector["xml"]])
    found = root.xpath(selector["xpath"], namespaces=NS)
    runs = root.xpath(selector["run_xpath"], namespaces=NS)
    if (len(found) != 1 or found[0].tag != HP + "p"
            or own_text(found[0]) != selector["text_before_generation_verbatim"]
            or len(runs) != 1 or runs[0].getparent() is not found[0]):
        raise ComposeError("Management role exact source paragraph/run mismatch")
    cell = nearest(found[0], HP + "tc")
    if ((cell is None) != (selector["cell_address"] is None)
            or cell is not None and dict(cell.find("hp:cellAddr", NS).attrib) != selector["cell_address"]):
        raise ComposeError("Management role source cell address mismatch")
    header = parse_xml(doc._entries["Contents/header.xml"])
    chars = {p.get("id"): p for p in header.findall(".//hh:charPr", NS)}
    char = chars[runs[0].get("charPrIDRef")]
    flags = {"bold": char.find("hh:bold", NS) is not None,
             "italic": char.find("hh:italic", NS) is not None}
    if flags != selector["source_flags"] or int(char.get("height")) != selector["source_height_hwp"]:
        raise ComposeError("Management role resolved source formatting mismatch")
    return found[0]


def load_contract(doc, role):
    profile_path = Path(__file__).resolve().parents[2] / "resources/style-upgrade/profiles" / (role + ".json")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    targets = profile["targets"].get("management_character_roles")
    if targets is None:
        return None
    if (role not in _NAMES or set(targets) != _NAMES[role]
            or profile["role"] != role or profile["source_template"]["sha256"] != doc.source_sha256):
        raise ComposeError("Unsupported management character-role contract")
    selectors = profile["management_character_role_sources"]
    if set(selectors) != set(targets):
        raise ComposeError("Management role targets and source selectors differ")
    for name, target in targets.items():
        if (not target or set(target) - {"bold", "italic"}
                or not all(isinstance(value, bool) for value in target.values())):
            raise ComposeError("Management roles permit explicit bold/italic flags only")
        source_paragraph(doc, selectors[name]["source"])
        flag_source = selectors[name]["source"]
        if "regular_reference" in selectors[name]:
            reference = source_paragraph(doc, selectors[name]["regular_reference"])
            if own_text(reference) != "":
                raise ComposeError("Management regular value reference must be an empty source value")
            flag_source = selectors[name]["regular_reference"]
        if any(flag_source["source_flags"][key] != value for key, value in target.items()):
            raise ComposeError("Management target flag differs from its declared source role")
    doc._editorial_management_profile_digest = _digest(profile)
    doc._editorial_management_roles = []
    doc._editorial_management_expected = {name: 0 for name in targets}
    appendix = profile.get("generated_appendix_prototype")
    if appendix is not None:
        if role != "SF-PM2" or appendix != {"source_role": "meeting_special_notes_value", "left_hwp": 0, "intent_hwp": 0}:
            raise ComposeError("Unsupported management appendix prototype declaration")
        prototype = source_paragraph(doc, selectors[appendix["source_role"]]["source"])
        if own_text(prototype) or any(node.tag.rsplit("}", 1)[-1] in PROTECTED_CONTENT for node in prototype.iter()):
            raise ComposeError("Management appendix prototype must be an empty plain source value")
        header = parse_xml(doc._entries["Contents/header.xml"])
        paragraphs = header.xpath(".//hh:paraPr[@id=$id]", namespaces=NS, id=prototype.get("paraPrIDRef"))
        if len(paragraphs) != 1:
            raise ComposeError("Management appendix source paragraph style is unresolved")
        for name in ("left", "intent"):
            values = paragraphs[0].findall(".//hc:" + name, NS)
            if len(values) != 2 or any(int(value.get("value")) != appendix[name + "_hwp"] for value in values):
                raise ComposeError("Management appendix source margin differs from its neutral declaration")
        doc._editorial_appendix_prototype = prototype
    return selectors


def _register(doc, name, paragraph, table, cell, text, *, entity_id, input_pointer):
    if nearest(paragraph, HP + "tc") is not cell or nearest(cell, HP + "tbl") is not table:
        raise ComposeError("Management semantic paragraph has no exact generated cell owner")
    doc._editorial_management_roles.append({"name": name, "paragraph": paragraph,
        "table": table, "cell": cell, "text": text, "entity_id": entity_id,
        "input_pointer": input_pointer})
    doc._editorial_management_expected[name] += 1


def split_meeting_value(doc, table, row, field, label, value, selectors, *, entity_id, input_pointer):
    """Split only the four verified full-span plain-text source cells."""
    label_key, value_key = f"meeting_{field}_label", f"meeting_{field}_value"
    label_source = source_paragraph(doc, selectors[label_key]["source"])
    value_source = source_paragraph(doc, selectors[value_key]["source"])
    cell = doc.cell(table, row, 0)
    address, span = cell.find("hp:cellAddr", NS), cell.find("hp:cellSpan", NS)
    paragraphs = cell.findall("hp:subList/hp:p", NS)
    label_index = selectors[label_key]["source_paragraph_index"]
    value_index = selectors[value_key]["source_paragraph_index"]
    if (int(table.get("colCnt")) != 2 or len(table.findall("hp:tr", NS)) != 8
            or dict(address.attrib) != {"colAddr": "0", "rowAddr": str(row)}
            or int(span.get("colSpan")) != 2
            or len(paragraphs) <= max(label_index, value_index) or label_index >= value_index
            or own_text(paragraphs[label_index]) != own_text(label_source)
            or own_text(paragraphs[value_index]) != own_text(value_source)
            or any(node.tag.rsplit("}", 1)[-1] in PROTECTED_CONTENT
                   for p in paragraphs for node in p.iter())):
        raise ComposeError("PM2 source label/value row or plain-text boundary mismatch")
    sublist = cell.find("hp:subList", NS)
    # Reuse the exact source label/value paragraphs. Allocating replacement
    # paragraphs would needlessly shift later cloned header/footer IDs.
    label_p, value_p = paragraphs[label_index], paragraphs[value_index]
    doc.set_paragraph_text(label_p, label)
    doc.set_paragraph_text(value_p, value)
    for p in paragraphs:
        if p is not label_p and p is not value_p:
            sublist.remove(p)
    doc.invalidate_layout(cell)
    doc.use_paragraph_keep(label_p, keep_lines=True, keep_with_next=True)
    _register(doc, label_key, label_p, table, cell, label, entity_id=entity_id, input_pointer=None)
    _register(doc, value_key, value_p, table, cell, value, entity_id=entity_id, input_pointer=input_pointer)
    return value_p


def register_change_value(doc, table, row, text, *, entity_id, input_pointer):
    if int(table.get("colCnt")) != 8 or row < 1:
        raise ComposeError("PM3 ledger value requires its verified eight-column row")
    cell = doc.cell(table, row, 2)
    paragraphs = cell.findall("hp:subList/hp:p", NS)
    if (dict(cell.find("hp:cellAddr", NS).attrib) != {"colAddr": "2", "rowAddr": str(row)}
            or len(paragraphs) != 1 or own_text(paragraphs[0]) != text):
        raise ComposeError("PM3 request-number generated value owner mismatch")
    _register(doc, "change_request_number_value", paragraphs[0], table, cell, text,
              entity_id=entity_id, input_pointer=input_pointer)
    return paragraphs[0]


def prepare_overrides(doc, profile):
    targets = profile["targets"].get("management_character_roles")
    if targets is None or not hasattr(doc, "_editorial_management_expected"):
        return []  # A direct source-form compose has no generated value claim.
    if profile["role"] not in _NAMES or set(targets) != _NAMES[profile["role"]]:
        raise ComposeError("Management semantic targets do not match the supported role")
    if _digest(profile) != doc._editorial_management_profile_digest:
        raise ComposeError("Management source profile changed during rendering")
    counts = {name: 0 for name in targets}
    prepared, seen = [], set()
    for record in doc._editorial_management_roles:
        name, paragraph, cell, table = (record[key] for key in ("name", "paragraph", "cell", "table"))
        if (name not in targets or paragraph in seen or own_text(paragraph) != record["text"]
                or nearest(paragraph, HP + "tc") is not cell or nearest(cell, HP + "tbl") is not table
                or any(a.tag.rsplit("}", 1)[-1] in {"header", "footer", "footNote", "endNote"}
                       for a in paragraph.iterancestors())):
            raise ComposeError("Management registered label/value identity mismatch")
        source_paragraph(doc, profile["management_character_role_sources"][name]["source"])
        seen.add(paragraph)
        counts[name] += 1
        prepared.append((record, targets[name]))
    if counts != doc._editorial_management_expected:
        raise ComposeError("Management generated role count mismatch")
    return prepared


def prepare_preserved_titles(doc, profile):
    """Preserve the one source-owned PM3 request-card title, including spacing."""
    targets = profile["targets"].get("management_preserved_titles")
    registry = getattr(doc, "_editorial_management_preserved_titles", {})
    if targets is None or not registry:
        return []
    if (profile["role"] != "SF-PM3" or set(targets) != {"change_request_title"}
            or set(registry) != set(targets)
            or targets["change_request_title"] != {"preserve_source_own_run_styles": True,
                "preserve_source_paragraph_except_declared_keeps": True}):
        raise ComposeError("Unsupported preserved management title contract")
    selector = profile["management_preserved_title_sources"]["change_request_title"]
    source = source_paragraph(doc, selector)
    paragraph = registry["change_request_title"]
    if (doc._source_paragraph_locations.get(paragraph) != (selector["xml"], selector["xpath"])
            or doc._source_paragraph_text.get(paragraph) != own_text(source)
            or own_text(paragraph) != own_text(source)
            or paragraph.getparent() is not doc.root(0)):
        raise ComposeError("PM3 preserved title source/renderer identity mismatch")
    runs = paragraph.findall("hp:run", NS)
    source_runs = source.findall("hp:run", NS)
    if [run.get("charPrIDRef") for run in runs] != [run.get("charPrIDRef") for run in source_runs]:
        raise ComposeError("PM3 title own-run source typography changed before profile")
    return [{"name": "change_request_title", "paragraph": paragraph,
        "paraPrIDRef": paragraph.get("paraPrIDRef"),
        "runs": [(run, run.get("charPrIDRef")) for run in runs],
        "source": selector}]
