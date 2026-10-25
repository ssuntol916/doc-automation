"""Independent corpus checks: source hashes and literal XML text coverage."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import re
from zipfile import ZipFile

from lxml import etree as ET


def compact(s):
    return re.sub(r"\s+", "", s)


def audit(folder: Path):
    inventory = json.loads((folder / "inventory.json").read_text())
    checks = []
    for entry in inventory["documents"]:
        path = Path(entry["source_path"])
        d = json.loads((folder / "profiles" / f"{entry['id']}.json").read_text())
        failures = []
        if sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            failures.append("source_changed")
        with ZipFile(path) as z:
            for section in d["sections"]:
                root = ET.fromstring(z.read(section["name"]))
                paragraphs = root.xpath("//*[local-name()='p' and namespace-uri()='http://www.hancom.co.kr/hwpml/2011/paragraph']")
                if len(paragraphs) != len(section["paragraphs"]):
                    failures.append(f"{section['name']}:paragraph_count")
                    continue
                for p, output in zip(paragraphs, section["paragraphs"]):
                    literal = []
                    for t in p.xpath(".//*[local-name()='t' and namespace-uri()='http://www.hancom.co.kr/hwpml/2011/paragraph']"):
                        owners = t.xpath("ancestor::*[local-name()='p' and namespace-uri()='http://www.hancom.co.kr/hwpml/2011/paragraph'][1]")
                        if owners and owners[0] is p:
                            literal.extend(t.itertext())
                    if compact("".join(literal)) != compact(output["text"]):
                        failures.append(output["evidence"] + ":text_mismatch")
                source_tables = root.xpath("//*[local-name()='tbl' and namespace-uri()='http://www.hancom.co.kr/hwpml/2011/paragraph']")
                if len(source_tables) != len(section["tables"]):
                    failures.append(section["name"] + ":table_count")
        checks.append({"id": entry["id"], "sha256": entry["sha256"], "source_unchanged": "source_changed" not in failures, "failures": failures, "passed": not failures})
    result = {"scope": "Source preservation, paragraph literal text including inline tails, paragraph/table coverage; not native layout verification", "documents_checked": len(checks), "passed": all(c["passed"] for c in checks), "checks": checks}
    (folder / "extraction-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    result = audit(args.folder)
    print(json.dumps({"documents_checked": result["documents_checked"], "passed": result["passed"]}))
    raise SystemExit(0 if result["passed"] else 1)
