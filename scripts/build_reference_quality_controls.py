"""Build bounded, source-linked editorial reproduction cases from frozen cells.

These are local reproduction fixtures, never new-project execution evidence.
The selected original cells and original source defects remain in the selection
file; each non-verbatim field mapping is declared in fixture notes.
"""
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
import argparse
import json
from pathlib import Path
import shutil
import unicodedata
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
COLLECTIONS = ("requirements", "features", "screens", "programs", "database_tables", "test_cases", "defects", "deployment_items", "operation_periods", "progress_reports", "meetings", "changes", "kpis", "trace_links", "attachments", "reviews")
NOTICE = "참고 원문 비교자료(제출용 아님·새 사업 사실 아님)"


def rows(selection):
    result = defaultdict(dict)
    for cell in selection["cells"]:
        result[int(cell["address"]["rowAddr"])][int(cell["address"]["colAddr"])] = cell["text_verbatim"]
    return result


def base(role, selection, *, output_dir=None, reference_root=None, asset_manifest=None, selection_base=None):
    source = selection["source"]
    output_dir = Path(output_dir or ROOT / "outputs/reference-quality-controls").resolve()
    original = Path(source["path"])
    if not original.is_absolute():
        original = Path(selection_base or ROOT) / original
    if reference_root is not None:
        name = unicodedata.normalize("NFC", original.name)
        matches = [p for p in Path(reference_root).expanduser().resolve().rglob("*.hwpx")
                   if unicodedata.normalize("NFC", p.name) == name
                   and sha256(p.read_bytes()).hexdigest() == source["sha256"]]
        if len(matches) != 1:
            raise ValueError("Expected one reference source with the selected filename and SHA: " + name)
        original = matches[0]
    if not original.is_file():
        raise ValueError("Reference source is unavailable; provide --reference-root with the read-only original corpus: " + str(original))
    if sha256(original.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError("Reference source changed")
    copy = output_dir / "sources" / original.name
    copy.parent.mkdir(parents=True, exist_ok=True)
    if copy.exists() and sha256(copy.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError("Refusing to replace a different reference source copy: " + str(copy))
    shutil.copyfile(original, copy)
    sid = "SOURCE-CONTROL-" + role
    ref = lambda locator: [{"source_id": sid, "locator": locator}]
    project = {"id": "STYLE-CONTROL-" + role, "name": "참고 문안 편집 재현 실험(새 사업·실제 수행 자료 아님)", "status": "unverified", "source_refs": ref(selection["table_locator"]),
               "requested_deliverables": [role], "program_name": "참고자료 편집 재현 실험", "program_year": None, "template_version": "V2.0 (재현 시험)",
               "customer": {"name": "참고 문안 재현", "status": "unverified", "source_refs": ref(selection["table_locator"])}, "supplier": {"name": "문서 자동화 검증", "status": "unverified", "source_refs": ref(selection["table_locator"])},
               "start_date": None, "end_date": None, "notes": "원문 비교용 로컬 실험. 원문의 수행·설치·승인 문구는 미검증 참고 문안이며 새로운 사실로 사용하지 않음."}
    data = {"schema_version": "1.0", "dataset_kind": "reference_extraction", "project": project,
            "sources": [{"id": sid, "title": "참고 문안 재현 실험의 원본 사본", "kind": "reference_document", "path": str(copy), "sha256": source["sha256"], "verification_status": "provided"}],
            **{key: [] for key in COLLECTIONS}, "extraction_issues": [], "submission_ready": False}
    return data, ref


def item(identifier, name, refs, **fields):
    return {"id": identifier, "name": name, "status": "unverified", "source_refs": refs, **fields}


def requirement(identifier, name, description, refs, kind="functional", notes=None):
    return item(identifier, name, refs, system_name="참고 문안 재현", business_area=None, kind=kind, change_type=None,
                description=description, details=[], constraints=[], owner={"name": None, "review_status": "unverified"}, notes=notes)


def td5(selection, **kwargs):
    data, ref = base("SF-TD5", selection, **kwargs)
    grouped = {}
    for row, cells in rows(selection).items():
        if row == 0:
            continue
        tid = cells[1]
        if tid not in grouped:
            grouped[tid] = item(tid, cells[0], ref(f"{selection['table_locator']}/R{row}C1"),
                description="참고자료의 동일 테이블 문안 재현. 실제 DB 구현·설치·검증 자료 아님.", columns=[],
                notes="원문은 컬럼명/컬럼ID 헤더와 실제 값의 의미가 전치되어 있다. 재현 입력에서는 C2를 물리 ID, C3를 논리명으로 명시적으로 대응한다. 원문 셀 전체는 same-content-selections.json에 보존한다.")
        pk, fk = cells.get(5, ""), cells.get(6, "")
        key = "primary_foreign" if pk == fk == "Y" else "primary" if pk == "Y" else "foreign" if fk == "Y" else None
        null = cells.get(7, "")
        nullable = False if null.casefold().replace(" ", "") == "notnull" else True if null.casefold() == "null" else None
        grouped[tid]["columns"].append(item(cells[2], cells[3], ref(f"{selection['table_locator']}/R{row}C2"),
            type=cells[4], length=None, nullable=nullable, key=key, default_value=cells.get(8, ""), encryption=None,
            notes=f"참고 원문 PK={pk!r}; FK={fk!r}; NULL={null!r}; 디폴트={cells.get(8, '')!r}; 비고={cells.get(9, '')!r}. 빈 칸은 확정적인 미적용 판정으로 바꾸지 않음."))
    data["database_tables"] = list(grouped.values())
    return data


def td3(selection, **kwargs):
    data, ref = base("SF-TD3", selection, **kwargs)
    r = rows(selection)
    screen = item(r[0][1], r[0][3], ref(selection["table_locator"]), system_name="참고 문안 재현", path=r[1][1],
        description="참고 화면 명세와 그림의 편집 재현 실험. 새로운 실제 화면·승인·수행 자료 아님.", change_type=None,
        steps=[r[3][1]], checks=[r[4][1]], requirement_ids=[], feature_ids=[], program_ids=[],
        notes="주요 항목 설명·처리순서·필수입력 원문을 하나의 문안으로 보존. 원문의 오탈자도 임의 정정하지 않음.")
    if selection.get("figures") and kwargs.get("asset_manifest") is None:
        raise ValueError("Reference figures require an explicit private --asset-manifest")
    assets = json.loads(Path(kwargs["asset_manifest"]).read_text())["records"] if kwargs.get("asset_manifest") else []
    for index, figure in enumerate(selection.get("figures", []), 1):
        aid = f"REFERENCE-CONTROL-TD3-FIGURE-{index}"
        # Selection records preserve binaryItemIDRef, package member and SHA.
        match = next((a for a in assets if a["document_id"] == "reference-sf-td3" and a["sha256"] == figure.get("binary_sha256")), None)
        if match is None:
            raise ValueError("Selected reference picture is missing from the source asset catalog: " + str(figure.get("binary_sha256")))
        if match["source_sha256"] != selection["source"]["sha256"] or match["package_path"] != figure["zip_member"]:
            raise ValueError("Selected reference picture source/member binding differs")
        # Extract the exact selected member from the verified original copy.
        # Old analysis asset_path is historical metadata and is never read.
        source_copy = Path(data["sources"][0]["path"])
        with ZipFile(source_copy) as archive:
            blob = archive.read(match["package_path"])
        if sha256(blob).hexdigest() != match["sha256"]:
            raise ValueError("Selected reference picture bytes differ from recorded SHA")
        path = source_copy.parent.parent / "assets" / (match["sha256"] + ".bmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != blob:
            raise ValueError("Refusing to replace different selected picture bytes: " + str(path))
        path.write_bytes(blob)
        data["attachments"].append(item(aid, "참고 원본 그림 재현 시험", ref(selection["table_locator"]), path=str(path), sha256=match["sha256"],
            source_id=data["sources"][0]["id"], purpose="같은 원본 그림의 배치·가독성 재현 비교", verification_status="provided", media_type="image/bmp",
            caption="참고 원본 그림 재현 시험·새 사업의 실제 화면 아님", notes="출처 문서의 그림을 원문 비교용으로만 사용. 수행·승인 사실은 검증하지 않음."))
        screen.setdefault("after_attachment_ids", []).append(aid)
    data["screens"] = [screen]
    return data


def pm4(selections, **kwargs):
    selection = selections[0]
    data, ref = base("SF-PM4", selection, **kwargs)
    seen_tests = {}
    for selection in selections:
        for row, c in rows(selection).items():
            if row == 0:
                continue
            functional = len(c) == 9
            refs = ref(f"{selection['table_locator']}/R{row}C1")
            raw_notes = None if functional else "참고 원문 주장(진위 미검증·새 사업 결과 아님):\n결과물명: " + c[4] + "\n추진 현황: " + c[5] + "\n비고: " + c[6]
            data["requirements"].append(requirement(c[1], c[2], c[3], refs, "functional" if functional else "nonfunctional", raw_notes))
            if not functional:
                continue
            rid, screen_id, program_id = c[1], c[4], c[5]
            data["screens"].append(item(screen_id, c[2], refs, system_name="참고 문안 재현", path=None, description=c[3], change_type=None, steps=[], checks=[], requirement_ids=[rid], feature_ids=[], program_ids=[program_id]))
            data["programs"].append(item(program_id, c[2], refs, system_name="참고 문안 재현", description=c[3], change_type=None, functions=[], requirement_ids=[rid], screen_ids=[screen_id], table_ids=[]))
            for column, stage in ((6, "unit"), (7, "integration"), (8, "acceptance")):
                tid = c[column]
                if tid not in seen_tests:
                    test = item(tid, "참고 추적표의 시험 ID 연결 재현", refs, stage=stage, scenario="연결 ID의 편집 재현 fixture이며 실제 시험 시나리오를 확정하지 않음.", data=None, expected=None, actual=None, result="planned", execution_date=None, executor=None, evidence_ids=[], requirement_ids=[rid])
                    seen_tests[tid] = test
                    data["test_cases"].append(test)
                else:
                    seen_tests[tid]["requirement_ids"].append(rid)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selections", type=Path, required=True, help="Private source-linked selected cells/figures JSON; not a public resource")
    parser.add_argument("--asset-manifest", type=Path, help="Private original-picture metadata when selected figures are present")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/reference-quality-controls")
    parser.add_argument("--reference-root", type=Path, help="Read-only original reference corpus; select exact original filenames and SHA")
    args = parser.parse_args()
    selections = json.loads(args.selections.expanduser().resolve().read_text())["selections"]
    folder = args.output_dir.expanduser().resolve()
    if not folder.is_relative_to(ROOT / "outputs"):
        parser.error("Output directory must be inside this checkout's ignored outputs/ directory")
    folder.mkdir(parents=True, exist_ok=True)
    kwargs = {"output_dir": folder, "reference_root": args.reference_root, "asset_manifest": args.asset_manifest, "selection_base": args.selections.resolve().parent}
    cases = {"SF-TD5": td5(next(x for x in selections if x["role"] == "SF-TD5"), **kwargs),
             "SF-TD3": td3(next(x for x in selections if x["role"] == "SF-TD3"), **kwargs),
             "SF-PM4": pm4([x for x in selections if x["role"] == "SF-PM4"], **kwargs)}
    for role, data in cases.items():
        path = folder / f"control-{role[3:].lower()}.project.json"
        encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
        if path.exists() and path.read_bytes() != encoded:
            raise ValueError("Refusing to overwrite a different control input; use a new output directory: " + str(path))
        path.write_bytes(encoded)
        print(path)


if __name__ == "__main__":
    main()
