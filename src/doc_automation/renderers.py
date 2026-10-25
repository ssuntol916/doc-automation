"""Render the nineteen v2.0 deliverable roles using their original HWPX forms.

Facts, plans and unknowns stay separate. Generated drafts carry no submission,
test execution, installation, signature or approval assertion.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

from .business import validate_project
from .compose import ComposeError, TemplateDocument, HANCOM_MAC_12_30_PNG_METADATA
from .hwpx import own_text
from .sourcebinding import resolve_templates
from .narrative import DOMAIN_LABELS, SourceNotes, code_label, describe_fields, editorial_context_active, readable_value, source_note_scope, source_reference_text, trace_paragraphs, typed_value


HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS = {"hp": HP}
HH = {"hh": "http://www.hancom.co.kr/hwpml/2011/head"}
NOTICE = "검증용 합성 자료(제출용 아님)"
UNKNOWN = "미확인(자료 미제공)"
ROLES = (
    "SF-AD1", "SF-AD2", "SF-AD3", "SF-TD1", "SF-TD2", "SF-TD3", "SF-TD4", "SF-TD5",
    "SF-CD1", "SF-TI1", "SF-TI2", "SF-TI3", "SF-TI4", "SF-OS1", "SF-OS2",
    "SF-PM1", "SF-PM2", "SF-PM3", "SF-PM4",
)
TITLES = dict(zip(ROLES, (
    "현행업무분석서", "요구사항정의서", "기능대비표", "개선업무설계서", "아키텍처설계서",
    "화면설계서", "프로그램설계서", "데이터베이스설계서", "단위테스트결과서", "통합테스트결과서",
    "시스템전환결과서", "매뉴얼", "사용자테스트결과서", "운영지원계획서", "운영현황보고서",
    "월간보고서", "회의록", "변경관리내역서", "요구사항추적표",
)))
CHANGE = {"existing": "기존(재사용 가정)", "new": "추가(설계 계획)", "modified": "변경(검토안)", "deleted": "삭제(검토안)"}
NARRATIVE_KEEP_MAX_CHARS = 240
# Bounded source-reference groups stay together with their owner key. A single
# locator exceeding this bound can still flow rather than forming a huge keep.
SOURCE_REF_GROUP_MAX_CHARS = 480
APPENDIX_SCALAR_GROUP_MAX_FIELDS = 4
APPENDIX_SCALAR_GROUP_MAX_CHARS = 160
PM4_RAW_TRACE_KEEP_MAX_CHARS = 720
# These exact trailing guide paragraphs carry unintended PAGE=1 restarts in
# the fingerprinted v2 source forms. The real body-start controls are separate.
STALE_GUIDE_PAGE_RESTARTS = {
    "SF-TD4": "- 관련 테이블 항목은 프로그램에서 사용되는 테이블명을 기술함",
    "SF-CD1": "- 결함관리 내역은 결함번호, 단위테스트 ID, 결함 내역, 발생일자, 조치 내역, 완료일자를 기술함",
    "SF-TI4": "- 결함관리 내역은 결함번호, 사용자테스트 ID, 결함 내역, 발생일자, 조치 내역, 확인자를 기술함",
}


def _notice(data):
    return NOTICE if data["dataset_kind"] == "synthetic" else "검토용 초안(제출 전 사실·증거 확인 필요)"


def _execution_missing(data):
    # Synthetic is a provenance label, never an execution/approval status.
    return "실제 수행 자료 미제공·미확인"


def _cover_program_identity(project):
    """Compose provided identity, never a document/execution date or new fact."""
    name, year = project.get("program_name"), project.get("program_year")
    if year is not None and type(year) is not int:
        raise ValueError("Cover identity requires a provided integer program_year or null")
    shown_name = _text(name)
    prefix = re.match(r"^\s*([0-9]{4})\s*년(?:도)?", shown_name)
    if prefix:
        text, strategy = shown_name, "provided_name_already_begins_with_year"
        expressed = ["/project/program_name"]
    elif year is not None:
        text, strategy = f"{year}년도 {shown_name}", "provided_program_year_plus_name"
        expressed = ["/project/program_year", "/project/program_name"]
    else:
        text, strategy = shown_name, "program_year_unprovided_preserve_name"
        expressed = ["/project/program_name"]
    return {"text": text, "strategy": strategy, "program_name_input": name,
            "program_year_input": year, "name_prefix_year_literal": prefix.group(1) if prefix else None,
            "expressed_input_pointers": expressed,
            "program_year_field_expressed_by_composition": "/project/program_year" in expressed,
            "limitation": "An existing name-year prefix is preserved verbatim; any difference from the structural year is not resolved or reclassified as a new cover assertion. Body/header source owners remain separate."}


def _deployment_actual_text(data, item):
    text = f"실제 설치 입력 상태: {_text(item.get('installation_status'))}\n실제 사양 입력: {_text(item.get('actual_specification'))}\n실제 설치 수량: {_text(item.get('installed_quantity'))}{_text(item.get('unit'), '')}; 설치일: {_text(item.get('installation_date'))}\n검증 결과 입력: {_text(item.get('verification_result'), _execution_missing(data))}\n증거 연결: {_join(item.get('evidence_ids', []), '미제공')}; 근거: {_refs(item)}"
    for row in item.get("migration_counts", []):
        text += f"\n초기데이터 입력: {_text(row.get('data_type'))}; 계획 {_text(row.get('planned_count'))} / 실제 {_text(row.get('actual_count'))}; 검증 {_text(row.get('validation_result'), _execution_missing(data))}; 근거: {_refs(row)}"
    return text


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(value: Any, default: str = UNKNOWN) -> str:
    if value is None:
        return default
    if value == "" or value == []:
        return readable_value(value) if editorial_context_active() else default
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, list):
        return "\n".join(f"{i}. {_text(item)}" for i, item in enumerate(value, 1))
    if isinstance(value, dict):
        return readable_value(value)
    return str(value)


def _join(values, default=UNKNOWN):
    return ", ".join(str(v) for v in values if v is not None) or default


def _person(value):
    return _text((value or {}).get("name"), "담당자 미지정·확인/서명 자료 미제공")


def _refs(item):
    compact = source_reference_text(item.get("source_refs", []))
    if compact is not None:
        return compact
    return "; ".join(f"{r['source_id']} {r['locator']}" for r in item.get("source_refs", [])) or "출처 미제공"


def _review_summary(data, ids):
    reviews = {r["id"]: r for r in data["reviews"]}
    return "\n".join(f"{rid}: {code_label(reviews[rid]['review_type'])} / {code_label(reviews[rid]['outcome'])} / 확인상태 {code_label(reviews[rid]['status'])} / 검토자 {_text(reviews[rid].get('reviewer'))} / 검토일 {_text(reviews[rid].get('reviewed_at'))}" for rid in ids if rid in reviews) or "검토 기록 미제공"


def _own_text(p):
    return "".join(p.xpath("./hp:run/hp:t//text()", namespaces=NS))


def _paragraph(table):
    return next(p for p in table.iterancestors() if p.tag == f"{{{HP}}}p")


def _small_plain_paragraph(doc, p):
    if _own_text(p).strip() or any(e.tag.rsplit("}", 1)[-1] in {"tbl", "pic", "ctrl", "secPr", "colPr", "header", "footer", "fieldBegin", "fieldEnd", "rect", "equation"} for e in p.iter()):
        return False
    chars = {e.get("id"): int(e.get("height", "0")) for e in doc.xml("Contents/header.xml").findall(".//hh:charPr", HH)}
    sizes = [chars.get(run.get("charPrIDRef"), 0) for run in p.findall("hp:run", NS)]
    return bool(sizes) and all(900 <= size <= 1100 for size in sizes)


def _cover_notice(doc, customer, data):
    cover = doc.root(0)
    preceding = list(cover)[:list(cover).index(customer)]
    slot = next((p for p in reversed(preceding) if _small_plain_paragraph(doc, p)), None)
    if slot is None:
        raise ValueError("No small plain cover notice slot in this source profile")
    # Fill an existing 9–11 pt blank line. Do not add a line to the large
    # customer/title paragraph or alter cover spacing and page properties.
    doc.set_paragraph_text(slot, _notice(data))
    doc._editorial_cover_paragraphs["notice"] = slot


def _set(doc, table, row, col, value):
    cell = doc.cell(table, row, col)
    try:
        doc.set_cell_text(cell, _text(value))
    except ComposeError:
        controls = {e.tag.rsplit("}", 1)[-1] for e in cell.iter()}
        if controls & {"tbl", "pic", "ole", "fieldBegin", "fieldEnd", "rect", "chart", "equation"}:
            raise
        # Some original column labels anchor pageNum(pos=NONE). Retain that
        # document control and replace only owned text in the cell paragraphs.
        paragraphs = cell.findall("hp:subList/hp:p", NS)
        for i, p in enumerate(paragraphs):
            doc.set_paragraph_text(p, _text(value) if i == 0 else "")


def _all_tables(doc):
    return [table for i in range(len(doc.sections)) for table in doc.tables(section=i)]


def _repeat_cards(doc, table, items, fill):
    """Repeat the original table-containing paragraph, preserving its geometry."""
    original = _paragraph(table)
    previous = original
    cards = [table]
    for _ in items[1:]:
        paragraph = doc.clone_paragraph(original)
        paragraph.set("pageBreak", "1")
        previous.addnext(paragraph)
        previous = paragraph
        cards.append(paragraph.find(".//hp:tbl", NS))
    for index, item in enumerate(items):
        fill(cards[index], item, index)
    return cards


def _row_table(doc, table, rows, *, prototype=1, header=1, columns=None):
    rows = rows or [["해당 자료 미제공·발생 없음으로 판정하지 않음"]]
    doc.replace_body_rows(table, prototype_row_index=prototype, rows_count=len(rows), header_rows=header)
    doc.repeat_header_rows(table, count=header)
    for index, values in enumerate(rows, header):
        for col, value in zip(columns or range(len(values)), values):
            _set(doc, table, index, col, value)


def _narrative(doc, table, sections):
    """Keep native heading/body paragraph formats inside the original content cell."""
    cell = doc.cell(table, 0, 0)
    sublist = cell.find("hp:subList", NS)
    originals = list(sublist.findall("hp:p", NS))
    plain = next((p for p in originals if not _own_text(p).strip() and not p.findall(".//hp:tbl", NS)), originals[0])
    prototypes = [(re.sub(r"\s+", "", _own_text(p)), p) for p in originals]
    content = []
    for heading, paragraphs in sections:
        key = re.sub(r"\s+", "", heading)
        heading_style = next((p for text, p in prototypes if text.startswith(key) or key.startswith(text) and text), plain)
        title = doc.new_paragraph(heading, prototype=heading_style)
        if hasattr(doc, "_editorial_heading_paragraphs"):
            doc._editorial_heading_paragraphs.add(title)
        doc.use_paragraph_keep(title, keep_with_next=True)
        content.append(title)
        for paragraph in paragraphs:
            text = _text(paragraph)
            # A multiline source block becomes separate text paragraphs. Keep
            # each short paragraph independently, never chain the whole block.
            for line in text.split("\n"):
                body = doc.new_paragraph(line, prototype=plain)
                if line.strip() and len(line) <= NARRATIVE_KEEP_MAX_CHARS:
                    doc.use_paragraph_keep(body, keep_lines=True)
                content.append(body)
    for p in originals:
        doc.remove(p)
    for p in content:
        sublist.append(p)


def _narrative_owned_blocks(doc, table, sections):
    """Bind the declared writer sequence to real own paragraphs, without guessing IDs."""
    paragraphs = list(doc.cell(table, 0, 0).findall("hp:subList/hp:p", NS))
    offset = 0
    result = []
    for heading, values in sections:
        if offset >= len(paragraphs) or own_text(paragraphs[offset]) != heading:
            raise ValueError("Narrative heading/owner sequence differs from its declared writer")
        offset += 1
        blocks = []
        for value in values:
            lines = _text(value).split("\n")
            owned = paragraphs[offset:offset + len(lines)]
            if [own_text(p) for p in owned] != lines:
                raise ValueError("Narrative field block differs from its declared own text")
            blocks.append(owned)
            offset += len(lines)
        result.append(blocks)
    if offset != len(paragraphs):
        raise ValueError("Unexpected unowned narrative paragraphs")
    return result


def _prepare(doc, role, data, *, editorial=False):
    project = data["project"]
    removed = 0
    # Instructions occupy the final, explicitly labelled region in each v2 form.
    # Select that structural region rather than making colour a deletion rule.
    for section in range(len(doc.sections)):
        root = doc.root(section)
        marked = False
        for p in list(root):
            if "※ 작성 방법" in _own_text(p):
                marked = True
            if marked:
                if p.find(".//hp:tbl", NS) is not None:
                    raise ValueError("Instruction boundary unexpectedly contains a table; review mapping")
                testing_restart = None
                if role == "SF-TI1" and editorial:
                    from .testing_roles import stale_guide_restart as testing_guide_restart
                    testing_restart = testing_guide_restart(doc, role, p)
                try:
                    # These final guide paragraphs own a second PAGE=1 restart.
                    # Keeping that now-empty guide control resets the last
                    # generated program card's footer. This exact source-guide
                    # exception preserves the intended body-start restart.
                    numbers = p.findall(".//hp:newNum", NS)
                    stale_guide_restart = _own_text(p).strip() == STALE_GUIDE_PAGE_RESTARTS.get(role) and len(numbers) == 1 and dict(numbers[0].attrib) == {"num": "1", "numType": "PAGE"} and all(
                        e.tag.rsplit("}", 1)[-1] not in {"secPr", "colPr", "header", "footer", "pageNum", "pageHiding"} for e in p.iter())
                    if testing_restart is not None:
                        stale_guide_restart = testing_restart
                    doc.remove(p, allow_scope_controls=stale_guide_restart)
                except ComposeError:
                    doc.set_paragraph_text(p, "")
                removed += 1
    # These cover fields are direct paragraphs in section 0. Identical words
    # inside body tables are fixed field labels and must remain labels.
    cover = doc.root(0)
    doc._editorial_cover_paragraphs = {}
    cover_tables = doc.tables(section=0)
    if cover_tables:
        for paragraph in cover_tables[0].iter(f"{{{HP}}}p"):
            text = _own_text(paragraph).strip()
            if re.sub(r"\s+", "", text) in {"스마트공장보급·확산사업", "스마트공장구축및고도화사업"}:
                doc._editorial_cover_paragraphs["program"] = paragraph
                if editorial:
                    identity = _cover_program_identity(project)
                    doc.set_paragraph_text(paragraph, identity["text"])
                    doc._editorial_cover_program_identity = identity
            elif text == TITLES[role] or role == "SF-TI3" and text == "메뉴얼":
                doc._editorial_cover_paragraphs["title"] = paragraph
    for p in list(cover):
        text = _own_text(p).strip()
        if text == "도입기업명":
            _cover_notice(doc, p, data)
            doc._editorial_cover_paragraphs["customer"] = p
            doc.set_paragraph_text(p, _text((project.get('customer') or {}).get('name')))
        elif text == "공급기업명":
            doc._editorial_cover_paragraphs["supplier"] = p
            doc.set_paragraph_text(p, _text((project.get("supplier") or {}).get("name")))
        elif re.fullmatch(r"202\s*\.\s*\.", text):
            doc._editorial_cover_paragraphs["date"] = p
            doc.set_paragraph_text(p, "작성일 미확정 · 검토용 초안")
    for section in range(len(doc.sections)):
        for p in doc.root(section).iter(f"{{{HP}}}p"):
            text = _own_text(p).strip()
            in_header = any(a.tag == f"{{{HP}}}header" for a in p.iterancestors())
            if in_header and "사업" in text:
                doc.set_paragraph_text(p, f"{project.get('program_year') or '미확인'}년도 {_text(project.get('program_name'))} | {TITLES[role]}")
            elif re.fullmatch(r"SF-[A-Z]{2}\d+v", text):
                doc.set_paragraph_text(p, role)
    doc.set_metadata(title=f"{TITLES[role]} | {_notice(data)}", clear_legacy=True)
    return removed


def _toc(doc, entries):
    """Replace example IDs/page numbers; never assert unmeasured page numbers."""
    for section in range(len(doc.sections)):
        root = doc.root(section)
        children = list(root)
        start = next((i for i, p in enumerate(children) if _own_text(p).strip() == "목 차"), None)
        if start is None:
            continue
        region = []
        for p in children[start + 1:]:
            if p.get("pageBreak") == "1" or p.find(".//hp:tbl", NS) is not None:
                break
            region.append(p)
        if region:
            first = next((p for p in region if _own_text(p).strip()), region[0])
            doc._editorial_toc_paragraphs = {"title": children[start], "entries": first}
            doc.set_paragraph_text(first, "\n".join(entries + ["쪽수: 네이티브 출력 후 확인 예정"]))
            for p in region[region.index(first) + 1:]:
                if p is not first:
                    try:
                        doc.remove(p)
                    except ComposeError:
                        # Header/footer/page controls can be anchored in a TOC spacer.
                        doc.set_paragraph_text(p, "")


def _body_notice(doc, table, data, extra=None):
    p = _paragraph(table)
    # A native body cell paragraph is the typography prototype, not a cover title.
    prototype = table.find(".//hp:tc/hp:subList/hp:p", NS)
    notice = doc.new_paragraph(f"{_notice(data)}\n과제: {data['project']['name']}\n{extra or '협의·수행·승인·서명 사실과 근거는 별도 확인이 필요하다.'}", prototype=prototype)
    if p.find(".//hp:secPr", NS) is not None:
        # Hancom requires section properties in the first section paragraph.
        p.addnext(notice)
    else:
        p.addprevious(notice)


def _body_start_numbering(doc, role, tables):
    """Relocate only the four source profiles with TOC-anchored body numbers."""
    expected = {"SF-OS1": 2, "SF-TD3": 1, "SF-TD4": 1, "SF-TD5": 1}
    if role not in expected:
        return
    root = doc.root(0)
    if role == "SF-TD3":
        target = next((p for p in root if _own_text(p).startswith("1. 화면 표준(검토안)")), None)
    else:
        target = _paragraph(tables[1])
    sources = [p for p in root if p.findall("./hp:run/hp:ctrl/hp:newNum[@numType='PAGE']", NS)]
    if target is None or target.get("pageBreak") != "1" or len(sources) != expected[role]:
        raise ValueError(f"{role} body-start numbering boundary differs from its source profile")
    if any(dict(n.attrib) != {"num": "1", "numType": "PAGE"} for p in sources for n in p.findall("./hp:run/hp:ctrl/hp:newNum", NS)):
        raise ValueError(f"{role} source numbering is not the expected PAGE=1")
    doc.move_page_numbering(sources, target)


def _render_ad1(doc, data, tables, ctx):
    project = data["project"]
    processes = project.get("business_processes", [])
    systems = project.get("systems", [])
    sections = [
        ("1. 업무 현황 분석 결과", [_notice(data), "제공된 업무 입력을 정리한 분석 초안이다. 현장 조사·인터뷰의 실제 실시 여부와 근거는 별도 확인한다."]),
        ("1) 도입기업 소개", [f"기업: {_text((project.get('customer') or {}).get('name'))}", _text(project.get("business_profile")), "연혁·주생산품·조직도·현장 담당자의 분류별 상세 자료는 추가 확인이 필요하다."]),
        ("2) 전체 업무 흐름도", [f"{p['id']} {p['name']}\n현행 입력: " + " → ".join(p.get("current_steps", [])) for p in processes] or [UNKNOWN]),
        ("3) 주요 공정별 업무 흐름도", [f"{p['name']}\n" + _text(p.get("current_steps")) + f"\n수집 방식: {_text(p.get('data_collection_mode'))}; 자동화 수준: {_text(p.get('automation_level'))}. 실제 제어·설비 연결 여부는 미확인." for p in processes] or [UNKNOWN]),
        ("4) 현행 업무 분석 결과", [f"{p['name']}\n입력 문제점: {_text(p.get('issues'))}\n검토 방향: {_text(p.get('expected_effects'))}\n연결 요구사항: {_join(p.get('requirement_ids', []))}\n근거: {_refs(p)}" for p in processes] or [UNKNOWN]),
        ("2. 기존시스템에 대한 현황 분석 결과", ["계획 시스템과 현행 시스템의 제공 내용을 구별한다. 설치 상태를 확정할 분류별 증거는 추가 확인이 필요하다."]),
        ("1) 시스템 구성도", [f"{s['id']} {s['name']}\n현행: {_text(s.get('as_is_description'))}\n계획: {_text(s.get('to_be_description'))}\n제공 구성: {_text(s.get('configuration'))}\n출처: {_refs(s)}" for s in systems] or [UNKNOWN]),
        ("2) H/W 구성도", ["실제 서버·PC·설비·주변장치 목록 및 연결 자료 미제공. 장비가 없다고 판단하지 않는다."]),
        ("3) S/W 구성도", [f"{s['name']}: {_text(s.get('description'))}" for s in systems] or [UNKNOWN]),
        ("4) N/W 구성도", [f"{s['name']}: 통신 방식 {_text(s.get('network_method'))}. 실제 주소·망 분리·방화벽 설정은 미확인." for s in systems] or [UNKNOWN]),
        ("5) 메뉴 구조도", [f"{s['path']} → {s['id']} {s['name']} (목표 설계안; 현행 메뉴 실측자료 아님)" for s in data["screens"]] or [UNKNOWN]),
        ("6) 기존 시스템 분석 결과", ["실제 프로그램·데이터·라이선스 자산과 재사용 범위를 조사한 자료가 없어 재활용 여부는 확정하지 않는다.", f"가정한 도입범위: {_text(project.get('implementation_scope'))}"]),
    ]
    _narrative(doc, tables[-1], sections)
    if ctx.get("editorial"):
        blocks = _narrative_owned_blocks(doc, tables[-1], sections)
        for index, process in enumerate(processes):
            owners = [p for section in (2, 3, 4) for p in blocks[section][index]]
            for field in process:
                ctx.setdefault("primary_field_owners", {})[f"/project/business_processes/{index}/{field}"] = owners
        for index, system in enumerate(systems):
            owners = [p for section in (6, 8, 9) for p in blocks[section][index]]
            for field in system:
                ctx.setdefault("primary_field_owners", {})[f"/project/systems/{index}/{field}"] = owners
    _testing_frame_flow(doc, tables[-1], ctx, notice_position="next")
    if ctx.get("editorial"):
        ctx["organization_chart_anchor"] = next(p for p in doc.cell(tables[-1], 0, 0).findall("hp:subList/hp:p", NS) if own_text(p) == "2) 전체 업무 흐름도").getprevious()


def _ad2_groups(data):
    """Use supplied classification, retaining source order within each group."""
    requirements = data["requirements"]
    groups = [("기능 요구사항(SW)", [r for r in requirements if r.get("kind") == "functional"]),
              ("비기능 요구사항(HW 등)", [r for r in requirements if r.get("kind") == "nonfunctional"]),
              ("유형 미확인 요구사항", [r for r in requirements if r.get("kind") not in {"functional", "nonfunctional"}])]
    return [(title, items) for title, items in groups if items]


def _render_ad2(doc, data, tables, ctx):
    def fill(t, r, i):
        values = {(0, 1): r.get("system_name"), (0, 3): r.get("business_area"), (1, 1): r["id"], (1, 3): r["name"],
            (2, 1): r.get("description"), (3, 1): _text(r.get("details")), (4, 1): _text(r.get("constraints")),
            (5, 1): {"functional": "기능", "nonfunctional": "비기능"}.get(r.get("kind"), "구분 미확인"), (5, 3): _person(r.get("owner")),
            (6, 1): _refs(r), (7, 1): f"{_notice(data)}\n구분: {CHANGE.get(r.get('change_type'), UNKNOWN)}\n{_text(r.get('notes'))}"}
        for (row, col), value in values.items(): _set(doc, t, row, col, value)
        if ctx.get("editorial"):
            # The document already carries the synthetic/draft notice. Keep
            # item-specific status here, without repeating that long warning.
            note = [f"구분: {CHANGE.get(r.get('change_type'), UNKNOWN)}", "비고: " + readable_value(r.get("notes"))]
            for field in ("status", "original_id", "original_classification", "field_states"):
                if field in r:
                    note.append(f"{ {'status': '확인 상태', 'original_id': '원문 ID', 'original_classification': '원문 분류', 'field_states': '필드별 확인 상태'}[field]}: {code_label(r[field]) if field in {'status', 'original_classification'} else readable_value(r[field])}")
            _set(doc, t, 7, 1, "\n".join(note))
    ordered = [item for _, items in _ad2_groups(data) for item in items]
    cards = _repeat_cards(doc, tables[-1], ordered or [{"id": "미확인", "name": "요구사항 자료 미제공"}], fill)
    for card in cards:
        # Existing source positions are floating. CELL permits long details to
        # continue; repeat system/area and requirement ID/name on continuation.
        doc.use_table_pagination(card, break_mode="CELL")
        doc.repeat_header_rows(card, count=2)
    ctx["warnings"].append("AD2 상세카드는 기존 floating 위치를 유지하며 CELL 분할·첫2행 반복을 요청; 장문 전체 내용과 계속쪽의 요구 ID는 현재 바이트 native 검토 필요")


def _render_ad3(doc, data, tables, ctx):
    table = tables[-1]
    title_owner = _paragraph(table)
    if ctx.get("editorial"):
        from lxml import etree as ET
        profile = json.loads((Path(__file__).resolve().parents[2] / "resources/style-upgrade/profiles/SF-AD3.json").read_text())
        source = profile.get("feature_comparison_title_owner", {})
        location = (source.get("xml"), source.get("xpath"))
        namespaces = {**NS, "hs": "http://www.hancom.co.kr/hwpml/2011/section"}
        if (source.get("source_sha256") != doc.source_sha256 or location[0] not in doc.sections
                or doc._source_paragraph_locations.get(title_owner) != location
                or doc._source_paragraph_text.get(title_owner) != source.get("text_before_generation_verbatim")):
            raise ValueError("AD3 title/table source owner fingerprint or identity mismatch")
        original = ET.fromstring(doc._entries[location[0]]).xpath(location[1], namespaces=namespaces)
        original_table = original[0].find("hp:run/hp:tbl", NS) if len(original) == 1 else None
        original_position = original_table.find("hp:pos", NS) if original_table is not None else None
        if (len(original) != 1 or own_text(original[0]) != source.get("text_before_generation_verbatim")
                or original_position is None or original_position.get("treatAsChar") != "0"
                or original_position.get("vertOffset") != source.get("table_vert_offset_hwp")
                or table.getparent().getparent() is not title_owner or table.get("colCnt") != "6"):
            raise ValueError("AD3 title/table source flow shape mismatch")
    if doc._source_paragraph_text.get(title_owner) != "1. 000시스템":
        raise ValueError("AD3 exact source title owner missing")
    short_change = {"existing": "기존", "new": "추가", "modified": "변경", "deleted": "삭제"}
    rows = []
    for i, f in enumerate(data["features"], 1):
        status = "협의근거참조" if f.get("meeting_ids") or f.get("review_ids") else "협의미확인"
        rows.append([f.get("major_category"), f.get("middle_category"), f"{f['id']}\n{f.get('minor_category') or f['name']}", short_change.get(f.get("change_type"), "미확인"),
            f"{CHANGE.get(f.get('change_type'), UNKNOWN)}\n{_text(f.get('description'))}\n변경 전: {_text(f.get('before'))}\n검토안: {_text(f.get('after'))}",
            (f"[F{i}] 연결·근거 상세\n{status}" if ctx.get("editorial") else "\n".join(f.get("requirement_ids", [])) + f"\n{status}\n[F{i}]")])
    _row_table(doc, table, rows, prototype=9)
    if ctx.get("editorial"):
        bounded = all(all(len(str(value)) <= 300 for value in row) for row in rows)
        # The exact source title and table share one paragraph/run, with tbl
        # before owned text. Source floating offset2672 places the title above
        # its table. Inline flow inverted that physical order. Keep the original
        # paragraph/control/offset identity; no new title paragraph is needed.
        doc.use_table_pagination(table, break_mode="TABLE" if bounded else "CELL", inline=False)
        for row in table.findall("hp:tr", NS)[1:]:
            doc.use_paragraph_style(row, align="LEFT", break_latin="KEEP_WORD")
            doc.use_character_style(row, bold=False)
        if not bounded:
            ctx["warnings"].append("AD3 장문 기능행은 CELL 분할 유지; 실제 계속행의 기능ID·F키 문맥과 긴token 가독성은 native 확인 필요")
    # Long locators and notes belong to the full page width, with a short
    # table key preserving the source/consultation cross-reference.
    anchor = _paragraph(table)
    plain = next((p for p in doc.root() if _small_plain_paragraph(doc, p)), None)
    if plain is None:
        raise ValueError("No original body-size paragraph style for AD3 evidence notes")
    title = doc.new_paragraph("2. 기능별 근거·검토상태", prototype=anchor)
    doc._editorial_heading_paragraphs.add(title)
    doc.use_paragraph_keep(title, keep_with_next=True)
    anchor.addnext(title)
    previous = title
    for i, f in enumerate(data["features"], 1):
        paragraphs = [f"[F{i}] {f['id']} {f['name']}",
            f"구분 설명: {CHANGE.get(f.get('change_type'), UNKNOWN)}; 입력 확인상태: {code_label(f['status'])}",
            *(["분류 입력: " + describe_fields({field: f.get(field) for field in ("major_category", "middle_category", "minor_category")}, typed=True)] if ctx.get("editorial") else []),
            f"요구사항: {_join(f.get('requirement_ids', []))}",
            f"회의 연결: {_join(f.get('meeting_ids', []), '미제공')}",
            f"검토 연결: {_join(f.get('review_ids', []), '미제공')}",
            f"검토 상태: {_review_summary(data, f.get('review_ids', []))}",
            f"기타/가정: {_case_literal(f.get('notes')) if ctx.get('editorial') else _text(f.get('notes'))}", f"전체 출처: {_refs(f)}"]
        owned = []
        for paragraph_index, value in enumerate(paragraphs):
            for line in value.split("\n"):
                shown = f"[F{i}] {line}" if ctx.get("editorial") and paragraph_index else line
                p = doc.new_paragraph(shown, prototype=plain)
                if paragraph_index == 0:
                    doc._editorial_heading_paragraphs.add(p)
                elif ctx.get("editorial"):
                    doc.use_character_style(p, bold=False)
                    doc.use_paragraph_style(p, align="LEFT", break_latin="KEEP_WORD")
                doc.use_paragraph_keep(p, keep_lines=len(shown) <= NARRATIVE_KEEP_MAX_CHARS,
                    keep_with_next=paragraph_index == 0)
                previous.addnext(p)
                previous = p
                owned.append(p)
        if ctx.get("editorial"):
            main_columns = {"major_category": 0, "middle_category": 1, "id": 2, "minor_category": 2,
                "change_type": 3, "description": 4, "before": 4, "after": 4}
            for field in f:
                if field in main_columns:
                    owner = list(doc.cell(table, i, main_columns[field]).findall("hp:subList/hp:p", NS))
                    if field in {"major_category", "middle_category", "minor_category"}:
                        owner += owned
                else:
                    owner = owned
                ctx.setdefault("primary_field_owners", {})[f"/features/{i-1}/{field}"] = owner
    doc.set_paragraph_text(title_owner, "1. 시스템별 기능 대비(" + ("합성 설계 가정" if data["dataset_kind"] == "synthetic" else "제공 입력 검토") + ")")
    doc._editorial_heading_paragraphs.add(title_owner)
    ctx["warnings"].append("AD3의 병합 예시군 대신 원본 비병합 9행을 반복 단위로 사용; editorial 열폭은 선언 profile 기준이며 원본 셀 소유관계 보존")
    ctx["warnings"].append("AD3 editorial 비고는 F키·협의상태로 연결; 요구 ID·회의·검토·전체 출처·notes는 매 문단 F키를 가진 기능별 상세에 보존")


def _render_td1(doc, data, tables, ctx):
    processes = data["project"].get("business_processes", [])
    sections = [
        ("1. 개선된 전체 업무 흐름도", [_notice(data)] + [f"{p['id']} {p['name']}\n개선안: " + " → ".join(p.get("target_steps", [])) + f"\n연결 요구사항: {_join(p.get('requirement_ids', []))}" for p in processes]),
        ("2. 개선된 공정별 업무 흐름도", [f"{p['name']}\n현행 가정: " + " → ".join(p.get("current_steps", [])) + "\n변경 계획:\n" + _text(p.get("target_steps")) + f"\n수동 수집/부분 자동화 구분: {_text(p.get('data_collection_mode'))}/{_text(p.get('automation_level'))}; 실시간 제어는 {_text(p.get('real_time_control'))}.\n근거: {_refs(p)}" for p in processes] or [UNKNOWN]),
        ("3. 본 사업을 통한 기대효과", [f"{p['name']}\n현행 문제: {_text(p.get('issues'))}\n기대효과(계획): {_text(p.get('expected_effects'))}" for p in processes] + ["위 내용은 기능 연결과 검증 절차의 설계 목표다. 실제 구축·운영 효과나 KPI 달성을 주장하지 않는다."]),
    ]
    _narrative(doc, tables[-1], sections)
    if ctx.get("editorial"):
        blocks = _narrative_owned_blocks(doc, tables[-1], sections)
        for index, process in enumerate(processes):
            owners = [p for section in (0, 1, 2) for p in blocks[section][index + (section == 0)]]
            for field in process:
                ctx.setdefault("primary_field_owners", {})[f"/project/business_processes/{index}/{field}"] = owners
    _testing_frame_flow(doc, tables[-1], ctx, notice_position="next")


def _render_td2(doc, data, tables, ctx):
    project = data["project"]
    def installation(item, index):
        value = f"{item['id']} {item['name']}\n계획 사양: {_text(item.get('planned_specification'))}\n계획 수량: {_text(item.get('planned_quantity'))}{_text(item.get('unit'), '')}; 예정일: {_text(item.get('scheduled_date'))}\n검증 계획: {_text(item.get('verification_method'))}\n{_deployment_actual_text(data, item)}"
        return "\n".join(f"[I{index}] {line}" for line in value.split("\n")) if ctx.get("editorial") else value
    sections = [
        ("1. 시스템 구성도", [_notice(data)] + [f"{s['id']} {s['name']}\n제공 구성: {_text(s.get('configuration'))}\n현행 설명: {_text(s.get('as_is_description'))}\n목표 계획: {_text(s.get('to_be_description'))}\n실제 배포 확인: {_execution_missing(data)}\n근거: {_refs(s)}" for s in project.get("systems", [])]),
        ("2. 하드웨어 구성도", ["장비의 제공 계획·실제 사양·수량·설치 상태는 5절의 항목별 입력을 참조한다. 그림과 자산 배치의 확인 범위는 제공된 첨부·출처를 기준으로 검토한다."]),
        ("3. 소프트웨어 구성도", [f"{p['id']} {p['name']}\n입구: {_text(p.get('interfaces'))}\n기능 목록(번호는 입력 배열 위치, 실행순서 미확정): " + "; ".join(f"{index}. {function}" for index, function in enumerate(p.get("functions", []), 1)) + f"\n관련 테이블: {_join(p.get('table_ids', []))}" for p in data["programs"]]),
        ("4. 네트워크 구성도", [f"{s['name']}: {_text(s.get('network_method'))}" for s in project.get("systems", [])] + ["망 구간·전송보호·포트·인증 연동·백업 경로는 실제 환경 자료를 받은 후 설계한다. 임의 IP나 계정을 발급한 것으로 기재하지 않는다."]),
        ("5. 장비 도입 및 설치 계획", [installation(item, index) for index, item in enumerate(data["deployment_items"], 1)] or [UNKNOWN]),
        ("6. 클라우드 서비스 이용 내용", [f"{system['name']} — 제공 목표 계획: {_text(system.get('to_be_description'))}" for system in project.get("systems", [])] + ["클라우드 사용 여부는 제공된 목표 계획을 기준으로 검토한다. 입력에 없는 사업자·상품·리전·계약·개통 정보는 별도 확인이 필요하다."]),
    ]
    _narrative(doc, tables[-1], sections)
    if ctx.get("editorial"):
        blocks = _narrative_owned_blocks(doc, tables[-1], sections)
        for index, system in enumerate(project.get("systems", [])):
            owners = [p for section in (0, 3, 5) for p in blocks[section][index + (section == 0)]]
            for field in system:
                ctx.setdefault("primary_field_owners", {})[f"/project/systems/{index}/{field}"] = owners
    _testing_frame_flow(doc, tables[-1], ctx, notice_position="next")
    if ctx.get("editorial"):
        container = doc.cell(tables[-1], 0, 0).find("hp:subList", NS)
        for index, item in enumerate(data["deployment_items"]):
            owners = [p for p in container.findall("hp:p", NS) if own_text(p).startswith(f"[I{index + 1}] ")]
            if not owners:
                raise ValueError("Architecture installation detail owner is missing: " + item["id"])
            # Only this exact record's first paragraph joins its first plan
            # value. Later paragraphs retain independent CELL pagination.
            doc.use_paragraph_keep(owners[0], keep_lines=True, keep_with_next=True)
            for field in item:
                ctx.setdefault("primary_field_owners", {})[f"/deployment_items/{index}/{field}"] = owners


def _td3_plain_paragraphs(doc, paragraph, *, linked_titles=(), intro_blocks=None):
    """Split this source profile's plain run, preserving its direct formatting."""
    runs = paragraph.findall("hp:run", NS)
    if len(runs) != 1 or [e.tag.rsplit("}", 1)[-1] for e in paragraph] != ["run"] or [e.tag.rsplit("}", 1)[-1] for e in runs[0]] != ["t"]:
        raise ValueError("TD3 paragraph splitting requires the observed one-run plain-text source shape")
    if any(e.tag.rsplit("}", 1)[-1] not in {"lineBreak", "tab", "fwSpace", "nbSpace"} for e in runs[0][0]):
        raise ValueError("TD3 paragraph splitting cannot discard semantic inline content")
    text = own_text(paragraph)
    lines = intro_blocks if intro_blocks is not None else text.split("\n")
    if "\n".join(lines) != text:
        raise ValueError("TD3 explicit intro blocks differ from the original notice")
    container = paragraph.getparent()
    index = container.index(paragraph)
    # Build from the original reference before the first paragraph gains keeps.
    added = [doc.new_paragraph(line, prototype=paragraph) for line in lines[1:]]
    doc.set_paragraph_text(paragraph, lines[0])
    for offset, p in enumerate(added, 1):
        container.insert(index + offset, p)
    for p, line in zip([paragraph, *added], lines):
        if editorial_context_active():
            doc.use_character_style(p, bold=False)
            doc._editorial_body_paragraphs.add(p)
        doc.use_paragraph_keep(p,
            keep_lines=bool(line.strip()) and len(line) <= NARRATIVE_KEEP_MAX_CHARS,
            keep_with_next=intro_blocks is not None or line.rstrip().endswith(":") or line in linked_titles or editorial_context_active() and bool(re.match(r"^필드 \d+\. ", line)))


def _append_images(doc, data, item, container, slots, ctx, *, prototype=None):
    """Insert supplied pictures; keep original/embedded byte identities separate."""
    from io import BytesIO
    from PIL import Image
    attachments = {attachment["id"]: attachment for attachment in data["attachments"]}
    prototype = prototype if prototype is not None else container.find("hp:p", NS)
    provided = []
    for field, label in slots:
        for attachment_id in item.get(field, []):
            attachment = attachments[attachment_id]
            path = Path(attachment["path"])
            if not path.is_absolute():
                path = ctx["input_dir"] / path
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != attachment["sha256"]:
                raise ValueError(f"TD3 image SHA mismatch: {attachment_id}")
            embedded = raw
            media = attachment["media_type"]
            with Image.open(BytesIO(raw)) as image:
                width, height = image.size
                if image.format == "BMP":
                    output = BytesIO()
                    image.save(output, format="PNG")
                    embedded = output.getvalue()
                    media = "image/png"
            # Explicit supplied ratio; no cropping or invented screen content.
            cell = container.getparent()
            size = cell.find("hp:cellSz", NS) if cell is not None else None
            width_mm = min(140.0, float(size.get("width")) / (7200 / 25.4) - 3.0) if size is not None else 140.0
            height_mm = width_mm * height / width
            if height_mm > 110:
                width_mm *= 110 / height_mm
                height_mm = 110.0
            given_caption = attachment.get("caption") or attachment["name"]
            synthetic = attachment.get("status") == "synthetic" or attachment.get("verification_status") == "synthetic"
            if ctx.get("editorial"):
                notes = ctx.setdefault("attachment_notes", {})
                if attachment_id not in notes:
                    notes[attachment_id] = {"key": f"A{len(notes) + 1}", "attachment": dict(attachment), "usages": []}
                record = notes[attachment_id]
                record["usages"].append({"entity_id": item.get("id"), "entity_name": item.get("name"), "slot": field, "slot_label": label})
                # Long explicit captions remain verbatim in the readable
                # attachment correspondence; do not truncate their source text.
                shown_caption = given_caption if len(given_caption) <= 88 else item.get("name") or attachment["name"]
                caption = f"{label} — {item.get('id', item.get('name', UNKNOWN))} · {shown_caption} [{record['key']}]"
                if synthetic and not ("합성" in shown_caption and "실제" in shown_caption):
                    caption += " · 합성 시안·실제 실행화면 아님"
            else:
                caption = f"{label} — {item.get('id', item.get('name', UNKNOWN))} [{attachment_id}] — {given_caption}"
                if synthetic:
                    caption += " (합성 시안·실제 실행화면 아님)"
            paragraph = doc.new_paragraph("", prototype=prototype)
            container.append(paragraph)
            if ctx.get("editorial"):
                doc._editorial_picture_paragraphs.add(paragraph)
            caption_paragraph = doc.new_paragraph(caption, prototype=prototype)
            container.append(caption_paragraph)
            if ctx.get("editorial"):
                doc._editorial_caption_paragraphs.add(caption_paragraph)
                ctx.setdefault("after_picture_captions", {})[caption_paragraph] = paragraph
            details = f"첨부 확인상태: {code_label(attachment['status'])}; 검증상태: {code_label(attachment.get('verification_status', UNKNOWN))}\n용도: {readable_value(attachment.get('purpose'))}\n출처: {_refs(attachment)}"
            if not ctx.get("editorial"):
                details += "\n출처 ID: " + readable_value(attachment.get("source_id"))
            if "notes" in attachment:
                details += "\n첨부 비고: " + readable_value(attachment["notes"])
            if not ctx.get("editorial"):
                container.append(doc.new_paragraph(details, prototype=prototype))
            binding = {"entity_id": item.get("id"), "entity_name": item.get("name"), "slot": field, "attachment_id": attachment_id, "sha256": attachment["sha256"], "embedded_sha256": hashlib.sha256(embedded).hexdigest(), "conversion": "bmp_to_png_lossless" if embedded != raw else "none", "caption": caption, "provided_caption": attachment.get("caption"), "attachment_note_key": record["key"] if ctx.get("editorial") else None, "width_mm": width_mm, "height_mm": height_mm, "crop": "none"}
            provided.append(binding)
            ctx.setdefault("_pending_images", []).append({"paragraph": paragraph, "bytes": embedded, "media_type": media, "pixels": (width, height), "binding": binding})
    if provided:
        ctx.setdefault("image_bindings", []).extend(provided)
    return provided


def _materialize_images(doc, ctx):
    """Use final profile geometry, rather than the pre-profile portrait width."""
    units_per_mm = 7200 / 25.4
    for pending in ctx.get("_pending_images", []):
        paragraph = pending["paragraph"]
        root = next(root for index in range(len(doc.sections)) if (root := doc.root(index)) in paragraph.iterancestors())
        page = root.find("./hp:p/hp:run/hp:secPr/hp:pagePr", NS)
        if page is None:
            raise ComposeError("Picture has no owning section page geometry")
        margin = page.find("hp:margin", NS)
        edges = sorted((int(page.get("width")), int(page.get("height"))))
        page_width, page_height = edges[::-1] if page.get("landscape") == "NARROWLY" else edges
        available_width = page_width - sum(int(margin.get(key, "0")) for key in ("left", "right", "gutter"))
        available_height = page_height - sum(int(margin.get(key, "0")) for key in ("top", "bottom"))
        cell = next((ancestor for ancestor in paragraph.iterancestors() if ancestor.tag == f"{{{HP}}}tc"), None)
        if cell is not None:
            size = cell.find("hp:cellSz", NS)
            cell_margin = cell.find("hp:cellMargin", NS)
            available_width = min(available_width, int(size.get("width")) - sum(int(cell_margin.get(key, "0")) for key in ("left", "right")))
        # Leave finite room for the caption and source note. Large source
        # pictures still need native readability review; no raster is cropped.
        max_width_mm = max(1.0, available_width / units_per_mm)
        max_height_mm = max(10.0, available_height / units_per_mm - 25.0)
        if not ctx.get("editorial"):
            max_width_mm, max_height_mm = min(140.0, max_width_mm), min(110.0, max_height_mm)
        media = pending["media_type"]
        raster_profile = ctx.get("raster_metadata_profile") if media == "image/png" else None
        picture = doc.insert_picture(paragraph, pending["bytes"], media_type=media, extension="png" if media == "image/png" else "jpg", width_mm=max_width_mm, height_mm=max_height_mm, description=pending["binding"]["caption"], raster_metadata_profile=raster_profile, viewport_pixels=pending.get("viewport_pixels"))
        actual = picture.find("hp:curSz", NS)
        pending["binding"].update({"width_hwp": int(actual.get("width")), "height_hwp": int(actual.get("height")), "width_mm": int(actual.get("width")) / units_per_mm, "height_mm": int(actual.get("height")) / units_per_mm, "geometry_source": "post_editorial_layout" if ctx.get("editorial") else "source_layout", "raster_metadata_profile": raster_profile})


def _td3_images(doc, data, screen, table, ctx):
    sublist = doc.cell(table, 2, 1).find("hp:subList", NS)
    prototype = sublist.find("hp:p", NS)
    provided = _append_images(doc, data, screen, sublist, (("standard_attachment_ids", "화면 표준"), ("before_attachment_ids", "기존 화면"), ("after_attachment_ids", "변경 화면")), ctx)
    if provided:
        # Replace the text owning paragraph only; the newly attached pictures
        # remain separate semantic objects in their own paragraphs.
        labels = {item["slot"] for item in provided}
        summary = [f"화면 구성: {readable_value(screen.get('description'))}"]
        slots = [f"{label}: {'그림 참조' if field in labels else '자료 미제공'}" for field, label in (("standard_attachment_ids", "표준 시안"), ("before_attachment_ids", "기존 화면"), ("after_attachment_ids", "변경 화면"))]
        if ctx.get("editorial"):
            summary.append(f"구분: {CHANGE.get(screen.get('change_type'), UNKNOWN)} · " + "; ".join(slots))
        else:
            summary += [f"구분: {CHANGE.get(screen.get('change_type'), UNKNOWN)}"] + slots + ["이미지의 존재는 실제 구현·수행·검토 승인을 증명하지 않는다."]
        doc.set_paragraph_text(prototype, "\n".join(summary))


def _image_groups(data, role):
    """Source-owned attachment fields and their document-specific meanings."""
    if role == "SF-AD1":
        return [("project", [data["project"]], (("organization_chart_attachment_ids", "도입기업 조직도"),)),
                ("project/business_processes", data["project"].get("business_processes", []), (("as_is_attachment_ids", "현행 업무 흐름도"),)),
                ("project/systems", data["project"].get("systems", []), (("as_is_diagram_ids", "현행 시스템 구성도"),))]
    if role == "SF-TD1":
        return [("project/business_processes", data["project"].get("business_processes", []), (("as_is_attachment_ids", "현행 업무 흐름도"), ("to_be_attachment_ids", "개선 업무 흐름도")))]
    if role == "SF-TD2":
        return [("project/systems", data["project"].get("systems", []), (("as_is_diagram_ids", "현행 시스템 구성도"), ("to_be_diagram_ids", "목표 시스템 구성도")))]
    if role == "SF-TD3":
        return [("screens", data["screens"], (("before_attachment_ids", "기존 화면"), ("after_attachment_ids", "변경 화면"), ("standard_attachment_ids", "화면 표준")))]
    if role == "SF-TD4":
        return [("programs", data["programs"], (("module_flow_attachment_ids", "프로그램 모듈 흐름도"),))]
    if role == "SF-TI3":
        return [("project/manual_sections", data["project"].get("manual_sections", []), (("attachment_ids", "매뉴얼 설명 그림"),)),
                ("screens", data["screens"], (("standard_attachment_ids", "매뉴얼 화면 표준"), ("before_attachment_ids", "매뉴얼 기존 화면"), ("after_attachment_ids", "매뉴얼 변경 화면")))]
    stage = {"SF-CD1": "unit", "SF-TI1": "integration", "SF-TI4": "acceptance"}.get(role)
    if stage:
        return [("test_cases", [case for case in data["test_cases"] if case.get("stage") == stage], (("flow_attachment_ids", "시험 흐름도"),))]
    return []


def _role_images(doc, role, data, tables, ctx):
    """Add provided diagrams near the owning specification or evidence section."""
    if role == "SF-TD3":
        return  # The before/after/standard slots are inside their screen cards.
    for prefix, items, slots in _image_groups(data, role):
        for item in items:
            organization_chart = role == "SF-AD1" and prefix == "project"
            if not any(item.get(field) for field, _ in slots) and not (organization_chart and "organization_chart_attachment_ids" in item):
                continue
            if organization_chart:
                container = doc.cell(tables[-1], 0, 0).find("hp:subList", NS)
                anchor = ctx.get("organization_chart_anchor")
                if anchor is None and not ctx.get("editorial"):
                    heading = next((p for p in container.findall("hp:p", NS) if own_text(p) == "2) 전체 업무 흐름도"), None)
                    anchor = heading.getprevious() if heading is not None else None
                if anchor is None or anchor.getparent() is not container:
                    raise ValueError("AD1 organization chart has no exact customer-overview owner")
                prototype = anchor
            elif role == "SF-TD4":
                card = next(table for table in _all_tables(doc)[1:] if own_text(doc.cell(table, 0, 1).find("hp:subList/hp:p", NS)) == item["id"])
                container = doc.cell(card, 2, 1).find("hp:subList", NS)
                for p in container.findall("hp:p", NS):
                    if "독립 모듈 흐름도 이미지는 제공되지 않았다." in own_text(p):
                        doc.set_paragraph_text(p, own_text(p).replace("독립 모듈 흐름도 이미지는 제공되지 않았다.", "제공된 모듈 흐름도는 아래 그림과 출처를 참조한다."))
                prototype = container.find("hp:p", NS)
            elif role in {"SF-CD1", "SF-TI1", "SF-TI4"}:
                container = _paragraph(tables[-2]).getparent()
                prototype = next(p for p in tables[-2].iter(f"{{{HP}}}p") if p.find("hp:run/hp:t", NS) is not None)
            else:
                container = doc.cell(tables[-1], 0, 0).find("hp:subList", NS)
                prototype = next((p for p in container.findall("hp:p", NS) if own_text(p).strip() and not own_text(p).startswith(("1.", "2.", "3."))), container.find("hp:p", NS))
            before_images = set(container) if organization_chart or role == "SF-TI3" and ctx.get("editorial") else None
            before_captions = set(doc._editorial_caption_paragraphs) if role in {"SF-AD1", "SF-TD1", "SF-TD2", "SF-TD4"} and ctx.get("editorial") else None
            if organization_chart:
                label = "합성 조직도 설계자료·실제 회사 조직/임명 확인 아님" if data["dataset_kind"] == "synthetic" else "제공 조직도·실제 조직/임명 확인은 출처 검토 범위에 따름"
                context = doc.new_paragraph(f"도입기업 조직도 — {_text((item.get('customer') or {}).get('name'))}; 사업 ID: {item['id']}\n{label}\n첨부 목록: {typed_value(item['organization_chart_attachment_ids'])}", prototype=prototype)
                doc.use_character_style(context, bold=False)
                doc.use_paragraph_style(context, align="LEFT", break_latin="KEEP_WORD")
                doc.use_paragraph_keep(context, keep_lines=False, keep_with_next=bool(item["organization_chart_attachment_ids"]))
                container.append(context)
                if ctx.get("editorial"):
                    doc._editorial_body_paragraphs.add(context)
            bindings = _append_images(doc, data, item, container, slots, ctx, prototype=prototype)
            if organization_chart:
                for binding in bindings:
                    aid = binding["attachment_id"]
                    binding.update(entity_kind="project", entity_input_pointer="/project",
                        slot_input_pointer="/project/organization_chart_attachment_ids",
                        attachment_value_input_pointer=f"/project/organization_chart_attachment_ids/{item['organization_chart_attachment_ids'].index(aid)}",
                        attachment_input_pointer=f"/attachments/{next(i for i, a in enumerate(data['attachments']) if a['id'] == aid)}",
                        placement="after_exact_customer_overview_before_overall_workflow")
                    caption = next(p for p in container.findall("hp:p", NS) if own_text(p) == binding["caption"])
                    integrity = doc.new_paragraph(f"조직도 첨부 ID: {aid}\nSHA-256: {binding['sha256']}", prototype=prototype)
                    doc.use_character_style(integrity, bold=False)
                    doc.use_paragraph_style(integrity, align="LEFT", break_latin="KEEP_WORD")
                    doc.use_paragraph_keep(integrity, keep_lines=True, keep_with_next=False)
                    caption.addnext(integrity)
                    if ctx.get("editorial"):
                        doc._editorial_body_paragraphs.add(integrity)
            if before_captions is not None:
                for paragraph in doc._editorial_caption_paragraphs - before_captions:
                    doc.use_paragraph_style(paragraph, align="LEFT", break_latin="KEEP_WORD")
            if before_images is not None:
                anchor = anchor if organization_chart else ctx.get("manual_image_anchors", {}).get(item.get("id"))
                if anchor is None or anchor.getparent() is not container:
                    raise ValueError("Manual picture has no declared description owner: " + str(item.get("id")))
                added = [node for node in container if node not in before_images]
                for paragraph in added:
                    anchor.addnext(paragraph)
                    anchor = paragraph
                if organization_chart and ctx.get("editorial"):
                    ctx.setdefault("organization_chart_meaning", []).append({"input_pointer": "/project/organization_chart_attachment_ids",
                        "entity_id": item["id"], "entity_name": (item.get("customer") or {}).get("name"),
                        "scope": "Customer-overview organization chart; no actual organization, appointment or approval inferred.",
                        "fields": [{"input_pointer": "/project/organization_chart_attachment_ids", "input_value": item["organization_chart_attachment_ids"],
                            "input_type": "list", "representation": "customer_overview_organization_chart",
                            "content_review_status": "pending", "_primary_paragraphs": added}]})
                if not organization_chart:
                    for binding in bindings:
                        binding["placement"] = "after_exact_manual_or_screen_description"


def _append_context_fields(doc, root, prototype, context, fields, *, typed=False, compact=False, align=None):
    """Keep exact field descriptions and a context key on every continuation.

    Only the source/review appendices opt into packing bounded short scalar
    fields. Long prose and nested values keep their separate owned paragraphs;
    no value is abbreviated and no document-wide style is changed to fit.
    """
    pending = []

    def append(text):
        paragraph = doc.new_paragraph(text, prototype=prototype)
        doc.use_character_style(paragraph, bold=False)
        if compact or align is not None:
            # Technical source tokens should wrap without spreading a short
            # preceding phrase across the full page width.
            doc.use_paragraph_style(paragraph, align=align or "LEFT")
        doc.use_paragraph_keep(paragraph, keep_lines=len(text) <= NARRATIVE_KEEP_MAX_CHARS, keep_with_next=False)
        root.append(paragraph)

    def flush():
        if pending:
            append(f"{context} " + "; ".join(pending))
            pending.clear()

    for key, value in fields.items():
        lines = describe_fields({key: value}, typed=typed).split("\n")
        atomic = not isinstance(value, (dict, list)) or not value or key.endswith("source_refs")
        short = len(lines) == 1 and len(lines[0]) <= APPENDIX_SCALAR_GROUP_MAX_CHARS // 2
        if compact and atomic and short:
            candidate = f"{context} " + "; ".join([*pending, lines[0]])
            if pending and (len(pending) >= APPENDIX_SCALAR_GROUP_MAX_FIELDS or len(candidate) > APPENDIX_SCALAR_GROUP_MAX_CHARS):
                flush()
            pending.append(lines[0])
            continue
        flush()
        for line in lines:
            append(f"{context} {line}")
    flush()


def _appendix_prototype(doc, table):
    """Use a declared neutral source value only for PM2 generated appendices."""
    prototype = getattr(doc, "_editorial_appendix_prototype", None)
    return prototype if prototype is not None else list(table.iter(f"{{{HP}}}p"))[-1]


def _append_attachment_notes(doc, ctx):
    """Readable exact attachment metadata, outside the figure's narrow cell."""
    records = list(ctx.get("attachment_notes", {}).values())
    if not records:
        return
    table = _all_tables(doc)[-1]
    root = _paragraph(table).getparent()
    prototype = _appendix_prototype(doc, table)
    title = doc.new_paragraph("부록. 첨부 그림 대응표", prototype=prototype)
    doc._editorial_heading_paragraphs.add(title)
    doc.use_paragraph_keep(title, keep_with_next=True)
    root.append(title)
    for record in records:
        attachment = record["attachment"]
        heading = doc.new_paragraph(f"[{record['key']}] {attachment['name']} — {attachment['id']}", prototype=prototype)
        doc._editorial_heading_paragraphs.add(heading)
        doc.use_paragraph_keep(heading, keep_with_next=True)
        root.append(heading)
        usages = "; ".join(f"{usage['entity_id'] or usage['entity_name']} / {usage['slot_label']}" for usage in record["usages"])
        fields = {key: value for key, value in attachment.items() if key not in {"id", "name"}}
        _append_context_fields(doc, root, prototype, f"[{record['key']}]", {"본문 연결": usages, **fields}, align="LEFT")


def _append_linked_review_notes(doc, data, ctx):
    """Keep all supplied details of reviews referenced by this role's entities."""
    owners = defaultdict(list)
    for entity in ctx.get("meaning_map", []):
        for field in entity["fields"]:
            if field["input_pointer"].endswith("/review_ids"):
                for review_id in field["input_value"]:
                    owners[review_id].append(entity.get("entity_id") or entity.get("entity_name") or entity["input_pointer"])
    for owner, review_ids in ctx.get("additional_review_bindings", []):
        for review_id in review_ids:
            owners[review_id].append(owner)
    if not owners:
        return
    table = _all_tables(doc)[-1]
    root = _paragraph(table).getparent()
    prototype = _appendix_prototype(doc, table)
    title = doc.new_paragraph("부록. 연결 검토 기록", prototype=prototype)
    doc._editorial_heading_paragraphs.add(title)
    doc.use_paragraph_keep(title, keep_with_next=True)
    root.append(title)
    reviews = {review["id"]: review for review in data["reviews"]}
    records = []
    for review_id, references in owners.items():
        review = reviews[review_id]
        review_key = f"RV{len(records) + 1}"
        heading = doc.new_paragraph(f"검토 {review_id} — {readable_value(review.get('name'))} [{review_key}]", prototype=prototype)
        doc._editorial_heading_paragraphs.add(heading)
        doc.use_paragraph_keep(heading, keep_with_next=True)
        root.append(heading)
        references = list(dict.fromkeys(references))
        _append_context_fields(doc, root, prototype, f"[{review_key}]", {"연결 항목": references, **{key: value for key, value in review.items() if key not in {"id", "name"}}}, compact=True)
        records.append({"key": review_key, "review": review, "referenced_by": references})
    ctx["linked_reviews"] = records


def _append_source_notes(doc, data, notes):
    """Human source correspondence, kept separate from narrow business cells."""
    if not notes.records and not notes.code_mappings:
        return
    last_table = _all_tables(doc)[-1]
    root = _paragraph(last_table).getparent()
    prototype = _appendix_prototype(doc, last_table)
    title = doc.new_paragraph("부록. 출처 대응표", prototype=prototype)
    doc.use_paragraph_keep(title, keep_with_next=True)
    doc._editorial_heading_paragraphs.add(title)
    root.append(title)
    code_paragraph = None
    if notes.code_mappings:
        paragraph = doc.new_paragraph("표시값 원문 대응: " + "; ".join(f"{label} ← {original}" for original, label in notes.code_mappings.items()), prototype=prototype)
        doc.use_paragraph_keep(paragraph, keep_lines=False, keep_with_next=False)
        doc.use_character_style(paragraph, bold=False)
        root.append(paragraph)
        code_paragraph = paragraph
    sources = {source["id"]: source for source in data["sources"]}
    grouped = defaultdict(list)
    for record in notes.records:
        grouped[record["source_ref"]["source_id"]].append(record)
    for number, (source_id, records) in enumerate(grouped.items(), 1):
        source_start = len(root)
        source_key = f"D{number}"
        source = sources.get(source_id, {})
        heading = doc.new_paragraph(f"자료: {source.get('title') or source.get('name') or source_id} — {source_id} [{source_key}] (확인 상태 원문: {source.get('verification_status', source.get('status', UNKNOWN))})", prototype=prototype)
        doc.use_paragraph_keep(heading, keep_lines=True, keep_with_next=True)
        root.append(heading)
        metadata = {key: value for key, value in source.items() if key not in {"id", "title", "name", "verification_status", "status"}}
        if metadata:
            _append_context_fields(doc, root, prototype, f"[{source_key}]", metadata, compact=True)
        pending = []

        def flush_references():
            if not pending:
                return
            text = f"[{source_key}] " + "; ".join(f"[{record['key']}] {record['source_ref']['locator']}" for record in pending)
            paragraph = doc.new_paragraph(text, prototype=prototype)
            doc.use_character_style(paragraph, bold=False)
            doc.use_paragraph_style(paragraph, align="LEFT")
            doc.use_paragraph_keep(paragraph, keep_lines=len(text) <= SOURCE_REF_GROUP_MAX_CHARS, keep_with_next=False)
            root.append(paragraph)
            for record in pending:
                record["_paragraph"] = paragraph
            pending.clear()

        for record in records:
            reference = record["source_ref"]
            record["source_key"] = source_key
            if set(reference) == {"source_id", "locator"}:
                candidate = f"[{source_key}] " + "; ".join(f"[{entry['key']}] {entry['source_ref']['locator']}" for entry in [*pending, record])
                if pending and len(candidate) > SOURCE_REF_GROUP_MAX_CHARS:
                    flush_references()
                pending.append(record)
                continue
            flush_references()
            fields = [f"[{record['key']}] 자료 {source_key} · 원문 위치: {reference['locator']}"]
            fields.extend(f"{key}: {readable_value(value)}" for key, value in reference.items() if key not in {"source_id", "locator"})
            paragraph = doc.new_paragraph("\n".join(fields), prototype=prototype)
            doc.use_character_style(paragraph, bold=False)
            doc.use_paragraph_style(paragraph, align="LEFT")
            doc.use_paragraph_keep(paragraph, keep_lines=len("\n".join(fields)) <= NARRATIVE_KEEP_MAX_CHARS, keep_with_next=False)
            root.append(paragraph)
            record["_paragraph"] = paragraph
        flush_references()
        source_paragraphs = list(root)[source_start:]
        # A short bibliography introduction belongs with its first citation.
        # Bound the chain rather than keeping an unbounded source appendix or
        # hiding a continuation behind smaller type. Long metadata can flow.
        intro_count = next((i + 1 for i, p in enumerate(source_paragraphs)
                            if any(record.get("_paragraph") is p for record in records)), 0)
        introduction = source_paragraphs[:intro_count]
        if (introduction and len(introduction) <= 8
                and sum(len(own_text(p)) for p in introduction) <= 1200
                and all(len(own_text(p)) <= SOURCE_REF_GROUP_MAX_CHARS for p in introduction)):
            for p in introduction[:-1]:
                doc.use_paragraph_keep(p, keep_with_next=True)
            if number == 1 and code_paragraph is not None and len(own_text(code_paragraph)) <= NARRATIVE_KEEP_MAX_CHARS:
                doc.use_paragraph_keep(code_paragraph, keep_with_next=True)
    if notes.code_mappings:
        text = "표시값 원문 대응: " + "; ".join(f"{label} ← {original}" for original, label in notes.code_mappings.items())
        if code_paragraph is None:
            code_paragraph = doc.new_paragraph(text, prototype=prototype)
            doc.use_character_style(code_paragraph, bold=False)
            doc.use_paragraph_keep(code_paragraph, keep_lines=False, keep_with_next=False)
            title.addnext(code_paragraph)
        else:
            doc.set_paragraph_text(code_paragraph, text)


# Fields deliberately composed in the role's main specification. Any other
# supplied field goes to a readable supplement, instead of silently vanishing.
# These sets route writing; they do NOT certify semantic coverage or native QA.
_MEANING_SPECS = {
    "SF-AD1": [("project/business_processes", "id name current_steps issues expected_effects data_collection_mode automation_level requirement_ids source_refs"), ("project/systems", "id name description as_is_description to_be_description configuration network_method source_refs")],
    "SF-AD2": [("requirements", "id name system_name business_area kind change_type description details constraints source_refs notes status original_id original_classification field_states")],
    "SF-AD3": [("features", "id name major_category middle_category minor_category change_type description before after requirement_ids meeting_ids review_ids source_refs status notes")],
    "SF-TD1": [("project/business_processes", "id name current_steps target_steps issues expected_effects data_collection_mode automation_level real_time_control requirement_ids source_refs")],
    "SF-TD2": [("project/systems", "id name as_is_description to_be_description configuration network_method source_refs"), ("deployment_items", "id name planned_specification planned_quantity unit scheduled_date actual_specification installed_quantity installation_date installation_status verification_method verification_result evidence_ids migration_counts source_refs")],
    "SF-TD3": [("screens", "id name path description change_type steps fields buttons permissions checks requirement_ids feature_ids program_ids review_ids before_attachment_ids after_attachment_ids standard_attachment_ids notes status field_states menu_levels source_refs")],
    "SF-TD4": [("programs", "id name description change_type interfaces functions query_conditions registration_conditions calculation_rules output_fields screen_ids table_ids requirement_ids notes source_refs module_flow_attachment_ids")],
    "SF-TD5": [("database_tables", "id name description columns notes status source_refs")],
    "SF-CD1": [("test_cases", "id name scenario data expected actual result execution_date executor evidence_ids requirement_ids notes field_states status source_refs"), ("defects", "id name test_case_id description cause detected_date resolution resolution_status resolved_date evidence_ids verification_evidence_ids notes field_states status source_refs")],
    "SF-TI1": [("test_cases", "id name scenario data expected actual result execution_date executor evidence_ids requirement_ids notes field_states status source_refs"), ("defects", "id name test_case_id description cause detected_date resolution resolution_status resolved_date evidence_ids verification_evidence_ids notes field_states status source_refs")],
    "SF-TI2": [("deployment_items", "id name planned_specification planned_quantity unit scheduled_date actual_specification installed_quantity installation_date installation_status verification_method verification_result evidence_ids migration_counts source_refs")],
    "SF-TI3": [("project/manual_sections", "name audience content version online_url notes status source_refs attachment_ids"), ("screens", "id name path description steps checks before_attachment_ids after_attachment_ids standard_attachment_ids source_refs"), ("project/systems", "id name status lifecycle configuration as_is_description to_be_description network_method as_is_diagram_ids to_be_diagram_ids source_refs")],
    "SF-TI4": [("test_cases", "id name scenario data expected actual result execution_date executor evidence_ids requirement_ids notes field_states status source_refs"), ("defects", "id name test_case_id description cause detected_date resolution resolution_status resolved_date evidence_ids verification_evidence_ids notes field_states status source_refs")],
    "SF-OS1": [("project/support_activities", "id name category plan period_start period_end actual_result evidence_ids source_refs"), ("project/staff_members", "name role organization_role")],
    "SF-OS2": [("operation_periods", "id name period_start period_end raw_records reported_totals aggregation_method aggregation_rules notes status source_refs"), ("kpis", "id name formula formula_kind numerator denominator actual unit baseline target status notes source_refs")],
    "SF-PM1": [("progress_reports", "report_kind period_start period_end report_date current_plan_percent current_actual_percent cumulative_plan_percent cumulative_actual_percent calculation_basis work_items risks notes status source_refs")],
    "SF-PM2": [("meetings", "id name date location agenda discussions decisions special_notes source_refs")],
    "SF-PM3": [("changes", "id name request_number request_date response_number response_date response_content description before after impact approval_status approval_evidence_ids requester notes status source_refs")],
    "SF-PM4": [("requirements", "id name description kind change_type original_id original_classification fulfillment_status deliverable_ids review_ids notes status source_refs")],
}


def _meaning_supplement(doc, role, data, ctx):
    """Route unhandled supplied fields and record real XML owners for review."""
    if not ctx.get("editorial"):
        return
    from .narrative import LABELS
    last_table = _all_tables(doc)[-1]
    root = _paragraph(last_table).getparent()
    prototype = _appendix_prototype(doc, last_table)
    section = next(name for name in doc.sections if doc.xml(name) is root)
    title = None
    supplement_count = 0
    records = []
    stage = {"SF-CD1": "unit", "SF-TI1": "integration", "SF-TI4": "acceptance"}.get(role)
    selected_cases = {case["id"] for case in data["test_cases"] if case.get("stage") == stage}
    for pointer, composed_fields in _MEANING_SPECS[role]:
        collection = data
        for component in pointer.split("/"):
            collection = collection.get(component, []) if isinstance(collection, dict) else []
        for index, item in enumerate(collection):
            if pointer == "test_cases" and stage and item.get("stage") != stage:
                continue
            if pointer == "defects" and stage and item.get("test_case_id") not in selected_cases:
                continue
            written = set(composed_fields.split())
            identity = item.get("id") or item.get("name") or item.get("role") or f"{pointer}/{index}"
            field_records = []
            # Dedicated historical-quotation owners are appended below. Empty
            # optional slots have a no-output contract, including supplements.
            from .quotations import FIELDS as quotation_fields
            dedicated = {quotation_fields.get(pointer)} - {None}
            extras = {key: value for key, value in item.items() if key not in written | dedicated}
            supplement_key = None
            if extras:
                supplement_count += 1
                supplement_key = f"B{supplement_count}"
                if title is None:
                    title = doc.new_paragraph("부록. 항목별 보완 명세", prototype=prototype)
                    doc.use_paragraph_keep(title, keep_with_next=True)
                    doc._editorial_heading_paragraphs.add(title)
                    root.append(title)
                    explanation = doc.new_paragraph("연결 입력 0개는 빈 목록을 뜻하며 실제 부재·미수행을 판정하지 않는다.", prototype=prototype)
                    doc.use_character_style(explanation, bold=False)
                    # Title -> finite note -> first item heading -> first field.
                    # The first field ends the chain; never bind the appendix.
                    doc.use_paragraph_keep(explanation, keep_lines=True, keep_with_next=True)
                    root.append(explanation)
                heading = doc.new_paragraph(f"보완 명세 — {identity} [{supplement_key}]", prototype=prototype)
                doc.use_paragraph_keep(heading, keep_with_next=True)
                doc._editorial_heading_paragraphs.add(heading)
                root.append(heading)
            for key, value in item.items():
                if key in dedicated:
                    continue
                input_pointer = "/" + pointer + f"/{index}/" + key.replace("~", "~0").replace("/", "~1")
                record = {"input_pointer": input_pointer, "input_value": value, "input_type": type(value).__name__, "content_review_status": "pending"}
                if key in written:
                    record.update(representation="role_main_specification", owner_basis="declared_role_writer; independent semantic review required")
                    if input_pointer in ctx.get("primary_field_owners", {}):
                        record["_primary_paragraphs"] = ctx["primary_field_owners"][input_pointer]
                else:
                    local_labels = {"organizer": "주최자 세부", "attendees": "참석자 명단"} if role == "SF-PM2" and pointer == "meetings" else {}
                    text = describe_fields({key: value}, typed=True, field_labels=local_labels) if key in local_labels else describe_fields({key: value}, typed=True)
                    fragments = []
                    for number, line in enumerate(text.split("\n")):
                        label = "" if number == 0 else local_labels.get(key, LABELS.get(key, key)) + " · "
                        shown = f"[{supplement_key}] {label}{line}"
                        paragraph = doc.new_paragraph(shown, prototype=prototype)
                        doc.use_character_style(paragraph, bold=False)
                        doc.use_paragraph_keep(paragraph, keep_lines=len(shown) <= NARRATIVE_KEEP_MAX_CHARS, keep_with_next=False)
                        root.append(paragraph)
                        fragments.append(paragraph)
                    record.update(representation="readable_supplement", label=local_labels.get(key, LABELS.get(key, key)),
                        rendered_text=own_text(fragments[0]), rendered_fragments=[own_text(p) for p in fragments],
                        supplement_key=supplement_key, _paragraph=fragments[0], _primary_paragraphs=fragments)
                field_records.append(record)
            records.append({"input_pointer": "/" + pointer + f"/{index}", "entity_id": item.get("id"), "entity_name": item.get("name"), "supplement_key": supplement_key, "fields": field_records})
    ctx["meaning_map"] = records + ctx.pop("organization_chart_meaning", [])


def _append_project_context(doc, data, ctx):
    """Keep printed business identity attached to its supplied source locators."""
    if not ctx.get("editorial"):
        return
    table = _all_tables(doc)[-1]
    root = _paragraph(table).getparent()
    prototype = _appendix_prototype(doc, table)
    project = data["project"]
    fields = []

    def append(value, *, heading=False):
        paragraph = doc.new_paragraph(value, prototype=prototype)
        doc.use_character_style(paragraph, bold=heading)
        doc.use_paragraph_style(paragraph, align="LEFT")
        doc.use_paragraph_keep(paragraph, keep_lines=len(value) <= NARRATIVE_KEEP_MAX_CHARS, keep_with_next=heading)
        if heading:
            doc._editorial_heading_paragraphs.add(paragraph)
        root.append(paragraph)
        return paragraph

    def bind(pointer, value, paragraph):
        fields.append({"input_pointer": pointer, "input_value": value, "input_type": type(value).__name__,
            "representation": "shared_project_context", "content_review_status": "pending",
            "rendered_text": own_text(paragraph), "_paragraph": paragraph, "_primary_paragraphs": [paragraph]})

    append("부록. 사업 식별·출처", heading=True)
    identity = append(f"[사업] 사업명: {readable_value(project.get('name'))}; 사업연도: {readable_value(project.get('program_year'))}; 지원사업명: {readable_value(project.get('program_name'))}")
    for key in ("name", "program_year", "program_name"):
        if key in project:
            bind("/project/" + key, project[key], identity)
    identifiers = append(f"[사업] 입력 과제 ID: {readable_value(project.get('id'))}; 입력 양식 버전: {readable_value(project.get('template_version'))}")
    for key in ("id", "template_version"):
        if key in project:
            bind("/project/" + key, project[key], identifiers)
    period = append(f"[사업] 사업기간(입력값): {readable_value(project.get('start_date'))} ~ {readable_value(project.get('end_date'))}; 실제 착수·완료 확인과 구분")
    for key in ("start_date", "end_date"):
        if key in project:
            bind("/project/" + key, project[key], period)
    for key, label in (("implementation_scope", "도입 범위"), ("notes", "사업 비고")):
        if key in project:
            paragraph = append(f"[사업] {label}: {readable_value(project[key])}")
            bind("/project/" + key, project[key], paragraph)
    provenance = append(f"[사업] 입력자료 확인 상태: {code_label(project.get('status'))}; 사업 출처: {_refs(project)}")
    for key in ("status", "source_refs"):
        if key in project:
            bind("/project/" + key, project[key], provenance)
    for kind, label in (("customer", "도입기업"), ("supplier", "공급기업")):
        party = project.get(kind)
        if not isinstance(party, dict):
            continue
        paragraph = append(f"[사업] {label}: {readable_value(party.get('name'))}; 입력자료 확인 상태: {code_label(party.get('status'))}; 기업명 출처: {_refs(party)}")
        for key in ("name", "status", "source_refs"):
            if key in party:
                bind(f"/project/{kind}/{key}", party[key], paragraph)
    if "synthetic_notice" in data:
        notice = getattr(doc, "_editorial_cover_paragraphs", {}).get("notice")
        if notice is None or own_text(notice) != data["synthetic_notice"]:
            notice = append("[사업] 제공 고지문 원문: " + readable_value(data["synthetic_notice"]))
        bind("/synthetic_notice", data["synthetic_notice"], notice)
    ctx.setdefault("meaning_map", []).append({"input_pointer": "/project", "entity_id": None,
        "entity_name": project.get("name"), "scope": "Printed business identity and provenance; no execution or approval inferred.", "fields": fields})


def _input_leaves(value, pointer):
    if isinstance(value, dict) and value:
        return [leaf for key, item in value.items() for leaf in _input_leaves(item, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))]
    if isinstance(value, list) and value:
        return [leaf for index, item in enumerate(value) for leaf in _input_leaves(item, pointer + f"/{index}")]
    return [{"input_pointer": pointer, "value": value, "type": type(value).__name__}]


def _finalize_meaning_map(doc, records):
    """Resolve owners after section moves; mappings remain review requirements."""
    for entity in records:
        identity = entity.get("entity_id") or entity.get("entity_name")
        entity["identity_anchors"] = [{"section": name, "xpath": doc.xml(name).getroottree().getpath(paragraph)}
            for name in doc.sections for paragraph in doc.xml(name).iter(f"{{{HP}}}p") if identity and str(identity) in own_text(paragraph)]
        for field in entity["fields"]:
            field["input_leaves"] = _input_leaves(field["input_value"], field["input_pointer"])
            paragraph = field.pop("_paragraph", None)
            if paragraph is not None:
                member = next(name for name in doc.sections if doc.xml(name) in paragraph.iterancestors())
                field["owner"] = {"section": member, "xpath": doc.xml(member).getroottree().getpath(paragraph)}
            paragraphs = field.pop("_primary_paragraphs", [])
            if paragraphs:
                field["owners"] = []
                field["owner_basis"] = "explicit_writer_owners; independent semantic review required"
                for paragraph in paragraphs:
                    member = next(name for name in doc.sections if doc.xml(name) in paragraph.iterancestors())
                    field["owners"].append({"section": member, "xpath": doc.xml(member).getroottree().getpath(paragraph), "rendered_text": own_text(paragraph)})
    return records


def _finalize_trace_bindings(doc, records):
    result = []
    for record in records:
        row = record["_row"]
        member = next(name for name in doc.sections if doc.xml(name) in row.iterancestors())
        tree = doc.xml(member).getroottree()
        cells = [{"column": index, "xpath": tree.getpath(cell), "owned_paragraphs": [own_text(p) for p in cell.findall("hp:subList/hp:p", NS)]}
                 for index, cell in enumerate(row.findall("hp:tc", NS))]
        result.append({**{key: value for key, value in record.items() if not key.startswith("_")}, "owner": {"section": member, "xpath": tree.getpath(row)}, "cells": cells})
    return result


def _finalize_source_note_records(doc, records, sources):
    result = []
    for record in records:
        item = {key: value for key, value in record.items() if not key.startswith("_")}
        paragraph = record.get("_paragraph")
        if paragraph is not None:
            member = next(name for name in doc.sections if doc.xml(name) in paragraph.iterancestors())
            item["owner"] = {"section": member, "xpath": doc.xml(member).getroottree().getpath(paragraph), "rendered_text": own_text(paragraph)}
        item["source"] = sources.get(record["source_ref"]["source_id"])
        result.append(item)
    return result


def _render_td3(doc, data, tables, ctx):
    initial_chapters = {}
    if ctx.get("editorial"):
        from .layout import register_td3_initial_chapters
        initial_profile = json.loads((Path(__file__).resolve().parents[2] / "resources/style-upgrade/profiles/SF-TD3.json").read_text())
        initial_chapters = register_td3_initial_chapters(doc, initial_profile)
    def fill(t, s, i):
        _set(doc, t, 0, 1, s["id"]); _set(doc, t, 0, 3, s["name"]); _set(doc, t, 1, 1, s.get("path"))
        if ctx.get("editorial"):
            levels = s.get("menu_levels")
            path = _text(s.get("path"))
            if isinstance(levels, list) and path == " > ".join(levels):
                metadata = f"경로·메뉴 단계({len(levels)}개): {path}"
            else:
                metadata = f"경로: {path}"
                if "menu_levels" in s:
                    metadata += "\n메뉴 단계: " + (" → ".join(levels) if levels else readable_value(levels))
            _set(doc, t, 1, 1, metadata + f" · 자료 상태: {code_label(s.get('status'))}")
        approval_note = "입력 항목과 검증 내용은 아래 참조; 캡처 이미지 미삽입. 승인 범위·상태는 연결 검토 기록과 근거 확인 필요."
        _set(doc, t, 2, 1, f"화면 구성 설계안(실행화면 아님)\n{s.get('description', UNKNOWN)}\n구분: {CHANGE.get(s.get('change_type'), UNKNOWN)}\n기존화면: 자료 미제공\n변경화면: {approval_note}")
        fields = []
        for field in s.get("fields", []):
            required = "필수" if field.get("required") is True else "선택" if field.get("required") is False else "필수 여부 미확인"
            default = "기본값 미확인(null)" if field.get("default_value") is None else "기본값=" + json.dumps(field["default_value"], ensure_ascii=False, sort_keys=True)
            fields.append(f"{field['name']} [{field.get('data_type') or '형식 미확인'} / {required} / {default}]: {_text(field.get('validation'))}")
        buttons = [f"{b['name']}: {b.get('action') or UNKNOWN}" for b in s.get("buttons", [])]
        _set(doc, t, 3, 1, "처리 순서\n" + _text(s.get("steps")) + "\n필드\n" + "\n".join(fields) + "\n버튼\n" + "\n".join(buttons))
        linked = [r for r in data["requirements"] if r["id"] in s.get("requirement_ids", [])]
        rules = "\n".join(f"{r['id']} {r['name']}\n세부 검증:\n{_text(r.get('details'))}\n제약/전제:\n{_text(r.get('constraints'))}" for r in linked)
        _set(doc, t, 4, 1, _text(s.get("checks")) + f"\n구체 검증 기준(요구사항 원문 입력):\n{rules}\n기능 연결: {_join(s.get('feature_ids', []))}\n프로그램: {_join(s.get('program_ids', []))}\n화면 비고: {_text(s.get('notes'))}\n권한 입력: " + "; ".join(f"{p['role']}={p['permission']}" for p in s.get("permissions", [])) + f"\n도입기업 검토:\n{_review_summary(data, s.get('review_ids', []))}\n근거: {_refs(s)}")
        for row in (3, 4):
            _td3_plain_paragraphs(doc, doc.cell(t, row, 1).find("hp:subList/hp:p", NS),
                                  linked_titles={f"{r['id']} {r['name']}" for r in linked})
        if ctx.get("editorial"):
            field_blocks = []
            for index, field in enumerate(s.get("fields", []), 1):
                required = "필수" if field.get("required") is True else "선택" if field.get("required") is False else "필수 여부 미확인(null)"
                field_blocks.extend([f"필드 {index}. {field['name']} — 형식: {readable_value(field.get('data_type'))}; 입력 구분: {required}; 기본값: {typed_value(field.get('default_value'))}",
                    "검증: " + readable_value(field.get("validation")) + "; 출처: " + _refs(field)])
                extras = {key: value for key, value in field.items() if key not in {"name", "data_type", "required", "default_value", "validation", "source_refs"}}
                if extras:
                    field_blocks.append(describe_fields(extras))
            button_blocks = []
            for index, button in enumerate(s.get("buttons", []), 1):
                button_blocks.append(f"버튼 {index}. {button['name']} — {readable_value(button.get('action'))}; 출처: {_refs(button)}")
                extra = {key: value for key, value in button.items() if key not in {"name", "action", "source_refs"}}
                if extra:
                    button_blocks.append(describe_fields(extra))
            _set(doc, t, 3, 1, "처리 순서:\n" + _text(s.get("steps")) + "\n필드 명세:\n" + "\n".join(field_blocks) + "\n버튼 명세:\n" + "\n".join(button_blocks))
            linked_text = "; ".join(f"{r['id']} [R{data['requirements'].index(r) + 1}]" for r in linked) or "미연결"
            checks = _text(s.get("checks")) + f"\n연결 검증 기준: {linked_text}\n기능 연결: {_join(s.get('feature_ids', []))}; 프로그램: {_join(s.get('program_ids', []))}\n화면 비고: {readable_value(s.get('notes'))}\n권한 명세:\n"
            checks += "\n".join(f"{readable_value(permission.get('role'))}: {code_label(permission.get('permission'))}; 출처: {_refs(permission)}" + ("\n" + describe_fields({key: value for key, value in permission.items() if key not in {'role', 'permission', 'source_refs'}}) if any(key not in {'role', 'permission', 'source_refs'} for key in permission) else "") for permission in s.get("permissions", []))
            checks += f"\n도입기업 검토:\n{_review_summary(data, s.get('review_ids', []))}\n근거: {_refs(s)}"
            extras = {key: s[key] for key in ("field_states",) if key in s}
            if extras:
                checks += "\n" + describe_fields(extras)
            _set(doc, t, 4, 1, checks)
            for row in (3, 4):
                _td3_plain_paragraphs(doc, doc.cell(t, row, 1).find("hp:subList/hp:p", NS), linked_titles={f"{r['id']} {r['name']}" for r in linked})
            _set(doc, t, 2, 1, f"화면 구성: {readable_value(s.get('description'))}\n구분: {CHANGE.get(s.get('change_type'), UNKNOWN)} · 화면 그림 자료 미제공")
        _td3_images(doc, data, s, t, ctx)
    cards = _repeat_cards(doc, tables[-1], data["screens"], fill)
    for card in cards:
        # Hancom's inline-table mode disables multipage continuation. Keep the
        # existing floating position/flow geometry and allow cell text to split.
        doc.use_table_pagination(card, break_mode="CELL", inline=False)
        doc.repeat_header_rows(card, count=1)
    first_card = _paragraph(cards[0])
    intro = first_card.getprevious()
    blocks = [_notice(data), f"과제: {data['project']['name']}", "협의·수행·승인·서명 사실과 근거는 별도 확인이 필요하다."]
    if intro is None or own_text(intro) != "\n".join(blocks):
        raise ValueError("TD3 expected its explicit body notice immediately before the first card")
    if ctx.get("editorial"):
        blocks = [f"과제: {data['project']['name']}"]
        doc.set_paragraph_text(intro, blocks[0])
    _td3_plain_paragraphs(doc, intro, intro_blocks=blocks)
    last_card = _paragraph(cards[-1])
    def chapter(paragraph, title, body, *, initial_key=None):
        if not ctx.get("editorial"):
            doc.set_paragraph_text(paragraph, "\n".join([title, *body]))
            return
        doc.set_paragraph_text(paragraph, title)
        doc._editorial_heading_paragraphs.add(paragraph)
        doc.use_paragraph_keep(paragraph, keep_with_next=True)
        record = initial_chapters.get(initial_key)
        if initial_key is not None:
            if record is None or record["heading"] is not paragraph:
                raise ComposeError("TD3 initial chapter renderer/source owner mismatch")
            record.update(expected_heading_text=title, expected_body_texts=list(body), body=[])
        previous = paragraph
        for text in body:
            child = doc.new_paragraph(text, prototype=paragraph)
            doc.use_character_style(child, bold=False)
            doc.use_paragraph_keep(child, keep_lines=len(text) <= NARRATIVE_KEEP_MAX_CHARS, keep_with_next=False)
            doc._editorial_body_paragraphs.add(child)
            if record is not None:
                record["body"].append(child)
            previous.addnext(child)
            previous = child

    for p in list(doc.root().iter(f"{{{HP}}}p")):
        text = _own_text(p).strip()
        if text == "1. 화면 표준":
            approval = "메인/로그인/팝업 시안과 공통 표준의 실제 승인 범위·상태는 제공된 검토 기록과 근거로 확인해야 한다."
            chapter(p, "1. 화면 표준(검토안)", ["필수 항목·검증 메시지·저장 상태를 구분한다. " + approval, "R: 연결 요구사항 상세 · A: 첨부 그림 · S: 출처 대응표"], initial_key="standards" if ctx.get("editorial") else None)
        elif text == "2. 메뉴구조도":
            chapter(p, "2. 메뉴구조도(권한 설계안)", [f"{s['path']} → {s['id']}" for s in data["screens"]] + ["관리자 메뉴·실제 계정과 역할 승인은 미확인."], initial_key="menu" if ctx.get("editorial") else None)
        elif text == "3. 화면(보고서) 설계":
            doc._editorial_heading_paragraphs.add(p)
            p.set("pageBreak", "1")
            doc.use_paragraph_keep(p, keep_lines=True, keep_with_next=True)
        elif text.startswith("4. 화면 검토 결과("):
            chapter(p, "4. 화면 검토 결과", ["화면별 검토 연결 ID는 주요 체크 사항에 기재한다. 실제 승인자·승인일·검토 범위·첨부 근거의 확인이 필요하다."])
            p.set("pageBreak", "1")
            last_card.addnext(p)
    if ctx.get("editorial"):
        if (len(initial_chapters["standards"]["body"]) != 2
                or len(initial_chapters["menu"]["body"]) != len(data["screens"]) + 1):
            raise ComposeError("TD3 initial chapter generated prose count mismatch")
        root = last_card.getparent()
        prototype = doc.cell(cards[-1], 4, 1).find("hp:subList/hp:p", NS)
        connected = {rid for screen in data["screens"] for rid in screen.get("requirement_ids", [])}
        if connected:
            heading = doc.new_paragraph("부록. 화면 연결 요구사항", prototype=prototype)
            doc._editorial_heading_paragraphs.add(heading)
            doc.use_paragraph_keep(heading, keep_with_next=True)
            root.append(heading)
            for index, requirement in enumerate(data["requirements"], 1):
                if requirement["id"] not in connected:
                    continue
                ctx.setdefault("additional_review_bindings", []).append((requirement["id"], requirement.get("review_ids", [])))
                title = doc.new_paragraph(f"[R{index}] {requirement['id']} {requirement['name']}", prototype=prototype)
                doc._editorial_heading_paragraphs.add(title)
                doc.use_paragraph_keep(title, keep_with_next=True)
                root.append(title)
                screens = ", ".join(screen["id"] for screen in data["screens"] if requirement["id"] in screen.get("requirement_ids", []))
                _append_context_fields(doc, root, prototype, f"[R{index}]", {"연결 화면": screens, **{key: value for key, value in requirement.items() if key not in {"id", "name"}}})
    ctx["warnings"].append("TD3 긴 카드는 CELL 분할·floating 앵커 유지; 짧은 셀 문단만 keepLines, 콜론 label/연결 요구 제목만 keepWithNext. 3절 제목·고지3문단의 짧은 intro 연결 및 모든 카드 뒤 4절 배치는 현재 바이트 native 검토 필요")
    ctx["warnings"].append("TD3 필드/버튼/권한의 개별 source_refs와 제공 메타데이터는 화면 명세에 보존" if ctx.get("editorial") else "TD3 출처 표시는 화면 상위 source_refs에 한정; 필드/버튼/권한의 개별 source_refs는 원입력 JSON에서 별도 확인 필요")
    # Literal instruction of this fingerprinted v2.0 template, not a universal
    # project-ID policy. Report the discrepancy without changing supplied IDs.
    differing_ids = [s["id"] for s in data["screens"] if not re.fullmatch(r"[^\s-]{3}-[^\s-]{3}-[0-9]{3}", s["id"])]
    if differing_ids:
        ctx["warnings"].append("TD3 v2.0 원본 작성 지침(시스템명 3자리 + 문서명 3자리 + 일련번호 3자리)과 제공 화면 ID 형식이 다름: "
                               + ", ".join(differing_ids) + "; 제공 ID를 보존하며 실제 사업의 명명 규칙은 추가 확인 필요")


def _render_td4(doc, data, tables, ctx):
    def fill(t, p, i):
        _set(doc, t, 0, 1, p["id"]); _set(doc, t, 0, 3, p["name"])
        _set(doc, t, 1, 1, f"{_text(p.get('description'))}\n{CHANGE.get(p.get('change_type'), UNKNOWN)}; 구현·실행 사실은 출처와 증거로 별도 확인\n입출력: {_text(p.get('interfaces'))}\n출력 항목: {_join(p.get('output_fields', []))}")
        flow_note = ("모듈 흐름도 연결 입력: " + _case_literal(p["module_flow_attachment_ids"]) + "; 실제 도식의 부재·구현 사실은 별도 확인" if "module_flow_attachment_ids" in p else "모듈 흐름도 연결 입력 키 미제공; 실제 도식 부재로 판정하지 않음") if ctx.get("editorial") else "독립 모듈 흐름도 이미지는 제공되지 않았다."
        _set(doc, t, 2, 1, "기능 명세 항목(목록 배치는 실행 순서를 뜻하지 않음)\n" + readable_value(p.get("functions")) + f"\n화면: {_join(p.get('screen_ids', []))}\n테이블: {_join(p.get('table_ids', []))}\n{flow_note}")
        conditions = ""
        if ctx.get("editorial"):
            conditions = "\n" + "\n".join(describe_fields({key: p[key]}) for key in ("query_conditions", "registration_conditions", "calculation_rules") if key in p)
        _set(doc, t, 3, 1, _text(p.get("functions")) + conditions + f"\n요구사항: {_join(p.get('requirement_ids', []))}\n{_text(p.get('notes'))}\n근거: {_refs(p)}")
        _set(doc, t, 4, 1, _join(p.get("table_ids", [])))
    cards = _repeat_cards(doc, tables[-1], data["programs"], fill)
    if ctx.get("editorial"):
        first = cards[0]
        anchor = _paragraph(first)
        notice = anchor.getprevious()
        if notice is None or not own_text(notice).startswith((NOTICE, "검토용 초안")):
            raise ValueError("Program card notice boundary differs from its declared source")
        # Keep the source body PAGE=1/table anchor intact. Only the generated
        # notice joins the first program's description instead of owning a page.
        container = doc.cell(first, 1, 1).find("hp:subList", NS)
        container.insert(0, notice)
        doc.use_character_style(notice, bold=False)
        doc.use_paragraph_style(notice, align="LEFT")
        doc.use_paragraph_keep(notice, keep_lines=True, keep_with_next=True)
        columns = {"id": (0, 1), "name": (0, 3), "description": (1, 1), "change_type": (1, 1),
            "interfaces": (1, 1), "output_fields": (1, 1), "screen_ids": (2, 1), "module_flow_attachment_ids": (2, 1),
            "functions": (3, 1), "query_conditions": (3, 1), "registration_conditions": (3, 1),
            "calculation_rules": (3, 1), "requirement_ids": (3, 1), "notes": (3, 1),
            "source_refs": (3, 1), "table_ids": (4, 1)}
        for index, (program, card) in enumerate(zip(data["programs"], cards)):
            for field, (row, column) in columns.items():
                if field in program:
                    ctx.setdefault("primary_field_owners", {})[f"/programs/{index}/{field}"] = list(doc.cell(card, row, column).findall("hp:subList/hp:p", NS))


def _datatype(column):
    result = _text(column.get("type"))
    if column.get("length") is not None:
        result += f"({column['length']})"
    elif column.get("precision") is not None:
        scale = "미확인" if column.get("scale") is None else column["scale"]
        result += f"({column['precision']},{scale})"
    return result


def _render_td5(doc, data, tables, ctx):
    details = []
    keys = {}
    for item in data["database_tables"]:
        for column in item.get("columns", []):
            key = f"C{len(details) + 1}"
            keys[(item["id"], column["id"])] = key
            details.append((key, item, column))
    def table_rows(item):
        rows = []
        for c in item.get("columns", []):
            key = c.get("key")
            unknown_key = "?" if ctx.get("editorial") else "미확인"
            null_label = "미확인" if c.get("nullable") is None else ("허용" if c["nullable"] else "불가") if ctx.get("editorial") else "NULL" if c["nullable"] else "NOT NULL"
            rows.append([item["name"], item["id"], c["name"], c["id"], _datatype(c), unknown_key if key is None else "Y" if key in ("primary", "primary_foreign") else "N", unknown_key if key is None else "Y" if key in ("foreign", "primary_foreign") else "N", null_label, keys[(item['id'], c['id'])]])
        return rows
    if ctx.get("editorial"):
        # One continuing grid prevents two independently floating cards from
        # sharing the continuation page when a preceding table grows in native.
        _row_table(doc, tables[-1], [row for item in data["database_tables"] for row in table_rows(item)])
        _set(doc, tables[-1], 0, 8, "비고\nPK/FK ?: 미확인")
        doc.use_table_pagination(tables[-1], break_mode="TABLE", inline=False)
        cards = [tables[-1]]
        ctx["warnings"].append("TD5 reference-v1은 테이블명·ID를 각 행에 유지한 단일 연속 표와 TABLE 행 단위 분할을 사용한다. PK/FK의 ?는 원입력 미확인이며 정확한 key/null 원값은 Cn 상세에 보존한다. 페이지보다 긴 행은 별도 native 경계 검토가 필요하다.")
    else:
        cards = _repeat_cards(doc, tables[-1], data["database_tables"], lambda table, item, index: _row_table(doc, table, table_rows(item)))
    anchor = _paragraph(cards[-1])
    plain = next((p for p in doc.root() if _small_plain_paragraph(doc, p)), None)
    if plain is None:
        raise ValueError("No original body-size paragraph style for TD5 column evidence")
    previous = anchor
    column_detail_key = None
    def append(value, *, heading=False):
        nonlocal previous
        if ctx.get("editorial") and column_detail_key and not heading:
            value = f"[{column_detail_key}] {value}"
        p = doc.new_paragraph(value, prototype=plain)
        if heading:
            doc._editorial_heading_paragraphs.add(p)
        doc.use_paragraph_keep(p,
            keep_lines=True if value.strip() and len(value) <= NARRATIVE_KEEP_MAX_CHARS else None,
            keep_with_next=True if heading or not ctx.get("editorial") and re.match(r"^\[(?:T|C)\d+\] ", value) or value in {"2. 테이블별 설명·제약·근거", "3. 컬럼별 제약·암호화·기본값·근거"} or ctx.get("editorial") and value.startswith(("앞 목록의 테이블ID", "표의 비고 Cn")) else None)
        previous.addnext(p)
        previous = p
        return p
    def keep_short_entry(paragraphs):
        values = [own_text(p) for p in paragraphs]
        if len(values) <= 6 and all(len(value) <= NARRATIVE_KEEP_MAX_CHARS for value in values) and sum(map(len, values)) <= 720:
            for i, p in enumerate(paragraphs):
                doc.use_paragraph_keep(p, keep_with_next=i < len(paragraphs) - 1)
    if ctx.get("editorial"):
        append("PK/FK 범례: Y=해당 키 구분에 포함; N=해당 키 구분 아님; ?=원입력 미확인. 각 Cn에 정확한 원값과 타입을 보존한다.")
    append(f"{_notice(data)}\n과제: {data['project']['name']}\n협의·수행·승인·서명 사실과 근거는 별도 확인이 필요하다.\n전체 테이블: " + _join(t["id"] for t in data["database_tables"]) + "\n부속: " + ctx.get("companion_label", "실제 물리DB Excel 미제공") + "\n설계 입력이며 실제 물리DB 구현·추출 검증과 구분한다. 실제 물리DB 추출·구축 결과로 승인할 수 없다.")
    append("2. 테이블별 설명·제약·근거", heading=True)
    append("앞 목록의 테이블ID·테이블명은 아래 [Tn]의 같은 ID·이름과 대응한다. 설명·제약/비고·전체 출처는 이 전폭 본문에 보존한다.")
    for i, item in enumerate(data["database_tables"], 1):
        heading = append(f"[T{i}] {item['id']} — {item['name']} (확인상태: {code_label(item['status'])})", heading=True)
        description = append("설계 설명: " + _text(item.get("description")))
        entry = [heading, description]
        if ctx.get("editorial"):
            for column in item["columns"]:
                if (column.get("key") in {"foreign", "primary_foreign"}
                        or column.get("foreign_table_id") is not None or column.get("foreign_column_ids")):
                    target_table = readable_value(column.get("foreign_table_id"))
                    target_columns = _join(column.get("foreign_column_ids", []), "참조 컬럼 미확인(빈 목록)")
                    entry.append(append(f"제공 참조 설계: {item['id']}.{column['id']} → {target_table} / {target_columns}. 입력한 연결 대상이며 실제 DB 구현은 미확인이다. 상세 [{keys[(item['id'], column['id'])]}]."))
        notes = append(("제공 제약·비고 원문: " if ctx.get("editorial") else "테이블 제약/비고: ") + _text(item.get("notes")))
        sources = append("출처: " + _refs(item))
        entry += [notes, sources]
        if ctx.get("editorial"):
            primary = ctx.setdefault("primary_field_owners", {})
            for field in ("id", "name", "status"):
                primary[f"/database_tables/{i - 1}/{field}"] = [heading]
            primary[f"/database_tables/{i - 1}/description"] = [description]
            primary[f"/database_tables/{i - 1}/notes"] = [notes]
            primary[f"/database_tables/{i - 1}/source_refs"] = [sources]
        keep_short_entry(entry)
    append("3. 컬럼별 제약·암호화·기본값·근거", heading=True)
    append("표의 비고 Cn은 아래 [Cn]의 컬럼 명세와 대응한다(예: C10 → [C10]). 기본값의 값과 자료형을 함께 표시한다. 미확인은 기본값 없음·암호화 미적용을 뜻하지 않으며, 필드별 확인 상태와 출처 대응표를 함께 확인한다." if ctx.get("editorial") else "표의 비고 Cn은 아래 [Cn]의 전체 컬럼 입력과 대응한다(예: C10 → [C10]). null은 자료 미제공/미확인 값이며 기본값 없음과의 구분은 field_states를 확인한다. false와 0은 null로 바꾸지 않는다. 암호화 적용·알고리즘의 null을 미적용으로 판단하지 않는다.")
    literal = typed_value if ctx.get("editorial") else lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)
    for key, item, column in details:
        column_detail_key = key
        definition = f"타입: {_datatype(column)}; length={literal(column.get('length'))}, precision={literal(column.get('precision'))}, scale={literal(column.get('scale'))}; KEY={literal(column.get('key'))}; nullable={literal(column.get('nullable'))}; 기본값={literal(column.get('default_value'))}"
        if ctx.get("editorial"):
            key_label = {"primary": "기본키(primary)", "foreign": "외래키(foreign)", "primary_foreign": "기본·외래키(primary_foreign)", "none": "키 아님(none)"}.get(column.get("key"), readable_value(column.get("key")))
            definition = f"물리 형식: {_datatype(column)}; 길이: {readable_value(column.get('length'))}; 정밀도: {readable_value(column.get('precision'))}; 소수 자릿수: {readable_value(column.get('scale'))}; 키 구분: {key_label}; NULL 허용: {readable_value(column.get('nullable'))}; 기본값: {typed_value(column.get('default_value'))}"
        entry = [append(f"[{key}] {item['id']}.{column['id']} — {column['name']} (확인상태: {code_label(column['status'])})", heading=True),
                 append(definition)]
        enc = column.get("encryption")
        if isinstance(enc, dict):
            entry.append(append(f"암호화 적용: {readable_value(enc.get('applied'))}; 알고리즘: {readable_value(enc.get('algorithm'))}; 정책 비고: {readable_value(enc.get('notes'))}; 컬럼 비고: {readable_value(column.get('notes'))}" if ctx.get("editorial") else f"암호화 적용={literal(enc.get('applied'))}; 알고리즘={literal(enc.get('algorithm'))}; 정책 비고={literal(enc.get('notes'))}; 컬럼 비고={literal(column.get('notes'))}"))
            entry.append(append(f"출처: {_refs(column)}; 암호화 출처: {_refs(enc)}"))
        else:
            entry.append(append(f"암호화 입력={literal(enc)}; 컬럼 비고={literal(column.get('notes'))}; 출처: {_refs(column)}"))
        if column.get("foreign_table_id") is not None or column.get("foreign_column_ids") or ctx.get("editorial") and any(field in column for field in ("foreign_table_id", "foreign_column_ids")):
            entry.append(append(f"FK 참조: {literal(column.get('foreign_table_id'))}; 참조 컬럼: {literal(column.get('foreign_column_ids', []))}"))
        if "field_states" in column:
            entry.append(append("필드별 확인 상태: " + (describe_fields(column["field_states"]) if ctx.get("editorial") else literal(column["field_states"]))))
        if column.get("expected_id") is not None or column.get("expected_name") is not None or column.get("definition_source_refs") or ctx.get("editorial") and any(field in column for field in ("expected_id", "expected_name", "definition_source_refs")):
            entry.append(append(f"기준 ID={literal(column.get('expected_id'))}; 기준명={literal(column.get('expected_name'))}; 기준 출처: " + _refs({"source_refs": column.get("definition_source_refs", [])})))
        if ctx.get("editorial"):
            original = {field: column[field] for field in ("original_id", "original_classification") if field in column}
            if original:
                entry.append(append(describe_fields(original, typed=True)))
        keep_short_entry(entry)
    column_detail_key = None
    ctx["warnings"].append("현재 DB 입력과 일치 확인된 부속 Excel 미제공; 별도 재생성이 필요하다." if "미제공" in ctx.get("companion_label", "미제공") else "DB 정의는 설계 입력이다. 합성 부속 Excel은 실제 구현된 물리DB export가 아니다.")
    ctx["warnings"].append("TD5의 좁은 비고는 괄호 없는 Cn 참조키만 사용; [Cn] 컬럼별 NULL/KEY/암호화/기본값/notes/출처는 표 뒤 전폭 상세에 보존")


def _case_literal(value):
    return typed_value(value) if editorial_context_active() else _text(value)


def _test_result(case):
    if case.get("result") in ("planned", "not_run"):
        actual = ("미확인(null)" if editorial_context_active() else "미확인") if case.get("actual") is None else "입력 actual과 미수행 판정의 정합 검토 필요: " + _case_literal(case["actual"])
        state = f"실행 상태: {code_label(case['result'])}" if editorial_context_active() else f"미수행 ({case['result']})"
        result = f"{state}\n실제 결과: {actual}\n실행일 입력: {_text(case.get('execution_date'))}\n수행자 입력: {_person(case.get('executor'))}\n증거 연결: {_join(case.get('evidence_ids', []), '미제공')}\n서명 이미지를 생성하지 않음"
    else:
        result = f"입력 판정: {code_label(case.get('result'))}\n실제 결과: {_case_literal(case.get('actual'))}\n실행일: {_text(case.get('execution_date'))}\n수행자: {_person(case.get('executor'))}\n증거: {_join(case.get('evidence_ids', []))}"
    if editorial_context_active():
        code_label(case.get("result"))  # Record the exact state/code correspondence.
        result += f"\n자료 상태: {code_label(case.get('status'))}; 출처: {_refs(case)}"
        for field in ("notes", "field_states", "executor"):
            if field in case:
                result += "\n" + describe_fields({field: case[field]})
    return result


def _testing_detail_paragraphs(doc, after, prototype, key, identity, text):
    """Keep one testing record's full prose at page width with a visible key."""
    heading = doc.new_paragraph(f"[{key}] {identity}", prototype=prototype)
    doc._editorial_heading_paragraphs.add(heading)
    doc.use_paragraph_keep(heading, keep_lines=True, keep_with_next=True)
    after.addnext(heading)
    previous = heading
    paragraphs = [heading]
    for line in text.split("\n"):
        paragraph = doc.new_paragraph(f"[{key}] {line}", prototype=prototype)
        doc.use_character_style(paragraph, bold=False)
        doc.use_paragraph_style(paragraph, align="LEFT")
        doc.use_paragraph_keep(paragraph, keep_lines=len(line) <= NARRATIVE_KEEP_MAX_CHARS, keep_with_next=False)
        previous.addnext(paragraph)
        previous = paragraph
        paragraphs.append(paragraph)
    return previous, paragraphs


def _testing_defect_details(doc, table, data, stage, ctx):
    """Use bounded register rows and preserve every defect value in keyed details."""
    from lxml import etree as ET
    role = {"unit": "SF-CD1", "integration": "SF-TI1", "acceptance": "SF-TI4"}[stage]
    profile = json.loads((Path(__file__).resolve().parents[2] / "resources/style-upgrade/profiles" / f"{role}.json").read_text())
    source = profile.get("defect_grid_title_owner", {})
    title_owner = _paragraph(table)
    location = (source.get("xml"), source.get("xpath"))
    namespaces = {**NS, "hs": "http://www.hancom.co.kr/hwpml/2011/section"}
    if (source.get("source_sha256") != doc.source_sha256
            or profile["source_template"]["sha256"] != doc.source_sha256
            or location[0] not in doc.sections
            or doc._source_paragraph_locations.get(title_owner) != location
            or doc._source_paragraph_text.get(title_owner) != source.get("text_before_generation_verbatim")):
        raise ValueError("Testing defect title/table source owner fingerprint or identity mismatch")
    original = ET.fromstring(doc._entries[location[0]]).xpath(location[1], namespaces=namespaces)
    original_runs = original[0].findall("hp:run", NS) if len(original) == 1 else []
    original_table = original_runs[0].find("hp:tbl", NS) if len(original_runs) == 1 else None
    original_position = original_table.find("hp:pos", NS) if original_table is not None else None
    if (len(original) != 1 or own_text(original[0]) != source.get("text_before_generation_verbatim")
            or len(original_runs) != 1
            or [child.tag.rsplit("}", 1)[-1] for child in original_runs[0]] != ["tbl", "t"]
            or original_position is None or original_position.get("treatAsChar") != "0"
            or original_position.get("vertOffset") != source.get("table_vert_offset_hwp")
            or original_position.get("horzOffset") != source.get("table_horz_offset_hwp")
            or table.getparent().getparent() is not title_owner
            or table.get("colCnt") != str(source.get("table_column_count"))
            or own_text(title_owner) != source.get("text_before_generation_verbatim")):
        raise ValueError("Testing defect title/table source flow shape mismatch")
    ids = {case["id"] for case in data["test_cases"] if case.get("stage") == stage}
    defects = [(index, item) for index, item in enumerate(data["defects"]) if item.get("test_case_id") in ids]
    rows = []
    for number, (_, defect) in enumerate(defects, 1):
        key = f"D{number}"
        identity = defect["id"] if defect.get("detected_date") is not None else f"미확정 후보\n{defect['id']}"
        row = [identity, defect.get("test_case_id"), f"[{key}] 결함 내용·원인 상세 참조",
               _text(defect.get("detected_date"), "미확인"), f"{code_label(defect.get('resolution_status'))}\n[{key}] 조치·검증 상세 참조"]
        row += [f"[{key}] 담당자 상세", f"[{key}] 검증 상세 참조"] if stage == "acceptance" else [_text(defect.get("resolved_date"), "미확인")]
        rows.append(row)
    if not rows:
        cases = [case for case in data["test_cases"] if case.get("stage") == stage]
        label = "시험 자료 미제공" if not cases else "시험 미수행" if all(case.get("result") in ("planned", "not_run") for case in cases) else "결함 원장 미제공/확인 필요"
        rows = [[label, "해당 단계", "발생/등록 여부 미확인; 결함 없음으로 판정하지 않음", "미확인", "조치 자료 미제공"] + (["미지정", "검증 자료 미제공"] if stage == "acceptance" else ["미확인"])]
    _row_table(doc, table, rows)
    targets = profile["targets"]
    doc.set_table_layout(table, column_widths_hwp=targets["testing_defect_column_widths_hwp"],
        cell_margins_hwp=targets["cell_margin_hwp"])
    # Atomic rows prevent the observed one-word source continuation without an
    # ID. Arbitrarily long supplied IDs/people still need CELL + native review.
    bounded = all(all(len(str(value)) <= 240 and str(value).count("\n") <= 5 for value in row) for row in rows)
    # The exact source paragraph owns tbl before its title text in one run.
    # Its floating offset places the title above the grid; inline flow reverses
    # the physical order. Preserve that source owner, offset and row policy.
    doc.use_table_pagination(table, break_mode="TABLE" if bounded else "CELL", inline=False)
    if not bounded:
        ctx["warnings"].append("결함표에 긴 식별자/담당자 입력이 있어 CELL 분할을 유지함; 실제 계속행 소속과 전쪽 가독성 검토 필요")
    for row in table.findall("hp:tr", NS)[1:]:
        doc.use_character_style(row, bold=False)
        doc.use_paragraph_style(row, align="LEFT")
        for cell in row.findall("hp:tc", NS):
            column = int(cell.find("hp:cellAddr", NS).get("colAddr"))
            if column == 3 or stage != "acceptance" and column == 5:
                doc.use_paragraph_style(cell, break_latin="KEEP_WORD")
    previous = _paragraph(table)
    prototype = doc.cell(table, 1, 2).find("hp:subList/hp:p", NS)
    for number, (index, defect) in enumerate(defects, 1):
        key = f"D{number}"
        heading = f"{defect['id']} — {_text(defect.get('name'))}; 연결 시험: {_text(defect.get('test_case_id'))}"
        # Typed values include null/empty/false/0, notes, sources, verification
        # evidence and people. A short table key never substitutes for this text.
        previous, paragraphs = _testing_detail_paragraphs(doc, previous, prototype, key, heading,
            describe_fields(defect, typed=True, field_labels={
                "test_case_id": "연결 시험 ID", "cause": "발생 원인",
                "detected_date": "발견일자", "resolution": "조치 내용",
                "resolved_date": "조치 완료일자(입력)", "resolution_status": "조치 상태(입력)",
            }, code_fields={"resolution_status"}) + "\n서명·확인자 실명 자료의 진위는 별도 검토하며 입력만으로 조치 완료를 판정하지 않는다.")
        for field in defect:
            pointer = f"/defects/{index}/" + field.replace("~", "~0").replace("/", "~1")
            ctx.setdefault("primary_field_owners", {})[pointer] = paragraphs


def _testing_frame_flow(doc, table, ctx, *, notice_position="previous"):
    """Fix explicitly selected one-cell frames using their source notice boundary."""
    if not ctx.get("editorial"):
        return
    if table.get("rowCnt") != "1" or table.get("colCnt") != "1":
        raise ValueError("Declared narrative-frame flow requires its one-cell source shape")
    anchor = _paragraph(table)
    if notice_position not in {"previous", "next"}:
        raise ValueError("Frame notice selection must declare its source neighbor")
    notice = anchor.getprevious() if notice_position == "previous" else anchor.getnext()
    if notice is None or not own_text(notice).startswith((NOTICE, "검토용 초안")):
        raise ValueError("Testing/support frame notice boundary differs from the declared source")
    # Put the generated notice inside its owning frame before the first heading.
    # The original body's forced break and PAGE numbering anchor remain intact;
    # there is no separate generated notice page before that body anchor.
    container = doc.cell(table, 0, 0).find("hp:subList", NS)
    container.insert(0, notice)
    doc.use_paragraph_keep(notice, keep_lines=True, keep_with_next=True)
    doc.use_character_style(notice, bold=False)
    # These seven explicitly selected source frames contain unbounded prose.
    # Hancom12.30 did not continue oversized inline CELL frames in six native
    # cases. Floating CELL retains source flow without a length-based guess.
    doc.use_table_pagination(table, break_mode="CELL", inline=False)
    headings = doc._editorial_heading_paragraphs
    for paragraph in table.iter(f"{{{HP}}}p"):
        if paragraph in headings:
            continue
        value = own_text(paragraph)
        doc.use_character_style(paragraph, bold=False)
        doc.use_paragraph_style(paragraph, align="LEFT")
        doc.use_paragraph_keep(paragraph, keep_lines=bool(value.strip()) and len(value) <= NARRATIVE_KEEP_MAX_CHARS,
            keep_with_next=bool(value.strip()) and len(value) <= 48 and value.rstrip().endswith(":") )
        doc._editorial_body_paragraphs.add(paragraph)


def _defects(doc, table, data, stage, *, editorial=False, ctx=None):
    if editorial:
        _testing_defect_details(doc, table, data, stage, ctx)
        return
    cases = [t for t in data["test_cases"] if t.get("stage") == stage]
    ids = {t["id"] for t in cases}
    rows = []
    wide_details = []
    for defect in data["defects"]:
        if defect.get("test_case_id") not in ids: continue
        row = [f"미확정 후보\n{defect['id']}" if defect.get("detected_date") is None else defect["id"], defect.get("test_case_id"),
               _text(defect.get("description")) + "\n원인: " + _text(defect.get("cause")), _text(defect.get("detected_date"), "발생 미확인"),
               f"입력 조치상태: {_text(defect.get('resolution_status'))}\n조치: {_text(defect.get('resolution'), '조치 자료 미제공')}\n조치 증거: {_join(defect.get('evidence_ids', []), '미제공')}"]
        if editorial:
            row[2] += f"\n자료 상태: {code_label(defect.get('status'))}; 출처: {_refs(defect)}"
            for field in ("notes", "field_states"):
                if field in defect:
                    row[2] += "\n" + describe_fields({field: defect[field]})
        verified = f"입력 검증상태: {_text(defect.get('resolution_status'))}\n검증 증거: {_join(defect.get('verification_evidence_ids', []), '미제공')}\n확인자 실명 자료 미제공"
        if stage == "unit":
            key = f"D{len(wide_details) + 1}"
            row[4] += f"\n[{key}] 검증 상세 참조"
            # The source date column is only 3374 HWP units wide. Keep it a
            # date field; preserve its former verification prose at page width.
            row.append(_text(defect.get("resolved_date"), "미확인"))
            wide_details.append((key, defect, verified))
        elif stage == "acceptance":
            row += [_person(defect.get("owner")), verified]
        else:
            row.append(_text(defect.get("resolved_date"), "완료 미확인") + "\n" + verified)
        rows.append(row)
    if not rows:
        label = "시험 자료 미제공" if not cases else "시험 미수행" if all(c.get("result") in ("planned", "not_run") for c in cases) else "결함 원장 미제공/확인 필요"
        rows = [[label, "해당 단계", "발생/등록 여부 미확인; 결함 없음으로 판정하지 않음", "미확인", "조치 자료 미제공"] + (["미지정", "검증 자료 미제공"] if stage == "acceptance" else ["미확인"])]
    _row_table(doc, table, rows)
    if wide_details:
        prototype = doc.cell(table, 1, 4).find("hp:subList/hp:p", NS)
        previous = _paragraph(table)
        paragraphs = ["3. 결함별 검증 상태·근거 상세", "결함표의 조치 내역 [Dn]은 아래 동일 키에 대응한다. 완료일자 칸은 제공된 날짜 또는 미확인만 표시하며, 날짜만으로 조치·검증 완료를 판정하지 않는다."]
        for key, defect, verified in wide_details:
            paragraphs += [f"[{key}] {defect['id']} — {_text(defect.get('name'))}; 연결 시험: {_text(defect.get('test_case_id'))}; 입력 확인상태: {code_label(defect['status'])}",
                f"발생일: {_text(defect.get('detected_date'))}; 완료일: {_text(defect.get('resolved_date'))}; 조치 담당자: {_person(defect.get('owner'))}", verified,
                f"조치 증거: {_join(defect.get('evidence_ids', []), '미제공')}; 출처: {_refs(defect)}; 비고: {_text(defect.get('notes'))}"]
            if defect.get("field_states"):
                paragraphs.append("필드별 확인 상태: " + (describe_fields(defect["field_states"]) if editorial else json.dumps(defect["field_states"], ensure_ascii=False, sort_keys=True)))
        for value in paragraphs:
            p = doc.new_paragraph(value, prototype=prototype)
            previous.addnext(p)
            previous = p


def _render_cd1(doc, data, tables, ctx):
    cases = [t for t in data["test_cases"] if t.get("stage") == "unit"]
    editorial = ctx.get("editorial", False)
    rows = [[c["id"], c["name"], _text(c.get("scenario")) + f"\n요구: {_join(c.get('requirement_ids', []))}", _case_literal(c.get("data")), _case_literal(c.get("expected")),
             f"{code_label(c.get('result'))}\n[U{number}] 결과·근거 상세" if editorial else _test_result(c)] for number, c in enumerate(cases, 1)]
    _row_table(doc, tables[-2], rows)
    if editorial:
        doc.use_table_pagination(tables[-2], break_mode="CELL", inline=True)
        previous = _paragraph(tables[-2])
        prototype = doc.cell(tables[-2], 1, 5).find("hp:subList/hp:p", NS)
        for number, case in enumerate(cases, 1):
            previous, paragraphs = _testing_detail_paragraphs(doc, previous, prototype, f"U{number}",
                f"{case['id']} — {case['name']} 결과·근거", _test_result(case))
            index = next(index for index, item in enumerate(data["test_cases"]) if item is case)
            for field, column in {"id": 0, "name": 1, "scenario": 2, "requirement_ids": 2, "data": 3, "expected": 4}.items():
                if field in case:
                    ctx.setdefault("primary_field_owners", {})[f"/test_cases/{index}/{field}"] = list(doc.cell(tables[-2], number, column).findall("hp:subList/hp:p", NS))
            for field in ("actual", "result", "execution_date", "executor", "evidence_ids", "notes", "field_states", "status", "source_refs"):
                if field in case:
                    ctx.setdefault("primary_field_owners", {})[f"/test_cases/{index}/{field}"] = paragraphs
        for row in tables[-2].findall("hp:tr", NS)[1:]:
            doc.use_character_style(row, bold=False)
            doc.use_paragraph_style(row, align="LEFT")
        for number, _ in enumerate(cases, 1):
            for column in (3, 4):
                doc.use_paragraph_style(doc.cell(tables[-2], number, column), break_latin="KEEP_WORD")
    _defects(doc, tables[-1], data, "unit", editorial=editorial, ctx=ctx)


def _render_grouped_test(doc, data, tables, ctx, stage):
    cases = [t for t in data["test_cases"] if t.get("stage") == stage]
    groups = defaultdict(list)
    for case in cases: groups[case.get("group_id") or case["id"]].append(case)
    values = list(groups.items())
    card_flow = None
    group_ordinals = {}
    if ctx.get("editorial"):
        from .testing_roles import prepare_case_cards
        role = "SF-TI1" if stage == "integration" else "SF-TI4"
        card_flow = prepare_case_cards(doc, role, tables[-2])
        group_ordinals = {id(case): number for _, group_cases in values for number, case in enumerate(group_cases, 1)}
        values = [(gid, [case]) for gid, group_cases in values for case in group_cases]
    def fill(t, group, i):
        gid, cases = group
        integration = stage == "integration"
        process = next(iter(data["project"].get("business_processes", [])), {})
        if integration:
            _set(doc, t, 0, 1, _join(sorted({c.get("process_name") or ("공정명 미확인" if ctx.get("editorial") else process.get("name")) or "공정명 미확인" for c in cases})))
        identity = gid
        if card_flow:
            group_id = readable_value(cases[0]["group_id"]) if "group_id" in cases[0] else "입력 항목 미제공"
            identity = f"제공 그룹 ID: {group_id}\n케이스 ID: {cases[0]['id']}"
        _set(doc, t, 1 if integration else 0, 1, identity)
        _set(doc, t, 1 if integration else 0, 6, cases[0]["name"] if len(cases) == 1 else f"{len(cases)}개 케이스 계획")
        flow = " → ".join(process.get("target_steps", [])) or "업무 흐름 자료 미제공"
        flow_label = "프로젝트 참고 흐름(케이스 연계 별도 확인)" if ctx.get("editorial") else "목표 업무 흐름(설계안)"
        _set(doc, t, 2 if integration else 1, 1, f"{flow_label}\n{flow}\n실행환경: {_text(cases[0].get('environment'))}; 실제 수행·검수 상태는 각 케이스의 결과·담당자·증거 입력을 참조")
        rows = [[f"{c.get('case_number') or group_ordinals.get(id(c), n)}. {c['id']} {c['name']}\n{_text(c.get('scenario'))}\n연결 요구: {_join(c.get('requirement_ids', []))}", _case_literal(c.get("data")), _case_literal(c.get("expected")), _test_result(c)] for n, c in enumerate(cases, 1)]
        start = 4 if integration else 3
        _row_table(doc, t, rows, prototype=start, header=start, columns=[0, 2, 3, 5])
        if ctx.get("editorial"):
            doc.use_table_pagination(t, break_mode=card_flow["page_break"], inline=card_flow["inline"])
            for row in t.findall("hp:tr", NS)[start:]:
                doc.use_character_style(row, bold=False)
                doc.use_paragraph_style(row, align="LEFT")
            for offset in range(start, start + len(cases)):
                for column in (2, 3):
                    doc.use_paragraph_style(doc.cell(t, offset, column), break_latin="KEEP_WORD")
            for offset, case in enumerate(cases, start):
                index = next(index for index, item in enumerate(data["test_cases"]) if item is case)
                fields = {"id": 0, "name": 0, "scenario": 0, "requirement_ids": 0, "data": 2, "expected": 3,
                    **{field: 5 for field in ("actual", "result", "execution_date", "executor", "evidence_ids", "notes", "field_states", "status", "source_refs")}}
                for field, column in fields.items():
                    if field in case:
                        ctx.setdefault("primary_field_owners", {})[f"/test_cases/{index}/{field}"] = list(doc.cell(t, offset, column).findall("hp:subList/hp:p", NS))
    if values: _repeat_cards(doc, tables[-2], values, fill)
    else: _set(doc, tables[-2], 4 if stage == "integration" else 3, 0, "시험 계획 자료 미제공·실행 여부 미확인")
    _defects(doc, tables[-1], data, stage, editorial=ctx.get("editorial", False), ctx=ctx)


def _render_ti2(doc, data, tables, ctx):
    deployment = data["deployment_items"]
    def category(name):
        found = [d for d in deployment if d.get("category") == name]
        return [f"{d['id']} {d['name']}\n계획: {_text(d.get('planned_specification'))}\n수량: 계획 {_text(d.get('planned_quantity'))}{_text(d.get('unit'), '')}; 실제 {_text(d.get('installed_quantity'))}\n설치예정 {_text(d.get('scheduled_date'))}; 실제설치일 {_text(d.get('installation_date'))}\n입력 상태: {_text(d.get('installation_status'))}\n실제 사양: {_text(d.get('actual_specification'))}\n검증 계획: {_text(d.get('verification_method'))}\n검증 결과: {_text(d.get('verification_result'), _execution_missing(data))}\n증거: {_join(d.get('evidence_ids', []), '미제공')}\n{_refs(d)}" for d in found] or ["설치 대상 자료 미제공. 설치 대상 없음 또는 설치 완료로 판단하지 않는다."]
    def migration_row(item, row):
        text = f"적재 입력: {row['data_type']} 계획 {_text(row.get('planned_count'))}건 / 실제 {_text(row.get('actual_count'))}건 / 검증 {_text(row.get('validation_result'), _execution_missing(data))}"
        if ctx.get("editorial"):
            return f"{item['id']} · {text}; 근거: {_refs(row)}"
        return text
    initial = [d for d in deployment if d.get("category") == "initial_data"]
    sections = [
        ("1. 하드웨어 설치 결과", [_notice(data), "1) 설치 대상 / 2) 설치 내역 / 3) 검증 결과"] + category("hardware")),
        ("2. 소프트웨어 설치 및 전환 결과", ["1) 계획 대상 / 2) 실제 설치 / 3) 전환 / 4) 검증의 제공 입력을 구별한다. 실제 배포·라이선스·환경설정 증거 연결은 아래 식별자를 참조한다."] + category("software") + [f"프로그램 설계 목록 {len(data['programs'])}개: {_join(p['id'] for p in data['programs'])}\nDB 설계 목록 {len(data['database_tables'])}개: {_join(t['id'] for t in data['database_tables'])}\n위 수량은 설계 입력의 개수이며 실제 개발 본수/구축 테이블 수로 자동 동일시하지 않는다."]),
        ("3. 네트워크 설치 결과", ["1) 설치 대상 / 2) 설치 내역 / 3) 검증 결과"] + category("network")),
        ("4. 초기데이터 전환 결과", category("initial_data") + [migration_row(d, row) for d in initial for row in d.get("migration_counts", [])] + ["원시 전환 파일·정합성·충분성·담당자 확인은 연결된 실제 근거를 검토해야 한다. 빈 값을 완료로 바꾸지 않는다."]),
    ]
    _narrative(doc, tables[-1], sections)
    if ctx.get("editorial"):
        blocks = _narrative_owned_blocks(doc, tables[-1], sections)
        positions = {"hardware": (0, 2), "software": (1, 1), "network": (2, 1), "initial_data": (3, 0)}
        for index, item in enumerate(deployment):
            category_name = item.get("category")
            if category_name not in positions:
                continue  # An unsupported category never receives a guessed owner.
            section, offset = positions[category_name]
            siblings = [entry for entry in deployment if entry.get("category") == category_name]
            ordinal = next(i for i, entry in enumerate(siblings) if entry is item)
            owners = list(blocks[section][offset + ordinal])
            if category_name == "initial_data":
                start = len(initial) + sum(len(entry.get("migration_counts", [])) for entry in initial[:ordinal])
                owners += [p for block in blocks[3][start:start + len(item.get("migration_counts", []))] for p in block]
            for field in item:
                ctx.setdefault("primary_field_owners", {})[f"/deployment_items/{index}/{field}"] = owners
    _testing_frame_flow(doc, tables[-1], ctx)


def _render_ti3(doc, data, tables, ctx):
    project = data["project"]
    system_contexts = []
    for index, system in enumerate(project.get("systems", [])):
        if not ctx.get("editorial"):
            system_contexts.append({"text": _text(system.get("configuration")), "fields": {}})
            continue
        key = f"구성{index + 1}"
        value = lambda field: readable_value(system[field]) if field in system else "입력 항목 미제공"
        state = lambda field: code_label(system[field]) if field in system else "입력 항목 미제공"
        entries = [
            (("id", "name"), f"시스템: {value('id')} — {value('name')}"),
            (("status", "lifecycle"), f"입력 자료 상태: {state('status')}; 시스템 단계: {state('lifecycle')}"),
            (("configuration",), "제공 구성: " + value("configuration")),
            (("as_is_description",), "현행 설명: " + value("as_is_description")),
            (("to_be_description",), "목표 계획: " + value("to_be_description")),
            (("network_method",), "통신 방식 입력: " + value("network_method")),
            (("as_is_diagram_ids",), "현행 도식 연결: " + value("as_is_diagram_ids")),
            (("to_be_diagram_ids",), "목표 도식 연결: " + value("to_be_diagram_ids")),
            (("source_refs",), "출처: " + _refs(system)),
            ((), f"공통 구성도·캡션 확인: SF-TD2 아키텍처설계서의 동일 시스템 ID {value('id')} 참조. 위 제공 입력·도식 연결은 실제 설치·운영 검증과 구분한다."),
        ]
        lines, fields = [], {}
        for names, text in entries:
            start = len(lines)
            lines.extend(f"[{key}] {line}" for line in text.split("\n"))
            for field in names:
                if field in system:
                    fields[field] = list(range(start, len(lines)))
        system_contexts.append({"text": "\n".join(lines), "fields": fields})
    def manual_entry(manual):
        version = f"\n문서 버전: {_text(manual.get('version'))}" if ctx.get("editorial") else ""
        return f"{manual['name']}\n{_text(manual.get('content'))}{version}\n온라인 주소: {_text(manual.get('online_url'))}\n자료 상태: {code_label(manual.get('status'))}; 비고: {_text(manual.get('notes'))}; 출처: {_refs(manual)}"

    sections = [("1. 사용자 매뉴얼", [_notice(data), "제공된 절차를 검토하는 초안이다. 화면 캡처·실행 결과·온라인 주소의 실제 근거는 별도 확인한다."]),
        ("(1) 시스템 개요", [_text(project.get("business_profile")), "대상 범위: " + _text(project.get("implementation_scope"))]),
        ("(2) 시스템 구성도", [entry["text"] for entry in system_contexts]),
        ("(3) 메뉴 구조도", [f"{s['path']} → {s['id']} {s['name']}" for s in data["screens"]]),
        ("(4) 공통사항", ["계획상 필수 항목·수량 검증·권한 오류·저장 상태를 구분한다. 실제 오류 코드·메시지 문구·재시도 정책은 구현 후 검토해야 한다."]),
        ("(5) 사용자 화면 설명", [f"{s['id']} {s['name']}\n경로: {s['path']}\n구성: {s.get('description') or UNKNOWN}\n처리 순서(입력):\n{_text(s.get('steps'))}\n제약:\n{_text(s.get('checks'))}\n실제 화면과 수행 상태는 별도 확인.\n출처: {_refs(s)}" for s in data["screens"]] + [manual_entry(m) for m in project.get("manual_sections", []) if m.get("audience") == "user"]),
        ("2. 관리자(운영자) 매뉴얼", ["관리 절차는 확정 전 검토 항목이며 실제 운영 수행 이력을 뜻하지 않는다."]),
        ("(1) 상용소프트웨어 관리", ["상용SW 제품·버전·라이선스·설치/패치/종료 방법 자료 미제공. 공급사 문서 및 실제 계약 범위를 확인한 후 작성해야 한다."]),
        ("(2) 응용소프트웨어 관리", [f"{p['id']} {p['name']}: {_text(p.get('description'))}; 테이블 {_join(p.get('table_ids', []))}" for p in data["programs"]] + ["실제 배포 디렉터리·환경변수·기동/종료·업그레이드·롤백 명령은 미확인이다."]),
        ("(3) 사용자 및 프로그램 관리", [manual_entry(m) for m in project.get("manual_sections", []) if m.get("audience") == "administrator"] + ["계정 발급·변경·회수 승인자와 변경 이력의 실제 자료는 별도 확인한다."]),
        ("(4) 보안 관리", [f"{r['id']} {r['name']}\n{_text(r.get('details'))}\n{_text(r.get('constraints'))}" for r in data["requirements"] if r.get("kind") == "nonfunctional"]),
        ("(5) 장애 관리", ["실제 장애 유형·백업 주기·복구 목표·저장 위치·복구 검증 자료는 미확인이다. 장애 접수→영향 확인→담당 배정→조치/복구→재확인 순서를 검토할 수 있으나 승인된 운영 절차로 해석하지 않는다."]),
        ("(6) 비상 연락망", ["실제 담당자·연락처·호출 순서 미제공. 가상 이름·전화번호·지원 SLA를 실제 연락망으로 작성하지 않았다."]),
    ]
    unknown_audience = [m for m in project.get("manual_sections", []) if m.get("audience") not in {"user", "administrator"}]
    if unknown_audience:
        sections.append(("3. 대상 사용자 미확인 설명", ["대상 사용자 입력이 미확인이므로 사용자·관리자로 분류하지 않았다."] + [manual_entry(m) for m in unknown_audience]))
    _narrative(doc, tables[-1], sections)
    if ctx.get("editorial"):
        blocks = _narrative_owned_blocks(doc, tables[-1], sections)
        for index, entry in enumerate(system_contexts):
            for field, positions in entry["fields"].items():
                ctx.setdefault("primary_field_owners", {})[f"/project/systems/{index}/{field}"] = [blocks[2][index][position] for position in positions]
        for index, screen in enumerate(data["screens"]):
            if "description" in screen:
                ctx.setdefault("primary_field_owners", {})[f"/screens/{index}/description"] = blocks[5][index]
        for index, manual in enumerate(project.get("manual_sections", [])):
            audience = manual.get("audience")
            matching = [entry for entry in project.get("manual_sections", []) if entry.get("audience") == audience] if audience in {"user", "administrator"} else unknown_audience
            ordinal = next(i for i, entry in enumerate(matching) if entry is manual)
            section = 5 if audience == "user" else 9 if audience == "administrator" else len(sections) - 1
            offset = len(data["screens"]) if audience == "user" else 0 if audience == "administrator" else 1
            for field in manual:
                ctx.setdefault("primary_field_owners", {})[f"/project/manual_sections/{index}/{field}"] = blocks[section][offset + ordinal]
    _testing_frame_flow(doc, tables[-1], ctx)
    if ctx.get("editorial"):
        for index in range(len(system_contexts)):
            doc.use_paragraph_keep(blocks[2][index][0], keep_lines=True, keep_with_next=True)
        # The final paragraph of each exact screen/manual description owns its
        # pictures. Role image insertion later uses this registry, not text
        # prefix guessing or a single end-of-manual image collection.
        container = doc.cell(tables[-1], 0, 0).find("hp:subList", NS)
        paragraphs = list(container.findall("hp:p", NS))
        starts = {screen["id"]: f"{screen['id']} {screen['name']}" for screen in data["screens"]}
        starts.update({manual["id"]: manual["name"] for manual in project.get("manual_sections", [])})
        matched = {identity: next((p for p in paragraphs if own_text(p) == title), None) for identity, title in starts.items()}
        boundaries = set(doc._editorial_heading_paragraphs) | {p for p in matched.values() if p is not None}
        for identity, first in matched.items():
            if first is None:
                raise ValueError("Manual image owner heading is missing: " + identity)
            index = paragraphs.index(first)
            end = next((offset for offset in range(index + 1, len(paragraphs)) if paragraphs[offset] in boundaries), len(paragraphs))
            ctx.setdefault("manual_image_anchors", {})[identity] = paragraphs[end - 1]


def _render_os1(doc, data, tables, ctx):
    project = data["project"]
    support = project.get("support_activities", [])
    sections = [
        ("1. 운영 지원 대상", [_notice(data), "(1) 하드웨어: 분류별 실제 장비 목록 추가 확인. (2) 소프트웨어: 아래 계획 대상. (3) 네트워크: 실제 구성 추가 확인."] + [f"{d['id']} {d['name']}: {_text(d.get('planned_specification'))}" for d in data["deployment_items"]] + ["(4) 시스템 구축·(5) 초기데이터: 관련 설계와 적재 계획만 있으며 실제 전환 완료로 판단하지 않는다."]),
        ("2. 운영 지원 기간", [f"{s['name']}: 입력 기간 {_text(s.get('period_start'))}~{_text(s.get('period_end'))}" for s in support] + ["실제 전환일·운영 개시일·지원 계약기간은 별도 확인한다. 계획기간을 실제 지원 실적으로 바꾸지 않는다."]),
        ("3. 운영 지원 인력", [f"{s['role']} ({s['organization_role']}): 실제 인원 {_text(s.get('name'), '미지정')}" for s in project.get("staff_members", [])] + ["실제 당직·연락처·책임자 승인 자료는 없다."]),
        ("4. 운영 지원 내용", [f"{s['id']} {s['name']}\n지원 구분: {code_label(s.get('category')) if ctx.get('editorial') else _text(s.get('category'))}\n계획: {s.get('plan') or UNKNOWN}\n실제 결과: {_text(s.get('actual_result'), _execution_missing(data))}\n담당: {_person(s.get('contact'))}\n증거 연결: {_join(s.get('evidence_ids', []), '미제공')}\n근거: {_refs(s)}" for s in support]),
        ("(1) 헬프 데스크 운영", ["연락 채널·담당·접수 시간·응답/복구 목표 자료 미제공. 실제 계약에 따른 지원체계를 확인한 후 확정한다."]),
        ("(2) 운영 현황 분석 및 관리 지원", ["로그인 회수·사용분·등록/거래 건수의 원시 로그와 집계식을 확보해 일별·주별 비교를 계획한다. 합성 계산 예제는 실제 운영 로그와 구분한다."]),
        ("(3) 추가 교육 실시", [s.get("plan") for s in support if s.get("category") == "training"] or ["실제 교육 일정·강사·참석자 미확인."]),
        ("(4) 활성화 방안", ["미활용 기능·입력 오류·권한 장애를 확인한 후 교육/절차 개선안을 검토한다. 이용률 개선·교육 개최·참석·서명 실적은 실제 결과와 근거로 구별해 확인한다."]),
    ]
    _narrative(doc, tables[-1], sections)
    if ctx.get("editorial"):
        blocks = _narrative_owned_blocks(doc, tables[-1], sections)
        for index, activity in enumerate(support):
            owners = blocks[1][index] + blocks[3][index]
            for field in activity:
                ctx.setdefault("primary_field_owners", {})[f"/project/support_activities/{index}/{field}"] = owners
        for index, member in enumerate(project.get("staff_members", [])):
            for field in member:
                ctx.setdefault("primary_field_owners", {})[f"/project/staff_members/{index}/{field}"] = blocks[2][index]
    _testing_frame_flow(doc, tables[-1], ctx)


def _render_os2(doc, data, tables, ctx):
    def kpi_lines(kpi, index):
        lines = [f"{kpi['id']} {kpi['name']}",
            f"입력 산식: {_text(kpi.get('formula'))} ({_text(kpi.get('formula_kind'))}); 분자 {_text(kpi.get('numerator'))} / 분모 {_text(kpi.get('denominator'))}",
            f"입력 실적 {_text(kpi.get('actual'))}{_text(kpi.get('unit'), '')}; 기준 {_text(kpi.get('baseline'))}, 목표 {_text(kpi.get('target'))}; 확인상태 {code_label(kpi['status'])}. 실제 측정 여부는 출처와 증거로 별도 확인한다."]
        precision = kpi.get("actual_precision")
        notes = _text(kpi.get("notes"))
        if ctx.get("editorial"):
            lines.append(f"입력 실적 소수 자릿수: {readable_value(precision)}; 실적 원값과 산식은 위 입력 그대로이며 비고 원문은 아래에 보존한다.")
            # Supplementary display of a literal in supplied notes, not a new
            # measurement or an inferred KPI formula. Never rewrite the notes.
            if isinstance(precision, int) and not isinstance(precision, bool) and 0 <= precision <= 12:
                from decimal import Decimal, ROUND_HALF_UP, localcontext
                for number, value in enumerate(dict.fromkeys(re.findall(r"(?<![\d.])[-+]?\d+\.\d{7,}(?!\d)", notes)), 1):
                    with localcontext() as arithmetic:
                        arithmetic.prec = max(28, len(value) + precision + 4)
                        display = format(Decimal(value).quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP), "f")
                    lines.append(f"[K{index}.{number}] 비고 소수 표시: {display} (소수 {precision}자리 반올림 참고값); 원문 수치: {value}. 새 측정·실적·성공 판정이 아니다.")
        lines += ["비고 원문: " + notes, "출처: " + _refs(kpi)]
        return "\n".join(lines)
    def installation(category):
        return [f"{d['id']} {d['name']}\n계획 사양: {_text(d.get('planned_specification'))}; 실제 사양: {_text(d.get('actual_specification'))}\n계획 수량 {_text(d.get('planned_quantity'))} / 실제 수량 {_text(d.get('installed_quantity'))} {_text(d.get('unit'), '')}; 설치일 {_text(d.get('installation_date'))}; 입력상태 {code_label(d.get('installation_status')) if ctx.get('editorial') else _text(d.get('installation_status'))}\n검증 결과: {_text(d.get('verification_result'))}; 증거: {_join(d.get('evidence_ids', []), '미제공')}" for d in data["deployment_items"] if d.get("category") == category] or ["분류별 실제 설치 자료 미제공. 설치 없음/완료로 판단하지 않는다."]
    records = []
    for period in data["operation_periods"]:
        label = "실제 로그가 아닌 합성 계산 입력" if data["dataset_kind"] == "synthetic" else "제공된 운영 입력값(실제 로그·집계 근거 확인 별도)"
        records.append(f"{period['id']} {period['name']}\n기간 {_text(period.get('period_start'))}~{_text(period.get('period_end'))}\n아래 값은 {label}이다.")
        for index, row in enumerate(period.get("raw_records", []), 1):
            metrics = "; ".join(f"{name}={_text(row.get(key))}" for key, name in (("user_count", "사용자수"), ("login_count", "접속회수"), ("usage_minutes", "사용분"), ("incident_count", "장애건수"), ("registration_count", "등록건수"), ("transaction_count", "거래건수")) if key in row)
            records.append(f"원시행 {index}: {row['date']} / {metrics} / 자료 상태 {code_label(row.get('status'))} / 출처 {_refs(row)}")
        totals = period.get("reported_totals", {})
        records += [f"자료 상태: {code_label(period.get('status'))}; 출처: {_refs(period)}", f"집계식: {_text(period.get('aggregation_method'))}; 개별 산식: {_text(period.get('aggregation_rules'), '미지정')}\n입력 집계: " + "; ".join(f"{key}={_text(value)}" for key, value in totals.items()), _text(period.get("notes"))]
    _narrative(doc, tables[-1], [
        ("1. 시스템 구축 현황", [_notice(data), "계획과 실제를 구별한다. 설치·라이선스·자원 할당에 관한 제공 값과 증거 연결을 확인한다."]),
        ("(1) 하드웨어 설치 현황", installation("hardware")),
        ("(2) 소프트웨어 설치 현황", installation("software")),
        ("(3) 네트워크 설치 현황", installation("network")),
        ("(4) 시스템 구축 현황", [f"설계 입력 기준: 화면 {len(data['screens'])}개 / 프로그램 {len(data['programs'])}개 / 테이블 {len(data['database_tables'])}개. 실제 구현/가동 수량이 아니다."]),
        ("2. 시스템 (시범)운영 현황", ["합성 계산값은 실제 운영 성과가 아니다." if data["dataset_kind"] == "synthetic" else "제공된 운영 입력과 확인 상태를 구분한다. 생성만으로 실제 운영·집계의 진위를 확인하지 않는다."]),
        ("(1) 데이터 등록 및 활용 현황", ["실제 사용자·거래처·품목·생산/거래 등록 로그가 없어 주간 실적을 확정하지 않는다." if data["dataset_kind"] == "synthetic" else "등록/활용 원시자료와 집계 근거의 제공 범위·기간·검증 상태를 확인해야 한다. 아래 제공된 원시행과 집계 입력을 참조하며 입력 존재만으로 실제 로그의 진위를 확정하지 않는다."]),
        ("(2) 사용자 활용 현황", records or [UNKNOWN]),
        ("(3) 장애관리 현황", [f"{d['id']}: {d.get('description')}; 발생일 {_text(d.get('detected_date'))}; 조치 {_text(d.get('resolution'), _execution_missing(data))}" for d in data["defects"]] or ["실제 장애 원장 미제공. 장애 없음으로 판정하지 않는다."]),
        ("(4) 공급기업 지원 내역", [f"{s['name']}: 계획 {_text(s.get('plan'))}; 지원 결과 입력: {_text(s.get('actual_result'), _execution_missing(data))}" for s in data["project"].get("support_activities", [])]),
        ("3. KPI 계산 검토(실측 성과와 구별)", [kpi_lines(k, index) for index, k in enumerate(data["kpis"], 1)]),
    ])
    _testing_frame_flow(doc, tables[-1], ctx)
    if ctx.get("editorial"):
        # Keep the full decimal token on one line while letting ordinary prose
        # flow. This does not reduce point size, line spacing or precision.
        for paragraph in tables[-1].iter(f"{{{HP}}}p"):
            if re.search(r"(?<![\d.])[-+]?\d+\.\d{7,}(?!\d)", own_text(paragraph)):
                doc.use_paragraph_style(paragraph, break_latin="KEEP_WORD")


def _render_pm1(doc, data, tables, ctx):
    reports = data["progress_reports"]
    report = reports[0] if reports else {}
    weekly = report.get("report_kind") == "weekly"
    monthly = report.get("report_kind") == "monthly"
    kind = report.get("report_kind")
    title = "주간 계획자료 검토본(월간 양식 사용)" if weekly else "월간보고서 검토본" if monthly else {
        "interim": "중간보고 검토본(월간 양식 사용)", "completion": "종료보고 유형 검토본(월간 양식 사용)",
        "other": "기타 보고 검토본(월간 양식 사용)", None: "보고 유형 미확인 검토본(월간 양식 사용)"}[kind]
    period_label = "주간 입력·월간 실적 아님" if weekly else "입력 기간" if monthly else f"입력 보고 유형: {json.dumps(kind, ensure_ascii=False)}; 월간 양식 사용"
    values = {"00월 월간보고서": title,
        "과제명 :": f"과제명 : {data['project']['name']}",
        "기  간 :": f"기간 : {_text(report.get('period_start'))}~{_text(report.get('period_end'))} ({period_label})",
        "진척율 :": f"입력 진도: 해당기간 계획 {_text(report.get('current_plan_percent'))}%, 입력 실적 {_text(report.get('current_actual_percent'))}%; 누적 계획 {_text(report.get('cumulative_plan_percent'))}%, 입력 실적 {_text(report.get('cumulative_actual_percent'))}%",
        "1. 월간 업무": "1. 주간 검토 계획(월간 실적으로 재분류하지 않음)" if weekly else "1. 기간별 업무",
        "작성일자 :": "작성일자 : " + _text(report.get("report_date")), "공급기업 PM :": "공급기업 PM : " + _person(report.get("author")) + " / 확인·날인 근거 미제공"}
    for p in doc.root().iter(f"{{{HP}}}p"):
        text = _own_text(p).strip()
        for key, value in values.items():
            if text.startswith(key): doc.set_paragraph_text(p, value); break
    _set(doc, tables[1], 0, 0, "주간 입력 실적(확인 상태 별도)" if weekly else "해당기간 입력 실적" if monthly else "해당기간 입력 내용")
    _set(doc, tables[1], 0, 1, "차주 검토 계획" if weekly else "다음기간 계획")
    type_notice = "" if weekly or monthly else f"\n입력 보고 유형: {json.dumps(kind, ensure_ascii=False)}. 월간 양식을 사용한 검토본이며 보고 유형만으로 실제 완료·수행을 판정하지 않는다."
    report_provenance = f"\n자료 상태: {code_label(report.get('status'))}; 출처: {_refs(report)}; 비고: {_text(report.get('notes'))}" if ctx.get("editorial") else ""
    _set(doc, tables[1], 1, 0, f"{_notice(data)}{type_notice}{report_provenance}\n{_text(report.get('calculation_basis'))}\n" + "\n".join(f"{w.get('phase') or UNKNOWN}: 실제 결과: {_text(w.get('actual'), _execution_missing(data))}; 계획 {_text(w.get('plan'))}; 담당 {_text(w.get('person_name'), '미지정')}" for w in report.get("work_items", [])))
    _set(doc, tables[1], 1, 1, "\n".join(_text(w.get("next_plan")) for w in report.get("work_items", [])) or UNKNOWN)
    if ctx.get("editorial"):
        # These nested values belong to individual work/risk records; their
        # report-level status and totals cannot stand in for them.
        cell = doc.cell(tables[1], 1, 0)
        paragraph = cell.find("hp:subList/hp:p", NS)
        details = []
        for index, work in enumerate(report.get("work_items", []), 1):
            fields = {key: value for key, value in work.items() if key not in {"phase", "actual", "plan", "person_name", "next_plan"}}
            if fields:
                details.append(f"업무 {index} 추가 명세\n" + describe_fields(fields, typed=True))
        for index, risk in enumerate(report.get("risks", []), 1):
            fields = {key: value for key, value in risk.items() if key not in {"number", "kind", "description", "handling_status", "action"}}
            if fields:
                details.append(f"위험·이슈 {risk.get('number') or index} 근거\n" + describe_fields(fields, typed=True))
        if details:
            doc.set_paragraph_text(paragraph, own_text(paragraph) + "\n" + "\n".join(details))
    rows = [[r.get("number"), {"risk": "위험", "issue": "이슈"}.get(r.get("kind"), "미확인"), r.get("description"), f"{_text(r.get('handling_status'))}\n{_text(r.get('action'))}"] for r in report.get("risks", [])]
    _row_table(doc, tables[2], rows)
    if ctx.get("editorial"):
        start = next(p for p, text in doc._source_paragraph_text.items() if text == "00월 월간보고서")
        doc._editorial_body_start_paragraph = start
        doc.use_paragraph_keep(start, keep_lines=True, keep_with_next=True)
        doc._editorial_body_paragraphs.add(_paragraph(tables[1]).getprevious())
        for row in tables[1].findall("hp:tr", NS)[1:]:
            doc.use_character_style(row, bold=False, italic=False)
            doc.use_paragraph_style(row, align="LEFT")
        for row in tables[2].findall("hp:tr", NS)[1:]:
            doc.use_character_style(row, bold=False, italic=False)
            doc.use_paragraph_style(row, align="LEFT")
            cell = row.find("hp:tc", NS)
            if cell is not None and len(own_text(cell.find("hp:subList/hp:p", NS))) <= 18:
                doc.use_paragraph_style(cell, break_latin="KEEP_WORD")
    if weekly: ctx["warnings"].append("PM1 입력 report_kind=weekly 유지. 월간 양식 사용 사실 명시; 월간 실적을 생성하지 않음")
    elif not monthly: ctx["warnings"].append(f"PM1 입력 report_kind={json.dumps(kind, ensure_ascii=False)} 유지; 월간 양식을 사용하되 월간 실적·실제 완료로 재분류하지 않음")
    if len(reports) > 1: raise ValueError("PM1 multiple periods require an explicit per-period output choice")


def _render_pm2(doc, data, tables, ctx):
    from .management_roles import load_contract, split_meeting_value
    selectors = load_contract(doc, "SF-PM2") if ctx.get("editorial") else None
    def fill(t, m, i):
        missing_date = "개최일 미확인"
        _set(doc, t, 0, 1, _text(m.get("date"), missing_date))
        _set(doc, t, 1, 1, m.get("location")); _set(doc, t, 2, 1, _person(m.get("organizer")))
        _set(doc, t, 3, 1, f"{m['id']} {m['name']}\n" + _text(m.get("agenda")))
        values = [(4, "discussions", "5. 회의내용", _text(m.get("discussions"), "회의내용 자료 미제공. 개최·토의·발언 여부는 확인 필요.") + f"\n입력 안건: {_text(m.get('agenda'))}"),
                  (5, "decisions", "6. 회의결과(합의사항)", _text(m.get("decisions"), "합의사항·확인/서명 자료 미제공. 안건만으로 합의를 판정하지 않음.")),
                  (6, "special_notes", "7. 특이사항", f"{_notice(data)}\n{_text(m.get('special_notes'))}\n근거: {_refs(m)}"),
                  (7, "attendees", "8. 참석자", _text([_person(a) for a in m.get("attendees", [])], "실제 참석자·도입기업/공급기업 확인·서명 자료 없음."))]
        for row, field, label, value in values:
            if selectors is None:
                _set(doc, t, row, 0, label + "\n" + value)
            else:
                index = next(index for index, meeting in enumerate(data["meetings"]) if meeting is m)
                pointer = f"/meetings/{index}/{field}"
                paragraph = split_meeting_value(doc, t, row, field, label, value, selectors,
                    entity_id=m["id"], input_pointer=pointer)
                ctx.setdefault("primary_field_owners", {})[pointer] = [paragraph]
    _repeat_cards(doc, tables[-1], data["meetings"], fill)
    if ctx.get("editorial"):
        start = next(p for p, text in doc._source_paragraph_text.items() if text == "회의록" and p.getparent() is doc.root())
        doc._editorial_body_start_paragraph = start
        doc.use_paragraph_keep(start, keep_lines=True, keep_with_next=True)
        doc._editorial_body_paragraphs.add(_paragraph(tables[1]).getprevious())


def _render_pm3(doc, data, tables, ctx):
    from .management_roles import load_contract, register_change_value, source_paragraph
    selectors = load_contract(doc, "SF-PM3") if ctx.get("editorial") else None
    if selectors is not None:
        source = source_paragraph(doc, selectors["change_request_number_value"]["source"])
        current = doc.cell(tables[1], 1, 2).find("hp:subList/hp:p", NS)
        if (int(tables[1].get("colCnt")) != 8 or current is None
                or own_text(current) != own_text(source)
                or own_text(doc.cell(tables[1], 0, 2).find("hp:subList/hp:p", NS)) != "변경요청 공문번호"):
            raise ComposeError("PM3 expected its exact source request-number guide and ledger header")
    rows = [[str(i), c["name"] + f" (입력상태: {code_label(c['approval_status'])})", _text(c.get("request_number"), "미제공"), _text(c.get("request_date"), "미확인"), _text((c.get("requester") or {}).get("name"), "미지정"), _text(c.get("response_number"), "미제공"), _text(c.get("response_content"), "미제공"), _text(c.get("response_date"), "미확인")] for i, c in enumerate(data["changes"], 1)]
    _row_table(doc, tables[1], rows)
    if selectors is not None:
        for index, change in enumerate(data["changes"]):
            pointer = f"/changes/{index}/request_number"
            paragraph = register_change_value(doc, tables[1], index + 1,
                _text(change.get("request_number"), "미제공"), entity_id=change["id"], input_pointer=pointer)
            ctx.setdefault("primary_field_owners", {})[pointer] = [paragraph]
    def fill(t, c, i):
        p = data["project"]
        for row, col, value in [(0, 1, p.get("program_name")), (0, 3, (p.get("customer") or {}).get("name")),
            (1, 1, p.get("task_number")), (1, 3, (p.get("supplier") or {}).get("name")), (2, 1, c["name"]), (2, 3, _text(c.get("request_date"), "미확인")),
            (3, 1, c.get("reason")), (4, 1, f"변경 전(입력): {_text(c.get('before'))}\n변경 후(입력): {_text(c.get('after'))}"),
            (5, 1, c.get("impact")), (6, 1, f"{_notice(data)}\n변경 ID: {c['id']}; 입력 확인상태: {code_label(c['status'])}\n요청/승인 상태: {code_label(c.get('approval_status')) if ctx.get('editorial') else _text(c.get('approval_status'))}\n요청자 입력: {_person(c.get('requester'))}\n요청자 제공 세부: {_text(c.get('requester'))}\n요청 공문: {_text(c.get('request_number'), '공문자료 미제공')}; 요청일: {_text(c.get('request_date'), '요청일 미제공')}\n회신 공문: {_text(c.get('response_number'), '회신번호 미제공')}; 회신일: {_text(c.get('response_date'), '회신일 미제공')}\n회신내용: {_text(c.get('response_content'), '회신내용 미제공')}\n{_text(c.get('notes'))}\n승인 증거 연결: {_join(c.get('approval_evidence_ids', []), '입력0개(빈 목록; 실제 증거 부재 여부 미판정)')}\n근거: {_refs(c)}")]: _set(doc, t, row, col, value)
        if ctx.get("editorial"):
            for row in t.findall("hp:tr", NS):
                for cell in row.findall("hp:tc", NS):
                    if int(cell.find("hp:cellAddr", NS).get("colAddr")) in {1, 3}:
                        doc.use_character_style(cell, bold=False, italic=False)
                        doc.use_paragraph_style(cell, align="LEFT")
    cards = _repeat_cards(doc, tables[-1], data["changes"], fill)
    title = _paragraph(cards[0]).getprevious()
    if title is None or own_text(title).strip() != "변경요청서":
        raise ValueError("PM3 expected the original request heading immediately before its detail table")
    title.set("pageBreak", "1")
    doc.use_paragraph_keep(title, keep_lines=True, keep_with_next=True)
    if ctx.get("editorial"):
        if selectors is not None:
            doc._editorial_management_preserved_titles = {"change_request_title": title}
        start = next(p for p, text in doc._source_paragraph_text.items() if text == "변경관리대장" and p.getparent() is doc.root())
        doc._editorial_body_start_paragraph = start
        doc.use_paragraph_keep(start, keep_lines=True, keep_with_next=True)
        doc._editorial_body_paragraphs.add(_paragraph(tables[1]).getprevious())


def _requirement_traces(data, rid):
    return [trace for trace in data["trace_links"]
            if (trace.get("source_kind"), trace.get("source_id")) == ("requirements", rid)
            or (trace.get("target_kind"), trace.get("target_id")) == ("requirements", rid)]


def _targets(data, rid, domain, stage=None):
    result = {item["id"] for item in data[domain] if rid in item.get("requirement_ids", []) and (stage is None or item.get("stage") == stage)}
    for trace in _requirement_traces(data, rid):
        if trace.get("source_kind") == "requirements" and trace.get("source_id") == rid and trace.get("target_kind") == domain:
            tid = trace["target_id"]
        elif trace.get("target_kind") == "requirements" and trace.get("target_id") == rid and trace.get("source_kind") == domain:
            tid = trace["source_id"]
        else:
            continue
        if stage is None or any(i["id"] == tid and i.get("stage") == stage for i in data[domain]): result.add(tid)
    return _join(sorted(result), "미연결")


def _pm4_trace_details(data, rid, *, editorial=False):
    values = [f"화면: {_targets(data, rid, 'screens')}; 프로그램: {_targets(data, rid, 'programs')}; DB: {_targets(data, rid, 'database_tables')}",
              f"단위시험: {_targets(data, rid, 'test_cases', 'unit')}; 통합시험: {_targets(data, rid, 'test_cases', 'integration')}; 사용자시험: {_targets(data, rid, 'test_cases', 'acceptance')}"]
    related = _requirement_traces(data, rid)
    # Preserve the actual adjacent link objects (including direction, relation,
    # notes, status and sources), without inferring transitive links or dumping
    # metadata from unrelated requirements and other domain objects.
    if editorial:
        values += [paragraph for trace in related for paragraph in trace_paragraphs(trace)] or ["명시 추적 연결 자료 미제공; 위 연결은 개체의 직접 requirement_ids도 포함한다."]
    else:
        values += ["명시 추적 연결 원문: " + json.dumps(trace, ensure_ascii=False, sort_keys=True) for trace in related] or ["명시 추적 연결 원문 미제공; 위 연결은 개체의 직접 requirement_ids도 포함한다."]
    return values


def _render_pm4_editorial(doc, data, tables, ctx):
    """Compare explicit directed records once, with exact shared text references."""
    functional, nonfunctional, unclassified = [], [], []
    for index, requirement in enumerate(data["requirements"], 1):
        rid, key = requirement["id"], f"T{index}"
        if requirement.get("kind") == "functional":
            functional.append([index, rid, requirement["name"], requirement.get("description"), _targets(data, rid, "screens"), _targets(data, rid, "programs"),
                               _targets(data, rid, "test_cases", "unit"), _targets(data, rid, "test_cases", "integration"), _targets(data, rid, "test_cases", "acceptance"), key])
        elif requirement.get("kind") == "nonfunctional":
            nonfunctional.append([index, rid, requirement["name"], requirement.get("description"), "제공 결과물: " + _join(requirement.get("deliverable_ids", []), "미제공") + "\n연결 시험: " + _targets(data, rid, "test_cases"), code_label(requirement.get("fulfillment_status")), key])
        else:
            unclassified.append(requirement)
    _row_table(doc, tables[1], functional or [["—", "—", "—", "기능 요구사항 자료 미제공; 미분류 입력은 T명세 참조", "—", "—", "—", "—", "—", "—"]])
    _row_table(doc, tables[2], nonfunctional or [["—", "—", "—", "비기능 요구사항 자료 미제공; 미분류 입력은 T명세 참조", "—", "—", "—"]])
    root = _paragraph(tables[2]).getparent()
    previous = _paragraph(tables[2])
    prototype = doc.cell(tables[2], 1, 3).find("hp:subList/hp:p", NS)

    def append(text, *, heading=False):
        nonlocal previous
        paragraph = doc.new_paragraph(text, prototype=prototype)
        doc.use_character_style(paragraph, bold=heading)
        doc.use_paragraph_keep(paragraph, keep_lines=len(text) <= NARRATIVE_KEEP_MAX_CHARS, keep_with_next=heading)
        if heading:
            doc._editorial_heading_paragraphs.add(paragraph)
        previous.addnext(paragraph)
        previous = paragraph
        return paragraph

    append("3. 요구사항별 추적 근거·검토상태", heading=True)
    append("T번호는 요구사항 근거, Q번호는 입력 연결 사유, N번호는 연결의 추가 명세다. 직접 ID 연결과 명시 연결을 구분하며 의미 충족·실제 수행·승인을 추론하지 않는다.")
    for index, requirement in enumerate(data["requirements"], 1):
        rid = requirement["id"]
        append(f"[T{index}] {rid} {requirement['name']}", heading=True)
        fields = {key: requirement[key] for key in ("kind", "original_id", "original_classification", "change_type", "status", "fulfillment_status", "deliverable_ids", "notes", "review_ids", "source_refs") if key in requirement}
        if requirement in unclassified:
            fields.update({key: requirement[key] for key in ("description", "fulfillment_status", "deliverable_ids") if key in requirement})
        fields["기능 연결"] = [feature["id"] for feature in data["features"] if rid in feature.get("requirement_ids", [])]
        fields["변경 연결"] = [change["id"] + " / " + code_label(change.get("approval_status")) for change in data["changes"] if any(ref.get("kind") == "requirements" and ref.get("id") == rid for ref in change.get("affected_refs", []))]
        fields["DB 연결"] = _targets(data, rid, "database_tables")
        if requirement in unclassified:
            fields["분류 확인"] = "유형 미확인(null); 기능·비기능으로 확정 배치하지 않음"
            for domain, label in (("screens", "화면 연결"), ("programs", "프로그램 연결"), ("test_cases", "시험 연결")):
                fields[label] = _targets(data, rid, domain)
        for field, value in fields.items():
            for line in describe_fields({field: value}).split("\n"):
                paragraph = append(f"[T{index}] {line}")
                if field in requirement:
                    pointer = f"/requirements/{index - 1}/{field}"
                    ctx.setdefault("primary_field_owners", {}).setdefault(pointer, []).append(paragraph)

    append("4. 명시 추적 연결 비교", heading=True)
    append("각 행은 입력의 시작→대상 방향을 유지한 하나의 명시 연결이다. Q/N의 같은 키는 값과 타입이 정확히 같은 입력 문구에만 공유된다. 빈 출처 목록은 실제 증거 부재를 확정하지 않는다.")
    source_owner = _paragraph(tables[2])
    if len(source_owner.findall(".//hp:tbl", NS)) != 1 or own_text(source_owner).strip():
        raise ComposeError("PM4 trace grid requires the isolated seven-column table owner")
    owner = doc.clone_paragraph(source_owner)
    owner.set("pageBreak", "0")
    owner.set("columnBreak", "0")
    doc.use_paragraph_keep(owner, keep_lines=False, keep_with_next=False)
    previous.addnext(owner)
    previous = owner
    grid = owner.find(".//hp:tbl", NS)
    headers = ["연결 ID", "시작 종류 / ID", "대상 종류 / ID", "관계", "내용 검토 / 자료 상태", "사유 / 추가 명세", "출처"]
    for column, text in enumerate(headers):
        _set(doc, grid, 0, column, text)
    rationales, extras = [], []
    rationale_keys, extra_keys = {}, {}
    rows, bindings = [], []
    core = {"id", "source_kind", "source_id", "target_kind", "target_id", "relation", "status", "content_review_status", "rationale", "source_refs"}

    def common(value, records, keys, prefix):
        identity = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if identity not in keys:
            keys[identity] = f"{prefix}{len(records) + 1}"
            records.append({"key": keys[identity], "value": value})
        return keys[identity]

    for index, trace in enumerate(data["trace_links"]):
        reason_key = common(trace["rationale"], rationales, rationale_keys, "Q") if "rationale" in trace else None
        additional = {key: value for key, value in trace.items() if key not in core}
        note_key = common(additional, extras, extra_keys, "N") if additional else None
        rows.append([trace["id"], DOMAIN_LABELS.get(trace["source_kind"], trace["source_kind"]) + "\n" + trace["source_id"],
                     DOMAIN_LABELS.get(trace["target_kind"], trace["target_kind"]) + "\n" + trace["target_id"], code_label(trace["relation"]),
                     f"검토: {code_label(trace.get('content_review_status'))}\n자료: {code_label(trace.get('status'))}",
                     (f"[{reason_key}]" if reason_key else "사유 필드 미제공") + (f" / [{note_key}]" if note_key else ""), _refs(trace) if trace.get("source_refs") else "미제공(빈 목록)"])
        bindings.append({"input_pointer": f"/trace_links/{index}", "trace": trace, "rationale_key": reason_key, "additional_key": note_key, "content_review_status": "pending"})
    _row_table(doc, grid, rows or [["명시 연결 입력 0개", "—", "—", "—", "—", "—", "—"]])
    # Trace rows are short records: preserve ID, direction, relation and state
    # together, rather than leaving an anonymous partial row after the header.
    doc.use_table_pagination(grid, break_mode="TABLE", inline=False)
    doc.repeat_header_rows(grid, count=1)
    doc._editorial_trace_tables.add(grid)
    for binding, row in zip(bindings, grid.findall("hp:tr", NS)[1:]):
        binding["_row"] = row
    ctx["trace_bindings"] = bindings
    for records, heading, typed in ((rationales, "5. 연결 사유", False), (extras, "6. 연결 추가 명세", True)):
        if not records:
            continue
        append(heading, heading=True)
        for record in records:
            text = readable_value(record["value"]) if records is rationales else describe_fields(record["value"], typed=typed)
            for line in text.split("\n"):
                append(f"[{record['key']}] {line}")
    ctx["trace_common_rationales"] = rationales
    ctx["trace_additional_definitions"] = extras
    ctx["warnings"].append("PM4 reference profile keeps one exact directed trace per comparison row; shared Q/N definitions deduplicate exact supplied values only. Current bytes require native pagination/readability review.")


def _render_pm4(doc, data, tables, ctx):
    if ctx.get("editorial"):
        return _render_pm4_editorial(doc, data, tables, ctx)
    functional, nonfunctional = [], []
    details, unclassified = [], []
    for i, r in enumerate(data["requirements"], 1):
        key = f"T{i}"
        features = [f["id"] for f in data["features"] if r["id"] in f.get("requirement_ids", [])]
        changes = [f"{c['id']} ({code_label(c['approval_status'])})" for c in data["changes"] if any(x.get("kind") == "requirements" and x.get("id") == r["id"] for x in c.get("affected_refs", []))]
        if r.get("kind") == "functional":
            note = f"구분: {CHANGE.get(r.get('change_type'), UNKNOWN)}\n근거: {_refs(r)}\n기능 전후 근거: {_join(features, '미연결')}\n변경 검토: {_join(changes, '미연결')}\n{_text(r.get('notes'))}\nID 연결만으로 의미 충족·실제 수행·승인을 판정하지 않음"
            functional.append([i, r["id"], r["name"], r.get("description"), _targets(data, r["id"], "screens"), _targets(data, r["id"], "programs"),
                _targets(data, r["id"], "test_cases", "unit"), _targets(data, r["id"], "test_cases", "integration"), _targets(data, r["id"], "test_cases", "acceptance"),
                key])
            details.append((key, r, note))
        elif r.get("kind") == "nonfunctional":
            note = f"구분: {CHANGE.get(r.get('change_type'), UNKNOWN)}\n원문 구분 {code_label(r.get('original_classification'))} 유지\n근거: {_refs(r)}\n기능 전후 근거: {_join(features, '미연결')}\n변경 검토: {_join(changes, '미연결')}\n{_text(r.get('notes'))}"
            nonfunctional.append([i, r["id"], r["name"], r.get("description"), "제공 결과물: " + _join(r.get("deliverable_ids", []), "미제공") + "\n연결 시험: " + _targets(data, r["id"], "test_cases"), _text(r.get("fulfillment_status")), key])
            details.append((key, r, note))
        else:
            note = f"원문 구분: {code_label(r.get('original_classification'))}; 원문 ID: {_text(r.get('original_id'))}\n변경 구분: {CHANGE.get(r.get('change_type'), UNKNOWN)}\n근거: {_refs(r)}\n기능 전후 근거: {_join(features, '미연결')}\n변경 검토: {_join(changes, '미연결')}\n비고: {_text(r.get('notes'))}"
            unclassified.append((key, r, note))
    empty_functional = [["—", "—", "—", "기능으로 분류된 요구사항 자료 미제공; 미분류 입력은 별도 본문 참조", "—", "—", "—", "—", "—", "—"]]
    empty_nonfunctional = [["—", "—", "—", "비기능으로 분류된 요구사항 자료 미제공; 미분류 입력은 별도 본문 참조", "—", "—", "—"]]
    _row_table(doc, tables[1], functional or empty_functional)
    _row_table(doc, tables[2], nonfunctional or empty_nonfunctional)
    prototype = doc.cell(tables[2], 1, 3).find("hp:subList/hp:p", NS)
    previous = _paragraph(tables[2])
    values = ["3. 요구사항별 추적 근거·검토상태", "비고의 Tn은 아래 [Tn]과 대응한다. 좁은 비고에는 참조키만 기재하고 구분·notes·전체 출처·연결 기능과 변경검토 정보 및 화면·프로그램·DB·시험단계별 직접/명시 연결과 양방향 추적 원문은 여기에 보존한다. ID 연결만으로 의미 충족·실제 수행·승인을 판정하지 않는다."]
    for key, requirement, note in details:
        values += [f"[{key}] {requirement['id']} {requirement['name']}; 구분: {code_label(requirement['kind'])}; 원문 구분: {code_label(requirement.get('original_classification'))}; 입력 확인상태: {code_label(requirement['status'])}", note]
        values += _pm4_trace_details(data, requirement["id"], editorial=ctx.get("editorial", False))
    if unclassified:
        values += ["4. 구분 미확인 요구사항과 추적 근거", "아래 요구사항의 kind는 null이므로 기능/비기능 어느 표에도 확정 배치하지 않았다. 입력 내용과 추적 근거를 보존하며 분류 확인 후 해당 표에 편성해야 한다. 연결 ID와 보고 상태만으로 의미 충족·실제 수행·승인을 판정하지 않는다."]
        for key, requirement, note in unclassified:
            rid = requirement["id"]
            values += [f"[{key}] {rid} {requirement['name']}; 요구사항 구분: 미확인(null); 입력 확인상태: {code_label(requirement['status'])}",
                f"시스템: {_text(requirement.get('system_name'))}; 업무영역: {_text(requirement.get('business_area'))}",
                "요구사항 설명: " + _text(requirement.get("description")), "세부 내용:\n" + _text(requirement.get("details")),
                "제약/전제:\n" + _text(requirement.get("constraints")), "담당자 입력: " + _text(requirement.get("owner")),
                f"추진상태: {_text(requirement.get('fulfillment_status'))}; 결과물 ID: {_join(requirement.get('deliverable_ids', []))}; 검토 ID: {_join(requirement.get('review_ids', []))}", note]
            if requirement.get("field_states"):
                values.append("필드별 확인 상태: " + _text(requirement["field_states"]))
            values += _pm4_trace_details(data, rid, editorial=ctx.get("editorial", False))
    for value in values:
        p = doc.new_paragraph(value, prototype=prototype)
        # A raw trace stays a single unchanged JSON paragraph. Bound only that
        # one record, never all traces or the full requirement appendix.
        raw_trace = value.startswith("명시 추적 연결 원문: {") and len(value) <= PM4_RAW_TRACE_KEEP_MAX_CHARS
        title = bool(re.match(r"^\[T\d+\] ", value)) or value.startswith("명시 연결 [") or value in {"3. 요구사항별 추적 근거·검토상태", "4. 구분 미확인 요구사항과 추적 근거"}
        doc.use_paragraph_keep(p,
            keep_lines=True if value.strip() and (len(value) <= NARRATIVE_KEEP_MAX_CHARS or raw_trace) else None,
            keep_with_next=True if title else None)
        previous.addnext(p)
        previous = p
    ctx["warnings"].append("PM4 비고는 Tn 참조키; 모든 분류의 전체 notes/원문구분/출처/기능·변경연결과 화면·프로그램·DB·시험단계별 직접/양방향 명시 추적은 표 뒤 [Tn] 전폭 상세에 보존")
    ctx["warnings"].append("PM4 전폭의 240자 이하 문단과 한 개의 720자 이하 raw trace 문단만 keepLines; Tn/절 제목만 keepWithNext. trace 사이·요구사항 전체는 연결하지 않으며 현재 바이트 native 재검토 필요")
    if unclassified:
        ctx["warnings"].append(f"PM4 kind=null {len(unclassified)}건은 기능/비기능으로 확정하지 않고 별도 구분 미확인 본문에 전체 입력과 추적 근거를 보존")


RENDERERS = {
    "SF-AD1": _render_ad1, "SF-AD2": _render_ad2, "SF-AD3": _render_ad3,
    "SF-TD1": _render_td1, "SF-TD2": _render_td2, "SF-TD3": _render_td3,
    "SF-TD4": _render_td4, "SF-TD5": _render_td5, "SF-CD1": _render_cd1,
    "SF-TI1": lambda *a: _render_grouped_test(*a, stage="integration"), "SF-TI2": _render_ti2,
    "SF-TI3": _render_ti3, "SF-TI4": lambda *a: _render_grouped_test(*a, stage="acceptance"),
    "SF-OS1": _render_os1, "SF-OS2": _render_os2, "SF-PM1": _render_pm1,
    "SF-PM2": _render_pm2, "SF-PM3": _render_pm3, "SF-PM4": _render_pm4,
}


def _template_paths(template_root, roles=None):
    return resolve_templates(roles or ROLES, template_root=template_root)


def _toc_entries(role, data):
    if role == "SF-AD2":
        entries = []
        for group, (title, items) in enumerate(_ad2_groups(data), 1):
            for number, item in enumerate(items, 1):
                label = f"  {group}-{number}. {item['id']} {item['name']}"
                # One measured entry per card. The first child owns its group
                # heading as well, so each group points to its first real card.
                entries.append((f"{group}. {title}\n" if number == 1 else "") + label)
        return entries
    if role == "SF-TD3":
        return ["1. 화면 표준", "2. 메뉴구조도", "3. 화면(보고서) 설계"] + [f"  3-{i}. {s['id']} {s['name']}" for i, s in enumerate(data["screens"], 1)] + ["4. 화면 검토 결과"]
    domain = {"SF-AD2": "requirements", "SF-TD3": "screens", "SF-TD4": "programs", "SF-TD5": "database_tables"}.get(role)
    if domain:
        return [f"{i}. {item['id']} {item['name']}" for i, item in enumerate(data[domain], 1)]
    stage = {"SF-CD1": "unit", "SF-TI1": "integration", "SF-TI4": "acceptance"}.get(role)
    if stage:
        return [f"{i}. {c['id']} {c['name']}" for i, c in enumerate((x for x in data["test_cases"] if x["stage"] == stage), 1)] + ["결함관리 내역(미확정 후보/미수행 구분)"]
    entries = {
        "SF-AD1": ["1. 업무 현황 분석 결과", "2. 기존시스템에 대한 현황 분석 결과"],
        "SF-TD1": ["1. 개선된 전체 업무 흐름도", "2. 개선된 공정별 업무 흐름도", "3. 본 사업을 통한 기대효과"],
        "SF-TD2": ["1. 시스템", "2. H/W", "3. S/W", "4. N/W", "5. 도입/설치 계획", "6. 클라우드 미확인"],
        "SF-TI2": ["1. H/W 계획/미설치", "2. S/W 계획/미설치", "3. N/W 미확인", "4. 초기데이터 적재 계획/미수행"],
        "SF-TI3": ["1. 사용자 매뉴얼 검토안", "2. 관리자 매뉴얼 검토안"],
        "SF-OS1": ["1. 지원 대상", "2. 계획 기간", "3. 인력 역할/실인원 미확인", "4. 지원 계획/실제 미수행"],
        "SF-OS2": ["1. 구축 계획/실제 미확인", "2. 합성 운영집계 검토(실제 운영 아님)", "3. 합성 KPI 계산 검토"],
    }
    if role == "SF-TI2":
        return ["1. 하드웨어 설치 결과", "2. 소프트웨어 설치 및 전환 결과", "3. 네트워크 설치 결과", "4. 초기데이터 전환 결과"]
    if role == "SF-OS1":
        return ["1. 운영 지원 대상", "2. 운영 지원 기간", "3. 운영 지원 인력", "4. 운영 지원 내용"]
    if role == "SF-OS2" and data["dataset_kind"] == "project":
        return ["1. 시스템 구축 현황", "2. 시스템 (시범)운영 현황", "3. KPI 계산 검토(실측 성과와 구별)"]
    return entries.get(role, [TITLES[role]])


def _supported_inputs(data, selected, *, base_dir=None):
    unsupported = []
    from .quotations import entries as quotation_entries, role_for
    for pointer, parent, quote in quotation_entries(data):
        if role_for(pointer.split("/")[1], parent) not in selected:
            unsupported.append(pointer + ": historical quotations require their explicit TI1/TI2/TI4 owner role")
    if data["project"].get("organization_chart_attachment_ids") and "SF-AD1" not in selected:
        unsupported.append("/project/organization_chart_attachment_ids: organization charts are supported only for SF-AD1")
    fields = {
        "SF-TD5": [("database_tables", data["database_tables"], ("physical_export_attachment_ids",))],
    }
    for role in selected:
        for prefix, items, keys in fields.get(role, []):
            for i, item in enumerate(items):
                unsupported.extend(f"/{prefix}/{i}/{key}" for key in keys if item.get(key))
    attachments = {attachment["id"]: attachment for attachment in data["attachments"]}
    for role in selected:
        for prefix, items, slots in _image_groups(data, role):
            for index, item in enumerate(items):
                for field, _ in slots:
                    for attachment_id in item.get(field, []):
                        pointer = f"/{prefix}/{field}" if prefix == "project" else f"/{prefix}/{index}/{field}"
                        _validate_image_input(attachments, attachment_id, pointer, base_dir, unsupported)
    if "SF-PM1" in selected and len(data["progress_reports"]) > 1:
        unsupported.append("/progress_reports (multiple periods need separate output choice)")
    if unsupported:
        raise ValueError("Unsupported supplied content would be omitted by this profile; no output generated: " + ", ".join(unsupported))


def _validate_image_input(attachments, attachment_id, location, base_dir, unsupported):
    from PIL import Image
    attachment = attachments.get(attachment_id, {})
    expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/bmp": "BMP", "image/x-ms-bmp": "BMP"}.get(attachment.get("media_type"))
    location += f" ({attachment_id})"
    if expected is None:
        unsupported.append(location + ": only PNG/JPEG/BMP images are supported")
        return
    path = Path(attachment["path"])
    if not path.is_absolute():
        path = Path(base_dir or ".") / path
    try:
        with Image.open(path) as image:
            if image.format != expected or image.width <= 0 or image.height <= 0:
                unsupported.append(location + ": image bytes differ from declared MIME")
            image.verify()
    except (OSError, ValueError):
        unsupported.append(location + ": unreadable image bytes")


def _matching_companion(data, verification_path=None):
    """Use a companion report only when explicitly selected by the caller."""
    if verification_path is None:
        return None
    verification = Path(verification_path).expanduser().resolve()
    if data["dataset_kind"] != "synthetic" or not verification.is_file():
        return None
    try:
        report = json.loads(verification.read_text(encoding="utf-8"))
        companion, baseline = Path(report["output"]), Path(report["input"])
        if not companion.is_file() or _sha(companion) != report["output_sha256"] or not baseline.is_file() or _sha(baseline) != report["input_sha256"]:
            return None
        other = json.loads(baseline.read_text(encoding="utf-8"))
        canonical = lambda tables: json.dumps(tables, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return companion if canonical(data["database_tables"]) == canonical(other["database_tables"]) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


class ProjectInputCollision(ValueError):
    """A planned generated write or owned cleanup aliases the main dataset."""


class ProjectInputChanged(ValueError):
    """The main dataset no longer matches the exact bytes parsed at entry."""


def _project_input_alias(source, target):
    return (source.absolute() == target.absolute() or source.resolve() == target.resolve()
            or source.exists() and target.exists() and source.samefile(target))


def _reject_project_input_collisions(source, planned_paths):
    for target in map(Path, planned_paths):
        if _project_input_alias(source, target):
            raise ProjectInputCollision("Main project input aliases a planned output; no input may be overwritten or removed: " + str(source))


def _reject_input_output_collisions(source, data, planned_paths):
    """Re-evaluate both main and quotation aliases at the actual write gate."""
    from .quotations import reject_quotation_output_collisions
    paths = list(planned_paths)
    _reject_project_input_collisions(source, paths)
    reject_quotation_output_collisions(data, source.parent, paths)


def _discard_owned_output(source, data, target, expected_sha256):
    from .quotations import QuotationInputCollision
    try:
        _reject_input_output_collisions(source, data, [target])
    except (ProjectInputCollision, QuotationInputCollision):
        return  # A late alias is an input, never cleanup-owned output.
    if target.is_file() and _sha(target) == expected_sha256:
        target.unlink()


def _assert_project_input_stable(source, expected_sha256):
    try:
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError as exc:
        raise ProjectInputChanged("Main project input became unavailable before commit: " + str(source)) from exc
    if actual != expected_sha256:
        raise ProjectInputChanged("Main project input changed before commit: " + str(source))


def generate_project(input_path, output_dir, roles=None, template_root=None, *, style_profile=None, companion_verification=None, raster_metadata_profile=None):
    """Generate reviewable drafts; business errors stop before output mutation."""
    source = Path(input_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    source_bytes = source.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    data = json.loads(source_bytes.decode("utf-8"))
    validation = validate_project(data, base_dir=source.parent)
    _assert_project_input_stable(source, source_sha256)
    if validation["errors"]:
        raise ValueError("Project validation failed: " + "; ".join(e["code"] + " " + e["path"] for e in validation["errors"]))
    if data["dataset_kind"] not in ("synthetic", "project"):
        raise ValueError("Reference extractions are preserved as analysis evidence and cannot be presented as a new project's document")
    selected = list(roles or data["project"].get("requested_deliverables") or [])
    if len(set(selected)) != len(selected) or any(r not in ROLES for r in selected) or not selected:
        raise ValueError("roles must contain unique canonical v2 deliverable codes")
    if style_profile not in (None, "reference-v1"):
        raise ValueError("style_profile must be None or 'reference-v1'")
    if raster_metadata_profile not in (None, HANCOM_MAC_12_30_PNG_METADATA):
        raise ValueError("Unknown raster metadata profile")
    from .quotations import entries as quotation_entries
    if (any(quote.get("detail_regions") for _, _, quote in quotation_entries(data))
            and raster_metadata_profile != HANCOM_MAC_12_30_PNG_METADATA):
        raise ValueError("Quotation detail_regions requires the explicit Hancom Mac12.30 PNG profile before output generation")
    _supported_inputs(data, selected, base_dir=source.parent)
    templates = _template_paths(template_root, selected)
    for role in selected:
        template = templates[role]["path"]
        if output == template.parent or output in template.parents or output.is_relative_to(template.parent):
            raise ValueError("Generated output must be outside the original template directories")
    if source.parent == output or output in source.parents:
        raise ValueError("Output directory must not contain the input dataset")
    companion = _matching_companion(data, companion_verification)
    from .quotations import QuotationInputCollision
    planned_paths = [output / "manifest.json"]
    for role in selected:
        target = output / f"{role}_{TITLES[role]}_검증용.hwpx"
        planned_paths.append(target)
        if style_profile == "reference-v1":
            planned_paths.extend([target.with_suffix(".meaning.json"), target.with_suffix(".sources.json"),
                                  output / "profiles" / (role + ".json")])
    if "SF-TD5" in selected and companion is not None:
        planned_paths.append(output / companion.name)
    _reject_input_output_collisions(source, data, planned_paths)
    _assert_project_input_stable(source, source_sha256)
    output.mkdir(parents=True, exist_ok=True)
    stale_companions = []
    previous_manifest = output / "manifest.json"
    if "SF-TD5" in selected and companion is None and previous_manifest.is_file():
        try:
            previous = json.loads(previous_manifest.read_text(encoding="utf-8"))
            for item in previous.get("companions", []):
                old = Path(item["path"])
                if old.parent.resolve() == output and old.is_file() and _sha(old) == item.get("sha256"):
                    _reject_input_output_collisions(source, data, [old])
                    _assert_project_input_stable(source, source_sha256)
                    old.unlink()
                    stale_companions.append(str(old))
        except (QuotationInputCollision, ProjectInputCollision, ProjectInputChanged):
            raise
        except (OSError, ValueError, KeyError, TypeError):
            pass
    manifest = {"schema_version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(), "dataset_kind": data["dataset_kind"], "raster_metadata_profile": raster_metadata_profile,
        "input": {"path": str(source), "sha256": source_sha256}, "notice": _notice(data), "submission_ready": False,
        "validation": {"errors": validation["errors"], "warnings": validation["warnings"], "submission_blockers": validation["submission_blockers"]},
        "documents": [], "companions": [], "removed_owned_stale_companions": stale_companions, "native_review_status": "pending", "limitations": ["Native Hancom rendering and all-page visual review are pending.", "Provided facts, plans and verification status are distinct; generation does not establish execution, installation, approval or authentic signatures."]}
    if "SF-TD5" in selected and companion is not None:
        target = output / companion.name
        _reject_input_output_collisions(source, data, [target])
        _assert_project_input_stable(source, source_sha256)
        if target != companion: shutil.copyfile(companion, target)
        manifest["companions"].append({"role": "SF-TD5", "path": str(target), "sha256": _sha(target), "kind": "synthetic_design_workbook", "actual_physical_database_export": False})
    quotation_commit = {"_quotation_file_snapshots": {}}
    quotation_targets = []
    for role in selected:
        profile = templates[role]
        doc = TemplateDocument(profile["path"], expected_sha256=profile["sha256"])
        doc._editorial_heading_paragraphs = set()
        doc._editorial_caption_paragraphs = set()
        doc._editorial_picture_paragraphs = set()
        doc._editorial_toc_paragraphs = {}
        doc._editorial_body_paragraphs = set()
        doc._editorial_trace_tables = set()
        removed = _prepare(doc, role, data, editorial=style_profile == "reference-v1")
        tables = _all_tables(doc)
        ctx = {"warnings": [], "editorial": style_profile == "reference-v1", "input_dir": source.parent, "raster_metadata_profile": raster_metadata_profile, "companion_label": companion.name + " (합성 설계목록·물리DB 추출 아님)" if companion is not None else "현재 DB 입력과 일치 확인된 부속 Excel 미제공"}
        _toc(doc, _toc_entries(role, data))
        if role != "SF-TD5" and not (role == "SF-AD2" and ctx["editorial"]):
            _body_notice(doc, tables[1], data)
        source_notes = SourceNotes() if ctx["editorial"] else None
        with source_note_scope(source_notes):
            RENDERERS[role](doc, data, tables, ctx)
            _role_images(doc, role, data, tables, ctx)
            doc._editorial_after_picture_captions = ctx.get("after_picture_captions", {})
            _meaning_supplement(doc, role, data, ctx)
            from .quotations import append_reference_quotations
            append_reference_quotations(doc, role, data, ctx)
            _append_project_context(doc, data, ctx)
            if ctx.get("editorial"):
                from .related import append_reference_register
                last_table = _all_tables(doc)[-1]
                append_reference_register(doc, role, data, ctx,
                    parent=_paragraph(last_table).getparent(),
                    prototype=_appendix_prototype(doc, last_table))
            _append_attachment_notes(doc, ctx)
            _append_linked_review_notes(doc, data, ctx)
        if source_notes is not None:
            with source_note_scope(source_notes):
                _append_source_notes(doc, data, source_notes)
        _body_start_numbering(doc, role, tables)
        recoloured = sum(doc.blacken_text_runs(doc.root(section)) for section in range(len(doc.sections)))
        editorial_report = None
        if style_profile == "reference-v1":
            from .layout import apply_editorial_profile
            profile_path = Path(__file__).resolve().parents[2] / "resources/style-upgrade/profiles" / f"{role}.json"
            profile_bytes = profile_path.read_bytes()
            editorial_spec = json.loads(profile_bytes)
            profile_snapshot = output / "profiles" / f"{role}.json"
            profile_snapshot.parent.mkdir(exist_ok=True)
            if profile_snapshot.exists() and profile_snapshot.read_bytes() != profile_bytes:
                raise ComposeError("Refusing to replace a different frozen output profile; use a new output directory")
            _reject_input_output_collisions(source, data, [profile_snapshot])
            _assert_project_input_stable(source, source_sha256)
            profile_snapshot.write_bytes(profile_bytes)
            editorial_report = apply_editorial_profile(doc, role, profile=editorial_spec)
            if profile_path.read_bytes() != profile_bytes:
                raise ComposeError("Editorial source profile changed during application; regenerate from stable source bytes")
            editorial_report["profile_source"] = {"path": str(profile_snapshot), "sha256": hashlib.sha256(profile_bytes).hexdigest(), "origin_path": str(profile_path), "origin_sha256": hashlib.sha256(profile_bytes).hexdigest(), "profile_id": editorial_spec["profile_id"]}
            identity = getattr(doc, "_editorial_cover_program_identity", None)
            if identity is not None:
                owner = doc._editorial_cover_paragraphs["program"]
                if own_text(owner) != identity["text"]:
                    raise ComposeError("Cover program identity no longer matches its actual owner")
                editorial_report["cover_program_identity"] = {**identity,
                    "owner": {"section": doc.sections[0], "xpath": owner.getroottree().getpath(owner)}}
        _materialize_images(doc, ctx)
        target = output / f"{role}_{TITLES[role]}_검증용.hwpx"
        from .quotations import assert_quotation_files_stable
        assert_quotation_files_stable(ctx)
        _reject_input_output_collisions(source, data, [target])
        _assert_project_input_stable(source, source_sha256)
        quotation_commit["_quotation_file_snapshots"].update(ctx.get("_quotation_file_snapshots", {}))
        result = doc.save(target)
        try:
            assert_quotation_files_stable(ctx)
            _assert_project_input_stable(source, source_sha256)
        except ValueError:
            # Do not publish an output whose declared input provenance drifted
            # while saving. Cleanup never owns a main/quotation input alias.
            _discard_owned_output(source, data, target, result["sha256"])
            raise
        quotation_targets.append((target, result["sha256"]))
        meaning_report = None
        trace_records = _finalize_trace_bindings(doc, ctx.get("trace_bindings", []))
        if ctx.get("editorial"):
            meaning_path = target.with_suffix(".meaning.json")
            _reject_input_output_collisions(source, data, [meaning_path])
            records = _finalize_meaning_map(doc, ctx.get("meaning_map", []))
            meaning_path.write_text(json.dumps({"schema_version": "document-meaning-map-1", "role": role,
                "input_sha256": manifest["input"]["sha256"], "document_sha256": _sha(target),
                "xml_namespaces": {prefix: uri for member in doc.sections for prefix, uri in doc.xml(member).nsmap.items() if prefix},
                "scope": "Relevant role entities and declared linked-object projections; primary routes and actual supplemental/register owners. Declared routes and leaf counts are review requirements, not semantic-preservation proof.",
                "semantic_review_status": "pending", "entities": records, "explicit_trace_links": trace_records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            meaning_report = {"path": str(meaning_path), "sha256": _sha(meaning_path), "semantic_review_status": "pending", "entity_count": len(records), "field_count": sum(len(record["fields"]) for record in records)}
        source_note_report = None
        if source_notes is not None:
            source_note_path = target.with_suffix(".sources.json")
            _reject_input_output_collisions(source, data, [source_note_path])
            source_records = {source["id"]: source for source in data["sources"]}
            source_note_path.write_text(json.dumps({"schema_version": "document-source-notes-1", "role": role,
                "input_sha256": manifest["input"]["sha256"], "document_sha256": _sha(target),
                "xml_namespaces": {prefix: uri for member in doc.sections for prefix, uri in doc.xml(member).nsmap.items() if prefix},
                "references": _finalize_source_note_records(doc, source_notes.records, source_records), "code_mappings": source_notes.code_mappings,
                "attachments": list(ctx.get("attachment_notes", {}).values()), "linked_reviews": ctx.get("linked_reviews", []),
                "explicit_trace_links": trace_records, "trace_rationale_definitions": ctx.get("trace_common_rationales", []), "trace_additional_definitions": ctx.get("trace_additional_definitions", [])}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            source_note_report = {"path": str(source_note_path), "sha256": _sha(source_note_path), "reference_count": len(source_notes.records), "body_format": "[Sn]", "appendix_present": bool(source_notes.records or source_notes.code_mappings), "appendix_title": "부록. 출처 대응표" if source_notes.records or source_notes.code_mappings else None}
        if _sha(profile["path"]) != profile["sha256"]:
            raise RuntimeError("Original template changed during rendering")
        from .quotations import finalize_quotation_owners
        quotation_owners = finalize_quotation_owners(doc, ctx)
        manifest["documents"].append({"role": role, "title": TITLES[role], "path": str(target), "sha256": _sha(target),
            "source_template": {"path": str(profile["path"]), "sha256": profile["sha256"]}, "input_sha256": manifest["input"]["sha256"],
            "instruction_paragraphs_removed": removed, "black_text_runs_changed": recoloured, "warnings": ctx["warnings"], "toc_page_numbers": "pending_native_render", "native_review_status": "pending", "submission_ready": False,
            "editorial_profile": editorial_report, "image_bindings": ctx.get("image_bindings", []), "inserted_picture_metadata": result.get("inserted_picture_metadata", []), "source_notes": source_note_report, "meaning_map": meaning_report,
            "explicit_trace_grid": {"row_count": len(trace_records), "pagination": "TABLE", "mapping_review_status": "pending"} if trace_records else None,
            "reference_register": ctx.get("reference_register", []),
            **({"reference_quotations": quotation_owners} if quotation_owners else {})})
    destination = output / "manifest.json"
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    manifest_written = False
    try:
        # Earlier roles' sources must also remain stable until the complete
        # generation transaction publishes its manifest.
        assert_quotation_files_stable(quotation_commit)
        _assert_project_input_stable(source, source_sha256)
        _reject_input_output_collisions(source, data, [destination])
        destination.write_text(manifest_text, encoding="utf-8")
        manifest_written = True
        assert_quotation_files_stable(quotation_commit)
        _assert_project_input_stable(source, source_sha256)
    except ValueError:
        for target, expected in quotation_targets:
            _discard_owned_output(source, data, target, expected)
        if manifest_written:
            _discard_owned_output(source, data, destination, hashlib.sha256(manifest_text.encode("utf-8")).hexdigest())
        raise
    return manifest
