"""Independently inspect saved XLSX bytes against the normalized design facts."""
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as E
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'examples/demo-suite.project.json'
OUTPUT = ROOT / 'outputs/doc-automation-stage4/SF-TD5_DB설계_검증용.xlsx'
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
checks = []


def check(name, actual, expected):
    checks.append({'name': name, 'passed': actual == expected, 'actual': actual, 'expected': expected})


def main():
    data = json.loads(INPUT.read_text())
    with ZipFile(OUTPUT) as z:
        shared = [''.join(x.itertext()) for x in E.fromstring(z.read('xl/sharedStrings.xml'))]
        for ti, table in enumerate(data['database_tables'], 1):
            root = E.fromstring(z.read(f'xl/worksheets/sheet{ti}.xml'))
            cells = {}
            for cell in root.findall('.//s:sheetData/s:row/s:c', NS):
                value = cell.findtext('s:v', default='', namespaces=NS)
                if cell.get('t') == 's':
                    value = shared[int(value)]
                cells[cell.get('r')] = value
            check(f'{ti}:table physical id', cells['A2'], table['id'])
            check(f'{ti}:table description', cells['A3'], table['name'])
            check(f'{ti}:full design description', cells['D3'], table['description'])
            check(f'{ti}:table constraints', cells['A6'], '설계 제약: ' + table['notes'])
            check(f'{ti}:source locator', all(f"{r['source_id']} {r['locator']}" in cells['A5'] for r in table['source_refs']), True)
            check(f'{ti}:synthetic notice', '검증용 합성 자료(제출용 아님)' in cells['A4'], True)
            check(f'{ti}:not physical export', '실제 DB의 물리 구조를 추출한 파일이 아닌 설계 예시' in cells['A4'], True)
            rows = [r for r in root.findall('.//s:sheetData/s:row', NS) if int(r.get('r')) >= 8]
            check(f'{ti}:all columns', len(rows), len(table['columns']))
            for ri, column in enumerate(table['columns'], 8):
                expected = [str(ri-7), column['id'], column['name'], column['type'], str(column['length']) if column['length'] is not None else '', str(column.get('precision', '')), str(column.get('scale', '')), '허용' if column['nullable'] else '불허', {'primary': 'PK', 'foreign': 'FK', 'none': ''}[column['key']], '미확인' if column['default_value'] is None else str(column['default_value']), f"{column['foreign_table_id']}.{', '.join(column['foreign_column_ids'])}" if column.get('foreign_table_id') else '', '미확인', column['encryption']['notes']]
                for ci, value in enumerate(expected):
                    check(f'{ti}:{column["id"]}:{ci}', cells.get(f'{chr(65+ci)}{ri}', ''), value)
            check(f'{ti}:frozen headers', root.find('s:sheetViews/s:sheetView/s:pane', NS).get('ySplit'), '7')
    report = {'passed': all(x['passed'] for x in checks), 'checks': checks, 'input_sha256': sha256(INPUT.read_bytes()).hexdigest(), 'output_sha256': sha256(OUTPUT.read_bytes()).hexdigest(), 'verification_scope': 'Independent ZIP/XML field and notice comparison plus actual saved pane configuration. No native Excel execution was performed.'}
    target = ROOT / 'verification/db-workbook-audit.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': report['passed'], 'checks': len(checks)}, ensure_ascii=False))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
