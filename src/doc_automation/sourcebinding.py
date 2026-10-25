"""Bind private source locations to public, immutable inventory fingerprints.

Private configuration supplies paths only. It cannot replace the role pins,
source selectors, formatting targets, or any document facts.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


TEMPLATE_ROOT_ENV = "DOC_AUTOMATION_TEMPLATE_ROOT"
SOURCE_MAP_ENV = "DOC_AUTOMATION_SOURCE_MAP"
_ROLES = frozenset(("SF-AD1", "SF-AD2", "SF-AD3", "SF-TD1", "SF-TD2", "SF-TD3", "SF-TD4", "SF-TD5",
                    "SF-CD1", "SF-TI1", "SF-TI2", "SF-TI3", "SF-TI4", "SF-OS1", "SF-OS2",
                    "SF-PM1", "SF-PM2", "SF-PM3", "SF-PM4"))


class SourceBindingError(ValueError):
    """A configured location does not identify the pinned local source."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceBindingError("Duplicate source configuration key: " + key)
        result[key] = value
    return result


def _json(path):
    try:
        return json.loads(Path(path).read_bytes().decode("utf-8-sig"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceBindingError("Cannot read source metadata: " + str(path)) from exc


def _inventory_path(inventory_path):
    return (Path(inventory_path).expanduser().resolve() if inventory_path is not None else
            Path(__file__).resolve().parents[2] / "resources/stage1/inventory.json")


def _registry(inventory_path=None):
    inventory = _json(_inventory_path(inventory_path))
    if not isinstance(inventory, dict) or not isinstance(inventory.get("documents"), list):
        raise SourceBindingError("Public source inventory needs a documents list")
    result = {}
    for item in inventory["documents"]:
        if not isinstance(item, dict):
            raise SourceBindingError("Public source inventory item must be an object")
        identifier, fingerprint = item.get("id"), item.get("sha256")
        if (not isinstance(identifier, str) or not identifier
                or not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-fA-F]{64}", fingerprint) is None
                or identifier in result):
            raise SourceBindingError("Public source inventory needs unique IDs and fixed SHA-256 pins")
        result[identifier] = {"id": identifier, "sha256": fingerprint.lower()}
    return result


def profile_for_sha256(fingerprint, *, inventory_path=None):
    """Find optional compose metadata by bytes, never by a published home path."""
    path = _inventory_path(inventory_path)
    if not path.is_file():
        return None  # Generic compose callers may instead supply expected_sha256.
    matches = [item for item in _registry(path).values() if item["sha256"] == fingerprint]
    if len(matches) > 1:
        raise SourceBindingError("Source fingerprint has ambiguous public inventory identities")
    return dict(matches[0]) if matches else None


def _local_path(value, *, base=None):
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip() or urlsplit(str(value)).scheme:
        raise SourceBindingError("Source binding accepts nonempty local paths only")
    path = Path(value).expanduser()
    if not path.is_absolute() and base is not None:
        path = base / path
    return path.resolve()


def _locations(template_root, registry):
    if template_root is not None:
        return _local_path(template_root), None
    if TEMPLATE_ROOT_ENV in os.environ:
        return _local_path(os.environ[TEMPLATE_ROOT_ENV]), None
    if SOURCE_MAP_ENV not in os.environ:
        return (Path.home() / "projects/gov-grants/_templates").resolve(), None
    config = _local_path(os.environ[SOURCE_MAP_ENV])
    data = _json(config)
    if (not isinstance(data, dict) or set(data) - {"schema_version", "templates", "inventory"}
            or type(data.get("schema_version")) is not int or data["schema_version"] != 1
            or not isinstance(data.get("templates", {}), dict)
            or not isinstance(data.get("inventory", {}), dict)
            or not ({"templates", "inventory"} & set(data))):
        raise SourceBindingError("Private source map accepts schema_version and path-only templates/inventory maps")
    bindings = {}
    for role, path in data.get("templates", {}).items():
        if role not in _ROLES:
            raise SourceBindingError("Unsupported template role in private source map: " + str(role))
        identifier = "template-" + role.lower()
        if identifier not in registry:
            raise SourceBindingError("Private source map role has no public fingerprint pin: " + role)
        bindings[identifier] = _local_path(path, base=config.parent)
    for identifier, path in data.get("inventory", {}).items():
        if identifier not in registry or identifier in bindings:
            raise SourceBindingError("Unknown or duplicate inventory identity in private source map: " + str(identifier))
        bindings[identifier] = _local_path(path, base=config.parent)
    return None, bindings


def _checked(item, path, label):
    if not path.is_file():
        raise SourceBindingError("Pinned source is not a local file: " + str(path))
    try:
        observed = sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SourceBindingError("Cannot read pinned source: " + str(path)) from exc
    if observed != item["sha256"]:
        raise SourceBindingError(f"Template profile SHA mismatch for {label}; review the new template version")
    return {"id": item["id"], "path": path, "sha256": item["sha256"]}


def _resolve(item, root, bindings):
    identifier = item["id"]
    role = identifier.removeprefix("template-").upper()
    canonical = identifier.startswith("template-") and role in _ROLES
    if bindings is not None:
        if identifier not in bindings:
            raise SourceBindingError("Private source map has no binding for " + identifier)
        return _checked(item, bindings[identifier], role if canonical else identifier)
    if not root.is_dir():
        raise SourceBindingError("Template root is not a local directory: " + str(root))
    if canonical:
        matches = sorted(p.resolve() for p in root.rglob(role + " *.hwpx") if p.is_file())
    else:
        matches = []
        for path in sorted(root.rglob("*.hwpx")):
            if path.is_file() and sha256(path.read_bytes()).hexdigest() == item["sha256"]:
                matches.append(path.resolve())
    if len(matches) != 1:
        raise SourceBindingError(f"Expected one pinned {role if canonical else identifier} source under {root}; found {len(matches)}")
    return _checked(item, matches[0], role if canonical else identifier)


def resolve_inventory_item(item, template_root=None, *, inventory_path=None):
    """Resolve an inventory ID after cross-checking its public SHA-256 pin."""
    registry = _registry(inventory_path)
    if (not isinstance(item, dict) or item.get("id") not in registry
            or not isinstance(item.get("sha256"), str)
            or item["sha256"].lower() != registry[item["id"]]["sha256"]):
        raise SourceBindingError("Requested inventory item differs from its public fingerprint pin")
    root, bindings = _locations(template_root, registry)
    return _resolve(registry[item["id"]], root, bindings)


def resolve_templates(roles, *, template_root=None, inventory_path=None):
    """Return role -> {id, path: Path, sha256}; locations never supply pins."""
    roles = list(roles)
    if not roles or len(set(roles)) != len(roles) or any(role not in _ROLES for role in roles):
        raise SourceBindingError("Template roles must be unique supported canonical roles")
    registry = _registry(inventory_path)
    root, bindings = _locations(template_root, registry)
    result = {}
    for role in roles:
        identifier = "template-" + role.lower()
        if identifier not in registry:
            raise SourceBindingError("No public template fingerprint pin for " + role)
        result[role] = _resolve(registry[identifier], root, bindings)
    return result


def resolve_template(role, *, template_root=None, inventory_path=None):
    return resolve_templates([role], template_root=template_root, inventory_path=inventory_path)[role]
