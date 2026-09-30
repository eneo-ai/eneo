from __future__ import annotations

import json
import random
import socket
import urllib.request
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import jsonschema
import pytest
from referencing.exceptions import Unresolvable

from eneo.flows import output_processing
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    derive_freeform_schema_candidates,
    parse_schema_candidate,
)
from eneo.flows.ai_builder.ai_builder_tools import (
    NativeStrictSchemaError,
    validate_native_strict_schema,
    validate_propose_flow_tool_arguments,
)
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.domain.flow import Flow, FlowRunStatus
from eneo.flows.domain.flow_step_validation import FlowStepValidationError
from eneo.flows.flow_authoring_spec import AssistantSpec, FlowDraftSpecCore, StepSpec
from eneo.flows.output_processing import (
    compile_validators,
    validate_against_contract,
    validate_schema_syntax,
)
from eneo.flows.runtime.step_input_validation import validate_input_contract
from eneo.main.exceptions import TypedIOValidationException
from tests.unittests.flows import (
    test_flow_run_review_checkpoint_service as review_tests,
)
from tests.unittests.flows.test_flow_executor_runtime import (
    _build_executor,
    _run,
    _step_for_execute_step,
)
from tests.unittests.flows.test_flow_service import _service, _step


@pytest.fixture
def schema_listener():
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"type":"object"}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/schema.json", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _remote_schema(uri, keyword="$ref"):
    return {"type": "object", "properties": {"value": {keyword: uri}}}


def _validate(owner, schema):
    if owner == "contract":
        validate_against_contract({"value": {}}, schema, label="Step 2 output")
    elif owner == "syntax":
        validate_schema_syntax(schema, label="Step 2 output_contract")
    else:
        validators = compile_validators(
            [
                SimpleNamespace(
                    step_order=2, input_contract=schema, output_contract=schema
                )
            ]
        )
        validators[(owner, 2)].validate({"value": {}})


@pytest.mark.parametrize("owner", ["contract", "syntax", "input", "output"])
@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
@pytest.mark.filterwarnings(
    "ignore:Automatically retrieving remote references:DeprecationWarning"
)
def test_contract_validators_never_retrieve_from_listener(
    schema_listener, owner, keyword
):
    uri, requests = schema_listener
    error = Unresolvable if owner in {"input", "output"} else TypedIOValidationException
    with pytest.raises(error):
        _validate(owner, _remote_schema(uri, keyword))
    assert requests == []


@pytest.mark.parametrize("owner", ["contract", "syntax", "input", "output"])
@pytest.mark.parametrize("scheme", ["http", "https", "file"])
def test_contract_validators_never_open_sockets_or_urls(
    monkeypatch, schema_listener, tmp_path, owner, scheme
):
    uri, requests = schema_listener
    if scheme == "https":
        uri = uri.replace("http:", "https:")
    elif scheme == "file":
        path = tmp_path / "schema.json"
        path.write_text('{"type":"object"}')
        uri = path.as_uri()
    connect = Mock(side_effect=AssertionError("Schema opened a socket"))
    retrieve = Mock(side_effect=AssertionError("Schema retrieved a URL"))
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(urllib.request, "urlopen", retrieve)
    error = Unresolvable if owner in {"input", "output"} else TypedIOValidationException
    with pytest.raises(error):
        _validate(owner, _remote_schema(uri))
    connect.assert_not_called()
    retrieve.assert_not_called()
    assert requests == []


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
@pytest.mark.parametrize(
    "uri", ["https://example.com/schema", "other.json#/$defs/x", "", "urn:example:x"]
)
def test_authoring_rejects_non_fragment_refs_with_step_and_pointer(keyword, uri):
    schema = {"$defs": {"a/b~c": {"allOf": [{keyword: uri}]}}}
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_schema_syntax(schema, label="Step 2 output_contract")
    assert exc_info.value.code == "typed_io_invalid_schema"
    assert "Step 2 output_contract" in str(exc_info.value)
    assert f"/$defs/a~1b~0c/allOf/0/{keyword}" in str(exc_info.value)


@pytest.mark.parametrize("ref", ["#/$defs/value", "#value"])
@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
@pytest.mark.parametrize("anchor", ["$anchor", "$dynamicAnchor"])
def test_same_document_refs_validate_in_all_owners(ref, keyword, anchor):
    schema = {
        "type": "object",
        "$defs": {"value": {anchor: "value", "type": "object"}},
        "properties": {"value": {keyword: ref}},
    }
    for owner in ("syntax", "contract", "input", "output"):
        _validate(owner, schema)


def test_reference_like_instance_data_is_not_a_schema_reference():
    validate_schema_syntax(
        {
            "type": "object",
            "properties": {"$ref": {"type": "string"}},
            "default": {"$ref": "https://example.com/data"},
            "examples": [{"$dynamicRef": "https://example.com/data"}],
        },
        label="Step 2 output_contract",
    )


def test_missing_local_reference_is_a_typed_runtime_violation():
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract(
            {}, {"$ref": "#/$defs/missing"}, label="Step 2 output"
        )
    assert exc_info.value.code == "typed_io_contract_violation"


def test_remote_dialect_and_vocabulary_never_trigger_retrieval(
    monkeypatch, schema_listener
):
    uri, requests = schema_listener
    retrieve = Mock(side_effect=AssertionError("Schema retrieved a dialect"))
    connect = Mock(side_effect=AssertionError("Schema opened a socket"))
    monkeypatch.setattr(urllib.request, "urlopen", retrieve)
    monkeypatch.setattr(socket, "create_connection", connect)
    schema = {"$schema": uri, "$vocabulary": {uri: True}, "type": "object"}
    for owner in ("contract", "input", "output"):
        _validate(owner, schema)
    with pytest.raises(TypedIOValidationException) as exc_info:
        _validate("syntax", schema)
    assert exc_info.value.code == "typed_io_invalid_schema"
    retrieve.assert_not_called()
    connect.assert_not_called()
    assert requests == []


def test_authoring_rejects_remote_ref_in_legacy_definitions(schema_listener):
    uri, requests = schema_listener
    schema = {
        "type": "object",
        "definitions": {"value": {"$ref": uri}},
        "$ref": "#/definitions/value",
    }
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_schema_syntax(schema, label="Step 2 output_contract")
    assert exc_info.value.code == "typed_io_invalid_schema"
    assert "/definitions/value/$ref" in str(exc_info.value)
    assert requests == []


@pytest.mark.parametrize("input_type", ["json", "text"])
def test_runtime_input_contract_never_retrieves(schema_listener, input_type):
    uri, requests = schema_listener
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_input_contract(
            step_order=2,
            input_type=input_type,
            input_contract=_remote_schema(uri),
            text=json.dumps({"value": {}}),
            structured={"value": {}} if input_type == "json" else None,
        )
    assert exc_info.value.code == "typed_io_contract_violation"
    assert requests == []


@pytest.mark.asyncio
async def test_review_edit_contract_never_retrieves(user, schema_listener):
    uri, requests = schema_listener
    repo, access_policy = AsyncMock(), AsyncMock()
    run = review_tests._run(user=user, flow_id=uuid4())
    checkpoint = review_tests._review_checkpoint(
        user, run, output_contract_json=_remote_schema(uri)
    )
    access_policy.load_run.return_value = run
    repo.get_review_checkpoint_for_edit.return_value = checkpoint
    service = review_tests._service(
        user, checkpoint_repo=repo, access_policy=access_policy
    )
    with pytest.raises(TypedIOValidationException) as exc_info:
        await review_tests._edit(
            service=service, run=run, checkpoint=checkpoint, edited_value={"value": {}}
        )
    assert exc_info.value.code == "typed_io_contract_violation"
    repo.edit_review_checkpoint_payload.assert_not_awaited()
    assert requests == []


@pytest.mark.parametrize("owner", ["native", "proposal"])
def test_builder_tool_validators_never_retrieve(schema_listener, owner):
    uri, requests = schema_listener
    schema = {
        **_remote_schema(uri),
        "required": ["value"],
        "additionalProperties": False,
    }
    error = NativeStrictSchemaError if owner == "native" else TypedIOValidationException
    with pytest.raises(error):
        if owner == "native":
            validate_native_strict_schema(schema)
        else:
            validate_propose_flow_tool_arguments(
                arguments={"value": {}},
                tool_schema={
                    "type": "function",
                    "function": {"name": "test", "parameters": schema},
                },
            )
    assert requests == []


def test_builder_schema_evidence_rejects_remote_references(schema_listener):
    uri, requests = schema_listener
    assert parse_schema_candidate(json.dumps(_remote_schema(uri))) is None
    assert requests == []


def test_builder_compiled_spec_rejects_remote_references(schema_listener):
    uri, requests = schema_listener
    result = validate_spec(
        FlowDraftSpecCore(
            flow_name="Contracts",
            steps=[
                StepSpec(
                    plan_step_ref="produce",
                    name="Produce",
                    assistant_spec=AssistantSpec(instructions="Produce JSON"),
                    input_source="flow_input",
                    output_type="json",
                    output_contract=_remote_schema(uri),
                )
            ],
        )
    )
    assert not result.valid
    assert any(
        error.code == "invalid_output_contract_schema" for error in result.errors
    )
    assert requests == []


@pytest.mark.asyncio
async def test_executor_same_document_output_contract(user):
    executor, _, _, _ = _build_executor(user)
    schema = {
        "type": "object",
        "$defs": {"value": {"type": "object"}},
        "properties": {"value": {"$ref": "#/$defs/value"}},
    }
    result = await executor._process_typed_output(
        full_text=json.dumps({"value": {}}),
        step=replace(
            _step_for_execute_step(), output_type="json", output_contract=schema
        ),
        run=_run(status=FlowRunStatus.RUNNING, user=user),
    )
    assert result.structured_output == {"value": {}}


@pytest.mark.asyncio
async def test_executor_legacy_output_contract_never_retrieves(user, schema_listener):
    uri, requests = schema_listener
    executor, _, _, _ = _build_executor(user)
    step = replace(
        _step_for_execute_step(),
        output_type="json",
        output_contract=_remote_schema(uri),
    )
    with pytest.raises(TypedIOValidationException) as exc_info:
        await executor._process_typed_output(
            full_text=json.dumps({"value": {}}),
            step=step,
            run=_run(status=FlowRunStatus.RUNNING, user=user),
        )
    assert exc_info.value.code == "typed_io_contract_violation"
    assert requests == []


@pytest.mark.parametrize("scheme", ["http", "https", "file"])
@pytest.mark.asyncio
async def test_executor_output_contract_never_opens_sockets_or_urls(
    user, schema_listener, tmp_path, monkeypatch, scheme
):
    uri, requests = schema_listener
    if scheme == "https":
        uri = uri.replace("http:", "https:")
    elif scheme == "file":
        path = tmp_path / "schema.json"
        path.write_text('{"type":"object"}')
        uri = path.as_uri()
    connect = Mock(side_effect=AssertionError("Schema opened a socket"))
    retrieve = Mock(side_effect=AssertionError("Schema retrieved a URL"))
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(urllib.request, "urlopen", retrieve)
    executor, _, _, _ = _build_executor(user)
    with pytest.raises(TypedIOValidationException) as exc_info:
        await executor._process_typed_output(
            full_text=json.dumps({"value": {}}),
            step=replace(
                _step_for_execute_step(),
                output_type="json",
                output_contract=_remote_schema(uri),
            ),
            run=_run(status=FlowRunStatus.RUNNING, user=user),
        )
    assert exc_info.value.code == "typed_io_contract_violation"
    connect.assert_not_called()
    retrieve.assert_not_called()
    assert requests == []


@pytest.mark.parametrize("operation", ["create", "update", "publish"])
@pytest.mark.parametrize("field", ["input_contract", "output_contract"])
@pytest.mark.asyncio
async def test_authoring_services_reject_remote_contracts(
    user, schema_listener, operation, field
):
    uri, requests = schema_listener
    flow_repo, version_repo = AsyncMock(), AsyncMock()
    service = _service(user=user, flow_repo=flow_repo, version_repo=version_repo)
    steps = [
        _step().model_copy(
            update={
                "output_contract": {
                    "type": "object",
                    "properties": {"value": {"type": "object"}},
                }
            }
        ),
        _step(2).model_copy(update={"input_type": "json", field: _remote_schema(uri)}),
    ]
    flow = Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Contracts",
        steps=steps,
    )
    stored = flow.model_copy(
        update={"steps": [steps[0], steps[1].model_copy(update={field: None})]}
    )
    flow_repo.get.return_value = stored if operation == "update" else flow
    with pytest.raises(FlowStepValidationError) as exc_info:
        if operation == "create":
            await service.create_flow(
                space_id=flow.space_id, name=flow.name, steps=steps
            )
        elif operation == "update":
            await service.update_flow(flow_id=flow.id, steps=steps)
        else:
            await service.publish_flow(flow_id=flow.id)
    assert exc_info.value.code == f"invalid_{field}_schema"
    assert exc_info.value.step_order == 2
    assert "/properties/value/$ref" in str(exc_info.value)
    assert exc_info.value.context["json_pointer"] == "/properties/value/$ref"
    flow_repo.create.assert_not_awaited()
    flow_repo.update.assert_not_awaited()
    version_repo.create.assert_not_awaited()
    assert requests == []


_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_DRAFT_07 = "http://json-schema.org/draft-07/schema#"
_DRAFT_04 = "http://json-schema.org/draft-04/schema#"
_DRAFT_03 = "http://json-schema.org/draft-03/schema#"
_REMOTE = "https://example.com/schema"


def _refused(schema) -> TypedIOValidationException:
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_schema_syntax(schema, label="Step 2 output_contract")
    assert exc_info.value.code == "typed_io_invalid_schema"
    assert "Step 2 output_contract" in str(exc_info.value)
    return exc_info.value


_SCHEMA_POSITIONS = {
    "not": (lambda s: {"not": s}, "/not"),
    "if": (lambda s: {"if": s, "then": {}}, "/if"),
    "then": (lambda s: {"if": True, "then": s}, "/then"),
    "else": (lambda s: {"if": False, "else": s}, "/else"),
    "items": (lambda s: {"items": s}, "/items"),
    "prefixItems": (lambda s: {"prefixItems": [s]}, "/prefixItems/0"),
    "contains": (lambda s: {"contains": s}, "/contains"),
    "propertyNames": (lambda s: {"propertyNames": s}, "/propertyNames"),
    "additionalProperties": (
        lambda s: {"additionalProperties": s},
        "/additionalProperties",
    ),
    "patternProperties": (
        lambda s: {"patternProperties": {"^a": s}},
        "/patternProperties/^a",
    ),
    "dependentSchemas": (
        lambda s: {"dependentSchemas": {"a": s}},
        "/dependentSchemas/a",
    ),
    "unevaluatedProperties": (
        lambda s: {"unevaluatedProperties": s},
        "/unevaluatedProperties",
    ),
    "unevaluatedItems": (lambda s: {"unevaluatedItems": s}, "/unevaluatedItems"),
    "contentSchema": (
        lambda s: {"contentMediaType": "application/json", "contentSchema": s},
        "/contentSchema",
    ),
    "$defs": (lambda s: {"$defs": {"a": s}}, "/$defs/a"),
    "properties": (lambda s: {"properties": {"a": s}}, "/properties/a"),
    "allOf": (lambda s: {"allOf": [s]}, "/allOf/0"),
    "anyOf": (lambda s: {"anyOf": [s]}, "/anyOf/0"),
    "oneOf": (lambda s: {"oneOf": [s]}, "/oneOf/0"),
}


@pytest.mark.parametrize(
    ("keyword", "defect"),
    [
        ("$ref", {"$ref": _REMOTE}),
        ("$id", {"$id": "https://example.com/sub"}),
        ("$schema", {"$schema": _DRAFT_07}),
    ],
)
@pytest.mark.parametrize("position", list(_SCHEMA_POSITIONS))
def test_authoring_refuses_a_defect_at_every_schema_position(position, keyword, defect):
    build, prefix = _SCHEMA_POSITIONS[position]
    error = _refused(build(defect))
    pointer = f"{prefix}/{keyword}"
    assert pointer in str(error)
    assert error.context == {"json_pointer": pointer, "schema_rule": keyword}


@pytest.mark.parametrize(
    ("schema", "pointer"),
    [
        ({"$schema": _DRAFT_07, "type": "object"}, "/$schema"),
        ({"$schema": _DRAFT_04, "type": "object"}, "/$schema"),
        ({"$schema": "https://example.com/meta.json"}, "/$schema"),
        ({"$schema": _DIALECT + "#"}, "/$schema"),
        ({"$id": "https://example.com/root", "type": "object"}, "/$id"),
        (
            {
                "type": "object",
                "properties": {
                    "a": {
                        "$schema": _DRAFT_07,
                        "dependencies": {"x": {"$ref": _REMOTE}},
                    }
                },
            },
            "/properties/a/$schema",
        ),
        (
            {
                "type": "object",
                "properties": {
                    "a": {"$schema": _DRAFT_03, "extends": {"$ref": _REMOTE}}
                },
            },
            "/properties/a/$schema",
        ),
        (
            {
                "type": "object",
                "properties": {
                    "a": {
                        "$schema": _DRAFT_07,
                        "$id": "https://example.com/sub.json",
                        "$ref": "#/definitions/x",
                    }
                },
            },
            "/properties/a/$id",
        ),
    ],
)
def test_authoring_refuses_dialect_and_base_uri_changes(schema, pointer):
    error = _refused(schema)
    assert pointer in str(error)
    assert error.context["json_pointer"] == pointer


def test_authoring_accepts_the_2020_12_dialect_and_dialect_words_as_data():
    validate_schema_syntax(
        {
            "$schema": _DIALECT,
            "type": "object",
            "properties": {
                "$id": {"type": "string"},
                "$schema": {"type": "string"},
                "nested": {"$schema": _DIALECT, "type": "object"},
            },
            "required": ["$id"],
            "default": {"$id": "urn:x", "$schema": _DRAFT_07},
            "examples": [{"$id": "urn:y"}],
            "x-notes": {"$id": "urn:z", "$schema": _DRAFT_07},
        },
        label="Step 2 output_contract",
    )


@pytest.mark.parametrize(
    ("schema", "keyword"),
    [
        pytest.param(
            {
                "type": "object",
                "default": {"$ref": _REMOTE},
                "properties": {"value": {"$ref": "#/default"}},
            },
            "$ref",
            id="gate-example",
        ),
        pytest.param(
            {
                "default": {"type": "string"},
                "properties": {"value": {"$ref": "#/default"}},
            },
            "$ref",
            id="annotation-data",
        ),
        pytest.param(
            {"const": {"type": "string"}, "properties": {"value": {"$ref": "#/const"}}},
            "$ref",
            id="const-data",
        ),
        pytest.param(
            {"default": True, "properties": {"value": {"$ref": "#/default"}}},
            "$ref",
            id="boolean-data",
        ),
        pytest.param(
            {
                "items": True,
                "default": True,
                "properties": {"value": {"$ref": "#/default"}},
            },
            "$ref",
            id="boolean-data-beside-a-boolean-schema",
        ),
        pytest.param(
            {"properties": {"value": {"$ref": "#/$defs/missing"}}},
            "$ref",
            id="missing-definition",
        ),
        pytest.param(
            {"properties": {"value": {"$ref": "#/properties"}}},
            "$ref",
            id="keyword-container",
        ),
        pytest.param(
            {"type": "object", "properties": {"value": {"$ref": "#/type"}}},
            "$ref",
            id="keyword-value",
        ),
        pytest.param(
            {"allOf": [{}], "properties": {"value": {"$ref": "#/allOf/x"}}},
            "$ref",
            id="bad-array-index",
        ),
        pytest.param(
            {
                "examples": [{"$anchor": "hidden"}],
                "properties": {"value": {"$ref": "#hidden"}},
            },
            "$ref",
            id="anchor-in-data",
        ),
        pytest.param(
            {
                "x-notes": {"$dynamicAnchor": "hidden"},
                "properties": {"value": {"$dynamicRef": "#hidden"}},
            },
            "$dynamicRef",
            id="dynamic-anchor-in-unknown-keyword",
        ),
    ],
)
def test_authoring_refuses_a_local_reference_that_is_not_a_schema(schema, keyword):
    error = _refused(schema)
    assert error.context["json_pointer"] == f"/properties/value/{keyword}"


@pytest.mark.parametrize(
    "schema",
    [
        {
            "type": "object",
            "properties": {"value": {"type": "array", "items": {"$ref": "#"}}},
        },
        {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"$ref": "#/properties/a"}},
        },
        {"allOf": [{"type": "object"}], "properties": {"value": {"$ref": "#/allOf/0"}}},
        {
            "$defs": {"a/b~c": {"type": "object"}, "no": False},
            "properties": {
                "value": {"$ref": "#/$defs/a~1b~0c"},
                "other": {"$ref": "#/$defs/no"},
            },
        },
        {"items": True, "properties": {"value": {"$ref": "#/items"}}},
        {
            "$defs": {"n o": False, "a/b": True},
            "properties": {
                "value": {"$ref": "#/$defs/n%20o"},
                "other": {"$ref": "#/$defs/a~1b"},
            },
        },
    ],
)
def test_authoring_accepts_a_local_reference_to_a_schema(schema):
    validate_schema_syntax(schema, label="Step 2 output_contract")
    validate_against_contract({}, schema, label="Step 2 output")


def _unevaluable_contracts(uri):
    return {
        "reference-to-root": {"$ref": "#"},
        "reference-cycle": {
            "$defs": {"a": {"$ref": "#/$defs/a"}},
            "$ref": "#/$defs/a",
        },
        "dynamic-reference-cycle": {"$dynamicRef": "#"},
        "draft-03-nested-extends": {
            "type": "object",
            "properties": {"a": {"$schema": _DRAFT_03, "extends": {"$ref": uri}}},
        },
        "draft-07-nested-dependencies": {
            "type": "object",
            "properties": {
                "a": {"$schema": _DRAFT_07, "dependencies": {"x": {"$ref": uri}}}
            },
        },
        "draft-07-remote-reference": {
            "$schema": _DRAFT_07,
            "type": "object",
            "properties": {"a": {"$ref": uri}},
        },
        "non-string-dialect": {"$schema": ["x"], "type": "object"},
        "malformed-dialect-uri": {"$schema": "http://[bad", "type": "object"},
        "pointer-index": {"allOf": [{}], "$ref": "#/allOf/x"},
        "annotation-with-malformed-dialect": {
            "default": {"$schema": []},
            "properties": {"a": {"$ref": "#/default"}},
        },
        "annotation-with-null-type": {
            "default": {"type": None},
            "properties": {"a": {"$ref": "#/default"}},
        },
        "annotation-with-unknown-type": {
            "default": {"type": "unknown"},
            "properties": {"a": {"$ref": "#/default"}},
        },
        "invalid-keyword-value": {"type": "object", "minLength": "x"},
    }


@pytest.mark.parametrize("shape", list(_unevaluable_contracts("x")))
def test_stored_contract_that_cannot_be_evaluated_is_a_typed_violation(
    schema_listener, shape
):
    uri, requests = schema_listener
    schema = _unevaluable_contracts(uri)[shape]
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract({"a": {"x": 1}}, schema, label="Step 2 output")
    assert exc_info.value.code == "typed_io_contract_violation"
    assert "Step 2 output" in str(exc_info.value)
    assert requests == []


def _at_stack_depth(frames, call):
    return call() if frames == 0 else _at_stack_depth(frames - 1, call)


def test_recursion_limit_reached_inside_the_reference_engine_is_typed():
    # rpds panics instead of raising when the limit trips inside it, and where it
    # trips depends on how deep the stack already is.
    schema = {"allOf": [{"not": {"type": "array"}, "$ref": "#/allOf/0"}]}
    schema["$ref"] = "#/allOf/0"
    for frames in range(30):
        with pytest.raises(TypedIOValidationException) as exc_info:
            _at_stack_depth(
                frames,
                lambda: validate_against_contract({}, schema, label="Step 2 output"),
            )
        assert exc_info.value.code == "typed_io_contract_violation"


def test_only_the_reference_engine_panic_is_reported_as_recursion(monkeypatch):
    build = output_processing.build_schema_validator

    class Interrupted:
        def validate(self, instance):
            raise KeyboardInterrupt

    monkeypatch.setattr(
        output_processing,
        "build_schema_validator",
        lambda schema, **kwargs: (
            Interrupted() if schema == {"type": "object"} else build(schema, **kwargs)
        ),
    )
    with pytest.raises(KeyboardInterrupt):
        validate_against_contract({}, {"type": "object"}, label="Step 2 output")


@pytest.mark.parametrize(
    "shape", ["reference-to-root", "draft-03-nested-extends", "invalid-keyword-value"]
)
@pytest.mark.asyncio
async def test_executor_contract_that_cannot_be_evaluated_is_typed(
    user, schema_listener, shape
):
    uri, requests = schema_listener
    executor, _, _, _ = _build_executor(user)
    step = replace(
        _step_for_execute_step(),
        output_type="json",
        output_contract=_unevaluable_contracts(uri)[shape],
    )
    with pytest.raises(TypedIOValidationException) as exc_info:
        await executor._process_typed_output(
            full_text=json.dumps({"a": {"x": 1}}),
            step=step,
            run=_run(status=FlowRunStatus.RUNNING, user=user),
        )
    assert exc_info.value.code == "typed_io_contract_violation"
    assert requests == []


def test_errors_of_our_own_code_are_never_reported_as_a_bad_contract(monkeypatch):
    def broken_walk(schema):
        raise AttributeError("walker defect")

    monkeypatch.setattr(output_processing, "_schema_nodes", broken_walk)
    with pytest.raises(AttributeError):
        validate_schema_syntax({"type": "object"}, label="Step 2 output_contract")
    with pytest.raises(AttributeError):
        compile_validators([SimpleNamespace(input_contract={}, output_contract=None)])


def test_compiled_contract_that_cannot_be_built_is_a_typed_violation():
    with pytest.raises(TypedIOValidationException) as exc_info:
        compile_validators(
            [
                SimpleNamespace(
                    step_order=2, input_contract={"$id": 5}, output_contract=None
                )
            ]
        )
    assert exc_info.value.code == "typed_io_contract_violation"
    assert "Step 2 input" in str(exc_info.value)


def test_authoring_nesting_beyond_the_checkable_depth_is_a_typed_refusal():
    schema = {"type": "string"}
    for _ in range(400):
        schema = {"type": "object", "properties": {"a": schema}}
    assert _refused(schema).code == "typed_io_invalid_schema"


_VERDICT_CASES = [
    (
        {"$schema": _DRAFT_07, "type": "object", "dependencies": {"a": ["b"]}},
        {"a": 1},
        False,
    ),
    (
        {"$schema": _DRAFT_07, "type": "object", "dependencies": {"a": ["b"]}},
        {"a": 1, "b": 2},
        True,
    ),
    (
        {"$schema": _DRAFT_07, "dependencies": {"a": {"required": ["b"]}}},
        {"a": 1},
        False,
    ),
    (
        {
            "$schema": _DRAFT_07,
            "properties": {"n": {"$ref": "#/definitions/i", "maximum": 5}},
            "definitions": {"i": {"type": "integer"}},
        },
        {"n": 10},
        True,
    ),
    (
        {
            "$schema": _DRAFT_07,
            "properties": {"n": {"$ref": "#/definitions/i", "maximum": 5}},
            "definitions": {"i": {"type": "integer"}},
        },
        {"n": "x"},
        False,
    ),
    (
        {
            "$schema": _DRAFT_04,
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
            "additionalProperties": False,
        },
        {"a": "x", "b": 1},
        False,
    ),
    (
        {
            "$schema": _DRAFT_04,
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        },
        {"a": "x"},
        True,
    ),
    ({"$schema": "urn:unknown", "type": "string"}, "x", True),
    ({"type": "string", "minLength": "x"}, "abc", False),
]


@pytest.mark.parametrize(("schema", "instance", "accepted"), _VERDICT_CASES)
@pytest.mark.filterwarnings("ignore:The metaschema specified by:DeprecationWarning")
def test_stored_contract_verdict_matches_the_previous_validation(
    schema, instance, accepted
):
    def previous() -> bool:
        try:
            jsonschema.validate(instance, schema)
        except (jsonschema.ValidationError, jsonschema.SchemaError):
            return False
        return True

    def current() -> bool:
        try:
            validate_against_contract(instance, schema, label="Step 2 output")
        except TypedIOValidationException:
            return False
        return True

    assert previous() == current() == accepted


_DRAFT_06 = "http://json-schema.org/draft-06/schema#"
_DRAFT_2019 = "https://json-schema.org/draft/2019-09/schema"
_PASTED_BODIES = {
    "plain": {
        "type": "object",
        "properties": {
            "kind": {"enum": ["a", "b"]},
            "name": {"type": "string", "minLength": 2},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["kind"],
    },
    "composed": {
        "type": "object",
        "title": "Composed",
        "description": "Every kind of keyword the conversion allows",
        "properties": {
            "n": {"type": "integer", "minimum": 0, "exclusiveMaximum": 10},
            "s": {"type": "string", "pattern": "^a", "maxLength": 4},
            "c": {"const": "x"},
            "any": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "one": {"oneOf": [{"minimum": 5}, {"maximum": 1}]},
            "no": {"not": {"type": "boolean"}},
            "list": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 1,
                "uniqueItems": True,
            },
        },
        "patternProperties": {"^x_": {"type": "string"}},
        "propertyNames": {"maxLength": 6},
        "additionalProperties": {"type": "integer"},
        "allOf": [{"minProperties": 1}],
        "default": {},
        "examples": [{}],
    },
}
_PASTED_INSTANCES = [
    {},
    {"kind": "a"},
    {"kind": "c"},
    {"kind": "a", "name": "x"},
    {"kind": "a", "tags": ["x", 1]},
    {"n": 3, "s": "ab", "c": "x", "list": [1, 2]},
    {"n": 11, "s": "ba", "c": "y", "list": [1, 1]},
    {"any": None, "one": 3, "no": True, "x_a": "1", "other": 1.5},
    {"toolongname": 1},
    [],
]


def _paste(schema):
    return parse_schema_candidate(json.dumps(schema))


def _accepted(schema, instance) -> bool:
    try:
        validate_against_contract(instance, schema, label="Step 2 output")
    except TypedIOValidationException:
        return False
    return True


@pytest.mark.parametrize("body", list(_PASTED_BODIES))
@pytest.mark.parametrize("uri", [_DRAFT_06, _DRAFT_07, _DRAFT_2019])
def test_pasted_schema_of_a_supported_draft_becomes_a_contract_that_reads_the_same(
    uri, body
):
    schema = _PASTED_BODIES[body]
    pasted = {"$schema": uri, **schema}
    assert _paste(pasted) == schema
    draft = jsonschema.validators.validator_for(pasted)(pasted)
    for instance in _PASTED_INSTANCES:
        assert _accepted(schema, instance) == draft.is_valid(instance), instance


@pytest.mark.parametrize("uri", [_DRAFT_07, _DRAFT_2019])
def test_pasted_conditional_keywords_convert_where_the_draft_runs_them(uri):
    body = {
        "type": "object",
        "properties": {"kind": {"type": "string"}, "size": {"type": "integer"}},
        "if": {"properties": {"kind": {"const": "big"}}},
        "then": {"properties": {"size": {"minimum": 10}}},
        "else": {"properties": {"size": {"maximum": 9}}},
    }
    pasted = {"$schema": uri, **body}
    assert _paste(pasted) == body
    draft = jsonschema.validators.validator_for(pasted)(pasted)
    for instance in ({"kind": "big", "size": 3}, {"kind": "small", "size": 30}, {}):
        assert _accepted(body, instance) == draft.is_valid(instance)


def test_pasted_conditional_keywords_are_declined_where_the_draft_ignores_them():
    pasted = {
        "$schema": _DRAFT_06,
        "type": "object",
        "if": {"required": ["a"]},
        "then": {"required": ["b"]},
    }
    assert _paste(pasted) is None


def test_pasted_schema_that_already_is_a_contract_is_returned_as_it_came():
    contract = {"$schema": _DIALECT, **_PASTED_BODIES["plain"]}
    assert _paste(contract) == contract
    assert _paste(_PASTED_BODIES["plain"]) == _PASTED_BODIES["plain"]


@pytest.mark.parametrize("uri", [_DRAFT_06, _DRAFT_07, _DRAFT_2019])
def test_pasted_schemas_convert_with_the_verdicts_of_their_draft(uri):
    # Random schemas over the whole allowed vocabulary.
    rng = random.Random(uri)
    names = ["a", "b", "c"]
    values = [0, 1, 2, "a", "ab", None, True, [], {}]

    def schema(depth):
        if depth == 0 or rng.random() < 0.2:
            return rng.choice(
                [{}, {"type": "string"}, {"enum": [1, "a", None]}, {"minLength": 2}]
            )
        node = {}
        if rng.random() < 0.5:
            node["type"] = rng.choice(["object", "array", "string", "integer"])
        if rng.random() < 0.5:
            node["properties"] = {
                n: schema(depth - 1) for n in rng.sample(names, rng.randint(1, 3))
            }
        if rng.random() < 0.3:
            node["required"] = rng.sample(names, rng.randint(1, 2))
        if rng.random() < 0.3:
            node["items"] = schema(depth - 1)
        if rng.random() < 0.2:
            node["additionalProperties"] = rng.choice([False, schema(depth - 1)])
        for keyword in ("allOf", "anyOf", "oneOf"):
            if rng.random() < 0.15:
                node[keyword] = [schema(depth - 1) for _ in range(rng.randint(1, 2))]
        if rng.random() < 0.1:
            node["not"] = schema(depth - 1)
        if rng.random() < 0.2:
            node["minimum"] = rng.randint(0, 3)
        if rng.random() < 0.1:
            node["uniqueItems"] = True
        if uri != _DRAFT_06 and rng.random() < 0.1:
            node["if"], node["then"] = schema(depth - 1), schema(depth - 1)
        return node

    def instance(depth):
        if depth == 0 or rng.random() < 0.3:
            return rng.choice(values)
        if rng.random() < 0.5:
            return {
                n: instance(depth - 1) for n in rng.sample(names, rng.randint(0, 3))
            }
        return [instance(depth - 1) for _ in range(rng.randint(0, 3))]

    for _ in range(150):
        # A candidate is a top-level object schema.
        body = {"type": "object", "properties": {"a": schema(3), "b": schema(2)}}
        pasted = {"$schema": uri, **body}
        assert _paste(pasted) == body
        draft = jsonschema.validators.validator_for(pasted)(pasted)
        for _ in range(4):
            value = instance(3)
            assert _accepted(body, value) == draft.is_valid(value), (pasted, value)


def test_the_convertible_keywords_run_the_same_in_every_supported_draft():
    # Each keyword of the set has the same function in the draft's VALIDATORS map as
    # in 2020-12's, or is an annotation none of them runs. `items` differs only in its
    # array form, which the conversion declines; `if` is absent from draft 6, which
    # the conversion therefore declines too.
    current = jsonschema.Draft202012Validator.VALIDATORS
    for draft in (
        jsonschema.Draft6Validator,
        jsonschema.Draft7Validator,
        jsonschema.Draft201909Validator,
    ):
        different = {
            keyword
            for keyword in output_processing._CONVERTIBLE_KEYWORDS
            if draft.VALIDATORS.get(keyword) is not current.get(keyword)
        }
        assert different <= {"items", "if"}, draft
        assert ("if" in different) == (draft is jsonschema.Draft6Validator)


@pytest.mark.parametrize(
    "pasted",
    [
        {
            "$schema": _DRAFT_07,
            "$id": "#value",
            "definitions": {"s": {"$anchor": "value", "type": "string"}},
            "properties": {"value": {"$ref": "#value"}},
        },
        {"$schema": _DRAFT_07, "$id": "urn:contract"},
        {"$id": "urn:contract"},
        {"$schema": _DIALECT + "#"},
        {"$schema": _DRAFT_07, "definitions": {"s": {"type": "string"}}},
        {"$schema": _DRAFT_2019, "$defs": {"s": {"type": "string"}}},
        {
            "$schema": _DRAFT_07,
            "properties": {"a": {"type": "string"}, "b": {"$ref": "#/properties/a"}},
        },
        {"$schema": _DRAFT_07, "$comment": "a note"},
        {"$schema": _DRAFT_07, "dependencies": {"a": ["b"]}},
        {"$schema": _DRAFT_07, "dependencies": {"a": {"required": ["b"]}}},
        {
            "$schema": _DRAFT_07,
            "properties": {"a": {"type": "array", "items": [{"type": "string"}]}},
        },
        {
            "$schema": _DRAFT_07,
            "properties": {
                "a": {
                    "type": "array",
                    "items": {"type": "string"},
                    "additionalItems": False,
                }
            },
        },
        {
            "$schema": _DRAFT_07,
            "properties": {"a": {"$ref": "#/definitions/s", "maxLength": 1}},
            "definitions": {"s": {"type": "string"}},
        },
        {"$schema": _DRAFT_07, "properties": {"a": {"prefixItems": [{}]}}},
        {"$schema": _DRAFT_07, "minimum": 1, "exclusiveMinimum": True},
        {
            "$schema": _DRAFT_07,
            "properties": {
                "a": {"type": "array", "contains": {"type": "string"}, "minContains": 2}
            },
        },
        {
            "$schema": _DRAFT_04,
            "type": "object",
            "properties": {"value": {"type": "integer"}},
        },
        {
            "$schema": _DRAFT_2019,
            "$recursiveAnchor": True,
            "properties": {"a": {"$recursiveRef": "#"}},
        },
        {
            "$schema": _DRAFT_07,
            "type": "object",
            "properties": {"a": {"$schema": _DRAFT_07, "type": "string"}},
        },
        {"type": "object", "properties": {"a": {"$id": "urn:a", "type": "string"}}},
        {"$schema": "https://example.com/meta.json", "type": "object"},
        {"$schema": _DRAFT_03, "type": "object"},
        {"$schema": 5, "type": "object"},
        {"$schema": "http://[bad", "type": "object"},
        {"$schema": _DRAFT_07, "type": "object", "required": True},
        {
            "$id": "https://example.com/c.json",
            "properties": {"a": {"$ref": "https://example.com/c.json#/definitions/s"}},
            "definitions": {"s": {"type": "string"}},
        },
    ],
    ids=[
        "anchor-beside-a-root-id",
        "id-with-dialect",
        "id-alone",
        "hash-variant-of-2020-12",
        "definitions",
        "defs",
        "local-reference",
        "comment",
        "dependencies",
        "schema-dependencies",
        "array-items",
        "additional-items",
        "ref-with-sibling",
        "keyword-of-a-later-draft",
        "boolean-exclusive-minimum",
        "min-contains-before-2019-09",
        "draft-04-integer",
        "recursive-ref",
        "nested-dialect",
        "nested-id",
        "unknown-dialect",
        "draft-03",
        "non-string-dialect",
        "malformed-dialect-uri",
        "not-a-valid-schema",
        "reference-through-the-id",
    ],
)
def test_pasted_schema_outside_the_convertible_keywords_is_not_a_candidate(pasted):
    # It is not rewritten. A visible reason for it is not built yet: the only
    # evidence-refusal mechanism reports size limits, so the candidate is left out
    # exactly as any other invalid pasted schema is.
    assert (
        _paste({"type": "object", "properties": {"a": {"type": "string"}}, **pasted})
        is None
    )


def test_pasted_draft_07_schema_reaches_the_builder_as_a_2020_12_candidate():
    schema = _PASTED_BODIES["plain"]
    candidates = derive_freeform_schema_candidates(
        [
            ConversationMessage(
                message_id="pasted",
                role="user",
                content="```json\n"
                + json.dumps({"$schema": _DRAFT_07, **schema})
                + "\n```",
            )
        ]
    )
    assert [candidate.json_schema for candidate in candidates] == [schema]


def test_stored_contract_keeps_resolving_references_through_its_own_id():
    stored = {
        "$id": "urn:contract",
        "type": "object",
        "properties": {"a": {"$ref": "urn:contract#/definitions/s"}},
        "definitions": {"s": {"type": "string"}},
    }
    assert _accepted(stored, {"a": "x"})
    assert not _accepted(stored, {"a": 1})


def test_stored_contracts_and_authoring_keep_the_dialect_they_name():
    pasted = {"$schema": _DRAFT_07, **_PASTED_BODIES["plain"]}
    assert _refused(pasted).context["json_pointer"] == "/$schema"
    stored = {"$schema": _DRAFT_07, "dependencies": {"a": ["b"]}}
    assert not _accepted(stored, {"a": 1})
    assert _accepted(stored, {"a": 1, "b": 2})


def test_pasted_draft_4_schema_is_declined_because_it_counts_integers_differently():
    pasted = {
        "$schema": _DRAFT_04,
        "type": "object",
        "properties": {"value": {"type": "integer"}},
    }
    assert not jsonschema.Draft4Validator(pasted).is_valid({"value": 2.0})
    assert _paste(pasted) is None


@pytest.mark.parametrize("uri", [_DRAFT_06, _DRAFT_07, _DRAFT_2019])
def test_pasted_schema_of_a_supported_draft_counts_integers_like_2020_12(uri):
    pasted = {
        "$schema": uri,
        "type": "object",
        "properties": {"value": {"type": "integer"}},
    }
    schema = _paste(pasted)
    assert schema == {k: v for k, v in pasted.items() if k != "$schema"}
    draft = jsonschema.validators.validator_for(pasted)(pasted)
    for value in (2, 2.0, 2.5, "2", True, None):
        assert _accepted(schema, {"value": value}) == draft.is_valid({"value": value})


def test_the_supported_drafts_are_those_whose_type_checker_is_that_of_2020_12():
    # jsonschema: draft 6 redefines "integer" (2.0 is one) and later drafts inherit it;
    # drafts 3 and 4 keep the older rule.
    current = jsonschema.Draft202012Validator.TYPE_CHECKER
    for draft in (
        jsonschema.Draft6Validator,
        jsonschema.Draft7Validator,
        jsonschema.Draft201909Validator,
    ):
        assert draft.TYPE_CHECKER == current
    for draft in (jsonschema.Draft3Validator, jsonschema.Draft4Validator):
        assert draft.TYPE_CHECKER != current
        assert not draft.TYPE_CHECKER.is_type(2.0, "integer")


def test_admitting_many_references_to_one_anchor_crawls_the_contract_once(
    monkeypatch,
):
    from referencing import Registry, Resource

    def work(references: int) -> tuple[int, int]:
        crawls: list[int] = []
        visits: list[int] = []
        crawl, subresources = Registry.crawl, Resource.subresources
        monkeypatch.setattr(
            Registry, "crawl", lambda self: (crawls.append(1), crawl(self))[1]
        )
        monkeypatch.setattr(
            Resource,
            "subresources",
            lambda self: (visits.append(1), subresources(self))[1],
        )
        schema = {
            "$defs": {"target": {"$anchor": "target", "type": "string"}},
            "type": "object",
            "properties": {
                f"p{index}": {"$ref": "#target"}
                if index < references
                else {"type": "string"}
                for index in range(1000)
            },
        }
        validate_schema_syntax(schema, label="Step 2 output_contract")
        monkeypatch.undo()
        return len(crawls), len(visits)

    assert work(1000) == work(1)


def test_a_stored_contract_may_reference_a_bundled_metaschema_offline(monkeypatch):
    connect = Mock(side_effect=AssertionError("Schema opened a socket"))
    monkeypatch.setattr(socket, "create_connection", connect)
    stored = {
        "type": "object",
        "properties": {"a": {"$ref": _DIALECT}},
    }
    assert _accepted(stored, {"a": {"type": "string"}})
    assert not _accepted(stored, {"a": {"type": 5}})
    connect.assert_not_called()
    assert _refused(stored).context["json_pointer"] == "/properties/a/$ref"


def _flow_with_a_stored_legacy_contract(user):
    legacy = {
        "$schema": _DRAFT_07,
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "dependencies": {"value": ["other"]},
    }
    steps = [
        _step().model_copy(update={"output_contract": legacy}),
        _step(2).model_copy(update={"input_type": "json"}),
    ]
    flow = Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Legacy",
        steps=steps,
    )
    flow_repo = AsyncMock()
    flow_repo.get.return_value = flow
    service = _service(user=user, flow_repo=flow_repo, version_repo=AsyncMock())
    return service, flow_repo, flow, steps, legacy


@pytest.mark.asyncio
async def test_a_flow_with_a_stored_legacy_contract_can_still_be_saved(user):
    service, flow_repo, flow, steps, _ = _flow_with_a_stored_legacy_contract(user)

    await service.update_flow(flow_id=flow.id, name="Renamed")
    await service.update_flow(flow_id=flow.id, steps=steps)
    reordered = [steps[0], steps[1].model_copy(update={"user_description": "Other"})]
    await service.update_flow(flow_id=flow.id, steps=reordered)

    assert flow_repo.update.await_count == 3


@pytest.mark.asyncio
async def test_a_retained_contract_is_still_checked_against_the_metaschema(user):
    service, flow_repo, flow, steps, _ = _flow_with_a_stored_legacy_contract(user)
    flow.steps[0].output_contract = {"type": "object", "minLength": "x"}

    with pytest.raises(FlowStepValidationError) as exc_info:
        await service.update_flow(flow_id=flow.id, name="Renamed")

    assert exc_info.value.code == "invalid_output_contract_schema"
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_retained_draft_07_array_form_of_items_is_still_refused(user):
    service, flow_repo, flow, _, _ = _flow_with_a_stored_legacy_contract(user)
    flow.steps[0].output_contract = {
        "$schema": _DRAFT_07,
        "type": "array",
        "items": [{"type": "string"}],
    }

    with pytest.raises(FlowStepValidationError) as exc_info:
        await service.update_flow(flow_id=flow.id, name="Renamed")

    assert exc_info.value.code == "invalid_output_contract_schema"
    flow_repo.update.assert_not_awaited()


@pytest.mark.parametrize(
    "changed",
    [
        {"$schema": _DRAFT_07, "type": "object", "title": "Changed"},
        {"$schema": _DRAFT_07, "type": "object", "properties": {"a": {"$id": "urn:a"}}},
    ],
)
@pytest.mark.asyncio
async def test_changing_a_stored_legacy_contract_applies_the_contract_rules(
    user, changed
):
    service, flow_repo, flow, steps, _ = _flow_with_a_stored_legacy_contract(user)

    with pytest.raises(FlowStepValidationError) as exc_info:
        await service.update_flow(
            flow_id=flow.id,
            steps=[steps[0].model_copy(update={"output_contract": changed}), steps[1]],
        )

    assert exc_info.value.code == "invalid_output_contract_schema"
    assert exc_info.value.step_order == 1
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_contract_changed_only_in_a_json_type_is_not_retained(user):
    service, flow_repo, flow, steps, _ = _flow_with_a_stored_legacy_contract(user)
    stored = {"$schema": _DRAFT_07, "enum": [True]}
    flow.steps[0].output_contract = stored
    changed = {"$schema": _DRAFT_07, "enum": [1]}
    assert stored == changed  # Python calls them equal; JSON does not

    with pytest.raises(FlowStepValidationError) as exc_info:
        await service.update_flow(
            flow_id=flow.id,
            steps=[steps[0].model_copy(update={"output_contract": changed}), steps[1]],
        )

    assert exc_info.value.code == "invalid_output_contract_schema"
    assert exc_info.value.step_order == 1
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_new_step_is_checked_beside_a_retained_legacy_contract(user):
    service, flow_repo, flow, steps, legacy = _flow_with_a_stored_legacy_contract(user)
    new_step = _step(3).model_copy(
        update={"id": None, "input_type": "json", "output_contract": legacy}
    )

    with pytest.raises(FlowStepValidationError) as exc_info:
        await service.update_flow(flow_id=flow.id, steps=[*steps, new_step])

    assert exc_info.value.step_order == 3
    flow_repo.update.assert_not_awaited()
