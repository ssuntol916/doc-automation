from pathlib import Path
from zipfile import ZipFile

import pytest

from doc_automation.hwpx import NS, inline_text, own_text, parse_xml, section_order


def test_inline_control_tail_survives():
    t = parse_xml(f'<hp:t xmlns:hp="{NS["hp"]}">첫째<hp:lineBreak/>둘째<hp:tab/>셋째<hp:fwSpace/>넷째</hp:t>'.encode())
    assert inline_text(t) == "첫째\n둘째\t셋째\u3000넷째"


def test_nested_table_text_has_single_owner():
    p = parse_xml(f'<hp:p xmlns:hp="{NS["hp"]}"><hp:run><hp:t>본문</hp:t><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>셀</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'.encode())
    paragraphs = list(p.iter(f'{{{NS["hp"]}}}p'))
    assert [own_text(node) for node in paragraphs] == ["본문", "셀"]


def test_section_spine_controls_order_and_checks_missing(tmp_path: Path):
    path = tmp_path / "order.hwpx"
    content = '<package><manifest><item id="s0" href="section0.xml"/><item id="s1" href="section1.xml"/></manifest><spine><itemref idref="s1"/><itemref idref="s0"/></spine></package>'
    with ZipFile(path, "w") as z:
        z.writestr("Contents/content.hpf", content)
        z.writestr("Contents/section0.xml", "<sec/>")
        z.writestr("Contents/section1.xml", "<sec/>")
    with ZipFile(path) as z:
        assert section_order(z) == ["Contents/section1.xml", "Contents/section0.xml"]
    with ZipFile(path, "a") as z:
        z.writestr("Contents/section2.xml", "<sec/>")
    with ZipFile(path) as z:
        with pytest.raises(ValueError, match="Spine/section mismatch"):
            section_order(z)
