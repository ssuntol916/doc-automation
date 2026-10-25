"""Render every page with Poppler and create indexed contact sheets for review."""
from pathlib import Path
import argparse
from hashlib import sha256
import json
import math
import subprocess

from PIL import Image, ImageOps, ImageDraw
import pymupdf


def render(folder: Path, dpi: int = 96):
    output = folder / "rendered"
    output.mkdir(exist_ok=True)
    manifest = []
    manifest_path = folder / "render-manifest.json"
    previous = {}
    if manifest_path.exists():
        previous = {d["pdf"]: d for d in json.loads(manifest_path.read_text())["documents"]}
    for pdf in sorted(folder.glob("*.pdf")):
        digest = sha256(pdf.read_bytes()).hexdigest()
        prior = previous.get(str(pdf.resolve()))
        if prior and prior["sha256"] == digest and prior["dpi"] == dpi and all(Path(p).exists() for p in prior["page_images"] + prior["contact_sheets"]):
            manifest.append(prior)
            continue
        target = output / pdf.stem
        target.mkdir(exist_ok=True)
        for stale_page in target.glob("page-*.png"):
            stale_page.unlink()
        for stale_sheet in target.glob("contact-*.png"):
            stale_sheet.unlink()
        prefix = target / "page"
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(prefix)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        pages = sorted(target.glob("page-*.png"))
        document = pymupdf.open(pdf)
        if len(pages) != len(document):
            raise ValueError(f"Rendered page count mismatch: {pdf}")
        texts = [p.get_text() for p in document]
        (target / "text.txt").write_text("\n\f\n".join(texts))
        sheets = []
        for start in range(0, len(pages), 6):
            selected = pages[start:start+6]
            sheet = Image.new("RGB", (3*420, 2*620), "#dddddd")
            draw = ImageDraw.Draw(sheet)
            for pos, page in enumerate(selected):
                with Image.open(page) as im:
                    tile = ImageOps.contain(im.convert("RGB"), (410, 585))
                    x = (pos%3)*420 + (420-tile.width)//2
                    y = (pos//3)*620 + 25
                    sheet.paste(tile, (x,y))
                    draw.text(((pos%3)*420+10, (pos//3)*620+5), f"Page {start+pos+1}", fill="black")
            dest = target / f"contact-{start//6+1:03}.png"
            sheet.save(dest)
            sheets.append(str(dest.resolve()))
        manifest.append({"pdf": str(pdf.resolve()), "sha256": digest, "pages": len(document), "pdf_metadata": document.metadata, "renderer": "Poppler pdftoppm", "dpi": dpi, "page_images": [str(p.resolve()) for p in pages], "contact_sheets": sheets, "visual_review_status": "pending", "text_extraction_is_not_visual_verification": True})
        document.close()
    result = {"documents": manifest, "document_count": len(manifest), "page_count": sum(d["pages"] for d in manifest)}
    (folder/"render-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("folder",type=Path)
    parser.add_argument("--dpi",type=int,default=96)
    args=parser.parse_args()
    result=render(args.folder,args.dpi)
    print(json.dumps({k:result[k] for k in ("document_count","page_count")}))
