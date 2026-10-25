"""Private rule values stay external while file and history scans remain testable."""
import importlib.util
from pathlib import Path
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit_public_repository.py"
spec = importlib.util.spec_from_file_location("publication_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_normalized_private_values_are_reported_without_echoing_them():
    secret = "PRIVATE" + "-CORPUS-VALUE"
    found = audit.inspect_text("prefix " + secret.lower(), "file", [secret])
    assert found == [{"location": "file", "line": 1, "kind": "private_value", "private_rule": 0}]
    assert secret.casefold() not in str(found).casefold()


def test_home_and_contact_patterns_detect_actual_values():
    home = "/Users/" + "fixture-owner/file"
    phone = "010" + "-" + "1111" + "-" + "2222"
    assert {f["kind"] for f in audit.inspect_text(home + "\n" + phone, "file")} == {"personal_home_path", "unmasked_phone"}


def test_history_finds_removed_private_data(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init", "--quiet")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.com")
    secret = "PRIVATE" + "-CORPUS-VALUE"
    path = tmp_path / "fixture.txt"
    path.write_text(secret)
    git("add", ".")
    git("commit", "--quiet", "-m", "fixture")
    path.write_text("independent synthetic content")
    git("add", ".")
    git("commit", "--quiet", "-m", "replacement")
    assert audit.audit(tmp_path, forbidden=[secret])["passed"]
    result = audit.audit(tmp_path, forbidden=[secret], history=True)
    assert not result["passed"] and any(f["location"].startswith("git:") for f in result["findings"])


def test_staged_private_bytes_cannot_hide_behind_clean_worktree(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    value = "PRIVATE" + "-CORPUS-VALUE"
    path = tmp_path / "fixture.txt"
    path.write_text(value)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    path.write_text("independent synthetic replacement")
    assert audit.audit(tmp_path, forbidden=[value])["passed"]
    result = audit.audit(tmp_path, forbidden=[value], staged=True)
    assert not result["passed"] and result["staged_objects_scanned"] == 1
    assert any(f["location"] == "index:fixture.txt" for f in result["findings"])
