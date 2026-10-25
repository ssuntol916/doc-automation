"""Compare the observed native pilot roundtrips; not a universal HWP guarantee."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from zipfile import ZipFile

import pymupdf
from doc_automation.hwpx import parse_xml, section_order, NS, own_text

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'verification/generation-pilot'


def texts(path):
    with ZipFile(path) as z:
        return [re.sub(r'\s+', ' ', own_text(p)).strip() for s in section_order(z) for p in parse_xml(z.read(s)).iter(f'{{{NS["hp"]}}}p') if own_text(p).strip()]


def main():
    base = 'AD2-fixed'
    original = texts(FOLDER / (base + '.hwpx'))
    cases = []
    with pymupdf.open(FOLDER / (base+'.pdf')) as before:
        for name in ['AD2-native-roundtrip', 'AD2-hwp-roundtrip', 'AD2-hwp-back-to-hwpx']:
            hwpx = FOLDER / (name+'.hwpx')
            pdf = FOLDER / (name+'.pdf')
            item = {'id': name, 'pdf_sha256': sha256(pdf.read_bytes()).hexdigest()}
            if hwpx.exists():
                after_text = texts(hwpx)
                item.update(hwpx_sha256=sha256(hwpx.read_bytes()).hexdigest(), owned_paragraph_sequence_unchanged=after_text == original, owned_paragraph_multiset_unchanged=Counter(after_text) == Counter(original), paragraphs_before=len(original), paragraphs_after=len(after_text))
            else:
                hwp = FOLDER / (name+'.hwp')
                payload = hwp.read_bytes()
                item.update(hwp_sha256=sha256(payload).hexdigest(), ole_compound_signature=payload[:8].hex(), binary_hwp_created=payload[:8] == bytes.fromhex('d0cf11e0a1b11ae1'))
            with pymupdf.open(pdf) as after:
                item.update(pages_before=len(before), pages_after=len(after))
                item['page_text_unchanged'] = len(before) == len(after) and all(re.sub(r'\s+','',a.get_text()) == re.sub(r'\s+','',b.get_text()) for a,b in zip(before,after))
                item['page_pixel_checks'] = [dict(page=i+1, same=a.get_pixmap(matrix=pymupdf.Matrix(1,1),alpha=False).samples == b.get_pixmap(matrix=pymupdf.Matrix(1,1),alpha=False).samples) for i,(a,b) in enumerate(zip(before,after))]
                item['all_page_pixels_identical_at_72dpi'] = len(before) == len(after) and all(x['same'] for x in item['page_pixel_checks'])
            cases.append(item)
    report = {'scope': 'Observed synthetic AD2 pilot native Save As, native HWP conversion and reverse HWPX conversion only.', 'app': 'Hancom Office HWP 12.30.0 build6544', 'baseline_hwpx_sha256': sha256((FOLDER/(base+'.hwpx')).read_bytes()).hexdigest(), 'baseline_pdf_sha256': sha256((FOLDER/(base+'.pdf')).read_bytes()).hexdigest(), 'cases': cases, 'limits': ['This is not a guarantee for arbitrary binary HWP files, embedded objects, equations or other Hancom versions.', 'The pilot is not a final deliverable; readability, measured TOC and final suite review remain separate.']}
    (FOLDER / 'roundtrip-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(cases,ensure_ascii=False))


if __name__ == '__main__':
    main()
