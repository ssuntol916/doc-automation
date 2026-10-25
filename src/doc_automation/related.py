"""Readable, source-owned projections of objects referenced by another role.

The register prints supplied identities and direct links only. It does not infer
transitive relations, implementation, test execution or approval.
"""
from __future__ import annotations

from copy import deepcopy

from .compose import ComposeError
from .hwpx import own_text
from .narrative import DOMAIN_LABELS, LABELS, describe_fields


PROJECTIONS = {
    "SF-AD2": (("features", "id name change_type before after requirement_ids status source_refs"),
               ("changes", "id name reason before after affected_refs approval_status status source_refs")),
    "SF-TD1": (("requirements", "id name"),),
    "SF-TD2": (("programs", "id name screen_ids table_ids requirement_ids"),
               ("database_tables", "id name")),
    "SF-TD3": (("features", "id name requirement_ids"), ("programs", "id name")),
    "SF-TD4": (("database_tables", "id name"),),
    "SF-TI3": (("screens", "id name path steps checks before_attachment_ids after_attachment_ids standard_attachment_ids source_refs"),),
    "SF-OS1": (("project/systems", "id name current_configuration target_configuration"),),
    "SF-OS2": (("deployment_items", "id name installation_status actual_specification installed_quantity installation_date verification_result"),),
    "SF-PM4": tuple((domain, "id name requirement_ids stage group_id") for domain in
                    ("features", "screens", "programs", "database_tables", "test_cases"))
              + (("changes", "id name reason before after affected_refs approval_status status source_refs"),),
}
KEEP_MAX_CHARS = 240


def _collection(data, pointer):
    value = data
    for part in pointer.split("/"):
        value = value.get(part, []) if isinstance(value, dict) else []
    return value if isinstance(value, list) else []


def _applicable(role, pointer, item, data):
    if pointer != "changes" and not (role == "SF-AD2" and pointer == "features"):
        return True
    requirement_ids = {x["id"] for x in data["requirements"]}
    if pointer == "changes":
        return any(ref.get("kind") == "requirements" and ref.get("id") in requirement_ids
                   for ref in item.get("affected_refs", []))
    if role == "SF-AD2" and pointer == "features":
        return item.get("change_type") == "modified" and bool(requirement_ids.intersection(item.get("requirement_ids", [])))
    return True


def _field_record(entity, key, value, paragraphs, register_key):
    pointer = entity["input_pointer"] + "/" + key.replace("~", "~0").replace("/", "~1")
    field = next((x for x in entity["fields"] if x["input_pointer"] == pointer), None)
    if field is None:
        field = {"input_pointer": pointer, "input_value": deepcopy(value), "input_type": type(value).__name__}
        entity["fields"].append(field)
    elif field["input_type"] != type(value).__name__ or field["input_value"] != value:
        raise ComposeError("Reference register conflicts with supplied meaning: " + pointer)
    owners = list(field.get("_primary_paragraphs", []))
    previous = field.get("_paragraph")
    if previous is not None and previous not in owners:
        owners.append(previous)
    for paragraph in paragraphs:
        if paragraph not in owners:
            owners.append(paragraph)
    if previous is None:
        field["_paragraph"] = paragraphs[0]
        field["rendered_text"] = own_text(paragraphs[0])
    field.update(representation="linked_object_register", content_review_status="pending",
                 register_key=register_key, _primary_paragraphs=owners)


def append_reference_register(doc, role, data, ctx, *, parent, prototype):
    """Append explicit role projections and merge their actual paragraph owners.

    Called in the editorial source-note scope after the main meaning supplement.
    Numeric styles remain document-local; the selected profile supplies sizes.
    """
    if not ctx.get("editorial"):
        return []
    items = [(pointer, index, item, tuple(k for k in keys.split() if k in item))
             for pointer, keys in PROJECTIONS.get(role, ())
             for index, item in enumerate(_collection(data, pointer)) if _applicable(role, pointer, item, data)]
    if not items:
        return []
    registry = getattr(doc, "_editorial_heading_paragraphs", None)
    if registry is None:
        registry = doc._editorial_heading_paragraphs = set()

    def append(text, *, heading=False, bold=False, keep_next=False):
        paragraph = doc.new_paragraph(text, prototype=prototype)
        doc.use_character_style(paragraph, bold=heading or bold)
        doc.use_paragraph_style(paragraph, align="LEFT")
        doc.use_paragraph_keep(paragraph, keep_lines=len(text) <= KEEP_MAX_CHARS,
                               keep_with_next=keep_next)
        if heading:
            registry.add(paragraph)
        parent.append(paragraph)
        return paragraph

    append("부록. 연결 항목 명세", heading=True, keep_next=True)
    append("제공된 항목의 식별자·명칭을 정리하고 입력된 직접 연결만 표시한다. 목록 등재로 요구사항 연결을 추론하지 않으며 구현·시험 수행·승인을 판단하지 않는다.", keep_next=True)
    entities = ctx.setdefault("meaning_map", [])
    summary = []
    for number, (pointer, index, item, keys) in enumerate(items, 1):
        key = f"L{number}"
        path = "/" + pointer + f"/{index}"
        entity = next((x for x in entities if x["input_pointer"] == path), None)
        if entity is None:
            entity = {"input_pointer": path, "entity_id": item.get("id"),
                      "entity_name": item.get("name"), "fields": []}
            entities.append(entity)
        domain = DOMAIN_LABELS.get(pointer.split("/")[-1], "시스템" if pointer == "project/systems" else pointer)
        details = [name for name in keys if name not in {"id", "name"}]
        identity = " — ".join(str(item[name]) for name in ("id", "name") if name in item)
        heading = append(f"[{key}] {domain} · {identity}", heading=bool(details),
                         bold=True, keep_next=bool(details))
        for name in ("id", "name"):
            if name in keys:
                _field_record(entity, name, item[name], [heading], key)
        for name in details:
            text = describe_fields({name: item[name]}, typed=True)
            lines = text.split("\n")
            paragraphs = [append(f"[{key}] {line}" if n == 0 else
                                 f"[{key}] {LABELS.get(name, name)} · {line}")
                          for n, line in enumerate(lines)]
            _field_record(entity, name, item[name], paragraphs, key)
        summary.append({"key": key, "input_pointer": path, "entity_id": item.get("id"),
                        "field_names": list(keys), "semantic_review_status": "pending"})
    ctx["reference_register"] = summary
    return summary
