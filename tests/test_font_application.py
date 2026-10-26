"""Synthetic controls for actual font application, not native font rendering."""
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

from lxml import etree as E
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_font_application.py"
SPEC = importlib.util.spec_from_file_location("font_application", SCRIPT)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def fixture(path, *, faces=None, missing_ref=None, font_id="3", char_id="7", rich=False):
    """Independently authored package; no source business/template content."""
    faces = {script: "Fixture Sans" for script in gate.SCRIPTS} | (faces or {})
    header = E.Element(f"{{{gate.HH}}}head", nsmap={"hh": gate.HH})
    for script, face in faces.items():
        family = E.SubElement(header, f"{{{gate.HH}}}fontface", lang=script.upper())
        E.SubElement(family, f"{{{gate.HH}}}font", id=font_id, face=face, isEmbedded="0")
    char = E.SubElement(header, f"{{{gate.HH}}}charPr", id=char_id)
    E.SubElement(char, f"{{{gate.HH}}}fontRef", **{s: font_id for s in gate.SCRIPTS if s != missing_ref})
    section = E.Element(f"{{{gate.HS}}}sec", nsmap={"hs": gate.HS, "hp": gate.HP})
    p = E.SubElement(section, gate.P, id="parent")
    run = E.SubElement(p, gate.RUN, charPrIDRef=char_id)
    text = E.SubElement(run, gate.TEXT); text.text = "Synthetic"
    E.SubElement(text, f"{{{gate.HP}}}lineBreak").tail = " inline tail"
    if rich:
        # These invalid charPr refs are not used by text. They must not turn a
        # valid font declaration check into a general control/package audit.
        E.SubElement(p, gate.RUN, charPrIDRef="unresolved-empty")
        picture = E.SubElement(p, gate.RUN, charPrIDRef="unresolved-picture")
        E.SubElement(picture, f"{{{gate.HP}}}pic")
        marker = E.SubElement(p, gate.RUN, charPrIDRef="unresolved-marker")
        E.SubElement(marker, f"{{{gate.HP}}}fieldBegin", id="synthetic-field")
        result = E.SubElement(p, gate.RUN, charPrIDRef=char_id)
        E.SubElement(result, gate.TEXT).text = "Stored field result"
        E.SubElement(result, f"{{{gate.HP}}}fieldEnd", beginIDRef="synthetic-field")
        table_run = E.SubElement(p, gate.RUN, charPrIDRef="unresolved-table-parent")
        table = E.SubElement(table_run, f"{{{gate.HP}}}tbl")
        row = E.SubElement(table, f"{{{gate.HP}}}tr")
        cell = E.SubElement(row, f"{{{gate.HP}}}tc")
        sub = E.SubElement(cell, f"{{{gate.HP}}}subList")
        nested = E.SubElement(sub, gate.P, id="nested")
        nested_run = E.SubElement(nested, gate.RUN, charPrIDRef=char_id)
        E.SubElement(nested_run, gate.TEXT).text = "Cell-owned text"
    # Reverse lexical section filenames to exercise the OPF spine boundary.
    second = E.Element(f"{{{gate.HS}}}sec", nsmap={"hs": gate.HS, "hp": gate.HP})
    p2 = E.SubElement(second, gate.P, id="second")
    E.SubElement(E.SubElement(p2, gate.RUN, charPrIDRef=char_id), gate.TEXT).text = "Second section"
    opf = b'<package><manifest><item id="h" href="Contents/header.xml"/><item id="first" href="Contents/section2.xml"/><item id="second" href="Contents/section1.xml"/></manifest><spine><itemref idref="h"/><itemref idref="first"/><itemref idref="second"/></spine></package>'
    with ZipFile(path, "w") as z:
        for name, data in [("mimetype", b"application/hwp+zip"), ("Contents/header.xml", E.tostring(header)),
                           ("Contents/content.hpf", opf), ("Contents/section2.xml", E.tostring(section)),
                           ("Contents/section1.xml", E.tostring(second)),
                           ("settings.xml", b'<settings><profile-target face="Fixture Sans"/></settings>')]:
            z.writestr(name, data)
    return path


def expectations(**scope_changes):
    return {"schema_version": 1, "require_all_text_runs": True, "scopes": [
        {"id": "explicit-body", "section": "*", "xpath": "//hp:p", "expected_face": "Fixture Sans", **scope_changes}]}


def test_explicit_fonts_resolve_all_languages_and_owned_text_without_using_numeric_id_equality(tmp_path):
    path = fixture(tmp_path / "normal.hwpx", font_id="41", char_id="82", rich=True)
    before = path.read_bytes()
    report = gate.check_font_application(path, expectations())
    assert report["passed"] and path.read_bytes() == before
    assert report["opf_section_order"] == ["Contents/section2.xml", "Contents/section1.xml"]
    assert report["coverage"]["checked_unique_text_runs"] == report["coverage"]["total_text_runs"] == 4
    assert len(report["coverage"]["excluded_empty_or_control_only_runs"]) == 4
    first = report["scopes"][0]["runs"][0]
    assert first["text_characters"] == len("Synthetic\n inline tail")
    assert first["local_charPr_id"] == "82"
    assert all(x["face"] == "Fixture Sans" and x["local_font_id"] == "41" for x in first["font_faces"].values())
    assert report["scopes"][0]["matched_owners"] == 3
    # A paragraph selects its own stored field text, never the nested cell's
    # run. The latter remains a separately selectable, uncovered owner.
    own_only = expectations(xpath="/hs:sec/hp:p[@id='parent']")
    own_only["require_all_text_runs"] = False
    own = gate.check_font_application(path, own_only)
    assert own["passed"] and own["coverage"]["checked_unique_text_runs"] == 2
    assert len(own["coverage"]["uncovered_text_runs"]) == 2


def test_forced_batang_override_fails_even_with_unchanged_ids_and_declared_profile_targets(tmp_path):
    good = fixture(tmp_path / "intended.hwpx")
    bad = fixture(tmp_path / "overridden.hwpx", faces=dict.fromkeys(gate.SCRIPTS, "바탕"))
    assert gate.check_font_application(good, expectations())["passed"]
    report = gate.check_font_application(bad, expectations())
    assert not report["passed"]
    assert {x["script"] for x in report["failures"]} == set(gate.SCRIPTS)
    assert {x["actual"]["face"] for x in report["failures"]} == {"바탕"}
    assert {x["expected_face"] for x in report["failures"]} == {"Fixture Sans"}
    assert {x["local_charPr_id"] for x in report["scopes"][0]["runs"]} == {"7"}
    # The public CLI must return failure too, not just emit a diagnostic.
    spec, output = tmp_path / "expected.json", tmp_path / "report.json"
    spec.write_text(json.dumps(expectations()), encoding="utf-8")
    assert gate.main([str(bad), "--expect", str(spec), "--report", str(output)]) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is False


@pytest.mark.parametrize("options,script,code", [
    ({"missing_ref": "symbol"}, "symbol", "unresolved_font"),
    ({"faces": {"latin": "Fixture Different Face"}}, "latin", "font_face_mismatch"),
])
def test_missing_language_or_different_face_under_the_same_local_id_cannot_pass(tmp_path, options, script, code):
    path = fixture(tmp_path / "wrong-language.hwpx", **options)
    report = gate.check_font_application(path, expectations())
    assert not report["passed"]
    assert {(x["script"], x["code"]) for x in report["failures"]} == {(script, code)}
    # Same ID 3 in HANGUL and LATIN does not identify the same font family.
    actual = report["scopes"][0]["runs"][0]["font_faces"]
    assert actual["hangul"]["face"] == "Fixture Sans"
    if script == "latin":
        assert actual["hangul"]["local_font_id"] == actual["latin"]["local_font_id"] == "3"
        per_script = expectations(expected_face={s: ("Fixture Different Face" if s == "latin" else "Fixture Sans") for s in gate.SCRIPTS})
        assert gate.check_font_application(path, per_script)["passed"]


def test_empty_or_partial_scopes_fail_instead_of_vacuously_certifying_the_output(tmp_path):
    path = fixture(tmp_path / "scope.hwpx")
    empty = gate.check_font_application(path, expectations(xpath="//hp:p[@id='absent']"))
    assert not empty["passed"]
    assert {x["code"] for x in empty["failures"]} == {"insufficient_text_runs", "uncovered_text_runs"}
    partial = gate.check_font_application(path, expectations(section="Contents/section2.xml"))
    assert not partial["passed"] and partial["coverage"]["checked_unique_text_runs"] == 1
    assert partial["failures"] == [{"code": "uncovered_text_runs", "count": 1}]
    with pytest.raises(ValueError, match="complete seven-language"):
        gate.check_font_application(path, expectations(expected_face={"hangul": "Fixture Sans"}))


@pytest.mark.parametrize("destination", ["input", "expectations"])
def test_read_only_cli_cannot_overwrite_either_input_with_its_report(tmp_path, destination):
    path = fixture(tmp_path / "current.hwpx")
    spec = tmp_path / "expected.json"
    spec.write_text(json.dumps(expectations()), encoding="utf-8")
    before = path.read_bytes(), spec.read_bytes()
    output = path if destination == "input" else spec
    assert gate.main([str(path), "--expect", str(spec), "--report", str(output)]) == 2
    assert (path.read_bytes(), spec.read_bytes()) == before


@pytest.mark.parametrize("control", ["pageNum", "autoNum"])
def test_automatic_display_control_without_text_checks_actual_font_and_full_coverage(tmp_path, control):
    path = fixture(tmp_path / "automatic-number.hwpx")
    with ZipFile(path) as z:
        entries = {n:z.read(n) for n in z.namelist()}
    header = E.fromstring(entries["Contents/header.xml"])
    for family in header.findall(f"{{{gate.HH}}}fontface"):
        E.SubElement(family, f"{{{gate.HH}}}font", id="99", face="Fixture Wrong Number Face")
    wrong = deepcopy(header.find(f"{{{gate.HH}}}charPr")); wrong.set("id", "99")
    wrong.find(f"{{{gate.HH}}}fontRef").attrib.update(dict.fromkeys(gate.SCRIPTS, "99")); header.append(wrong)
    section = E.fromstring(entries["Contents/section2.xml"])
    p = E.SubElement(section, gate.P, id="automatic-number")
    run = E.SubElement(p, gate.RUN, charPrIDRef="99")
    if control == "autoNum":
        E.SubElement(run, gate.TEXT).text = " \n\t"
    ctrl = E.SubElement(run, f"{{{gate.HP}}}ctrl")
    E.SubElement(ctrl, f"{{{gate.HP}}}{control}", formatType="DIGIT")
    entries["Contents/header.xml"], entries["Contents/section2.xml"] = E.tostring(header), E.tostring(section)
    with ZipFile(path, "w") as z:
        for name, data in entries.items(): z.writestr(name, data)
    report = gate.check_font_application(path, expectations())
    assert not report["passed"]
    assert len(report["failures"]) == 7 and {x["code"] for x in report["failures"]} == {"font_face_mismatch"}
    control_run = report["scopes"][0]["runs"][1]
    assert control_run["usage_kind"] == "display_control"
    assert control_run["text_characters"] == (0 if control == "pageNum" else 3)
    assert control_run["display_controls"][0]["type"] == control
    assert report["coverage"]["total_display_runs"] == report["coverage"]["checked_unique_display_runs"] == 3
    # The control-only owner is a valid nonempty font-check scope, but selecting
    # only hp:t-bearing runs cannot satisfy global display-run coverage.
    only_number = expectations(xpath="//hp:p[@id='automatic-number']", expected_face="Fixture Wrong Number Face")
    only_number["require_all_text_runs"] = False
    assert gate.check_font_application(path, only_number)["passed"]
    only_stored = gate.check_font_application(path, expectations(xpath="//hp:run[hp:t[normalize-space(.)!='']]"))
    assert not only_stored["passed"]
    assert only_stored["failures"] == [{"code": "uncovered_text_runs", "count": 1}]


def test_nonprinting_field_number_settings_empty_and_object_runs_remain_distinct_from_display_controls(tmp_path):
    path = fixture(tmp_path / "nonprinting-controls.hwpx", rich=True)
    with ZipFile(path) as z:
        entries = {n:z.read(n) for n in z.namelist()}
    section = E.fromstring(entries["Contents/section2.xml"])
    nested = section.xpath("//hp:p[@id='nested']", namespaces=gate.NS)[0]
    nested_run = E.SubElement(nested, gate.RUN, charPrIDRef="7")
    E.SubElement(E.SubElement(nested_run, f"{{{gate.HP}}}ctrl"), f"{{{gate.HP}}}autoNum", numType="FIGURE", num="1")
    p = E.SubElement(section, gate.P, id="nonprinting")
    run = E.SubElement(p, gate.RUN, charPrIDRef="unresolved-nonprinting")
    E.SubElement(run, gate.TEXT).text = " \n\t"
    ctrl = E.SubElement(run, f"{{{gate.HP}}}ctrl")
    E.SubElement(ctrl, f"{{{gate.HP}}}newNum", num="1")
    E.SubElement(ctrl, f"{{{gate.HP}}}pageNumCtrl", pageStartsOn="BOTH")
    E.SubElement(ctrl, f"{{{gate.HP}}}fieldBegin", id="nonprinting-field")
    E.SubElement(ctrl, f"{{{gate.HP}}}fieldEnd", beginIDRef="nonprinting-field")
    # A control inside an opaque image/formula object is not directly owned
    # by its outer run. Do not infer picture/formula lettering from its tag.
    image = E.SubElement(run, f"{{{gate.HP}}}pic")
    E.SubElement(image, f"{{{gate.HP}}}autoNum")
    formula = E.SubElement(run, f"{{{gate.HP}}}equation")
    E.SubElement(formula, f"{{{gate.HP}}}pageNum")
    entries["Contents/section2.xml"] = E.tostring(section)
    with ZipFile(path, "w") as z:
        for name, data in entries.items(): z.writestr(name, data)
    report = gate.check_font_application(path, expectations())
    assert report["passed"] and report["coverage"]["checked_unique_display_runs"] == 5
    assert len(report["coverage"]["excluded_empty_or_control_only_runs"]) == 5
    numbers = [r for r in report["scopes"][0]["runs"] if r["display_controls"]]
    assert len(numbers) == 1 and "/hp:tbl/" in numbers[0]["xpath"]
    own_only = expectations(xpath="//hp:p[@id='parent']"); own_only["require_all_text_runs"] = False
    assert gate.check_font_application(path, own_only)["coverage"]["checked_unique_display_runs"] == 2
    empty = expectations(xpath="//hp:p[@id='nonprinting']"); empty["require_all_text_runs"] = False
    assert gate.check_font_application(path, empty)["failures"] == [
        {"scope":"explicit-body", "code":"insufficient_text_runs", "expected_minimum":1, "actual":0}]
