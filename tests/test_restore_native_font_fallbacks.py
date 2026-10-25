"""Conservative font repair controls; these do not claim native UI execution."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree as E
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/restore_native_font_fallbacks.py"
SPEC = importlib.util.spec_from_file_location("font_repair", SCRIPT)
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


def package(path, *, fallback=True, font_id="3", duplicate=False, primary=None, sub=None, type_info="1", opf_root_relative=False):
    attrs = {"id": font_id, "face": "Fixture primary", "type": "HFT", "isEmbedded": "0", **(primary or {})}
    header = E.Element(f"{{{repair.HH}}}head", nsmap={"hh": repair.HH})
    face = E.SubElement(header, f"{{{repair.HH}}}fontface", lang="LATIN")
    font = E.SubElement(face, f"{{{repair.HH}}}font", **attrs)
    if fallback:
        E.SubElement(font, repair.SUBST, **{"face": "Fixture fallback", "type": "TTF", "isEmbedded": "0",
                                           "binaryItemIDRef": "", **(sub or {})})
    E.SubElement(font, f"{{{repair.HH}}}typeInfo", familyType=type_info)
    if duplicate:
        other = deepcopy(font)
        other.set("id", "99")
        face.append(other)
    char = E.SubElement(header, f"{{{repair.HH}}}charPr", id="0")
    E.SubElement(char, f"{{{repair.HH}}}fontRef", latin=font_id)
    section = f'<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="{repair.HP}"><hp:p><hp:run charPrIDRef="0"><hp:t>Fixture text</hp:t></hp:run></hp:p></hs:sec>'.encode()
    opf = b'<package><manifest><item id="h" href="header.xml"/><item id="s" href="section1.xml"/></manifest><spine><itemref idref="h"/><itemref idref="s"/></spine></package>'
    if opf_root_relative:
        opf = opf.replace(b'href="', b'href="Contents/')
    with ZipFile(path, "w") as z:
        z.comment = b"fixture archive comment"
        for name, data in (("mimetype", b"application/hwp+zip"), (repair.HEADER, E.tostring(header)),
                           ("Contents/content.hpf", opf), ("Contents/section1.xml", section), ("BinData/unchanged.bin", b"\x00\xffraw fixture")):
            z.writestr(name, data)
    return path


def run_repair(tmp_path, **native_options):
    source = package(tmp_path / "reference.hwpx")
    native = package(tmp_path / "native.hwpx", fallback=False, **native_options)
    output, report = tmp_path / "output.hwpx", tmp_path / "report.json"
    result = repair.restore(source, native, output, report)
    return source, native, output, report, result


def test_exact_repair_matches_meaning_not_local_id_and_preserves_every_other_entry(tmp_path):
    source, native, output, report, result = run_repair(tmp_path, font_id="7")
    assert repair.verify_report(report) == result
    assert result["restored_fallback_declarations"] == result["source_fallback_declarations"] == 1
    assert result["source_usage"]["used_restored_font_declarations"] == 1
    assert result["source_usage"]["affected_nonempty_owned_paragraphs"] == [
        {"spine_entry": "Contents/section1.xml", "nonempty_owned_paragraph_index": 0}]
    assert result["restorations"][0]["source_local_font_id"] == "3"
    assert result["restorations"][0]["native_local_font_id"] == "7"
    with ZipFile(native) as a, ZipFile(output) as b:
        assert a.namelist() == b.namelist() and a.comment == b.comment
        assert [n for n in a.namelist() if a.read(n) != b.read(n)] == [repair.HEADER]


def test_package_root_relative_opf_paths_are_resolved_in_spine_order(tmp_path):
    a = package(tmp_path / "a.hwpx", opf_root_relative=True)
    b = package(tmp_path / "b.hwpx", fallback=False, opf_root_relative=True)
    result = repair.restore(a, b, tmp_path / "o.hwpx", tmp_path / "r.json")
    assert result["source_usage"]["affected_nonempty_owned_paragraphs"] == [
        {"spine_entry": "Contents/section1.xml", "nonempty_owned_paragraph_index": 0}]


@pytest.mark.parametrize("side", ["source", "native"])
def test_ambiguous_definition_is_rejected_even_when_one_local_id_matches(tmp_path, side):
    a = package(tmp_path / "a.hwpx", duplicate=side == "source")
    b = package(tmp_path / "b.hwpx", fallback=False, duplicate=side == "native")
    with pytest.raises(ValueError, match="unique"):
        repair.restore(a, b, tmp_path / "o.hwpx", tmp_path / "r.json")
    assert not (tmp_path / "o.hwpx").exists()


@pytest.mark.parametrize("options", [
    {"primary": {"face": "Different primary"}},
    {"type_info": "9"},
    {"primary": {"isEmbedded": "1"}},
])
def test_other_primary_definition_changes_cannot_be_overwritten(tmp_path, options):
    with pytest.raises(ValueError):
        run_repair(tmp_path, **options)


@pytest.mark.parametrize("source_options", [
    {"primary": {"isEmbedded": "1"}},
    {"sub": {"isEmbedded": "1"}},
    {"sub": {"binaryItemIDRef": "embedded-font"}},
])
def test_embedded_or_resource_backed_fallback_is_rejected(tmp_path, source_options):
    a = package(tmp_path / "a.hwpx", **source_options)
    b = package(tmp_path / "b.hwpx", fallback=False)
    with pytest.raises(ValueError, match="Embedded/resource"):
        repair.restore(a, b, tmp_path / "o.hwpx", tmp_path / "r.json")


def test_conflicting_existing_fallback_is_not_replaced(tmp_path):
    a = package(tmp_path / "a.hwpx")
    b = package(tmp_path / "b.hwpx", sub={"face": "Different fallback"})
    with pytest.raises(ValueError, match="Conflicting"):
        repair.restore(a, b, tmp_path / "o.hwpx", tmp_path / "r.json")


def test_nothing_missing_is_not_reported_as_a_repair(tmp_path):
    a, b = package(tmp_path / "a.hwpx"), package(tmp_path / "b.hwpx")
    with pytest.raises(ValueError, match="No missing"):
        repair.restore(a, b, tmp_path / "o.hwpx", tmp_path / "r.json")


@pytest.mark.parametrize("mutation", ["tool_hash", "source_hash", "omitted_entry", "fabricated_count"])
def test_fabricated_or_stale_report_is_rejected(tmp_path, mutation):
    _, _, _, report, result = run_repair(tmp_path)
    if mutation == "tool_hash":
        result["tool"]["sha256"] = "0" * 64
    elif mutation == "source_hash":
        result["reference_source"]["sha256"] = "0" * 64
    elif mutation == "omitted_entry":
        result["entry_preservation"].pop()
    else:
        result["restored_fallback_declarations"] = 999
    report.write_text(json.dumps(result))
    with pytest.raises(ValueError):
        repair.verify_report(report)


def test_output_hash_and_report_cannot_hide_an_unrelated_entry_mutation(tmp_path):
    _, _, output, report, result = run_repair(tmp_path)
    with ZipFile(output) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    entries["BinData/unchanged.bin"] = b"changed"
    with ZipFile(output, "w") as z:
        for n, data in entries.items():
            z.writestr(n, data)
    result["output"] = repair.file_ref(output)
    # Even plausible forged per-entry hashes cannot change the allowed diff.
    result["entry_preservation"][-1].update(output_sha256=repair.digest(b"changed"), unchanged=False)
    report.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="Only Contents/header.xml"):
        repair.verify_report(report)


def test_alias_and_overwrite_are_rejected(tmp_path):
    a, b = package(tmp_path / "a.hwpx"), package(tmp_path / "b.hwpx", fallback=False)
    with pytest.raises(ValueError, match="alias"):
        repair.restore(a, b, b, tmp_path / "r.json")
    r = tmp_path / "r.json"
    r.write_text("preserve me")
    with pytest.raises(ValueError, match="overwrite"):
        repair.restore(a, b, tmp_path / "o.hwpx", r)
    assert r.read_text() == "preserve me"


def test_concurrent_output_creation_is_never_removed(tmp_path, monkeypatch):
    a, b = package(tmp_path / "a.hwpx"), package(tmp_path / "b.hwpx", fallback=False)
    out = tmp_path / "o.hwpx"
    original_open = Path.open
    def racing_open(path, *args, **kwargs):
        if path == out and args == ("xb",):
            with original_open(path, "wb") as handle:
                handle.write(b"concurrent file must survive")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", racing_open)
    with pytest.raises(FileExistsError):
        repair.restore(a, b, out, tmp_path / "r.json")
    assert out.read_bytes() == b"concurrent file must survive"
