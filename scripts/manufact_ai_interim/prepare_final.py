"""Remove proven orphan example media, preserving current XML and all fonts."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile
from lxml import etree as ET
from doc_automation.compose import TemplateDocument, validate_package

PROJECT=Path(__file__).resolve().parents[2]


def record(path):
    return {'path':str(path.resolve()),'sha256':sha256(path.read_bytes()).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    before=args.input.expanduser().resolve()
    after=args.output.expanduser().resolve()
    if not after.is_relative_to(PROJECT / "outputs"):
        parser.error("Output must be inside this checkout's ignored outputs/ directory")
    if after.exists():raise RuntimeError('Refusing to overwrite final-byte evidence')
    document=TemplateDocument(before)
    references={v for root in document._roots.values() for node in root.iter()
                for k,v in node.attrib.items() if 'binary' in k.lower()}
    package=document.xml('Contents/content.hpf')
    removed=[]
    for item in list(package.iter()):
        if ET.QName(item).localname=='item' and item.get('href','').startswith('BinData/') and item.get('id') not in references:
            member=item.get('href')
            removed.append({'id':item.get('id'),'member':member,
                            'sha256':sha256(document._entries[member]).hexdigest(),
                            'reason':'Original example media with no remaining XML binary reference'})
            del document._entries[member]
            item.getparent().remove(item)
    assert len(removed)==8
    document.save(after)
    with ZipFile(before) as a,ZipFile(after) as b:
        preserved=['Contents/header.xml',*document.sections]
        assert all(a.read(name)==b.read(name) for name in preserved)
    value={'before':record(before),'after':record(after),'removed':removed,
           'unchanged_xml_members':preserved,'all_declared_font_definitions_preserved':True,
           'package':validate_package(after),'submission_ready':False,
           'native_workflow':'Open/close/reopen/export current bytes without a native Save As transformation.',
           'limits':['Native Save As trials retained separately; strict font/paragraph preservation did not pass.',
                     'This generated final byte sequence must be opened and exported afresh; earlier PDFs are not its evidence.']}
    (after.parent/'preparation.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'final':value['after'],'package_valid':value['package']['valid']},ensure_ascii=False))


if __name__=='__main__':main()
