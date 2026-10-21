"""Small, bounded JSON Schema boundary shared by authoring and execution.

Schemas are self-contained. Instance validation runs in a disposable process:
an asyncio deadline alone cannot interrupt a pathological regular expression.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, NoReturn, cast
from urllib.parse import unquote

MAX_SCHEMA_BYTES = 131_072
MAX_VALUE_BYTES = 2_097_152
MAX_DEPTH = 32
MAX_NODES = 8192
CHECK_TIMEOUT_SECONDS = 3
_slots = asyncio.Semaphore(4)
SCHEMA_2020_12 = "https://json-schema.org/draft/2020-12/schema"


def check_schema(schema: dict[str, Any], *, authored: bool = True) -> None:
    """Cheap bounded admission; no instance matching and no remote resolution."""
    from jsonschema import Draft202012Validator, SchemaError
    from jsonschema.validators import validator_for

    try:
        encoded = json.dumps(schema, allow_nan=False).encode()
    except (ValueError, RecursionError) as exc:
        raise ValueError("schema must be finite JSON") from exc
    if len(encoded) > MAX_SCHEMA_BYTES:
        raise ValueError("schema is too large")
    pending: list[tuple[Any, int]] = [(schema, 0)]
    nodes = 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise ValueError("schema is too deeply nested or complex")
        if isinstance(value, dict):
            for key, item in cast(dict[str, Any], value).items():
                if key == "$id":
                    raise ValueError("$id is not allowed; use local references")
                if key in ("$ref", "$dynamicRef") and (
                    not isinstance(item, str) or not item.startswith("#")
                ):
                    raise ValueError("schema references must stay inside this schema")
                if authored and key == "$schema" and item != SCHEMA_2020_12:
                    raise ValueError("authored schemas must use JSON Schema 2020-12")
                pending.append((item, depth + 1))
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in cast(list[Any], value))
    try:
        # jsonschema supports a None fallback, though its annotation omits it.
        validator: Any = (
            validator_for(schema, default=cast(Any, None))
            if "$schema" in schema
            else Draft202012Validator
        )
        if validator is None:
            raise ValueError("unsupported JSON Schema dialect")
        validator.check_schema(schema)
    except (SchemaError, RecursionError) as exc:
        raise ValueError("invalid JSON Schema") from exc
    # Only actual schema locations can be referenced; defaults/examples are
    # data, even when their JSON happens to look like a schema.
    locations: dict[str, Any] = {}
    anchors: set[str] = set()
    references: list[str] = []
    schema_pending: list[tuple[Any, str]] = [(schema, "#")]
    single = {
        "additionalProperties",
        "unevaluatedProperties",
        "items",
        "contains",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
        "additionalItems",
        "unevaluatedItems",
        "contentSchema",
    }
    maps = {
        "properties",
        "patternProperties",
        "$defs",
        "definitions",
        "dependentSchemas",
        "dependencies",
    }
    lists = {"allOf", "anyOf", "oneOf", "prefixItems"}
    while schema_pending:
        node, path = schema_pending.pop()
        if not isinstance(node, (dict, bool)):
            continue
        locations[path] = node
        if not isinstance(node, dict):
            continue
        for key, item in cast(dict[str, Any], node).items():
            if key in ("$anchor", "$dynamicAnchor"):
                anchors.add("#" + str(item))
            elif key in ("$ref", "$dynamicRef"):
                references.append(unquote(str(item)))
            elif key in single and isinstance(item, (dict, bool)):
                schema_pending.append((cast(Any, item), path + "/" + key))
            elif key in maps and isinstance(item, dict):
                schema_pending.extend(
                    (
                        child,
                        path
                        + "/"
                        + key
                        + "/"
                        + str(name).replace("~", "~0").replace("/", "~1"),
                    )
                    for name, child in cast(dict[str, Any], item).items()
                )
            elif (key in lists or key == "items") and isinstance(item, list):
                schema_pending.extend(
                    (child, path + "/" + key + "/" + str(index))
                    for index, child in enumerate(cast(list[Any], item))
                )
    if any(ref not in locations and ref not in anchors for ref in references):
        raise ValueError("schema reference does not name a schema in this document")


async def validate_value(
    value: Any, schema: dict[str, Any], *, authored: bool = True
) -> None:
    """Fail closed within one deadline, including queue wait and process cleanup."""
    check_schema(schema, authored=authored)
    try:
        payload = json.dumps(
            {"schema": schema, "value": value}, allow_nan=False
        ).encode()
    except (ValueError, RecursionError) as exc:
        raise ValueError("value must be finite JSON") from exc
    if len(payload) > MAX_VALUE_BYTES:
        raise ValueError("JSON validation input is too large")
    process: asyncio.subprocess.Process | None = None
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            async with _slots:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "eneo.flows.schema_validation",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                output, _ = await process.communicate(payload)
                if output.startswith(b"invalid:"):
                    raise ValueError(output[8:508].decode(errors="replace"))
                if process.returncode != 0 or output != b"ok":
                    raise ValueError("value does not satisfy the JSON schema")
    except (TimeoutError, OSError) as exc:
        raise ValueError(
            "JSON schema validation could not finish within its limit"
        ) from exc
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


def _child() -> None:
    import resource

    from jsonschema import ValidationError
    from jsonschema.validators import validator_for
    from referencing import Registry
    from referencing.exceptions import NoSuchResource

    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))

    def refuse(uri: str) -> NoReturn:
        raise NoSuchResource(ref=uri)

    payload = json.loads(sys.stdin.buffer.read(MAX_VALUE_BYTES + 1))
    schema = payload["schema"]
    validator = validator_for(schema)
    try:
        validator(schema, registry=Registry[Any](retrieve=refuse)).validate(
            payload["value"]
        )
    except ValidationError as exc:
        path = ".".join(str(item) for item in exc.absolute_path)[:200] or "value"
        message = f"{path}: schema rule {exc.validator} was not satisfied"
        raw_instance: Any = exc.instance
        if exc.validator == "required" and isinstance(raw_instance, dict):
            required = cast(list[str], exc.validator_value)
            instance = cast(dict[str, Any], raw_instance)
            missing = [key[:80] for key in required if key not in instance][:4]
            message = f"{path}: required properties missing: {', '.join(missing)}"
        sys.stdout.buffer.write(b"invalid:" + message.encode()[:500])
        return
    sys.stdout.buffer.write(b"ok")


if __name__ == "__main__":
    _child()
