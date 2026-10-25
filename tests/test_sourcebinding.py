"""Public fingerprints with local-only, path-only source configuration."""
from hashlib import sha256
import json
from pathlib import Path

import pytest

from doc_automation.sourcebinding import (
    SOURCE_MAP_ENV, TEMPLATE_ROOT_ENV, SourceBindingError,
    profile_for_sha256, resolve_inventory_item, resolve_template, resolve_templates,
)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.delenv(SOURCE_MAP_ENV, raising=False)
    monkeypatch.delenv(TEMPLATE_ROOT_ENV, raising=False)
    root = tmp_path / "local-originals"
    root.mkdir()
    paths = {"SF-AD1": root / "SF-AD1 source.hwpx", "SF-AD2": root / "SF-AD2 source.hwpx",
             "template-forms-2025": root / "other-form.hwpx"}
    for key, path in paths.items():
        path.write_bytes(("local fixture " + key).encode())
    records = [{"id": key if key.startswith("template-") else "template-" + key.lower(),
                "sha256": sha256(path.read_bytes()).hexdigest()} for key, path in paths.items()]
    inventory = tmp_path / "public-inventory.json"
    inventory.write_text(json.dumps({"documents": records}))
    return root, paths, records, inventory


def source_map(tmp_path, monkeypatch, data):
    path = tmp_path / "private-locations.json"
    path.write_text(json.dumps(data))
    monkeypatch.setenv(SOURCE_MAP_ENV, str(path))
    return path


def test_explicit_root_uses_public_sha_pins_without_any_private_inventory_fields(corpus):
    root, paths, records, inventory = corpus
    before = {k: p.read_bytes() for k, p in paths.items()}
    result = resolve_templates(["SF-AD1", "SF-AD2"], template_root=root, inventory_path=inventory)
    assert result == {role: {"id": "template-" + role.lower(), "path": paths[role].resolve(),
                             "sha256": records[index]["sha256"]}
                      for index, role in enumerate(["SF-AD1", "SF-AD2"])}
    assert {k: p.read_bytes() for k, p in paths.items()} == before


def test_environment_root_and_explicit_argument_precedence(corpus, monkeypatch):
    root, paths, _, inventory = corpus
    monkeypatch.setenv(TEMPLATE_ROOT_ENV, str(root))
    monkeypatch.setenv(SOURCE_MAP_ENV, "missing-configuration.json")
    assert resolve_template("SF-AD1", inventory_path=inventory)["path"] == paths["SF-AD1"]
    monkeypatch.setenv(TEMPLATE_ROOT_ENV, "missing-directory")
    assert resolve_template("SF-AD1", template_root=root, inventory_path=inventory)["path"] == paths["SF-AD1"]


def test_path_map_resolves_relative_to_config_and_cannot_change_fingerprint(corpus, tmp_path, monkeypatch):
    root, paths, records, inventory = corpus
    source_map(tmp_path, monkeypatch, {"schema_version": 1,
               "templates": {"SF-AD1": str(paths["SF-AD1"].relative_to(tmp_path))}})
    result = resolve_template("SF-AD1", inventory_path=inventory)
    assert result["path"] == paths["SF-AD1"] and result["sha256"] == records[0]["sha256"]
    paths["SF-AD1"].write_bytes(b"changed input")
    with pytest.raises(SourceBindingError, match="SHA mismatch"):
        resolve_template("SF-AD1", inventory_path=inventory)


def test_generic_inventory_form_resolves_by_approved_sha_or_explicit_map(corpus, tmp_path, monkeypatch):
    root, paths, records, inventory = corpus
    assert resolve_inventory_item(records[2], root, inventory_path=inventory)["path"] == paths["template-forms-2025"]
    source_map(tmp_path, monkeypatch, {"schema_version": 1,
               "inventory": {records[2]["id"]: str(paths["template-forms-2025"])}})
    assert resolve_inventory_item(records[2], inventory_path=inventory)["sha256"] == records[2]["sha256"]


def test_generic_inventory_request_cannot_supply_a_different_pin(corpus):
    root, _, records, inventory = corpus
    with pytest.raises(SourceBindingError, match="public fingerprint"):
        resolve_inventory_item({**records[2], "sha256": "0" * 64}, root, inventory_path=inventory)


@pytest.mark.parametrize("config", [
    {"schema_version": 1, "templates": {}, "sha256": "0" * 64},
    {"schema_version": 1, "templates": {}, "targets": {}},
    {"schema_version": 1, "templates": {}, "selectors": {}},
    {"schema_version": True, "templates": {}},
    {"schema_version": 1, "templates": {"SF-AD1": {"path": "source.hwpx", "sha256": "0" * 64}}},
    {"schema_version": 1, "templates": {"SF-UNKNOWN": "source.hwpx"}},
    {"schema_version": 1, "templates": {"SF-AD1": "https://example.invalid/template.hwpx"}},
    {"schema_version": 1, "inventory": {"unregistered-source": "source.hwpx"}},
])
def test_private_map_rejects_metadata_or_unregistered_bindings(corpus, tmp_path, monkeypatch, config):
    _, _, _, inventory = corpus
    source_map(tmp_path, monkeypatch, config)
    with pytest.raises(SourceBindingError):
        resolve_template("SF-AD1", inventory_path=inventory)


def test_private_map_duplicate_alias_or_duplicate_json_key_is_rejected(corpus, tmp_path, monkeypatch):
    _, paths, records, inventory = corpus
    config = source_map(tmp_path, monkeypatch, {"schema_version": 1,
        "templates": {"SF-AD1": str(paths["SF-AD1"])},
        "inventory": {records[0]["id"]: str(paths["SF-AD1"])}})
    with pytest.raises(SourceBindingError, match="duplicate inventory"):
        resolve_template("SF-AD1", inventory_path=inventory)
    config.write_text('{"schema_version":1,"templates":{},"templates":{}}')
    with pytest.raises(SourceBindingError, match="Duplicate"):
        resolve_template("SF-AD1", inventory_path=inventory)


def test_private_map_missing_role_does_not_fall_back_or_rebind_other_role(corpus, tmp_path, monkeypatch):
    _, paths, _, inventory = corpus
    source_map(tmp_path, monkeypatch, {"schema_version": 1, "templates": {"SF-AD2": str(paths["SF-AD2"])}})
    with pytest.raises(SourceBindingError, match="no binding"):
        resolve_template("SF-AD1", inventory_path=inventory)
    source_map(tmp_path, monkeypatch, {"schema_version": 1, "templates": {"SF-AD1": str(paths["SF-AD2"])}})
    with pytest.raises(SourceBindingError, match="SHA mismatch"):
        resolve_template("SF-AD1", inventory_path=inventory)


@pytest.mark.parametrize("generic", [False, True])
def test_duplicate_source_matches_are_not_silently_selected(corpus, generic):
    root, paths, records, inventory = corpus
    key = "template-forms-2025" if generic else "SF-AD1"
    duplicate = root / ("generic-copy.hwpx" if generic else "SF-AD1 copy.hwpx")
    duplicate.write_bytes(paths[key].read_bytes())
    with pytest.raises(SourceBindingError, match="found 2"):
        resolve_inventory_item(records[2 if generic else 0], root, inventory_path=inventory)


def test_inventory_is_required_and_discovered_file_never_self_pins(corpus):
    root, paths, records, inventory = corpus
    with pytest.raises(SourceBindingError, match="Cannot read source metadata"):
        resolve_template("SF-AD1", template_root=root, inventory_path=inventory.with_name("absent.json"))
    inventory.write_text(json.dumps({"documents": records[1:]}))
    with pytest.raises(SourceBindingError, match="No public template fingerprint"):
        resolve_template("SF-AD1", template_root=root, inventory_path=inventory)


def test_public_legacy_source_path_is_ignored_and_compose_metadata_uses_sha_only(corpus):
    root, paths, records, inventory = corpus
    inventory.write_text(json.dumps({"documents": [{**r, "source_path": "unavailable-original-location"} for r in records]}))
    assert resolve_template("SF-AD1", template_root=root, inventory_path=inventory)["path"] == paths["SF-AD1"]
    assert profile_for_sha256(records[0]["sha256"], inventory_path=inventory) == records[0]
    assert profile_for_sha256("0" * 64, inventory_path=inventory) is None


def test_public_pin_registry_rejects_duplicate_identity(corpus):
    root, _, records, inventory = corpus
    inventory.write_text(json.dumps({"documents": [*records, records[0]]}))
    with pytest.raises(SourceBindingError, match="unique IDs"):
        resolve_template("SF-AD1", template_root=root, inventory_path=inventory)


def test_hex_case_does_not_change_public_fingerprint_identity(corpus):
    root, paths, records, inventory = corpus
    upper = {**records[2], "sha256": records[2]["sha256"].upper()}
    inventory.write_text(json.dumps({"documents": [*records[:2], upper]}))
    result = resolve_inventory_item(upper, root, inventory_path=inventory)
    assert result["path"] == paths["template-forms-2025"] and result["sha256"] == records[2]["sha256"]


def test_default_home_root_is_generic_and_still_requires_pinned_bytes(corpus, tmp_path, monkeypatch):
    _, paths, _, inventory = corpus
    default_root = tmp_path / "projects/gov-grants/_templates"
    default_root.mkdir(parents=True)
    expected = default_root / paths["SF-AD1"].name
    expected.write_bytes(paths["SF-AD1"].read_bytes())
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert resolve_template("SF-AD1", inventory_path=inventory)["path"] == expected
    expected.write_bytes(b"different local source")
    with pytest.raises(SourceBindingError, match="SHA mismatch"):
        resolve_template("SF-AD1", inventory_path=inventory)
