from pathlib import Path
from hashlib import sha256
import json
import pymupdf

ROOT = Path(__file__).resolve().parents[1]


def main():
    records = []
    for stage, kind in (("stage1", "templates"), ("stage2", "references")):
        inventory = json.loads((ROOT/f"resources/{stage}/inventory.json").read_text())
        renders = json.loads((ROOT/f"verification/baselines/{kind}/render-manifest.json").read_text())
        rendered = {Path(d["pdf"]).stem: d for d in renders["documents"]}
        for d in inventory["documents"]:
            copy = ROOT/f"verification/baselines/{kind}/{d['id']}.hwpx"
            pdf = copy.with_suffix(".pdf")
            record = {"id": d["id"], "source_sha256": d["sha256"], "source_unchanged": sha256(Path(d["source_path"]).read_bytes()).hexdigest() == d["sha256"], "opened_copy_unchanged": sha256(copy.read_bytes()).hexdigest() == d["sha256"], "pdf": str(pdf), "pdf_sha256": sha256(pdf.read_bytes()).hexdigest()}
            with pymupdf.open(pdf) as document:
                record["pages"] = len(document)
                record["pdf_metadata"] = document.metadata
            r = rendered[d["id"]]
            record["all_pages_rendered"] = record["pages"] == len(r["page_images"]) and all(Path(p).exists() for p in r["page_images"])
            record["passed"] = record["source_unchanged"] and record["opened_copy_unchanged"] and record["pages"] > 0 and record["all_pages_rendered"]
            records.append(record)
    result = {"scope": "Native PDF export availability, valid PDF parsing, full page rasterization, exact HWPX source/copy preservation. Does not establish semantic correctness or cross-version fidelity.", "documents": records, "document_count": len(records), "page_count": sum(r["pages"] for r in records), "passed": all(r["passed"] for r in records)}
    (ROOT/"verification/baselines/native-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ("document_count", "page_count", "passed")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
