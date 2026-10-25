"""Geometry fixtures are synthetic; named native cases reuse recorded exports."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

from lxml import etree as ET
import pymupdf
from corpus_sources import pinned_source_path
import pytest

from doc_automation.compose import HP, TemplateDocument
from doc_automation.hwpx import own_text
from doc_automation.renderers import _toc_entries, generate_project
from doc_automation.toc import TocError, PENDING, check_toc_convergence, finalize_toc, measure_toc

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "examples/demo.project.json"
DATA = json.loads(DATASET.read_text())
PILOT = ROOT / "verification/generation-pilot"
GENERATED = ROOT / "verification/generated"
SEED_NATIVE_CASES = (
    [("toc-v3-pass1", role) for role in ("SF-AD1", "SF-TD1", "SF-TD2")]
    + [("toc-v4-pass1", "SF-TD3")]
    + [("toc-v4-ready13", role) for role in
       ("SF-TD4", "SF-TD5", "SF-CD1", "SF-TI1", "SF-TI3", "SF-TI4", "SF-OS2")]
)
HISTORICAL_ASSERTIVE_LABEL_CASES = [("toc-v4-ready13", role) for role in ("SF-TI2", "SF-OS1")]
FIXED_NATIVE_CASES = (
    [("toc-fixedpoint-pass1", role) for role in
     ("SF-AD1", "SF-TD1", "SF-TD2", "SF-TD3", "SF-TD4")]
    + [("toc-v4-fixedpoint", role) for role in ("SF-TD4", "SF-TD5", "SF-CD1")]
)


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def recorded_native_case(directory, role):
    """Reuse an existing native association; never associate a new HWPX with its PDF."""
    path = GENERATED / directory / (role + ".json")
    if not path.exists():
        pytest.fail("Selected native regression requires recorded evidence: " + str(path))
    record = json.loads(path.read_text())
    hwpx, pdf, dataset = (
        Path(record["input_hwpx"]), Path(record["native_pdf"]), Path(record["input_dataset"]["path"]))
    if not all(item.exists() for item in (hwpx, pdf, dataset)):
        pytest.fail("Selected native regression requires every HWPX/PDF/dataset bound by: " + str(path))
    assert digest(hwpx) == record["input_sha256"] == record["native_source_sha256"]
    assert digest(pdf) == record["native_pdf_sha256"]
    assert digest(dataset) == record["input_dataset"]["sha256"]
    return record, hwpx, pdf, dataset


def assert_outside_toc_preserved(before, after, locator):
    """Compare whole XML subtrees, including owned text, tails, controls and tables."""
    assert before.sections == after.sections
    for member in before.sections:
        left, right = before.xml(member), after.xml(member)
        assert dict(left.attrib) == dict(right.attrib)
        assert len(left) == len(right)
        for original, revised in zip(left, right):
            if member == locator["section"] and left.getroottree().getpath(original) == locator["xpath"]:
                continue
            assert ET.tostring(original) == ET.tostring(revised), (member, left.getroottree().getpath(original))
    assert ET.tostring(before.xml("Contents/header.xml")) == ET.tostring(after.xml("Contents/header.xml"))


@pytest.mark.native
def test_native_td5_finalization_preserves_first_table_description_and_unique(tmp_path):
    record, hwpx, pdf, dataset = recorded_native_case("toc-v4-ready13", "SF-TD5")
    assert digest(hwpx) == "dde4a871ae168af5e3fa5fb8355eea3273afc3f4b56cb1294d9abaaa89eaec91"
    assert digest(pdf) == "7bf67d16dac7b2359088b7d5431a02f4b10f5c234007a600846bc31be0f97a9b"
    before = TemplateDocument(hwpx)
    metadata = list(before.root())[30]
    assert "설계 설명:" in own_text(metadata)
    assert "복합 UNIQUE 설계안: work_date, work_order_no, batch_no" in own_text(metadata)
    output = tmp_path / "TD5-preserved.hwpx"
    result = finalize_toc(hwpx, pdf, dataset, "SF-TD5", output, record["input_sha256"],
                          native_pdf_sha256=record["native_pdf_sha256"])
    after = TemplateDocument(output)
    assert own_text(list(after.root())[30]) == own_text(metadata)
    assert_outside_toc_preserved(before, after, record["toc_locator"])
    assert result["status"] == "updated" and result["native_status"] == "pending_reexport"


@pytest.mark.parametrize("directory,role", SEED_NATIVE_CASES)
@pytest.mark.native
def test_recorded_native_seed_changes_only_explicit_toc_paragraph(directory, role, tmp_path):
    record, hwpx, pdf, dataset = recorded_native_case(directory, role)
    output = tmp_path / (role + ".hwpx")
    result = finalize_toc(hwpx, pdf, dataset, role, output, record["input_sha256"],
                          native_pdf_sha256=record["native_pdf_sha256"])
    assert result["status"] == "updated"
    assert [(item["label"], item["page_label"]) for item in result["entries"]] == [
        (item["label"], item["page_label"]) for item in record["entries"]]
    assert_outside_toc_preserved(TemplateDocument(hwpx), TemplateDocument(output), record["toc_locator"])


@pytest.mark.parametrize("directory,role", HISTORICAL_ASSERTIVE_LABEL_CASES)
@pytest.mark.native
def test_historical_installation_and_support_toc_labels_are_rejected_without_mutation(directory, role, tmp_path):
    """Old native pairs stay intact; current labels do not assert nonexecution."""
    record, hwpx, pdf, dataset = recorded_native_case(directory, role)
    before = {path: path.read_bytes() for path in (hwpx, pdf, dataset)}
    output = tmp_path / (role + "-neutral-label-profile.hwpx")
    with pytest.raises(TocError) as error:
        finalize_toc(hwpx, pdf, dataset, role, output, record["input_sha256"],
                     native_pdf_sha256=record["native_pdf_sha256"])
    assert error.value.report["code"] == "TOC_CONTENT_MISMATCH"
    assert not output.exists()
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("role", ["SF-TI2", "SF-OS1"])
@pytest.mark.corpus
def test_current_neutral_section_labels_finalize_with_synthetic_geometry_and_preserve_scope(make, tmp_path, role):
    """Synthetic PDF geometry is parser/scope evidence, never native QA."""
    from doc_automation.toc import SECTION_ALIASES
    body = [[(40, 100, heading)] for heading in SECTION_ALIASES[role]]
    hwpx, pdf = make(role=role, body=body)
    before = TemplateDocument(hwpx)
    output = tmp_path / (role + "-current-finalized.hwpx")
    result = finalize_toc(hwpx, pdf, DATASET, role, output, digest(hwpx), native_pdf_sha256=digest(pdf))
    assert result["status"] == "updated" and result["native_status"] == "pending_reexport"
    assert [entry["label"] for entry in result["entries"]] == _toc_entries(role, DATA)
    assert [entry["printed_page"] for entry in result["entries"]] == [1, 2, 3, 4]
    assert [entry["pdf_page"] for entry in result["entries"]] == [3, 4, 5, 6]
    assert_outside_toc_preserved(before, TemplateDocument(output), result["toc_locator"])
    assert not result["pdf_reuse_allowed"]


@pytest.mark.parametrize("directory,role", FIXED_NATIVE_CASES)
@pytest.mark.native
def test_recorded_native_fixedpoints_still_write_nothing(directory, role, tmp_path):
    record, hwpx, pdf, dataset = recorded_native_case(directory, role)
    output = tmp_path / (role + ".hwpx")
    result = finalize_toc(hwpx, pdf, dataset, role, output, record["input_sha256"],
                          native_pdf_sha256=record["native_pdf_sha256"])
    assert result["status"] == "unchanged" and not result["output_written"]
    assert not output.exists() and digest(hwpx) == record["input_sha256"]


@pytest.fixture
def make(tmp_path):
    def fixture(role="SF-AD2", body=None, *, footers=True, input_dataset=DATASET):
        inventory = json.loads((ROOT / "resources/stage1/inventory.json").read_text())
        source = pinned_source_path(next(item for item in inventory["documents"]
                      if item["id"] == "template-" + role.lower()))
        if not Path(source).exists():
            pytest.fail("Selected corpus test requires the read-only source corpus: " + str(source))
        facts = json.loads(Path(input_dataset).read_text())
        manifest = generate_project(input_dataset, tmp_path / role, roles=[role])
        hwpx = Path(manifest["documents"][0]["path"])
        labels = _toc_entries(role, facts)
        if body is None:
            body = [[(40, 100, "요구사항 ID"), (150, 100, item["id"]), (300, 100, "요구사항명")]
                    for item in facts["requirements"]]
        pdf_path = tmp_path / (role + ".pdf")
        pdf = pymupdf.open()
        cover = pdf.new_page(width=595, height=842)
        cover.insert_text((40, 60), "Synthetic PDF geometry fixture", fontsize=10)
        toc = pdf.new_page(width=595, height=842)
        toc.insert_text((40, 80), "목 차", fontname="korea", fontsize=12)
        for index, label in enumerate(labels):
            toc.insert_text((40, 110 + index * 22), label, fontname="korea", fontsize=9)
        toc.insert_text((40, 150 + len(labels) * 22), PENDING, fontname="korea", fontsize=9)
        for number, records in enumerate(body, 1):
            page = pdf.new_page(width=595, height=842)
            for x, y, text in records:
                page.insert_text((x, y), text, fontname="korea", fontsize=10)
            if footers:
                page.insert_text((285, 800), f"- {number} -", fontsize=10)
        pdf.save(pdf_path)
        pdf.close()
        return hwpx, pdf_path
    return fixture


def measured(hwpx, pdf, role="SF-AD2", **kwargs):
    return measure_toc(hwpx, pdf, DATASET, role, digest(hwpx), native_pdf_sha256=digest(pdf), **kwargs)


@pytest.mark.parametrize("stem", ["AD2-fixed", "AD2-toc-pass1"])
@pytest.mark.native
def test_historical_native_ad2_linear_toc_is_rejected_by_grouped_profile(stem):
    hwpx, pdf = PILOT / (stem + ".hwpx"), PILOT / (stem + ".pdf")
    if not hwpx.exists() or not pdf.exists():
        pytest.fail("Selected native regression requires local pilot HWPX/PDF: " + str(hwpx))
    before = hwpx.read_bytes(), pdf.read_bytes()
    with pytest.raises(TocError) as error:
        measured(hwpx, pdf)
    assert error.value.report["code"] == "TOC_CONTENT_MISMATCH"
    assert before == (hwpx.read_bytes(), pdf.read_bytes())


@pytest.mark.parametrize("directory", ["toc-v3-pass1", "toc-fixedpoint-pass1"])
@pytest.mark.native
def test_historical_recorded_ad2_profile_refuses_to_write(directory, tmp_path):
    record, hwpx, pdf, facts = recorded_native_case(directory, "SF-AD2")
    output = tmp_path / "historical-profile.hwpx"
    before = hwpx.read_bytes()
    with pytest.raises(TocError) as error:
        finalize_toc(hwpx, pdf, facts, "SF-AD2", output, record["input_sha256"],
                     native_pdf_sha256=record["native_pdf_sha256"])
    assert error.value.report["code"] == "TOC_CONTENT_MISMATCH"
    assert hwpx.read_bytes() == before and not output.exists()


@pytest.mark.corpus
def test_grouped_ad2_measures_each_card_and_preserves_non_toc_scope(make, tmp_path):
    data = deepcopy(DATA)
    # Reverse classification order and retain null as its own final group.
    for requirement, kind in zip(data["requirements"], [None, "nonfunctional", "functional"]):
        requirement["kind"] = kind
    for collection in ("sources", "attachments"):
        for item in data[collection]:
            if item.get("path") and not Path(item["path"]).is_absolute():
                item["path"] = str((DATASET.parent / item["path"]).resolve())
    facts = tmp_path / "reverse-classifications.json"
    facts.write_text(json.dumps(data, ensure_ascii=False))
    expected = [data["requirements"][i] for i in [2, 1, 0]]
    body = [[(40, 100, "요구사항 ID"), (150, 100, item["id"]), (300, 100, "요구사항명")] for item in expected]
    hwpx, pdf = make(body=body, input_dataset=facts)
    before = TemplateDocument(hwpx)
    output = tmp_path / "grouped-finalized.hwpx"
    result = finalize_toc(hwpx, pdf, facts, "SF-AD2", output, digest(hwpx), native_pdf_sha256=digest(pdf))
    assert [entry["identifier"] for entry in result["entries"]] == [r["id"] for r in expected]
    assert [entry["printed_page"] for entry in result["entries"]] == [1, 2, 3]
    assert [entry["pdf_page"] for entry in result["entries"]] == [3, 4, 5]
    assert [entry["label"].splitlines()[0] for entry in result["entries"]] == [
        "1. 기능 요구사항(SW)", "2. 비기능 요구사항(HW 등)", "3. 유형 미확인 요구사항"]
    assert all(e["context"]["kind"] == "detail_card_id_name_band" for e in result["entries"])
    assert_outside_toc_preserved(before, TemplateDocument(output), result["toc_locator"])
    assert result["native_status"] == "pending_reexport" and not result["pdf_reuse_allowed"]


@pytest.mark.corpus
def test_finalization_is_scoped_black_and_requires_new_native_export(make, tmp_path):
    hwpx, pdf = make()
    before = TemplateDocument(hwpx)
    output = tmp_path / "finalized.hwpx"
    result = finalize_toc(hwpx, pdf, DATASET, "SF-AD2", output, digest(hwpx), native_pdf_sha256=digest(pdf))
    after = TemplateDocument(output)
    with ZipFile(hwpx) as original, ZipFile(output) as revised:
        assert original.read("Contents/section1.xml") == revised.read("Contents/section1.xml")
    assert [ET.tostring(table) for table in before.tables()] == [ET.tostring(table) for table in after.tables()]
    assert [ET.tostring(node) for node in before.root().iter(HP + "secPr")] == [ET.tostring(node) for node in after.root().iter(HP + "secPr")]
    text = "\n".join(own_text(p) for p in after.paragraphs())
    assert PENDING not in text and "... 1" in text and "... 3" in text
    assert result["native_status"] == "pending_reexport" and not result["pdf_reuse_allowed"]
    assert result["input_sha256"] != result["output_sha256"] and result["output_written"]
    assert digest(hwpx) == result["input_sha256"]


@pytest.mark.parametrize("mode", ["suffix", "prefix", "missing_pending", "split", "invalid_page", "two_headings"])
@pytest.mark.corpus
def test_uncertain_toc_text_is_rejected_without_erasing_body(make, tmp_path, mode):
    hwpx, pdf = make()
    doc = TemplateDocument(hwpx)
    toc = next(p for p in doc.root() if PENDING in own_text(p))
    current = own_text(toc)
    if mode == "suffix":
        doc.set_paragraph_text(toc, current + "\n본문 설계 설명과 UNIQUE는 삭제할 수 없다.")
    elif mode == "prefix":
        doc.set_paragraph_text(toc, "본문 고지\n" + current)
    elif mode == "missing_pending":
        doc.set_paragraph_text(toc, current.replace(PENDING, ""))
    elif mode == "split":
        first, rest = current.split("\n", 1)
        doc.set_paragraph_text(doc.clone_paragraph(toc, insert_after=True), rest)
        doc.set_paragraph_text(toc, first)
    elif mode == "invalid_page":
        doc.set_paragraph_text(toc, "\n".join(label + " ... 미확인" for label in _toc_entries("SF-AD2", DATA)))
    else:
        heading = next(p for p in doc.root() if own_text(p).replace(" ", "") == "목차")
        doc.clone_paragraph(heading, insert_after=True)
    uncertain = tmp_path / "uncertain.hwpx"
    doc.save(uncertain)
    before = uncertain.read_bytes()
    output = tmp_path / "keep-existing.hwpx"
    output.write_bytes(b"existing output")
    with pytest.raises(TocError) as error:
        finalize_toc(uncertain, pdf, DATASET, "SF-AD2", output, digest(uncertain), native_pdf_sha256=digest(pdf))
    assert error.value.report["code"] in {"TOC_CONTENT_MISMATCH", "TOC_REGION"}
    assert uncertain.read_bytes() == before and output.read_bytes() == b"existing output"


@pytest.mark.corpus
def test_one_logical_toc_paragraph_can_span_two_pdf_pages(make, tmp_path):
    hwpx, original_pdf = make()
    pdf_path = tmp_path / "two-toc-pages.pdf"
    labels = _toc_entries("SF-AD2", DATA)
    with pymupdf.open(original_pdf) as original, pymupdf.open() as pdf:
        pdf.insert_pdf(original, from_page=0, to_page=0)
        first = pdf.new_page(width=595, height=842)
        first.insert_text((40, 80), "목 차", fontname="korea", fontsize=12)
        for index, label in enumerate(labels[:-1]):
            first.insert_text((40, 110 + index * 22), label, fontname="korea", fontsize=9)
        last = pdf.new_page(width=595, height=842)
        last.insert_text((40, 80), labels[-1], fontname="korea", fontsize=9)
        last.insert_text((40, 120), PENDING, fontname="korea", fontsize=9)
        pdf.insert_pdf(original, from_page=2)
        pdf.save(pdf_path)
    result = measured(hwpx, pdf_path)
    assert result["toc_pdf_pages"] == [2, 3]
    assert [entry["pdf_page"] for entry in result["entries"]] == [4, 5, 6]
    assert [entry["page_label"] for entry in result["entries"]] == ["1", "2", "3"]


@pytest.mark.corpus
def test_stale_source_or_pdf_hash_fails_before_output_write(make, tmp_path):
    hwpx, pdf = make()
    output = tmp_path / "existing.hwpx"
    output.write_bytes(b"keep this output")
    with pytest.raises(TocError) as error:
        finalize_toc(hwpx, pdf, DATASET, "SF-AD2", output, "0" * 64)
    assert error.value.report["code"] == "STALE_NATIVE_SOURCE"
    with pytest.raises(TocError) as error:
        finalize_toc(hwpx, pdf, DATASET, "SF-AD2", output, digest(hwpx), native_pdf_sha256="0" * 64)
    assert error.value.report["code"] == "STALE_NATIVE_PDF"
    assert output.read_bytes() == b"keep this output"


@pytest.mark.corpus
def test_missing_exact_id_does_not_match_longer_identifier(make):
    body = [[(40, 100, "요구사항 ID"), (150, 100, item["id"] + ("0" if i == 2 else "")),
             (300, 100, "요구사항명")] for i, item in enumerate(DATA["requirements"])]
    hwpx, pdf = make(body=body)
    with pytest.raises(TocError) as error:
        measured(hwpx, pdf)
    assert error.value.report["code"] == "BODY_ANCHOR_MISSING"
    assert error.value.report["entry"]["identifier"] == DATA["requirements"][2]["id"]


@pytest.mark.corpus
def test_incidental_body_mention_is_not_a_detail_anchor(make):
    records = [[(40, 100, DATA["requirements"][0]["id"])]]
    records += [[(40, 100, "요구사항 ID"), (150, 100, item["id"]), (300, 100, "요구사항명")]
                for item in DATA["requirements"]]
    hwpx, pdf = make(body=records)
    result = measured(hwpx, pdf)
    assert result["entries"][0]["pdf_page"] == 4 and result["entries"][0]["printed_page"] == 2


@pytest.mark.corpus
def test_without_printed_footer_uses_explicit_pdf_page(make):
    hwpx, pdf = make(footers=False)
    result = measured(hwpx, pdf)
    assert [entry["page_label"] for entry in result["entries"]] == ["PDF 3쪽", "PDF 4쪽", "PDF 5쪽"]
    assert all(entry["page_basis"] == "explicit_pdf_page" for entry in result["entries"])


@pytest.mark.corpus
def test_td3_menu_ids_do_not_replace_detail_card_page(make):
    first = [(40, 80, "1. 화면 표준(검토안)"), (40, 130, "2. 메뉴구조도(권한 설계안)"),
             (40, 200, "3. 화면(보고서) 설계")]
    first += [(40, 240 + i * 20, screen["id"]) for i, screen in enumerate(DATA["screens"])]
    body = [first] + [[(40, 100, "화면(보고서) ID"), (160, 100, screen["id"]),
                       (320, 100, "화면(보고서)명")] for screen in DATA["screens"]]
    body += [[(40, 100, "4. 화면 검토 결과")]]
    hwpx, pdf = make("SF-TD3", body)
    result = measured(hwpx, pdf, "SF-TD3")
    assert result["entries"][3]["pdf_page"] == 4
    assert result["entries"][4]["pdf_page"] == 5


@pytest.mark.corpus
def test_td5_notice_ids_and_wrapped_table_ids_use_header_column(make):
    body = [[(40, 100, "전체 테이블: " + ", ".join(table["id"] for table in DATA["database_tables"]))]]
    for table in DATA["database_tables"]:
        identifier = table["id"]
        body.append([(30, 100, "테이블명"), (160, 100, "테이블ID"),
                     (290, 100, "컬럼명"), (410, 100, "컬럼ID"),
                     (160, 140, identifier[:10]), (160, 154, identifier[10:]),
                     (410, 145, table["columns"][0]["id"])])
    hwpx, pdf = make("SF-TD5", body)
    result = measured(hwpx, pdf, "SF-TD5")
    assert [entry["pdf_page"] for entry in result["entries"]] == [4, 5]
    assert all(entry["context"]["kind"] == "table_id_column" for entry in result["entries"])


@pytest.mark.corpus
def test_td2_explicit_heading_aliases(make):
    body = [[(40, 100 + i * 40, heading) for i, heading in enumerate([
        "1. 시스템 구성도", "2. 하드웨어 구성도", "3. 소프트웨어 구성도", "4. 네트워크 구성도",
        "5. 장비 도입 및 설치 계획", "6. 클라우드 서비스 이용 내용"])]]
    hwpx, pdf = make("SF-TD2", body)
    result = measured(hwpx, pdf, "SF-TD2")
    assert len(result["entries"]) == 6
    assert result["entries"][1]["anchor"] == "2. 하드웨어 구성도"


@pytest.mark.corpus
def test_no_toc_role_is_not_applicable_and_writes_nothing(make, tmp_path):
    hwpx, pdf = make("SF-AD3")
    output = tmp_path / "not-created.hwpx"
    result = finalize_toc(hwpx, pdf, DATASET, "SF-AD3", output, digest(hwpx))
    assert result["status"] == "not_applicable" and not result["output_written"]
    assert not output.exists() and result["active_hwpx"] == str(hwpx)


@pytest.mark.corpus
def test_bad_previous_manifest_cannot_write_a_new_output(make, tmp_path):
    hwpx, pdf = make()
    output = tmp_path / "no-write.hwpx"
    with pytest.raises(TocError) as error:
        finalize_toc(hwpx, pdf, DATASET, "SF-AD2", output, digest(hwpx), previous_manifest={"output_sha256": "wrong"})
    assert error.value.report["code"] == "CONVERGENCE_SOURCE_MISMATCH" and not output.exists()


def test_old_pdf_cannot_establish_convergence():
    previous = {"output_sha256": "new-hwpx", "native_pdf_sha256": "old-pdf"}
    current = {"input_sha256": "new-hwpx", "native_pdf_sha256": "old-pdf"}
    with pytest.raises(TocError) as error:
        check_toc_convergence(previous, current)
    assert error.value.report["code"] == "OLD_PDF_REUSED"


@pytest.mark.corpus
def test_input_path_is_never_overwritten(make):
    hwpx, pdf = make()
    before = hwpx.read_bytes()
    with pytest.raises(TocError) as error:
        finalize_toc(hwpx, pdf, DATASET, "SF-AD2", hwpx, digest(hwpx))
    assert error.value.report["code"] == "OUTPUT_IS_INPUT" and hwpx.read_bytes() == before


@pytest.mark.corpus
def test_cli_stale_hash_writes_failure_manifest(make, tmp_path):
    hwpx, pdf = make()
    report, output = tmp_path / "failure.json", tmp_path / "no-output.hwpx"
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/finalize_toc.py"), str(hwpx), str(pdf),
                           "--dataset", str(DATASET), "--role", "SF-AD2", "--output", str(output),
                           "--native-source-sha256", "0" * 64, "--native-pdf-sha256", digest(pdf),
                           "--manifest", str(report)], capture_output=True, text=True)
    assert proc.returncode == 2
    assert json.loads(report.read_text())["code"] == "STALE_NATIVE_SOURCE" and not output.exists()
