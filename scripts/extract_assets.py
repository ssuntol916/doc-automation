"""Deduplicate package assets by SHA-256 while keeping per-document provenance."""
from pathlib import Path
from hashlib import sha256
import json
from zipfile import ZipFile
import argparse
from PIL import Image


def extract(folder: Path):
    destination = folder / "assets"
    destination.mkdir(exist_ok=True)
    inventory = json.loads((folder / "inventory.json").read_text())
    records = []
    for document in inventory["documents"]:
        with ZipFile(document["source_path"]) as z:
            for name in z.namelist():
                if not name.startswith("BinData/") or name.endswith("/"):
                    continue
                data = z.read(name)
                digest = sha256(data).hexdigest()
                asset = destination / (digest + Path(name).suffix.lower())
                if not asset.exists():
                    asset.write_bytes(data)
                record = {"document_id": document["id"], "source_sha256": document["sha256"], "package_path": name, "sha256": digest, "asset_path": str(asset.resolve()), "size_bytes": len(data)}
                try:
                    with Image.open(asset) as image:
                        record.update({"width_px": image.width, "height_px": image.height, "image_format": image.format})
                except Exception as error:
                    record["raster_read_error"] = str(error)
                records.append(record)
    result = {"scope": "All BinData assets, including unused assets; a package asset is not evidence of execution or approval", "asset_occurrences": len(records), "unique_sha256": len({r['sha256'] for r in records}), "records": records}
    (folder / "assets-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    result = extract(args.folder)
    print(json.dumps({k: result[k] for k in ("asset_occurrences", "unique_sha256")}))
