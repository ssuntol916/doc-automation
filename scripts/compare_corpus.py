"""Curated role mappings and resolved direct-format comparisons."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text())


def resolved_formats(profile):
    definitions = profile["definitions"]
    faces = {}
    for face in definitions["fontfaces"]:
        faces[face["attributes"].get("lang")] = {f["attributes"].get("id"): f["attributes"].get("face") for f in face.get("children", []) if f["tag"] == "font"}
    formats = []
    for ident, count in profile["statistics"]["char_property_usage"].items():
        prop = definitions["charProperties"].get(ident, {})
        font_ref = next((p["attributes"] for p in prop.get("children", []) if p["tag"] == "fontRef"), {})
        resolved = {lang: faces.get(lang.upper(), {}).get(font_id, f"UNRESOLVED:{font_id}") for lang, font_id in font_ref.items()}
        formats.append({"local_property_id_for_evidence_only": ident, "run_count": count, "fonts": resolved, "attributes": {k:v for k,v in prop.get("attributes", {}).items() if k != "id"}, "properties": [p for p in prop.get("children", []) if p["tag"] != "fontRef"]})
    return {"used_character_formats": formats, "used_named_styles": [{"local_id_for_evidence_only": ident, "paragraph_count": count, "definition": definitions["styles"].get(ident)} for ident,count in profile["statistics"]["style_usage"].items()]}


def main():
    base = ROOT / "analysis"
    templates = {d["id"]: d for d in load(base/"stage1/inventory.json")["documents"]}
    references = load(base/"stage2/inventory.json")["documents"]
    overrides = {
        "reference-sf-pm2": ("template-sf-pm1", "partial_role", "주간보고서와 월간보고서는 보고 주기·집계 단위가 달라 부분 대응"),
        "reference-sf-pm4": ("template-sf-pm2", "same_role", "회의록: 참조 코드 PM4와 양식 코드 PM2"),
        "reference-sf-pm5": ("template-sf-pm3", "same_role", "변경관리내역서: 참조 PM5와 양식 PM3"),
        "reference-sf-pm6": (None, "no_dedicated_template", "성과측정결과서: v2.0 개발산출물 19종에 전용 양식 없음; 2025 서식 KPI는 보조 근거"),
        "reference-sf-pm7": ("template-sf-pm4", "same_role", "요구사항추적표: 참조 PM7와 양식 PM4"),
    }
    mappings = []
    comparisons = []
    for ref in references:
        key, relation, reason = overrides.get(ref["id"], (ref["id"].replace("reference-", "template-"), "same_role", "코드뿐 아니라 제목과 내부 문서 역할을 상세 비교 보고서에서 확인"))
        if key is not None and key not in templates:
            raise ValueError(f"Missing mapped template: {key}")
        entry = {"reference_id": ref["id"], "reference_name": ref["display_name"], "reference_sha256": ref["sha256"], "template_id": key, "relationship": relation, "basis": reason, "version_equivalence": "unverified", "compliance": "requires_per_document_review"}
        if key:
            entry["template_sha256"] = templates[key]["sha256"]
        mappings.append(entry)
        rp = load(base/f"stage2/profiles/{ref['id']}.json")
        comparison = {"mapping": entry, "reference": {"statistics": rp["statistics"], "direct_formats": resolved_formats(rp)}}
        if key:
            tp = load(base/f"stage1/profiles/{key}.json")
            comparison["template"] = {"statistics": tp["statistics"], "direct_formats": resolved_formats(tp)}
        comparisons.append(comparison)
    mapping = {"scope": "Curated semantic-role mapping; same role does not establish same version or compliance", "mappings": mappings, "templates_without_same_role_reference": ["template-sf-os1", "template-sf-pm1"], "notes": ["Monthly report has only a partial weekly-report analogue", "All 19 reference files belong to one project; observations are not universal requirements"]}
    (base/"stage2/mapping.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2)+"\n")
    (base/"stage2/pair-comparisons.json").write_text(json.dumps(comparisons, ensure_ascii=False, indent=2)+"\n")
    print(f"Mapped {len(mappings)} reference documents by role")


if __name__ == "__main__":
    main()
