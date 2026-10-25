"""Observable intake boundaries using independently constructed synthetic files."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest


HELPER = (Path(__file__).resolve().parents[1] / ".agents/skills/"
          "grant-project-analysis/scripts/inventory_sources.py")


@pytest.fixture(scope="module")
def intake():
    spec = importlib.util.spec_from_file_location("grant_project_intake", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def trees(tmp_path):
    source = tmp_path / "supplied-synthetic-input"
    workspace = tmp_path / "workspace"
    source.mkdir()
    workspace.mkdir()
    return source, workspace, workspace / "outputs" / "new-run"


def put(root, relative, content=b"independent synthetic input\n"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def bytes_in(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def link_or_skip(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"This environment does not permit synthetic symlinks: {error}")


def test_snapshot_matches_hashes_and_preserves_all_input_bytes(intake, trees):
    source, workspace, output = trees
    put(source, "01_plan/plan.hwpx", b"synthetic document bytes\x00\xff")
    put(source, "02_slides/slides.pptx", b"synthetic presentation bytes")
    put(source, "03_code/app.py", b'raise RuntimeError("input must never execute")\n')
    put(source, "03_code/opaque.bin", bytes(range(256)))
    put(source, "04_cost/cost.pdf", b"synthetic cost-document bytes")
    before = bytes_in(source)

    result = intake.run(source, output, workspace)

    assert bytes_in(source) == before
    assert result["source_bytes_unchanged_at_end"] is True
    assert result["submission_ready"] is False
    assert result["summary"]["files"] == result["summary"]["snapshots"] == 5
    assert result["summary"]["bytes"] == sum(map(len, before.values()))
    assert result["summary"]["categories"] == {
        "document": 3, "source_or_notebook": 1, "other": 1}
    assert len({row["source_id"] for row in result["sources"]}) == 5
    for row in result["sources"]:
        content = before[row["relative_path"]]
        snapshot = Path(row["snapshot_path"])
        assert snapshot.is_relative_to(output / "sources")
        assert snapshot.read_bytes() == content
        assert row["source_sha256"] == row["snapshot_sha256"] == sha256(content).hexdigest()
        assert row["file_hash_verified"] is True
        assert row["handling"] == "copied_without_execution"
        assert row["content_review"] == "not_reviewed"
        assert row["business_attribution"] == "unverified"
    assert json.loads((output / "source-inventory.json").read_text(encoding="utf-8")) == result


def test_selected_groups_exclude_other_groups_and_keep_empty_group(intake, trees):
    source, workspace, output = trees
    put(source, "01_plan/a.hwpx")
    (source / "02_empty").mkdir()
    put(source, "03_code/app.py")
    put(source, "99_unselected/do-not-copy.txt")
    put(source, "unselected-root.txt")

    result = intake.run(source, output, workspace, ("01_", "02_", "03_"))

    assert {row["relative_path"] for row in result["sources"]} == {
        "01_plan/a.hwpx", "03_code/app.py"}
    assert result["groups"] == [
        {"relative_path": "01_plan", "file_count": 1},
        {"relative_path": "02_empty", "file_count": 0},
        {"relative_path": "03_code", "file_count": 1},
    ]
    assert not (output / "sources/99_unselected").exists()
    assert not (output / "sources/unselected-root.txt").exists()


def test_repeated_and_overlapping_group_prefixes_do_not_duplicate_files(intake, trees):
    source, workspace, output = trees
    put(source, "01_plan/item.txt")
    put(source, "02_slides/item.txt")

    result = intake.run(source, output, workspace, ("0", "01_", "01_"))

    assert result["summary"]["files"] == result["summary"]["snapshots"] == 2
    assert len(result["sources"]) == len({r["source_id"] for r in result["sources"]}) == 2
    assert result["groups"] == [
        {"relative_path": "01_plan", "file_count": 1},
        {"relative_path": "02_slides", "file_count": 1},
    ]


@pytest.mark.parametrize("name", [".env", ".env.local", "test.key", "id_rsa", ".npmrc"])
def test_sensitive_settings_are_hashed_but_not_copied_or_extracted(intake, trees, name):
    source, workspace, output = trees
    content = b"INDEPENDENT_SYNTHETIC_TOKEN_DO_NOT_COPY=synthetic-only\n"
    put(source, "03_code/" + name, content)

    result = intake.run(source, output, workspace, ("03_",))

    row, = result["sources"]
    assert row["source_sha256"] == sha256(content).hexdigest()
    assert row["size_bytes"] == len(content)
    assert row["snapshot_path"] is None
    assert row["file_hash_verified"] is False
    assert row["handling"] == "sensitive_configuration_deferred_no_copy_or_text_extraction"
    assert result["summary"]["deferred_sensitive_files"] == 1
    assert result["summary"]["snapshots"] == 0
    assert not (output / "sources").exists()
    manifest_text = (output / "source-inventory.json").read_text(encoding="utf-8")
    assert content.decode().strip() not in manifest_text
    assert bytes_in(source) == {"03_code/" + name: content}


def test_dependency_cache_and_vcs_subtrees_are_recorded_without_copying(intake, trees):
    source, workspace, output = trees
    put(source, "03_code/src/main.py")
    excluded = {"03_code/node_modules", "03_code/.git", "03_code/.venv",
                "03_code/src/__pycache__"}
    for directory in excluded:
        put(source, directory + "/ignored.txt", b"independent excluded bytes")

    result = intake.run(source, output, workspace, ("03_",))

    assert [r["relative_path"] for r in result["sources"]] == ["03_code/src/main.py"]
    assert {r["relative_path"] for r in result["excluded_subtrees_or_files"]} == excluded
    assert {r["reason"] for r in result["excluded_subtrees_or_files"]} == {
        "dependency_cache_or_vcs_directory"}
    assert bytes_in(output / "sources") == {"03_code/src/main.py": b"independent synthetic input\n"}


def test_group_selection_does_not_bypass_dependency_exclusion(intake, trees):
    source, workspace, output = trees
    put(source, "node_modules/dependency.py", b"independent dependency fixture\n")

    result = intake.run(source, output, workspace, ("node_",))

    assert result["sources"] == []
    assert result["groups"] == [{"relative_path": "node_modules", "file_count": 0}]
    assert result["excluded_subtrees_or_files"] == [
        {"relative_path": "node_modules", "reason": "dependency_cache_or_vcs_directory"}]
    assert not (output / "sources").exists()


def test_missing_requested_group_rejects_before_creating_output(intake, trees):
    source, workspace, output = trees
    put(source, "01_plan/file.txt")
    before = bytes_in(source)

    with pytest.raises(ValueError, match="group prefix"):
        intake.run(source, output, workspace, ("01_", "02_"))

    assert not output.exists()
    assert bytes_in(source) == before


def test_existing_output_is_refused_without_overwriting_evidence(intake, trees):
    source, workspace, output = trees
    put(source, "input.txt")
    put(output, "source-inventory.json", b"previous independent evidence")
    before = bytes_in(output)

    with pytest.raises(ValueError, match="existing evidence"):
        intake.run(source, output, workspace)

    assert bytes_in(output) == before


@pytest.mark.parametrize("relationship", ["same", "output_inside_input", "input_inside_output"])
def test_overlapping_trees_are_refused_without_input_mutation(intake, tmp_path, relationship):
    workspace = tmp_path / "workspace"
    if relationship == "same":
        source = output = workspace / "outputs/run"
    elif relationship == "output_inside_input":
        source, output = workspace / "outputs/source", workspace / "outputs/source/run"
    else:
        source, output = workspace / "outputs/run/source", workspace / "outputs/run"
    put(source, "synthetic.txt")
    before = bytes_in(workspace)

    with pytest.raises(ValueError, match="disjoint"):
        intake.run(source, output, workspace)

    assert bytes_in(workspace) == before


@pytest.mark.parametrize("area", ["examples", "resources", "outside_workspace"])
def test_public_or_external_output_is_refused_before_writing(intake, trees, tmp_path, area):
    source, workspace, _ = trees
    put(source, "synthetic.txt")
    output = (tmp_path / "external/run" if area == "outside_workspace"
              else workspace / area / "run")

    with pytest.raises(ValueError, match="ignored private area"):
        intake.run(source, output, workspace)

    assert not output.exists()
    assert bytes_in(source) == {"synthetic.txt": b"independent synthetic input\n"}


@pytest.mark.parametrize("target_area", ["public", "external"])
def test_output_private_area_symlink_cannot_redirect_snapshots(intake, trees, tmp_path, target_area):
    source, workspace, _ = trees
    put(source, "synthetic.txt")
    target = workspace / "examples" if target_area == "public" else tmp_path / "external"
    target.mkdir()
    link_or_skip(workspace / "outputs", target, directory=True)

    with pytest.raises(ValueError, match="ignored private area"):
        intake.run(source, workspace / "outputs/new-run", workspace)

    assert bytes_in(target) == {}
    assert not (target / "new-run").exists()


def test_input_file_and_directory_symlinks_are_recorded_but_not_followed(intake, trees, tmp_path):
    source, workspace, output = trees
    put(source, "03_code/regular.txt")
    outside = tmp_path / "independent-link-target"
    target = put(outside, "not-in-input.txt", b"synthetic linked file must not copy")
    link_or_skip(source / "03_code/linked.txt", target)
    link_or_skip(source / "03_code/linked-directory", outside, directory=True)

    result = intake.run(source, output, workspace, ("03_",))

    assert [r["relative_path"] for r in result["sources"]] == ["03_code/regular.txt"]
    assert {r["relative_path"]: r["reason"] for r in result["excluded_subtrees_or_files"]} == {
        "03_code/linked.txt": "symlink_reparse_or_nonregular_file",
        "03_code/linked-directory": "symlink_or_reparse_point",
    }
    assert not (output / "sources/03_code/linked.txt").exists()
    assert not (output / "sources/03_code/linked-directory").exists()
    assert target.read_bytes() == b"synthetic linked file must not copy"


def test_selected_group_symlink_is_excluded_as_a_group(intake, trees, tmp_path):
    source, workspace, output = trees
    outside = tmp_path / "independent-selected-target"
    put(outside, "not-in-input.txt")
    link_or_skip(source / "01_linked", outside, directory=True)

    result = intake.run(source, output, workspace, ("01_",))

    assert result["sources"] == []
    assert result["groups"] == [{"relative_path": "01_linked", "file_count": 0}]
    assert result["excluded_subtrees_or_files"] == [
        {"relative_path": "01_linked", "reason": "symlink_or_reparse_point"}]
    assert not (output / "sources").exists()
