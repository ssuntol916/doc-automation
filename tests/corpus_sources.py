"""Resolve read-only corpus locations without storing private filesystem paths."""
from doc_automation.sourcebinding import resolve_inventory_item, resolve_template

def pinned_source_path(value):
    if isinstance(value, str):
        return resolve_template(value)["path"]
    if "role" in value:
        return resolve_template(value["role"])["path"]
    return resolve_inventory_item(value)["path"]
