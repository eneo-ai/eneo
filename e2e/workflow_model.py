"""Opt-in deterministic decisions; tools, file storage and exports remain real."""

import hashlib
import json
import re

MARKER = "E2E_WORKFLOW_"


def text(message):
    value = message.get("content") or ""
    if isinstance(value, str):
        return value
    return "\n".join(
        str(item.get("text", "")) for item in value if isinstance(item, dict)
    )


def objects(value):
    """Find JSON records in model-visible prose, without assuming a prompt layout."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", value):
        try:
            found, _ = decoder.raw_decode(value[match.start() :])
            if isinstance(found, dict):
                yield found
        except ValueError:
            pass


def response(payload):
    messages = payload.get("messages") or []
    users = [i for i, message in enumerate(messages) if message.get("role") == "user"]
    if not users:
        return None
    current = users[-1]
    question = text(messages[current])
    if MARKER not in question:
        return None
    offered = [
        tool["function"] for tool in payload.get("tools", []) if "function" in tool
    ]
    calls = {}
    records = []
    for message in messages:
        for call in message.get("tool_calls") or []:
            calls[call["id"]] = call["function"]
        if message.get("role") == "tool" and message.get("tool_call_id") in calls:
            records.append((calls[message["tool_call_id"]], text(message)))
    completed = [
        call["function"]["name"]
        for message in messages[current + 1 :]
        for call in message.get("tool_calls") or []
    ]

    def find(name):
        return next(
            (
                tool
                for tool in offered
                if tool["name"] == name or tool["name"].endswith("__" + name)
            ),
            None,
        )

    def done(name):
        return sum(name == value or value.endswith("__" + name) for value in completed)

    def call(name, args):
        tool = find(name)
        if tool is None:
            return {"role": "assistant", "content": "E2E workflow unavailable: " + name}
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "workflow_"
                    + hashlib.sha256(question.encode()).hexdigest()[:8]
                    + "_"
                    + str(len(completed)),
                    "type": "function",
                    "function": {"name": tool["name"], "arguments": json.dumps(args)},
                }
            ],
        }

    def result(name):
        return next(
            (
                body
                for tool, body in reversed(records)
                if tool["name"].endswith("__" + name)
            ),
            "",
        )

    def finish(value):
        return {"role": "assistant", "content": value}

    if find("eneo_activate_skill") and not done("eneo_activate_skill"):
        keys = find("eneo_activate_skill")["parameters"]["properties"]["skill_key"][
            "enum"
        ]
        return call("eneo_activate_skill", {"skill_key": keys[0]})

    if "E2E_WORKFLOW_EDIT" in question:
        if done("edit_document"):
            return finish("E2E workflow revision complete.")
        references = re.findall(r"eneo-file:[0-9a-f]{32}", result("create_document"))
        if not references:
            return finish("E2E workflow missing saved document reference.")
        return call(
            "edit_document",
            {
                "revises": {"url": references[-1], "filename": "Workflow report.md"},
                "edits": [{"find": "Draft wording.", "replace": "Revised wording."}],
            },
        )

    entries = [
        item
        for message in messages
        for item in objects(text(message))
        if item.get("filename", "").endswith(".xlsx") and item.get("file_ref")
    ]
    if not entries:
        return finish("E2E workflow missing workbook reference.")
    file = {"url": entries[-1]["file_ref"], "filename": entries[-1]["filename"]}
    if not done("inspect_table"):
        return call("inspect_table", {"files": [file]})
    inspection = next(
        (item for item in objects(result("inspect_table")) if "files" in item), None
    )
    if not inspection:
        return finish("E2E workflow inspection failed.")
    file["sheet"] = inspection["files"][0]["sheets"][0]["name"]
    if not done("query_table"):
        return call(
            "query_table", {"file": file, "sql": "SELECT * FROM t", "display": "table"}
        )
    if done("query_table") == 1:
        return call(
            "query_table",
            {
                "file": file,
                "sql": "SELECT region, SUM(amount) AS total FROM t GROUP BY region ORDER BY region",
                "display": "none",
            },
        )
    query = next(
        (item for item in objects(result("query_table")) if "rows" in item), None
    )
    if not query:
        return finish("E2E workflow query failed.")
    if not done("create_chart"):
        return call(
            "create_chart",
            {
                "type": "bar",
                "title": "Saved amounts by region",
                "labels": [str(row[0]) for row in query["rows"]],
                "series": [
                    {
                        "name": "Amount",
                        "values": [float(row[1]) for row in query["rows"]],
                    }
                ],
            },
        )
    total = sum(float(row[1]) for row in query["rows"])
    missing = sum(
        item["missing_cached_results"] for item in query.get("calculation_warnings", [])
    )
    if not done("create_document"):
        return call(
            "create_document",
            {
                "title": "Workflow report",
                "filename": "Workflow report",
                "format": "md",
                "content": f"# Workflow report\n\nSaved-value total: {total:g}.\n\nDraft wording.\n\n{missing} formula result missing. Formulas were not recalculated; this total covers saved values only.",
            },
        )
    return finish(
        f"E2E workflow complete. Saved-value total: {total:g}; {missing} formula result missing."
    )
