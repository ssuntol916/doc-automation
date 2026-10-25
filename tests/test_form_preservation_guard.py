"""Independent synthetic form behavior; no private corpus or native export."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/hwpx-authoring/scripts/check_form_preservation.py"
SPEC = importlib.util.spec_from_file_location("form_preservation_guard", SCRIPT)
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)
HP = GUARD.HP
NS = {"hp": HP}


def section():
    return ET.fromstring(f'''<sec xmlns="urn:synthetic:section" xmlns:hp="{HP}">
      <hp:p id="1"><hp:run charPrIDRef="0"><hp:secPr><hp:pagePr width="60000" height="85000"><hp:margin left="2000" right="2000"/></hp:pagePr></hp:secPr></hp:run></hp:p>
      <hp:p id="2"><hp:run charPrIDRef="0"><hp:tbl id="5" rowCnt="1" colCnt="2" pageBreak="CELL">
        <hp:sz width="20000" height="2000"/><hp:pos treatAsChar="0" horzOffset="0"/>
        <hp:tr><hp:tc><hp:subList><hp:p><hp:run charPrIDRef="0"><hp:t>합성 입력칸</hp:t></hp:run></hp:p></hp:subList><hp:cellAddr rowAddr="0" colAddr="0"/><hp:cellSpan rowSpan="1" colSpan="1"/><hp:cellSz width="10000" height="2000"/></hp:tc>
        <hp:tc><hp:subList><hp:p><hp:run charPrIDRef="0"><hp:t>합성 고정라벨</hp:t></hp:run></hp:p></hp:subList><hp:cellAddr rowAddr="0" colAddr="1"/><hp:cellSpan rowSpan="1" colSpan="1"/><hp:cellSz width="10000" height="2000"/></hp:tc></hp:tr>
      </hp:tbl></hp:run></hp:p></sec>''')


def write_package(path, roots):
    # Reverse lexical filenames prove reading uses the OPF spine.
    names = [f"section{9-i}.xml" for i in range(len(roots))]
    manifest = "".join(f'<item id="s{i}" href="{name}"/>' for i, name in enumerate(names))
    spine = "".join(f'<itemref idref="s{i}"/>' for i in range(len(roots)))
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/content.hpf", f'<package xmlns="http://www.idpf.org/2007/opf/"><manifest>{manifest}</manifest><spine>{spine}</spine></package>')
        for name, root in zip(names, roots):
            archive.writestr("Contents/" + name, ET.tostring(root))


def test_text_fill_and_local_ids_preserve_geometry(tmp_path):
    left, right = section(), section()
    for node in right.iter():
        if "id" in node.attrib:
            node.set("id", "900")
        if "charPrIDRef" in node.attrib:
            node.set("charPrIDRef", "99")
    right.find(".//hp:t", NS).text = "작성한 합성 내용"
    before, after = tmp_path / "before.hwpx", tmp_path / "after.hwpx"
    write_package(before, [left]); write_package(after, [right])
    assert GUARD.compare(before, after)["preserved"]


@pytest.mark.parametrize("mutation", ["delete_column", "merge", "add_table", "resize", "placement", "second_section_page"])
def test_form_changes_fail_with_difference_paths(tmp_path, mutation):
    left = [section(), section()]
    right = deepcopy(left)
    table = right[0].find(".//hp:tbl", NS)
    if mutation == "delete_column":
        table.find("hp:tr", NS).remove(table.findall("hp:tr/hp:tc", NS)[1])
        table.set("colCnt", "1")
    elif mutation == "merge":
        table.find(".//hp:cellSpan", NS).set("colSpan", "2")
    elif mutation == "add_table":
        right[0].findall("hp:p", NS)[1].find("hp:run", NS).append(deepcopy(table))
    elif mutation == "resize":
        table.find(".//hp:cellSz", NS).set("width", "9000")
    elif mutation == "placement":
        table.find("hp:pos", NS).set("treatAsChar", "1")
    else:
        right[1].find(".//hp:pagePr", NS).set("width", "70000")
    before, after = tmp_path / "before.hwpx", tmp_path / "after.hwpx"
    write_package(before, left); write_package(after, right)
    result = GUARD.compare(before, after)
    assert not result["preserved"]
    assert result["differences"] and all(d["path"].startswith("/sections/") for d in result["differences"])
    assert result["baseline_spine"] == ["Contents/section9.xml", "Contents/section8.xml"]


def test_cli_failure_exit_two_and_json_report(tmp_path):
    before, after, report = (tmp_path / name for name in ("before.hwpx", "after.hwpx", "report.json"))
    left, right = section(), section()
    right.find(".//hp:cellSpan", NS).set("rowSpan", "2")
    write_package(before, [left]); write_package(after, [right])
    result = subprocess.run([sys.executable, str(SCRIPT), str(before), str(after), "--report", str(report)], capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(report.read_text(encoding="utf-8"))["differences"]


def test_fixed_label_permission_is_explicitly_outside_guard(tmp_path):
    before, after = tmp_path / "before.hwpx", tmp_path / "after.hwpx"
    left, right = section(), section()
    right.findall(".//hp:t", NS)[1].text = "임의 라벨 변경"
    write_package(before, [left]); write_package(after, [right])
    result = GUARD.compare(before, after)
    assert result["preserved"]
    assert any("fixed-label" in limitation for limitation in result["limitations"])


def test_bad_zip_is_a_reported_failure(tmp_path):
    before, after = tmp_path / "before.hwpx", tmp_path / "broken.hwpx"
    write_package(before, [section()])
    after.write_bytes(b"not a package")
    result = GUARD.compare(before, after)
    assert not result["preserved"]
    assert result["errors"][0]["type"] == "BadZipFile"


def test_report_cannot_overwrite_document_through_hardlink(tmp_path):
    before, after, report = (tmp_path / name for name in ("before.hwpx", "after.hwpx", "report.json"))
    write_package(before, [section()]); write_package(after, [section()])
    original = before.read_bytes()
    try:
        os.link(before, report)
    except OSError as error:
        pytest.skip(f"Hard links unavailable: {error}")
    result = subprocess.run([sys.executable, str(SCRIPT), str(before), str(after), "--report", str(report)], capture_output=True, text=True)
    assert result.returncode == 2
    assert before.read_bytes() == original
