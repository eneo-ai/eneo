"""Inspect saved Builder plans and proposal diagnostics without provider calls."""

import json
from pathlib import Path

ROOT = Path(__file__).parent
CONTROLS = {"titel", "datum", "forfattare", "sammanfattning", "bakgrund", "analys", "slutsatser"}
MEMBERS = {"uppgift", "ansvarig", "tidsfrist"}
ROWS = []

for revision in ("parent", "candidate", "candidate2", "candidate3"):
    folder = ROOT / ("provider-" + revision)
    results = json.loads((folder / "results.json").read_text())
    assert len(results) == 3, (revision, "incomplete acquisition")
    for result in results:
        case = result["case"]
        evidence = folder / case
        diagnostics = json.loads((evidence / "proposal-telemetry.json").read_text())
        attempts = [attempt for turn in diagnostics["proposal_turns"] for attempt in turn["attempts"]]
        checks = {"plan_proposed": result["outcome"] == "plan"}
        if checks["plan_proposed"]:
            plan = json.loads((evidence / "plan.json").read_text())
            steps = plan["proposal"]["spec"]["steps"]
            checks["no_lint_warnings"] = not plan["proposal"]["lint_warnings"]
            if case.endswith("template_report"):
                terminal = steps[-1]
                properties = steps[0]["output_contract"]["properties"]
                checks["template_fill_docx"] = terminal["output_type"] == "docx" and terminal["output_mode"] == "template_fill"
                checks["seven_bindings"] = set(terminal["output_config"]["bindings"]) == CONTROLS
                checks["seven_string_fields"] = set(properties) == CONTROLS and all(field.get("type") == "string" for field in properties.values())
            else:
                contract = steps[-1]["output_contract"]
                properties = contract["properties"]
                items = properties.get("atgarder", {}).get("items", {})
                members = items.get("properties", {})
                checks["top_level_fields"] = set(properties) == {"sammanfattning", "atgarder"}
                checks["summary_string"] = properties.get("sammanfattning", {}).get("type") == "string"
                checks["array_of_objects"] = properties.get("atgarder", {}).get("type") == "array" and items.get("type") == "object"
                checks["exact_item_members"] = set(members) == MEMBERS and set(items.get("required", [])) == MEMBERS
                checks["string_item_members"] = set(members) == MEMBERS and all(field.get("type") == "string" for field in members.values())
        ROWS.append({
            "revision": revision,
            "case": case,
            "session_id": result["session_id"],
            "plan_id": result.get("plan_id"),
            "proposal_calls": len(attempts),
            "proposal_repairs": sum(attempt["kind"] != "initial" for attempt in attempts),
            "proposal_elapsed_ms": sum(attempt["elapsed_ms"] for attempt in attempts),
            "proposal_total_tokens": sum(attempt["total_tokens"] for attempt in attempts),
            "session_wall_seconds": result["wall_seconds"],
            "checks": checks,
            "requirements_pass": all(checks.values()),
        })

print(json.dumps(ROWS, ensure_ascii=False, indent=2))
assert all(row["requirements_pass"] for row in ROWS if row["revision"] == "candidate3"), "Final candidate misses a frozen requirement"
