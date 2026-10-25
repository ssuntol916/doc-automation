"""One source-bound synthetic interim report; does not extend the 19-role CLI."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import shutil
import unicodedata

from lxml import etree as ET
from doc_automation.compose import TemplateDocument, validate_package
from doc_automation.hwpx import own_text

REPO = Path(__file__).resolve().parents[2]
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS = {"hp": HP, "hs": "http://www.hancom.co.kr/hwpml/2011/section"}
EXPECTED = "502883660ded429a006560f0a10aac5e4f99df786e009f7b1acbd11935f0373b"
UNKNOWN = "미확인"


def digest(p):
    return sha256(Path(p).read_bytes()).hexdigest()


def artifact(p):
    return {"path": str(Path(p).resolve()), "sha256": digest(p)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, required=True, help='Read-only original manufacturing-AI HWPX')
    parser.add_argument('--content', type=Path, default=REPO / 'examples/manufact-ai-interim/content.json')
    parser.add_argument('--assets', type=Path, required=True, help='Folder produced by build_assets.py')
    parser.add_argument('--output', type=Path, required=True, help='New output HWPX; existing files are refused')
    args = parser.parse_args()
    candidate = args.output.expanduser().resolve()
    if not candidate.is_relative_to(REPO / "outputs"):
        parser.error("Output must be inside this checkout's ignored outputs/ directory")
    candidate_folder = candidate.parent
    if candidate.exists():
        raise RuntimeError('Use a new output path; do not overwrite output evidence')
    original = args.template.expanduser().resolve()
    assert digest(original) == EXPECTED, 'Template fingerprint mismatch'
    local = candidate_folder / 'source' / '제조AI특화_중간완료_원본사본.hwpx'
    local.parent.mkdir(parents=True, exist_ok=True)
    if not local.exists():
        shutil.copyfile(original, local)
    assert digest(local) == EXPECTED
    data_path = args.content.expanduser().resolve()
    data = json.loads(data_path.read_text())
    doc = TemplateDocument(local, expected_sha256=EXPECTED)
    root = doc.root()
    source_locations = {node: root.getroottree().getpath(node) for node in root.iter()}
    children = list(root)
    assert own_text(children[189]).strip() == '[서식 2]'
    for p in children[189:]:
        root.remove(p)
    children = children[:189]
    tables = doc.tables()
    assert len(tables) == 32
    first_section = ET.tostring(root.find('.//hp:secPr', NS))
    protected_tables = {i: ET.tostring(tables[i]) for i in (27, 28, 31)}
    photo_geometry = {i: [(dict(c.find('hp:cellAddr', NS).attrib), dict(c.find('hp:cellSpan', NS).attrib),
                           dict(c.find('hp:cellSz', NS).attrib)) for c in tables[i].findall('hp:tr/hp:tc', NS)]
                      for i in (11, 12, 13)}
    edits = []
    pictures = []

    def note(kind, node, value=None, **extra):
        edits.append({"kind": kind, "source_xpath": source_locations.get(node), "_node": node,
                      "value": value, **extra})

    def cell(t, r, c, value):
        target = doc.cell(tables[t], r, c)
        before = own_text(target.find('hp:subList/hp:p', NS))
        doc.set_cell_text(target, str(value))
        doc.use_text_colour(target, '#000000')
        doc.use_character_style(target, italic=False)
        doc.use_paragraph_style(target, break_latin='KEEP_WORD')
        note('cell_value', target, str(value), table=t, row=r, col=c, previous=before,
             fact_kind='synthetic_plan_or_explicit_unknown')

    def para(p, value, *, normal=False, bold=False):
        doc.set_paragraph_text(p, value)
        if normal:
            doc.use_character_style(p, font='함초롬바탕', size_pt=10.5, bold=bold, italic=False, colour='#000000')
            doc.use_paragraph_style(p, align='LEFT', line_spacing_percent=150)
            doc.use_paragraph_keep(p, keep_lines=len(value)<=240, keep_with_next=False)
        note('paragraph_owned_text', p, value)
        return p

    def after(anchor, texts, *, bold=False):
        if isinstance(texts, str):
            texts = [texts]
        for text in texts:
            p = doc.new_paragraph(text, prototype=children[8])
            para(p, text, normal=True, bold=bold)
            anchor.addnext(p)
            anchor = p
        return anchor

    def section(slot, key):
        after(children[slot], data['sections'][key])

    def retain_rows(index, retained):
        table = tables[index]
        old = table.findall('hp:tr', NS)
        retained = sorted(retained)
        mapping = {r: i for i, r in enumerate(retained)}
        for r, row in enumerate(old):
            if r not in mapping:
                table.remove(row)
                continue
            for tc in row.findall('hp:tc', NS):
                addr, span = tc.find('hp:cellAddr', NS), tc.find('hp:cellSpan', NS)
                a, n = int(addr.get('rowAddr')), int(span.get('rowSpan'))
                count = sum(a <= selected < a+n for selected in retained)
                assert count >= 1
                addr.set('rowAddr', str(mapping[a]))
                span.set('rowSpan', str(count))
        table.set('rowCnt', str(len(retained)))
        for zones in list(table):
            if ET.QName(zones).localname == 'cellzoneList':
                table.remove(zones)
        height = sum(max(int(tc.find('hp:cellSz', NS).get('height')) // int(tc.find('hp:cellSpan', NS).get('rowSpan'))
                         for tc in row.findall('hp:tc', NS)) for row in table.findall('hp:tr', NS))
        table.find('hp:sz', NS).set('height', str(height))
        doc.invalidate_layout(table.getparent().getparent())
        note('unused_example_rows_removed', table, retained, table=index)

    # Simple rows inherit the source KPI grid's local definitions, while each
    # new table explicitly declares a different, reviewed data repetition.
    header_cell = tables[4].find('hp:tr/hp:tc', NS)
    body_cell = tables[4].findall('hp:tr', NS)[1].find('hp:tc', NS)
    grid_prototype = tables[4]

    def simple_table(index, headers, rows, widths):
        old = tables[index]
        table = doc.clone_table(grid_prototype)
        for child in list(table):
            if ET.QName(child).localname in {'tr', 'cellzoneList'}:
                table.remove(child)
        table.set('colCnt', str(len(headers)))
        table.set('rowCnt', str(len(rows)+1))
        table.set('repeatHeader', '1')
        heights = []
        for ri, values in enumerate([headers, *rows]):
            assert len(values) == len(headers)
            row = ET.SubElement(table, f'{{{HP}}}tr')
            line_count = max(max(1, math.ceil(len(str(v))/max(1, (w-2)/3.5))) for v, w in zip(values, widths))
            height = max(1400, int(line_count * 1250 + 400))
            heights.append(height)
            for ci, value in enumerate(values):
                tc = doc._clone(header_cell if ri == 0 else body_cell)
                tc.find('hp:cellAddr', NS).attrib.update({'rowAddr':str(ri), 'colAddr':str(ci)})
                tc.find('hp:cellSpan', NS).attrib.update({'rowSpan':'1', 'colSpan':'1'})
                tc.find('hp:cellSz', NS).set('height', str(height))
                row.append(tc)
                doc.set_cell_text(tc, str(value))
                doc.use_character_style(tc, font='함초롬바탕', size_pt=10, bold=ri == 0, italic=False, colour='#000000')
                doc.use_paragraph_style(tc, align='LEFT', line_spacing_percent=130)
                for p in tc.findall('hp:subList/hp:p', NS):
                    doc.use_paragraph_keep(p, keep_lines=False, keep_with_next=False)
        table.find('hp:sz', NS).set('height', str(sum(heights)))
        doc.set_table_layout(table, column_widths_mm=widths, cell_margins_mm={'left': 1, 'right': 1, 'top': 0.7, 'bottom': 0.7})
        doc.use_table_pagination(table, break_mode='TABLE', inline=False)
        pos = table.find('hp:pos', NS)
        pos.attrib.update({'flowWithText':'1', 'vertOffset':'0', 'horzOffset':'0', 'vertRelTo':'PARA', 'horzRelTo':'PARA'})
        old.addprevious(table)
        doc.remove(old)
        tables[index] = table
        doc.repeat_header_rows(table)
        note('declared_source_example_table_repetition', table, {'headers': headers, 'rows': rows}, table=index)

    identity = data['identity']
    para(children[0], '[서식 1] · 검증용 합성 자료(제출용 아님)')
    cell(0, 0, 0, '제조AI특화 스마트공장 중간보고서(점검표)\n검증용 합성 작성예 · 제출용 아님')
    cell(0, 1, 1, identity['customer']); cell(0, 1, 3, identity['supplier'])
    cell(0, 2, 1, identity['project_number_display']); cell(0, 2, 3, identity['consortium_display'])
    a = after(children[1], [identity['project_name'], data['notice']], bold=True)
    after(a, f"합성 계획기간: {identity['plan_start']}~{identity['plan_end']} / 보고 기준일(가정): {identity['interim_as_of']}. 실제 협약·제출일이 아니다.")
    cell(1, 2, 0, '영상취득→AI 판독 보조→작업자 확인→LOT 이력·MES 연계. 합성 계획이며 구축 실적은 미확인.')
    cell(1, 2, 1, '미확인'); cell(1, 2, 2, '중간1\n(합성 목표)')

    # All inspector result cells stay empty; reporter results are unknown.
    for i, process in enumerate(data['processes']):
        row = 3 + i*2
        cell(2, row, 0, process['name']); cell(2, row, 1, process['plan'] + ' (합성 계획)')
        cell(2, row, 6, '?'); cell(2, row+1, 6, '')
        for col, key in enumerate(('collection', 'automation', 'control', 'linked_process'), 1):
            cell(2, row+1, col, process[key])
    after(children[23], '진척란의 ?는 실제 수행자료 미제공으로 수치 미확인을 뜻한다. 점검위원 진척란은 작성하지 않았다.')
    para(children[26], '산정기준의 계산 예(양식 지침, 본 과제 실적 아님): S/W 구현50%, H/W 구매60%인 경우')
    para(children[27], '예시 진도율 = 50%×0.6 + 60%×0.4 = 54%. 본 합성 과제 진척은 자료 미제공으로 미확인.')
    for row, kpi in enumerate(data['kpis'], 1):
        target = ('이상' if kpi.get('target_operator') == '>=' else '이하')
        values = [row, kpi['field'], kpi['name'], kpi['unit'], UNKNOWN,
                  f"{kpi['target']} {target}", kpi['weight'], '합성 목표\n실측 없음']
        for col, value in enumerate(values): cell(4, row, col, value)
        cell(5, row, 0, kpi['name']); cell(5, row, 1, kpi['method'])
    cell(4, 6, 6, '1.0'); cell(4, 6, 7, '목표 가중치')
    retain_rows(4, [0,1,2,3,6]); retain_rows(5, [0,1,2,3])
    for r in range(2, 27):
        for c in (3,4,5): cell(6, r, c, '?')
        for c in (6,7,8,9): cell(6, r, c, '—')
    for r, column, cost in ((6,7,0),(9,6,160),(14,6,17),(15,6,3),(16,6,40),(19,6,10)):
        cell(6,r,column,'계획');cell(6,r,9,str(cost) if cost else '배분 미정')
    after(children[42], '?=기존 보유·운영방식·제조사 자료 미제공. 계획 표시는 합성 도입안, —는 이번 계획 범위 밖이며 실제 미보유를 뜻하지 않는다. 금액은 별도 예산의 중복분류가 있어 합산하지 않는다.')

    scenario = data['ai_scenario']
    scenario_values = [scenario['function_name'],scenario['process'],scenario['purpose'],scenario['technology'],
                       scenario['input_data'],scenario['output_data'],'\n'.join(scenario['steps']),scenario['expected_effect']]
    for row, value in enumerate(scenario_values,1):
        if isinstance(value,list):value='\n'.join(value)
        cell(8,row,1,value)
    # Remove sample performance graphics, not replace them with invented charts.
    for pic in list(tables[9].findall('.//hp:pic',NS)): doc.remove(pic)
    for row,item in enumerate(data['ai_performance'],1):
        for col,value in enumerate((row,item['name'],item['unit'],item['target_display'],item['method']+'\n실측자료 미제공')):
            cell(9,row,col,value)

    hardware=data['budget']['hardware']
    for col,value in enumerate(['입고','성형','영상취득','추론','품질확인','포장','출하'],0):cell(10,1,1+col*2,value)
    for row,item in enumerate(hardware,3):
        cell(10,row,0,item['name'])
        for col in range(1,17):cell(10,row,col,'?' if col%2==0 else '—')
        cell(10,row,9,item['quantity']);cell(10,row,15,item['quantity'])
    for col in range(1,17):cell(10,12,col,'?' if col%2==0 else '—')
    cell(10,12,9,sum(h['quantity'] for h in hardware));cell(10,12,15,sum(h['quantity'] for h in hardware))
    retain_rows(10,list(range(9))+[12])
    after(children[75], '수량은 합성 신규 도입 계획이다. ?는 기존 설치수량 미확인, —는 해당 위치에 신규 배분하지 않은 계획을 뜻한다. 실제 입고·설치 수량은 확인되지 않았다.')
    for i,item in enumerate(data['as_is_to_be']):
        ti,offset=(11,0) if i<2 else (12,0) if i<4 else (13,0)
        base=1 if i in (0,2,4) else 4
        cell(ti,base,0,item['subject'])
        ar=base if base==1 else base+1;tr=3 if base==1 else 7
        cell(ti,ar,1,item['as_is']);cell(ti,tr,1,item['to_be'])
        cell(ti,base,3,'기대효과: '+item['expected_effect'])
        cell(ti,ar,2,'현장사진\n미제공');cell(ti,tr,2,'현장사진\n미제공')
    modules=[('기준·데이터', '품목/LOT 조회 → 영상취득·품질확인 → 라벨 검토'),
             ('AI·품질 판정', '등록 영상 → 버전 지정 AI 추론 → 작업자 확정'),
             ('검사이력·KPI','확정 검사 → LOT 이력 조회 → KPI 대시보드'),
             ('모델관리','데이터/모델 버전·검증근거 연결 → 승인 대기 → 배포 계획'),
             ('MES 연계','품목/LOT 수신 → 검사ID별 확정결과 송신·재전송'),
             ('운영·보안','권한/감사 기록·수동검사 전환·자료 반출 통제')]
    simple_table(14,['기능 모듈(합성 계획)','하위 기능 및 연계'],modules,[37,130])
    function_rows=[[f['module'],UNKNOWN,f['id']+'\n'+f['name'],f['description'],f['unit_process'],f['change_type'],'미확인'] for f in data['functions']]
    simple_table(15,['모듈','작동상태','기능명','상세내역','단위 과정','구분','패키지 미사용'],function_rows,[18,14,30,53,17,18,17])
    para(children[111], '')
    progress_notice = doc.new_paragraph('', prototype=children[8])
    children[111].addprevious(progress_notice)
    para(progress_notice, '합성 일정: 2025년 7~12월 / 기준일(가정): 2025.09.30 / 실제 진척: 미확인(실적자료 미제공)', normal=True)
    doc.use_paragraph_keep(progress_notice, keep_lines=True, keep_with_next=True)
    schedule_rows=[]
    for s in data['schedule']:
        months=['●' if f'2025-{m:02}' in s['planned_months'] else '—' for m in range(7,13)] + ['—','—']
        schedule_rows.append([s['phase']+f"({s['weight_percent']})",s['work'],s['deliverables'],'합성 계획',s['weight_percent'],*months,'미정'])
    simple_table(16,['단계','작업','산출물','구분','가중치','7','8','9','10','11','12','—','—','담당'],schedule_rows,[13,28,31,12,11,7,7,7,7,7,7,7,7,16])
    after(children[111], '●=합성 계획월, —=해당 월 배정 없음(계획). 표의 일정·가중치는 실제 수행률이 아니다.')
    for row in range(1,20):cell(17,row,6,UNKNOWN)

    budget=data['budget'];bycode={x['code']:x for x in budget['items']}
    for row,code in ((3,'A'),(5,'C'),(7,'B'),(9,'D'),(11,'E'),(13,'F'),(15,'G')):
        cell(18,row,1,f"{bycode[code]['plan']:,}")
        cell(18,row,3,UNKNOWN);cell(18,row,4,UNKNOWN)
        cell(18,row,5,'합성 예산\n집행자료 없음')
    cell(18,17,1,'300,000');cell(18,17,3,UNKNOWN);cell(18,17,4,UNKNOWN);cell(18,17,5,'합성 계획')
    for row,item in zip((4,6,8),budget['software_modules']):
        cell(20,row,0,item['name']);cell(20,row,1,f"{item['purchase_plan']:,}")
        for col in (2,3,4,5):cell(20,row,col,'산정대기')
        cell(20,row,6,f"{item['development_plan']:,}");cell(20,row,8,UNKNOWN)
    for col in range(1,7):cell(20,10,col,'—')
    cell(20,10,0,'계획 범위 외');cell(20,10,8,'—')
    for col,value in {1:'20,000',2:'산정대기',3:'산정대기',4:'산정대기',5:'산정대기',6:'140,000',8:UNKNOWN}.items():cell(20,12,col,value)
    retain_rows(20,list(range(10))+[12,13])
    after(children[130],'A/B 금액은 합성 예산 배정액이다. FP·개발원가·이윤·직접경비의 산정근거가 없어 원가 산식의 적정성을 판단하지 않는다.')
    keep=[0,1,2]
    for row,item in zip((3,7,11,17,21,25),hardware):
        keep.extend([row,row+1])
        cell(21,row,0,item['name']);cell(21,row,2,item['name'])
        cell(21,row,3,item['specification']+'\n제조사·모델 미확정')
        for col,key in ((4,'unit_price'),(5,'quantity'),(6,'subtotal')):cell(21,row,col,f"{item[key]:,}")
        for col in (8,9,10):cell(21,row,col,UNKNOWN)
    cell(21,53,4,'60,000 천원');cell(21,53,7,'보고: 미확인');keep.extend([53,54]);retain_rows(21,keep)
    for index,items,total in ((22,budget['network'],10000),(23,budget['other'],10000),(25,budget['cloud'],30000)):
        for i,row in enumerate((3,5,7)):
            if i<len(items):
                item=items[i];cell(index,row,0,'합성 계획') if i==0 else None
                cell(index,row,1,item['name']);cell(index,row,2,'규격·견적 미확정')
                for col,key in ((3,'monthly_cost' if index==25 else 'unit_price'),(4,'months' if index==25 else 'quantity'),(5,'subtotal')):cell(index,row,col,f"{item[key]:,}")
                for col in (7,8,9):cell(index,row,col,UNKNOWN)
            else:
                for col in (1,2,3,4,5,7,8,9):cell(index,row,col,'—')
        cell(index,9,3,f'{total:,} 천원');cell(index,9,6,'보고: 미확인')
    for i,item in enumerate(budget['personnel']):
        row=3+i*2
        values=[item['role'],item['work'],f"{item['monthly_salary']:,}",item['participation_percent'],item['months'],f"{item['subtotal']:,}"]
        for col,value in enumerate(values):cell(24,row,col,value)
        for col in (7,8):cell(24,row,col,UNKNOWN)
    cell(24,9,4,'30,000 천원');cell(24,9,7,UNKNOWN)
    retain_rows(24,[0,1,2,3,4,5,6,9,10])
    for row in (3,5,7,9,11,13):
        cell(26,row,1,'과정·일정 확인 필요');cell(26,row,2,'미확인');cell(26,row,6,'미확인')
    cell(26,15,6,'미확인')
    after(children[155], '기술교육 합성 계획: AI 데이터·검사기준·모델 검증 및 운영. 대상은 도입기업의 품질·생산 담당 역할이며, 2025년 11~12월을 계획한다. 실제 대상자·과정·기관·수료일은 미확인이다.')
    for row,item in enumerate(data['reporter_requests'],1):cell(29,row,0,'보고자 확인요청');cell(29,row,1,item['text'])
    para(children[184],'보고일자: 실제 제출일 미정 / 합성 보고 기준일: 2025.09.30')
    cell(30,0,1,identity['customer']);cell(30,1,1,identity['supplier'])
    cell(30,2,1,'참여정보 미제공');cell(30,3,1,'참여정보 미제공')

    for slot,key in ((9,'1.1'),(18,'1.2_as_is'),(21,'1.2_to_be'),(24,'1.3'),(34,'1.4'),(41,'1.5'),
                     (52,'2.1_technology'),(54,'2.1_process'),(55,'2.1_integration'),(62,'2.2'),(70,'3.1'),
                     (79,'3.3'),(83,'3.4'),(87,'3.5'),(90,'3.6'),(110,'4.1'),(115,'4.2'),(120,'5'),
                     (154,'5.8'),(159,'6.1_plan'),(161,'6.1_actual'),(163,'6.2_plan'),(165,'6.2_actual'),
                     (167,'6.3_plan'),(169,'6.3_actual'),(171,'7')):
        section(slot,key)

    image_slots={17:'01_process_as_is',20:'02_process_to_be',49:'03_ai_architecture',
                 71:'04_hw_network',77:'05_installation_plan',81:'08_sw_modules',86:'06_sw_data_pipeline'}
    for slot,name in image_slots.items():
        anchor=children[slot];old=anchor.findall('.//hp:pic',NS)
        assert len(old)==1
        p=old[0].getparent().getparent()
        source_xpath=root.getroottree().getpath(old[0])
        doc.remove(old[0])
        image=args.assets.expanduser().resolve()/(name+'.png')
        new=doc.insert_picture(p,image.read_bytes(),'image/png','png',width_mm=165,height_mm=98,
                               description='합성 계획도 · 실제 구축/실행 증거 아님 · '+name)
        pictures.append({'source_xpath':source_xpath,'new_picture_id':new.get('id'),'image':artifact(image),
                         'semantic_slot':name,'evidence_status':'synthetic_plan_not_execution'})
        doc.use_paragraph_style(p,align='CENTER')
        doc.use_paragraph_keep(p,keep_lines=True,keep_with_next=False)
    after(children[63],data['diagram_text']['measurement_placeholder'])

    # Source sample lengths forced each former subsection to a new page.
    # Keep main chapter boundaries and the two fixed photo-frame boundaries;
    # allow shorter, newly authored subsections to flow naturally.
    for index in (40,56,76,89,101,103,113):
        if children[index].get('pageBreak') == '1':
            children[index].set('pageBreak','0')
            note('sample_subsection_page_break_removed', children[index], index)
    for index in (2,3,4,5,6,8,9,10,17,18,20,21,22,23,24,25,26):
        doc.use_table_pagination(tables[index], break_mode='TABLE', inline=False)
        note('short_table_rows_atomic', tables[index], table=index)
    for index,count in ((2,3),(6,2),(10,3),(17,1)):
        doc.repeat_header_rows(tables[index],count=count)
        note('repeated_header_rows_declared',tables[index],count,table=index)
    # The original E frame carries an unsigned negative floating offset.
    # These two bounded short cost frames fit one page and flow inline,
    # keeping the heading/header/first item together without an empty page.
    for index in (23,25):
        doc.use_table_pagination(tables[index],break_mode='NONE',inline=True)
        pos=tables[index].find('hp:pos',NS)
        pos.attrib.update({'vertOffset':'0','horzOffset':'0','vertRelTo':'PARA','horzRelTo':'PARA','flowWithText':'1'})
        note('bounded_short_cost_frame_inline',tables[index],table=index)
    # A finite heading -> optional blank/instruction -> first content chain.
    top = list(root)
    for i,p in enumerate(top):
        if re.match(r'^\s*(?:[1-7](?:\.[0-9]+){0,2}(?:\.\s*|\s+)|[□■])',own_text(p)):
            doc.use_paragraph_keep(p,keep_lines=True,keep_with_next=True)
            for following in top[i+1:]:
                text = own_text(following).strip()
                objects = following.findall('.//hp:tbl',NS)+following.findall('.//hp:pic',NS)
                if objects or (text and not text.startswith(('※','*'))):
                    break
                doc.use_paragraph_keep(following,keep_with_next=True)

    assert first_section==ET.tostring(root.find('.//hp:secPr',NS))
    for i,before in protected_tables.items():assert ET.tostring(tables[i])==before
    for i,geometry in photo_geometry.items():
        now=[(dict(c.find('hp:cellAddr',NS).attrib),dict(c.find('hp:cellSpan',NS).attrib),dict(c.find('hp:cellSz',NS).attrib)) for c in tables[i].findall('hp:tr/hp:tc',NS)]
        assert geometry==now
    assert len(doc.tables())==32 and len(root.findall('.//hp:pic',NS))==7
    assert sum(k['weight'] for k in data['kpis'])==1
    assert sum(b['plan'] for b in budget['items'])==budget['total']==300000
    assert sum(s['weight_percent'] for s in data['schedule'])==100
    body='\n'.join(own_text(p) for p in root.iter(f'{{{HP}}}p'))
    assert '[서식 2]' not in body and '실적 : 100.00%' not in body and 'YOLOv8' not in body
    assert all(f['id'] in body and f['name'] in body for f in data['functions'])
    assert all(k['name'] in body for k in data['kpis'])
    doc.set_metadata(title='제조AI특화 스마트공장 중간보고서 — 합성 작성예',creator='문서 자동화 작성 시험',
                     subject='검증용 합성 자료·제출용 아님',description=data['notice'],clear_legacy=True)
    doc.save(candidate)
    assert digest(original)==digest(local)==EXPECTED
    for edit in edits:
        node = edit.pop('_node')
        edit['current_xpath'] = root.getroottree().getpath(node) if root in node.iterancestors() else None
    snapshot=candidate_folder/'build_report.snapshot.py'
    shutil.copyfile(__file__, snapshot)
    result={'recorded_at':datetime.now(timezone.utc).isoformat(),'status':'synthetic_draft_native_review_pending',
            'source':artifact(original),'local_source':artifact(local),'content':artifact(data_path),'builder':artifact(snapshot),
            'document':artifact(candidate),'submission_ready':False,'native_review_status':'pending',
            'source_scope':{'section':'Contents/section0.xml','original_root_children':[0,188],'completed_report_excluded':True},
            'package':validate_package(candidate),'style_choice':'Original form styles retained; inserted body Batang10.5pt/150%, replacement grids Batang10pt/130%.',
            'preservation':{'first_secPr_exact':True,'reviewer_tables_exact':[27,28,31],'photo_table_geometry_exact':[11,12,13],
                            'report_tables':32,'planned_diagrams':7,'sample_performance_pictures_removed':3},
            'edits':edits,'pictures':pictures,'limits':['Actual progress/execution/education/measurement/approval/signature evidence is not provided.',
             'Photo-required cells remain explicitly unavailable; plan diagrams do not substitute for actual site photographs.',
             'Source-specific one-off composition; does not claim CLI support for all2025 forms.',
             'Original form PM codes are retained as printed; their correspondence to internal19-role codes is not assumed.']}
    manifest=candidate_folder/'manifest.json'
    manifest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'document':result['document'],'edits':len(edits),'package_valid':result['package']['valid']},ensure_ascii=False))


if __name__=='__main__':
    main()
