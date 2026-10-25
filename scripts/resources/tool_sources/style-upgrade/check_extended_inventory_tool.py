"""Focused invariants for the task-local figure observation inventory.

No HWPX is rendered and no actual content/native/editorial pass is awarded.
"""
from __future__ import annotations
import os
if __name__ == "__main__" and os.environ.get("DOC_AUTOMATION_REBUILD_STAGED") != "1":
    raise SystemExit("Run this preserved tool through scripts/resources/run.py with an explicit new workspace.")

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('inventory_tool', BASE / 'freeze_observation_inventory.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--control-input', type=Path, help='Optional private reference-derived control JSON')
    parser.add_argument('--label-evidence', type=Path, help='Private direct source-label evidence, required with --control-input')
    args = parser.parse_args()
    input_path = tool.R / 'examples/style-upgrade/illustrated-extended-v2/illustrated.project.json'
    data = tool.load(input_path)
    sources, records, manual = tool.collect_figure_evidence(data, base_dir=input_path.parent)
    checks = []

    def check(name, condition):
        checks.append({'check': name, 'ok': bool(condition)})

    def rejects(name, callback):
        try:
            callback()
        except ValueError as error:
            checks.append({'check': name, 'ok': True, 'rejection': str(error)})
        else:
            checks.append({'check': name, 'ok': False})

    figures = {role: tool.figure_inventory(data, role, sources, records, manual, base_dir=input_path.parent) for role in tool.ROLE_PATHS}
    expected_counts = {'SF-AD1': 2, 'SF-TD1': 2, 'SF-TD2': 2, 'SF-TD3': 2, 'SF-TD4': 2, 'SF-TI3': 2}
    check('only_declared_role_slots_are_selected', {role: len(items) for role, items in figures.items() if items} == expected_counts)
    check('AD1_has_only_current_process_and_system_figures', {f['slot'] for f in figures['SF-AD1']} == {'as_is_attachment_ids', 'as_is_diagram_ids'})
    check('all_six_diagrams_have_source_bound_labels', all(f['essential_elements'] and all(e['label_basis'] == 'hash_bound_source_json' for e in f['essential_elements']) for role in ['SF-AD1', 'SF-TD1', 'SF-TD2', 'SF-TD4'] for f in figures[role]))
    check('program_function_lists_do_not_claim_execution_order', all(f['diagram_relations']['arrows_represent_supplied_step_order'] is False for f in figures['SF-TD4']))
    check('screen_field_button_coverage_is_19_units', sum(len(f['essential_elements']) for f in figures['SF-TD3']) == 19)
    check('all_new_figure_and_label_states_are_unknown', all(f['status'] == 'unknown' and all(e['status'] == 'unknown' for e in f['essential_elements']) for items in figures.values() for f in items))

    reused = copy.deepcopy(data)
    reused['screens'][0]['before_attachment_ids'] = reused['screens'][0]['after_attachment_ids'][:]
    units = [e['unit_id'] for f in tool.figure_inventory(reused, 'SF-TD3', sources, records, {}, base_dir=input_path.parent) for e in f['essential_elements']]
    check('same_screen_image_in_separate_slots_keeps_unique_observations', len(units) == 29 and len(set(units)) == 29)
    undefined = copy.deepcopy(data)
    undefined['screens'][0].pop('fields')
    undefined['screens'][0].pop('buttons')
    unmapped = tool.figure_inventory(undefined, 'SF-TD3', sources, records, {}, base_dir=input_path.parent)[0]
    check('supplied_unmapped_figure_keeps_required_unknown_unit', len(unmapped['essential_elements']) == 1 and unmapped['essential_elements'][0]['kind'] == 'unresolved_essential_mapping')

    wrong_source_sha = copy.deepcopy(data)
    wrong_source_sha['sources'][1]['sha256'] = '0' * 64
    rejects('stale_source_JSON_hash_is_rejected', lambda: tool.collect_figure_evidence(wrong_source_sha, base_dir=input_path.parent))
    wrong_entity = copy.deepcopy(sources)
    wrong_entity['SOURCE-EDITORIAL-DESIGN-FIXTURES']['diagrams'][0]['entity_id'] = 'OTHER-ENTITY'
    rejects('source_diagram_entity_mismatch_is_rejected', lambda: tool.figure_inventory(data, 'SF-AD1', wrong_entity, records, {}, base_dir=input_path.parent))
    wrong_image = copy.deepcopy(sources)
    wrong_image['SOURCE-EDITORIAL-DESIGN-FIXTURES']['diagrams'][0]['png']['sha256'] = '0' * 64
    rejects('source_diagram_image_mismatch_is_rejected', lambda: tool.figure_inventory(data, 'SF-AD1', wrong_image, records, {}, base_dir=input_path.parent))
    wrong_asset = copy.deepcopy(data)
    wrong_asset['attachments'][3]['sha256'] = '0' * 64
    rejects('input_attachment_hash_mismatch_is_rejected', lambda: tool.figure_inventory(wrong_asset, 'SF-AD1', sources, records, {}, base_dir=input_path.parent))

    if bool(args.control_input) != bool(args.label_evidence):
        parser.error('--control-input and --label-evidence must be provided together')
    evidence = None
    if args.control_input is not None:
        control = tool.load(args.control_input.resolve())
        evidence = args.label_evidence.resolve()
        control_sources, control_records, control_manual = tool.collect_figure_evidence(control, evidence, base_dir=args.control_input.resolve().parent)
        control_figures = tool.figure_inventory(control, 'SF-TD3', control_sources, control_records, control_manual, base_dir=args.control_input.resolve().parent)
        check('private_manual_regions_are_bound_without_new_verdicts', len(control_figures) == len(control_manual) and all(f['essential_elements'] and all(e['kind'] == 'source_screen_region' and e['status'] == 'unknown' for e in f['essential_elements']) for f in control_figures))
        wrong_manual = copy.deepcopy(control_manual)
        next(iter(wrong_manual.values()))['source_sha256'] = '0' * 64
        rejects('manual_label_evidence_for_different_image_is_rejected', lambda: tool.figure_inventory(control, 'SF-TD3', control_sources, control_records, wrong_manual, base_dir=args.control_input.resolve().parent))
    report = {'schema_version': 'editorial-inventory-tool-checks-1', 'recorded_at': tool.now(), 'python': sys.version, 'tool': tool.file_record(BASE / 'freeze_observation_inventory.py'), 'check_script': tool.file_record(__file__), 'extended_input': tool.file_record(tool.R / 'examples/style-upgrade/illustrated-extended-v2/illustrated.project.json'), 'source_label_evidence': tool.file_record(evidence) if evidence else None, 'private_control_scope': 'requested' if evidence else 'not_requested', 'checks': checks, 'static_checks_ok': all(x['ok'] for x in checks), 'actual_quality_score_percent': None, 'actual_native_status': 'not_recorded', 'scope': 'Selection, source binding, denominator coverage, and rejection invariants only. No generated page or native output was inspected.'}
    artifact = tool.write(args.output, report)
    print(json.dumps({**artifact, 'checks': len(checks), 'static_checks_ok': report['static_checks_ok']}, ensure_ascii=False))
    if not report['static_checks_ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
