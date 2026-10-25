"""Build explicitly synthetic, fact-linked screen design fixtures for editorial QA.

SVGs are deterministic diagrams of supplied field/button definitions, not screen
captures or execution evidence. Source facts and the original input stay intact.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import html
import json
import os
from pathlib import Path
import textwrap

import pymupdf


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def text(x, y, value, size=25, fill="#233044", weight="normal"):
    return f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="{size}" fill="{fill}" font-weight="{weight}">{html.escape(str(value))}</text>'


def screen_svg(screen):
    fields = screen.get("fields", [])
    rows = (len(fields) + 1) // 2
    height = max(760, 340 + rows * 100)
    chunks = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="{height}" viewBox="0 0 1600 {height}">',
              f'<rect width="1600" height="{height}" fill="#f4f6f8"/>',
              '<rect width="1600" height="80" fill="#23364c"/>',
              text(32, 51, screen.get("system_name", "시스템 설계"), 30, "#ffffff", "bold"),
              text(895, 49, "합성 설계 시안 | 실제 실행 화면 아님", 27, "#ffffff"),
              text(42, 126, screen.get("path", "접근 경로 미확인"), 22, "#65748a"),
              text(42, 181, screen["name"], 36, weight="bold"),
              text(42, 222, f"화면 ID: {screen['id']} · 입력 항목의 배치 검토용", 23, "#65748a")]
    for index, field in enumerate(fields):
        x = 42 + (index % 2) * 780
        y = 280 + (index // 2) * 100
        label = field["name"] + (" *" if field.get("required") is True else "")
        chunks.extend([text(x, y, label, 25, weight="bold"),
                       f'<rect x="{x + 215}" y="{y - 31}" width="485" height="53" rx="4" fill="#ffffff" stroke="#bec8d2" stroke-width="2"/>',
                       text(x + 230, y + 4, f"값 미입력 · 형식: {field.get('data_type') or '미확인'}", 22, "#75849a")])
    bottom = height - 155
    for index, button in enumerate(screen.get("buttons", [])):
        x = 42 + index * 180
        chunks.extend([f'<rect x="{x}" y="{bottom}" width="150" height="56" rx="5" fill="{("#315e88" if index == 0 else "#ffffff")}" stroke="#315e88" stroke-width="2"/>',
                       text(x + 47, bottom + 37, button["name"], 25, "#ffffff" if index == 0 else "#315e88")])
    chunks.extend([text(42, height - 53, "* 필수 입력 설계 · 검증 결과, 저장 성공, 측정값은 표시하지 않음", 23, "#65748a"), "</svg>"])
    return "\n".join(chunks)


def diagram_svg(title, identifier, labels, *, arrows):
    """A code-defined diagram of provided synthetic list/relationship labels."""
    count = max(1, len(labels))
    columns = min(4, count)
    rows = (count + columns - 1) // columns
    height = 260 + rows * 350
    chunks = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="{height}" viewBox="0 0 1800 {height}">',
        f'<rect width="1800" height="{height}" fill="#ffffff"/>', '<rect width="1800" height="82" fill="#23364c"/>',
        text(35, 56, title, 38, "#ffffff", "bold"), text(35, 140, "합성 설계 시안 | 실제 수행·구현 증거 아님", 35, "#65748a"),
        text(35, 192, identifier, 32, "#65748a")]
    width = 1640 / columns
    for index, label in enumerate(labels):
        x, y = 55 + (index % columns) * width, 240 + (index // columns) * 350
        box_width = width - 50
        lines = []
        for line in str(label).splitlines():
            lines.extend(textwrap.wrap(line, max(9, int(box_width / 37))) or [""])
        if len(lines) > 7:
            raise ValueError("Diagram label exceeds fixture capacity; preserve it in a larger diagram")
        chunks.append(f'<rect x="{x}" y="{y}" width="{box_width}" height="300" rx="8" fill="#eef3f8" stroke="#5d7792" stroke-width="2"/>')
        for j, line in enumerate(lines):
            chunks.append(text(x + 20, y + 48 + j * 37, line, 36))
        if arrows and index + 1 < len(labels) and (index + 1) % columns:
            x2 = x + box_width
            chunks.extend([f'<path d="M {x2+5} {y+150} H {x2+40}" stroke="#315e88" stroke-width="4" fill="none"/>',
                           f'<path d="M {x2+30} {y+140} L {x2+43} {y+150} L {x2+30} {y+160}" stroke="#315e88" stroke-width="4" fill="none"/>'])
    chunks.append("</svg>")
    return "\n".join(chunks)


def build(input_path, output_dir, *, with_diagrams=False):
    source = Path(input_path).resolve()
    folder = Path(output_dir).resolve()
    if folder == source.parent or folder in source.parents:
        raise ValueError("Use a separate fixture output directory")
    if (folder / "illustrated.project.json").exists():
        raise ValueError("Refusing to overwrite an existing fixture input; use a new directory")
    folder.mkdir(parents=True, exist_ok=True)
    data = json.loads(source.read_text())
    if data["dataset_kind"] != "synthetic":
        raise ValueError("Design fixtures are only supported for explicitly synthetic input")
    result = deepcopy(data)
    for record in result["sources"] + result["attachments"]:
        if record.get("path"):
            path = Path(record["path"]).expanduser()
            record["path"] = os.path.relpath((source.parent / path).resolve() if not path.is_absolute() else path.resolve(), folder)
    observation = {"scope": "Synthetic screen design diagrams, not implementation/execution/approval evidence", "input": {"path": os.path.relpath(source, folder), "sha256": digest(source)}, "screens": []}
    generated = []
    for i, screen in enumerate(data["screens"]):
        svg, png = folder / f"screen-{i+1:02}.svg", folder / f"screen-{i+1:02}.png"
        svg.write_text(screen_svg(screen), encoding="utf-8")
        with pymupdf.open(stream=svg.read_bytes(), filetype="svg") as doc:
            doc[0].get_pixmap(alpha=False).save(png)
        record = {"id": screen["id"], "name": screen["name"], "fields": screen.get("fields", []), "buttons": screen.get("buttons", []),
                  "source_refs": screen["source_refs"], "svg": {"path": os.path.relpath(svg, folder), "sha256": digest(svg)}, "png": {"path": os.path.relpath(png, folder), "sha256": digest(png)},
                  "is_synthetic_design": True, "actual_execution": False}
        observation["screens"].append(record)
        generated.append((i, png, record))
    observation["diagrams"] = []
    diagram_targets = []
    if with_diagrams:
        for i, process in enumerate(result["project"].get("business_processes", [])):
            for key, steps, label in (("as_is_attachment_ids", "current_steps", "현행 업무 가정"), ("to_be_attachment_ids", "target_steps", "개선 업무 설계")):
                diagram_targets.append((process, key, label, process.get(steps, []), True, process.get("source_refs", [])))
        for system in result["project"].get("systems", []):
            diagram_targets.append((system, "as_is_diagram_ids", "현행 시스템 가정", [system.get("as_is_description") or "미확인"], False, system.get("source_refs", [])))
            diagram_targets.append((system, "to_be_diagram_ids", "목표 시스템 설계", [system.get("to_be_description") or "미확인", system.get("configuration") or "미확인"], False, system.get("source_refs", [])))
        for program in result.get("programs", []):
            diagram_targets.append((program, "module_flow_attachment_ids", "프로그램 기능 명세 항목(실행 순서 미확정)", program.get("functions", []), False, program.get("source_refs", [])))
        for i, (entity, slot, title, labels, arrows, refs) in enumerate(diagram_targets):
            svg, png = folder / f"diagram-{i+1:02}.svg", folder / f"diagram-{i+1:02}.png"
            svg.write_text(diagram_svg(title, entity["id"], labels or ["자료 미제공"], arrows=arrows))
            with pymupdf.open(stream=svg.read_bytes(), filetype="svg") as doc:
                doc[0].get_pixmap(alpha=False).save(png)
            observation["diagrams"].append({"entity_id": entity["id"], "slot": slot, "title": title, "essential_labels": labels, "arrows_represent_supplied_step_order": arrows, "source_refs": refs,
                "svg": {"path": os.path.relpath(svg, folder), "sha256": digest(svg)}, "png": {"path": os.path.relpath(png, folder), "sha256": digest(png)}, "is_synthetic_design": True, "actual_execution": False})
    fact_source = folder / "design-fixture-facts.json"
    fact_source.write_text(json.dumps(observation, ensure_ascii=False, indent=2) + "\n")
    sid = "SOURCE-EDITORIAL-DESIGN-FIXTURES"
    if sid in {s["id"] for s in result["sources"]}:
        raise ValueError("Fixture source already exists")
    result["sources"].append({"id": sid, "title": "입력 필드·버튼에서 작성한 합성 설계 시안", "kind": "synthetic", "path": os.path.relpath(fact_source, folder), "sha256": digest(fact_source), "verification_status": "provided"})
    for i, png, record in generated:
        aid = f"EDITORIAL-SCREEN-DESIGN-{i+1:02}"
        result["attachments"].append({"id": aid, "name": record["name"] + " 합성 설계 시안", "status": "synthetic", "source_refs": [{"source_id": sid, "locator": f"/screens/{i}"}],
            "path": os.path.relpath(png, folder), "sha256": digest(png), "source_id": sid, "purpose": "입력 필드·버튼 배치와 문서의 그림 가독성 검증. 실제 화면·수행·승인 증거 아님.",
            "verification_status": "provided", "media_type": "image/png", "caption": "합성 설계 시안·실제 실행화면 아님 — " + record["name"], "notes": "동일 입력의 fields/buttons에서 결정적으로 구성한 시안. 기본값·실행 결과는 기입하지 않음."})
        result["screens"][i]["after_attachment_ids"] = [aid]
    for i, (entity, slot, title, labels, arrows, refs) in enumerate(diagram_targets):
        record = observation["diagrams"][i]
        aid = f"EDITORIAL-DIAGRAM-DESIGN-{i+1:02}"
        result["attachments"].append({"id": aid, "name": title, "status": "synthetic", "source_refs": [{"source_id": sid, "locator": f"/diagrams/{i}"}],
            "path": record["png"]["path"], "sha256": record["png"]["sha256"], "source_id": sid, "purpose": "제공된 합성 업무/명세 항목의 도식과 문서 배치·판독성 검증", "verification_status": "provided", "media_type": "image/png",
            "caption": "합성 설계 시안·실제 수행/구현 증거 아님 — " + title, "notes": "원문의 단계 배열은 명시된 순서로 표시. 기능 항목 목록은 실행 순서나 인과관계로 확정하지 않음."})
        entity[slot] = [aid]
    target = folder / "illustrated.project.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--with-diagrams", action="store_true")
    args = parser.parse_args()
    print(build(args.input, args.output, with_diagrams=args.with_diagrams))
