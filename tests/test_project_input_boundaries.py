"""Main JSON byte identity and generated-path alias protection."""
from hashlib import sha256
import json
from pathlib import Path

import pytest

from doc_automation import renderers
from doc_automation.compose import TemplateDocument
from test_reference_quotations import quotation

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "examples/style-upgrade/illustrated-extended-v2/illustrated.project.json"


def _relocated_input():
    data = json.loads(INPUT.read_text())
    for collection in ("sources", "attachments"):
        for record in data.get(collection, []):
            if record.get("path"):
                path = Path(record["path"]).expanduser()
                record["path"] = str((INPUT.parent / path if not path.is_absolute() else path).resolve())
    return data


def copy_input(tmp_path):
    source = tmp_path / "input" / "project.json"
    source.parent.mkdir()
    source.write_text(json.dumps(_relocated_input(), ensure_ascii=False))
    return source


def alias(target, source, kind):
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind == "symlink":
        target.symlink_to(source)
    else:
        target.hardlink_to(source)


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_main_input_collision_helper_rejects_lexical_resolved_and_samefile(tmp_path, kind):
    source = tmp_path / "source.json"
    source.write_text('{"synthetic": true}')
    target = tmp_path / "output.json"
    alias(target, source, kind)
    original = source.read_bytes()
    with pytest.raises(renderers.ProjectInputCollision):
        renderers._reject_project_input_collisions(source, [target])
    with pytest.raises(renderers.ProjectInputCollision):
        renderers._reject_project_input_collisions(source, [source])
    assert source.read_bytes() == original


@pytest.mark.corpus
@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
@pytest.mark.parametrize("target_kind", ["hwpx", "manifest", "meaning", "sources", "profile", "companion"])
def test_all_planned_write_aliases_are_rejected_before_input_mutation(tmp_path, monkeypatch, kind, target_kind):
    source = copy_input(tmp_path)
    original = source.read_bytes()
    output = tmp_path / "generated"
    role = "SF-TD5" if target_kind == "companion" else "SF-PM2"
    stem = f"{role}_{renderers.TITLES[role]}_검증용"
    targets = {"hwpx": output / (stem + ".hwpx"), "manifest": output / "manifest.json",
               "meaning": output / (stem + ".meaning.json"), "sources": output / (stem + ".sources.json"),
               "profile": output / "profiles" / (role + ".json"), "companion": output / "synthetic.xlsx"}
    if target_kind == "companion":
        companion = tmp_path / "synthetic.xlsx"
        companion.write_bytes(b"synthetic copy-path control; no actual database")
        monkeypatch.setattr(renderers, "_matching_companion", lambda *args, **kwargs: companion)
    alias(targets[target_kind], source, kind)
    with pytest.raises(renderers.ProjectInputCollision):
        renderers.generate_project(source, output, roles=[role], style_profile="reference-v1")
    assert source.exists() and source.read_bytes() == original
    assert not list(output.glob("*.hwpx")) or target_kind == "hwpx"


@pytest.mark.corpus
@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_owned_stale_companion_cleanup_must_not_delete_main_input_alias(tmp_path, kind):
    source = copy_input(tmp_path)
    original = source.read_bytes()
    output = tmp_path / "generated"
    stale = output / "old-owned.xlsx"
    alias(stale, source, kind)
    (output / "manifest.json").write_text(json.dumps({"companions": [{
        "path": str(stale), "sha256": sha256(original).hexdigest()}]}))
    with pytest.raises(renderers.ProjectInputCollision):
        renderers.generate_project(source, output, roles=["SF-TD5"])
    assert source.read_bytes() == original and stale.exists()


@pytest.mark.corpus
def test_validation_time_input_change_is_not_rehashed_as_the_parsed_dataset(tmp_path, monkeypatch):
    source = copy_input(tmp_path)
    changed = json.loads(source.read_bytes())
    changed["project"]["name"] = "합성 외부 변경 검출용"
    changed_bytes = json.dumps(changed, ensure_ascii=False).encode()
    original_validate = renderers.validate_project
    def validate_then_change(*args, **kwargs):
        result = original_validate(*args, **kwargs)
        source.write_bytes(changed_bytes)
        return result
    monkeypatch.setattr(renderers, "validate_project", validate_then_change)
    output = tmp_path / "must-not-exist"
    with pytest.raises(renderers.ProjectInputChanged, match="changed before commit"):
        renderers.generate_project(source, output, roles=["SF-PM2"])
    assert not output.exists() and source.read_bytes() == changed_bytes


@pytest.mark.corpus
@pytest.mark.parametrize("boundary", ["save", "manifest-before-write", "manifest-after-write"])
def test_commit_boundaries_reject_main_input_drift_without_deleting_changed_input(tmp_path, monkeypatch, boundary):
    source = copy_input(tmp_path)
    changed = json.loads(source.read_bytes())
    changed["project"]["name"] = "합성 저장 경계 외부 변경"
    changed_bytes = json.dumps(changed, ensure_ascii=False).encode()
    output = tmp_path / "generated"
    if boundary == "save":
        save = TemplateDocument.save
        def save_then_change(doc, target):
            result = save(doc, target)
            source.write_bytes(changed_bytes)
            return result
        monkeypatch.setattr(TemplateDocument, "save", save_then_change)
    else:
        write = Path.write_text
        def manifest_change(path, text, *args, **kwargs):
            selected = path == output / "manifest.json"
            if selected and boundary == "manifest-before-write":
                source.write_bytes(changed_bytes)
            result = write(path, text, *args, **kwargs)
            if selected and boundary == "manifest-after-write":
                source.write_bytes(changed_bytes)
            return result
        monkeypatch.setattr(Path, "write_text", manifest_change)
    with pytest.raises(renderers.ProjectInputChanged):
        renderers.generate_project(source, output, roles=["SF-PM2"])
    assert source.exists() and source.read_bytes() == changed_bytes
    assert not (output / "manifest.json").exists() and not list(output.glob("*.hwpx"))


@pytest.mark.corpus
@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
@pytest.mark.parametrize("quoted_input", ["source", "bitmap"])
def test_late_quotation_alias_after_picture_materialization_is_rejected_before_save(quotation, tmp_path, monkeypatch, kind, quoted_input):
    from doc_automation.quotations import QuotationInputCollision
    data, _, _, _ = quotation
    source = tmp_path / "project.json"
    source.write_text(json.dumps(data, ensure_ascii=False))
    watched = Path(data["sources"][-1]["path"] if quoted_input == "source" else data["attachments"][-1]["path"])
    original = watched.read_bytes()
    output = tmp_path / "generated"
    target = output / f"SF-TI1_{renderers.TITLES['SF-TI1']}_검증용.hwpx"
    materialize = renderers._materialize_images
    def materialize_then_alias(doc, ctx):
        materialize(doc, ctx)
        alias(target, watched, kind)
    monkeypatch.setattr(renderers, "_materialize_images", materialize_then_alias)
    with pytest.raises(QuotationInputCollision):
        renderers.generate_project(source, output, roles=["SF-TI1"], style_profile="reference-v1")
    assert watched.exists() and watched.read_bytes() == original
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize("quoted_input", ["source", "bitmap"])
def test_cleanup_never_unlinks_a_late_quotation_input_alias(quotation, tmp_path, quoted_input):
    data, _, _, _ = quotation
    source = tmp_path / "project.json"
    source.write_text(json.dumps(data, ensure_ascii=False))
    watched = Path(data["sources"][-1]["path"] if quoted_input == "source" else data["attachments"][-1]["path"])
    original = watched.read_bytes()
    target = tmp_path / "late-output.hwpx"
    alias(target, watched, "symlink")
    renderers._discard_owned_output(source, data, target, sha256(original).hexdigest())
    assert watched.exists() and watched.read_bytes() == original and target.is_symlink()
