"""Synthetic long-cell and continued-table fixtures; no execution/approval facts."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def main():
    raw = json.loads((ROOT / 'examples/sources/demo-facts.json').read_text())
    raw['stress_requirements'] = []
    for n in range(1, 3):
        raw['stress_requirements'].append({
            'id': f'STRESS-AD2-{n:03}',
            'name': f'장문 셀 페이지 흐름 검증 요구사항 {n}',
            'description': '실제 업무 요구사항이 아닌 긴 문장과 여러 문단의 출력 손실을 확인하기 위한 합성 검증 항목이다.',
            'details': [f'장문검증 {n}-{i:02}. 작업일자와 작업지시번호 및 배치번호를 확인하는 합성 절차를 계획한다. 입력 오류는 저장 성공과 구분하여 안내하며 실제 수행 결과를 기록하지 않는다. 문단 끝의 순번을 유지하여 출력 누락과 순서 변경을 확인한다.' for i in range(1, 15)] + [f'FINAL-STRESS-REQUIREMENT-{n:03}'],
            'constraints': ['행 분할 시 글자를 축소하거나 내용을 생략하지 않는다. 이 문장은 레이아웃 검증용 합성 입력이다.'],
        })
    raw['stress_database'] = {
        'id': 'STRESS_LONG_TABLE', 'name': '계속 표와 반복 헤더 검증용 합성 테이블',
        'columns': [{'id': f'stress_column_{i:03}', 'name': f'연속 표 검증 항목 {i:03}', 'type': 'VARCHAR', 'length': 50} for i in range(1, 56)],
    }
    raw['stress_database']['columns'][-1]['name'] = 'FINAL-STRESS-COLUMN-055'
    source = ROOT / 'examples/sources/stress-facts.json'
    dump(source, raw)
    data = json.loads((ROOT / 'examples/demo-suite.project.json').read_text())
    data['project']['requested_deliverables'] = ['SF-AD2', 'SF-TD5']
    data['sources'][0].update(path='sources/stress-facts.json', title='합성 장문·계속표 검증 원시 입력', sha256=sha256(source.read_bytes()).hexdigest())
    for i, fact in enumerate(raw['stress_requirements']):
        row = deepcopy(data['requirements'][0])
        row.update(fact, source_refs=[{'source_id': data['sources'][0]['id'], 'locator': f'/stress_requirements/{i}'}], change_type='new', business_area='문서 품질 검증', notes='합성 장문 흐름 검증용. 실제 업무 협의·구현·수행은 미수행이다.')
        data['requirements'].append(row)
    table = {
        'id': raw['stress_database']['id'], 'name': raw['stress_database']['name'],
        'status': 'synthetic', 'source_refs': [{'source_id': data['sources'][0]['id'], 'locator': '/stress_database'}],
        'description': '실제 설치 DB가 아닌 55열 정의의 계속 표 검증용 합성 논리설계.', 'change_type': 'new',
        'columns': [], 'notes': '내용의 생략 없이 여러 인쇄 페이지에 이어지는 행과 반복 헤더를 검토한다.',
    }
    for i, fact in enumerate(raw['stress_database']['columns']):
        table['columns'].append(dict(fact, status='synthetic', source_refs=[{'source_id': data['sources'][0]['id'], 'locator': f'/stress_database/columns/{i}'}], nullable=False, key='none', default_value=None, encryption={'applied': None, 'algorithm': None, 'notes': '정책 미확인', 'source_refs': [{'source_id': data['sources'][0]['id'], 'locator': '/stress_database'}]}))
    data['database_tables'].append(table)
    target = ROOT / 'examples/stress.project.json'
    dump(target, data)
    print(target)


if __name__ == '__main__':
    main()
