"""Apply this report's Malgun Gothic table preference to an explicit new output."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree as ET
from doc_automation.compose import TemplateDocument, validate_package
from doc_automation.hwpx import own_text, inline_text

HP='http://www.hancom.co.kr/hwpml/2011/paragraph'
HH='http://www.hancom.co.kr/hwpml/2011/head'
PROJECT=Path(__file__).resolve().parents[2]
NS={'hp':HP,'hh':HH}


def artifact(path):
    return {'path':str(path.resolve()),'sha256':sha256(path.read_bytes()).hexdigest()}


def in_table(node):
    return any(p.tag==f'{{{HP}}}tbl' for p in node.iterancestors())


def char_definitions(document):
    return {p.get('id'):p for p in document.xml('Contents/header.xml').findall('.//hh:charPr',NS)}


def without_font(definition):
    node=deepcopy(definition)
    node.attrib.pop('id',None)
    font=node.find('hh:fontRef',NS)
    if font is not None:node.remove(font)
    return ET.tostring(node,method='c14n')


def layout_content(document):
    result=[]
    for name in document.sections:
        root=deepcopy(document.xml(name))
        for run in root.iter(f'{{{HP}}}run'):
            if in_table(run):run.attrib.pop('charPrIDRef',None)
        for cache in list(root.iter(f'{{{HP}}}linesegarray')):
            cache.getparent().remove(cache)
        result.append(ET.tostring(root,method='c14n'))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--expected-sha256')
    parser.add_argument('--split-mentor-label',action='store_true',help='Retain the original15pt/13pt runs on separate lines')
    args=parser.parse_args()
    input_path=args.input.expanduser().resolve();output_path=args.output.expanduser().resolve()
    if not output_path.is_relative_to(PROJECT / "outputs"):
        parser.error("Output must be inside this checkout's ignored outputs/ directory")
    if output_path.exists():raise RuntimeError('Refusing to overwrite an existing output')
    expected=artifact(input_path)['sha256']
    if args.expected_sha256:assert expected==args.expected_sha256
    old=TemplateDocument(input_path);doc=TemplateDocument(input_path)
    before_chars=char_definitions(old)
    old_runs=[r for name in old.sections for r in old.xml(name).iter(f'{{{HP}}}run')]
    changes=[]
    for index,table in enumerate(doc.tables()):
        changed=doc.use_character_style(table,font='맑은 고딕')
        changes.append({'table_index':index,'table_id':table.get('id'),
                        'xpath':doc.root().getroottree().getpath(table),'changed_runs':changed})
    if args.split_mentor_label:
        label=doc.cell(doc.tables()[31],3,0)
        label_runs=label.findall('.//hp:run',NS)
        assert [inline_text(r.find('hp:t',NS)) for r in label_runs]==['DX멘토단명','(해당시)']
        doc.set_text_node(label_runs[0].find('hp:t',NS),'DX멘토단명\n')
    doc.save(output_path)
    current=TemplateDocument(output_path);after_chars=char_definitions(current)
    # Normalize only the explicitly requested line break in memory for comparison.
    comparison=TemplateDocument(output_path)
    if args.split_mentor_label:
        label=comparison.cell(comparison.tables()[31],3,0)
        comparison.set_text_node(label.find('.//hp:run/hp:t',NS),'DX멘토단명')
    new_runs=[r for name in current.sections for r in current.xml(name).iter(f'{{{HP}}}run')]
    assert len(old_runs)==len(new_runs)
    assert layout_content(old)==layout_content(comparison),'Undeclared section/object/paragraph/table change'
    assert [own_text(p) for name in old.sections for p in old.xml(name).iter(f'{{{HP}}}p')]==[own_text(p) for name in comparison.sections for p in comparison.xml(name).iter(f'{{{HP}}}p')]
    families={f.get('lang').lower():{p.get('id'):p.get('face') for p in f} for f in current.xml('Contents/header.xml').findall('.//hh:fontface',NS)}
    table_text_runs=0;outside_runs=0
    for before,after in zip(old_runs,new_runs):
        a,b=before.get('charPrIDRef'),after.get('charPrIDRef')
        if not in_table(before):
            assert a==b
            outside_runs+=1
        else:
            assert without_font(before_chars[a])==without_font(after_chars[b]),'Size/bold/colour/spacing/ratio changed'
            if any(inline_text(t) for t in after.findall('hp:t',NS)):
                font=after_chars[b].find('hh:fontRef',NS)
                assert all(families[script][fid]=='맑은 고딕' for script,fid in font.attrib.items())
                table_text_runs+=1
    assert len(current.tables())==len(old.tables())==32
    assert all(ET.tostring(before_chars[key],method='c14n')==ET.tostring(after_chars[key],method='c14n') for key in before_chars)
    assert artifact(input_path)['sha256']==expected
    record={'recorded_at':datetime.now(timezone.utc).isoformat(),
            'change_type':'user_preference_for_current_report','target_font':'맑은 고딕',
            'scope':'All native table text in the current synthetic interim report, all7script font references. Raster diagram lettering is image content.',
            'before':artifact(input_path),'after':artifact(output_path),'script':artifact(Path(__file__)),
            'declared_label_linebreak':args.split_mentor_label,
            'tables':changes,'table_count':32,'changed_runs':sum(x['changed_runs'] for x in changes),
            'verified_table_text_runs':table_text_runs,'outside_runs_unchanged':outside_runs,
            'preserved':{'all_owned_text_order':True,'section_table_cell_object_geometry':True,
                         'character_size_bold_italic_colour_spacing_ratio':True,'outside_table_formatting':True},
            'package':validate_package(output_path),'native_review_status':'pending_current_export','submission_ready':False}
    (output_path.parent/'font-change.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:record[k] for k in ('after','table_count','changed_runs','verified_table_text_runs','outside_runs_unchanged')},ensure_ascii=False))


if __name__=='__main__':main()
