"""What stored model settings send, and what a request's own settings send.

Stored settings (an assistant's or app's, loaded the way a run loads them)
stay as saved; a request sends only what the model accepts now, and a stored
reasoning effort it no longer accepts is left out and logged. Settings a
request supplies itself stay strict and reach request validation. Everything
a valid stored selection sends is pinned byte for byte.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    Context,
    ModelKwargs,
    ResponseType,
)
from eneo.apps.apps.app_factory import AppFactory
from eneo.assistants.api.assistant_models import KnowledgeMode
from eneo.assistants.assistant_factory import AssistantFactory
from eneo.completion_models.domain.completion_model import CompletionModel
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
    persist_discovered_model_kwargs_capabilities,
)
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.completion_models.infrastructure.completion_service import (
    CompletionService,
    ResolvedCompletionModelRoute,
)
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.main.exceptions import ProviderRejectedRequestException
from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided
from eneo.tenants.tenant import TenantInDB
from eneo.users.user import UserInDB

_CAPABILITIES = "eneo.completion_models.infrastructure.tenant_model_capabilities"
_OMITTED = "Stored model settings are not offered by the model; omitting them"
_LOW_MEDIUM_HIGH = ModelKwargCapability(
    supported=True, control="select", options=["low", "medium", "high"]
)
# The route's snapshot offers low/medium/high (the migration removed an
# unverified "none"), verbosity and a temperature slider.
_SNAPSHOT = persist_discovered_model_kwargs_capabilities(
    SupportedModelKwargs(
        temperature=ModelKwargCapability(
            supported=True, control="slider", minimum=0, maximum=2, step=0.01
        ),
        reasoning_effort=_LOW_MEDIUM_HIGH,
        verbosity=_LOW_MEDIUM_HIGH,
    )
)
# How a run loads stored settings: ordinary and space-loaded apps and
# assistants.
_LOAD_PATHS = ["app", "space-app", "assistant", "space-assistant"]


class _ContextBuilder:
    def build_context(self, **kwargs: object) -> Context:
        return Context(input=str(kwargs.get("input_str", "")), token_count=0)


class _OutboundAdapter:
    """Records the provider kwargs the real adapter would send."""

    def __init__(self, route_model: str) -> None:
        self.outbound: list[dict[str, object]] = []
        self._adapter = object.__new__(TenantModelAdapter)
        self._adapter.model = SimpleNamespace(max_output_tokens=4096)
        self._adapter.provider_type = "openai"
        self._adapter.litellm_model = f"openai/{route_model}"
        self._adapter.credential_resolver = SimpleNamespace(
            provider_type="openai",
            get_api_key=lambda *, required=False: "test-key",
            get_credential_field=lambda *, field, required=False: None,
        )

    def get_token_limit_of_model(self) -> int:
        return 8000

    def get_model_route(self) -> str:
        return self._adapter.litellm_model

    async def get_response(
        self, *, model_kwargs: ModelKwargs | None, **_: object
    ) -> Completion:
        sent = self._adapter._prepare_kwargs(model_kwargs=model_kwargs)
        self.outbound.append({k: v for k, v in sent.items() if k != "api_key"})
        return Completion(response_type=ResponseType.TEXT, text="ok")


def _model_row(*, capabilities: object | None, reasoning: bool) -> CompletionModels:
    now = datetime.now(timezone.utc)
    return CompletionModels(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="gpt-5-mini",
        nickname="GPT-5 mini",
        open_source=False,
        max_input_tokens=128000,
        max_output_tokens=4096,
        is_deprecated=False,
        family="openai",
        stability="stable",
        hosting="usa",
        vision=False,
        reasoning=reasoning,
        supports_tool_calling=True,
        supports_strict_tool_schema=False,
        model_kwargs_capabilities=capabilities,
        tenant_id=uuid4(),
        provider_id=uuid4(),
        is_enabled=True,
        is_default=False,
    )


def _domain_model(row: CompletionModels) -> CompletionModel:
    return CompletionModel.create_from_db(
        row,
        tenant=TenantInDB.model_construct(id=row.tenant_id, name="Tenant"),
        provider_type="openai",
    )


def _app_record(row: CompletionModels, stored: dict[str, object]) -> Apps:
    now = datetime.now(timezone.utc)
    record = Apps(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        tenant_id=row.tenant_id,
        user_id=uuid4(),
        space_id=uuid4(),
        name="App",
        description=None,
        completion_model_kwargs=stored,
        published=False,
        data_retention_days=None,
        template_id=None,
        completion_model_id=row.id,
        transcription_model_id=None,
        icon_id=None,
    )
    record.completion_model = row
    record.input_fields = []
    record.template = None
    return record


def _assistant_record(
    row: CompletionModels, stored: dict[str, object], user: UserInDB
) -> Assistants:
    record = Assistants(
        id=uuid4(),
        name="Assistant",
        user_id=user.id,
        space_id=uuid4(),
        completion_model_id=row.id,
        completion_model_kwargs=stored,
        guardrail_active=False,
        logging_enabled=False,
        is_default=False,
        published=False,
        description=None,
        insight_enabled=False,
        inline_file_text=True,
        knowledge_mode=KnowledgeMode.INJECT.value,
        data_retention_days=None,
        metadata_json={},
        hidden=False,
        origin="user",
        managing_flow_id=None,
        icon_id=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    record.user = user
    record.assistant_groups = []
    record.assistant_websites = []
    record.assistant_integration_knowledge = []
    record.attachments = []
    record.mcp_servers = []
    record.template = None
    setattr(record, "prompt", None)
    return record


async def _send(
    path: str,
    row: CompletionModels,
    stored: dict[str, object],
    user: UserInDB,
    *,
    reasoning_params: bool = True,
    request_kwargs: ModelKwargs | None = None,
    governed: CompletionModels | None = None,
    policy_effort: str | None | NotProvided = NOT_PROVIDED,
) -> tuple[ModelKwargs, dict[str, object]]:
    """Load the settings the way a run does and send one request; return the
    loaded settings and what was sent."""
    adapter = _OutboundAdapter(row.name)
    service = CompletionService(
        context_builder=_ContextBuilder(),  # pyright: ignore[reportArgumentType]
        tenant=SimpleNamespace(id=uuid4()),  # pyright: ignore[reportArgumentType]
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)  # pyright: ignore[reportAttributeAccessIssue]
    params = ["temperature", "verbosity"]
    if reasoning_params:
        params.append("reasoning_effort")
    with (
        patch(f"{_CAPABILITIES}.get_supported_openai_params", return_value=params),
        patch(
            f"{_CAPABILITIES}.litellm.get_model_info",
            return_value={"supports_reasoning": True},
        ),
    ):
        if path in ("app", "space-app"):
            apps = AppFactory(app_template_factory=MagicMock())
            app = (
                apps.create_app_from_db(_app_record(row, stored), attachments=[])
                if path == "app"
                else apps.create_space_app_from_db(
                    _app_record(row, stored),
                    attachments=[],
                    completion_models=[_domain_model(row)],
                )
            )
            loaded = app.completion_model_kwargs
            await app.run(
                files=[], text="hi", completion_service=service, transcriber=MagicMock()
            )
        else:
            assistants = AssistantFactory(
                prompt_factory=MagicMock(), assistant_template_factory=MagicMock()
            )
            record = _assistant_record(row, stored, user)
            assistant = (
                assistants.create_assistant_from_db(
                    record, attachments=[], completion_model=_domain_model(row)
                )
                if path == "assistant"
                else assistants.create_space_assistant_from_db(
                    record,
                    user,
                    attachments=[],
                    completion_models=[_domain_model(row)],
                )
            )
            loaded = assistant.completion_model_kwargs
            # A personal-chat policy may choose another model, and its own
            # effort; the assistant service builds the override this way.
            governed_model = _domain_model(governed) if governed else None
            if governed_model is not None and is_provided(policy_effort):
                request_kwargs = assistant.request_model_kwargs(
                    governed_model, reasoning_effort=policy_effort
                )
            await assistant.ask(
                question="hi",
                completion_service=service,
                references_service=MagicMock(),
                completion_model_override=governed_model,
                model_kwargs_override=request_kwargs,
            )
    assert len(adapter.outbound) == 1
    return loaded, adapter.outbound[0]


# Valid stored selections (and an unset effort) send what they sent before.
@pytest.mark.asyncio
@pytest.mark.parametrize("path", _LOAD_PATHS)
@pytest.mark.parametrize(
    ("capabilities", "reasoning", "stored", "expected"),
    [
        (
            _SNAPSHOT,
            True,
            {"reasoning_effort": "medium", "temperature": 0.3, "verbosity": "low"},
            {"reasoning_effort": "medium", "temperature": 0.3, "verbosity": "low"},
        ),
        (_SNAPSHOT, True, {"reasoning_effort": "high"}, {"reasoning_effort": "high"}),
        # Unset: the direct-OpenAI transport still sends its "low".
        (_SNAPSHOT, True, {}, {"reasoning_effort": "low"}),
        (
            _SNAPSHOT,
            True,
            {"temperature": 0.7, "top_p": 0.4},
            {"reasoning_effort": "low", "temperature": 0.7},
        ),
        (None, True, {"temperature": 0.3}, {"reasoning_effort": "low"}),
        (None, False, {}, {"reasoning_effort": "low"}),
        (
            _SNAPSHOT,
            True,
            {"temperature": 2.0},
            {"reasoning_effort": "low", "temperature": 2.0},
        ),
        (
            _SNAPSHOT,
            True,
            {"temperature": 0.0},
            {"reasoning_effort": "low", "temperature": 0.0},
        ),
    ],
    ids=[
        "offered-effort-and-controls",
        "offered-effort",
        "unset",
        "unset-with-sampling-controls",
        "no-capability-unset",
        "not-reasoning-unset",
        "temperature-at-maximum",
        "temperature-at-minimum",
    ],
)
async def test_valid_stored_settings_send_what_they_sent_before(
    path: str,
    capabilities: object | None,
    reasoning: bool,
    stored: dict[str, object],
    expected: dict[str, object],
    user: UserInDB,
) -> None:
    row = _model_row(capabilities=capabilities, reasoning=reasoning)

    with patch(f"{_CAPABILITIES}.logger") as logger:
        _, outbound = await _send(path, row, stored, user)

    assert outbound == expected
    logger.warning.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _LOAD_PATHS)
async def test_loading_keeps_stored_settings_as_saved(
    path: str, user: UserInDB
) -> None:
    # Values the model does not accept now (an effort it no longer offers, a
    # control it lacks) stay in the loaded settings, so a save keeps them.
    row = _model_row(capabilities=_SNAPSHOT, reasoning=True)
    stored: dict[str, object] = {"reasoning_effort": "none", "top_p": 0.4}

    loaded, _ = await _send(path, row, stored, user)

    assert loaded == ModelKwargs.model_validate(stored)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _LOAD_PATHS)
@pytest.mark.parametrize(
    ("capabilities", "reasoning", "stored_effort", "reasoning_params"),
    [
        # Stored before the migration removed "none" from the options.
        (_SNAPSHOT, True, "none", True),
        (_SNAPSHOT, True, "xhigh", True),
        # The admin turned the model's reasoning flag off.
        (None, False, "high", False),
        (_SNAPSHOT, False, "high", False),
        # No capability recorded: the model offers no effort to choose.
        (None, True, "high", True),
    ],
    ids=[
        "removed-none",
        "never-offered",
        "flag-off",
        "flag-off-with-snapshot",
        "no-capability",
    ],
)
async def test_a_stored_effort_the_model_does_not_offer_is_omitted_and_logged(
    path: str,
    capabilities: object | None,
    reasoning: bool,
    stored_effort: str,
    reasoning_params: bool,
    user: UserInDB,
) -> None:
    row = _model_row(capabilities=capabilities, reasoning=reasoning)

    with patch(f"{_CAPABILITIES}.logger") as logger:
        _, outbound = await _send(
            path,
            row,
            {"reasoning_effort": stored_effort, "temperature": 0.3},
            user,
            reasoning_params=reasoning_params,
        )
    _, unset = await _send(
        path, row, {"temperature": 0.3}, user, reasoning_params=reasoning_params
    )

    # The run goes ahead as if no effort were stored, and says why once.
    assert outbound == unset
    logger.warning.assert_called_once()
    assert logger.warning.call_args.args[0] == _OMITTED
    extra = logger.warning.call_args.kwargs["extra"]
    assert extra["completion_model_id"] == str(row.id)
    assert extra["omitted_settings"] == {"reasoning_effort": stored_effort}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _LOAD_PATHS)
@pytest.mark.parametrize("temperature", [2.5, -0.1, 999.0])
async def test_a_stored_value_outside_the_advertised_range_is_omitted_and_logged(
    path: str, temperature: float, user: UserInDB
) -> None:
    # The snapshot offers a temperature slider from 0 to 2.
    row = _model_row(capabilities=_SNAPSHOT, reasoning=True)

    with patch(f"{_CAPABILITIES}.logger") as logger:
        _, outbound = await _send(
            path, row, {"reasoning_effort": "high", "temperature": temperature}, user
        )

    assert outbound == {"reasoning_effort": "high"}
    logger.warning.assert_called_once()
    assert logger.warning.call_args.args[0] == _OMITTED
    assert logger.warning.call_args.kwargs["extra"]["omitted_settings"] == {
        "temperature": temperature
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("reasoning_params", [True, False])
async def test_a_request_scoped_effort_stays_strict(
    reasoning_params: bool, user: UserInDB
) -> None:
    # A request's own effort (the personal-chat policy override) is not a
    # stored setting: it is not dropped, and request validation decides.
    row = _model_row(capabilities=_SNAPSHOT, reasoning=True)
    request_kwargs = ModelKwargs(reasoning_effort="xhigh")

    with patch(f"{_CAPABILITIES}.logger") as logger:
        if reasoning_params:
            _, outbound = await _send(
                "assistant", row, {}, user, request_kwargs=request_kwargs
            )
            assert outbound == {"reasoning_effort": "xhigh"}
        else:
            with pytest.raises(ProviderRejectedRequestException):
                await _send(
                    "assistant",
                    row,
                    {},
                    user,
                    reasoning_params=False,
                    request_kwargs=request_kwargs,
                )
    logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_the_completion_service_keeps_a_callers_effort_for_validation() -> None:
    row = _model_row(capabilities=_SNAPSHOT, reasoning=True)
    model = _domain_model(row)
    adapter = _OutboundAdapter(row.name)
    service = CompletionService(
        context_builder=_ContextBuilder(),  # pyright: ignore[reportArgumentType]
        tenant=SimpleNamespace(id=uuid4()),  # pyright: ignore[reportArgumentType]
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)  # pyright: ignore[reportAttributeAccessIssue]

    with patch(
        f"{_CAPABILITIES}.get_supported_openai_params",
        return_value=["reasoning_effort"],
    ):
        await service.get_response(
            model=model,  # pyright: ignore[reportArgumentType]
            text_input="hi",
            model_kwargs=ModelKwargs(reasoning_effort="xhigh"),
        )

    assert adapter.outbound == [{"reasoning_effort": "xhigh"}]


@pytest.mark.parametrize("reasoning_params", [True, False])
def test_a_fresh_ai_builder_selection_is_still_refused(reasoning_params: bool) -> None:
    route = ResolvedCompletionModelRoute(
        litellm_model="openai/gpt-5-mini",
        provider_type="openai",
        litellm_kwargs={},
        supported_model_kwargs=SupportedModelKwargs(reasoning_effort=_LOW_MEDIUM_HIGH),
    )
    params = ["reasoning_effort"] if reasoning_params else []

    with (
        patch(f"{_CAPABILITIES}.get_supported_openai_params", return_value=params),
        patch(
            f"{_CAPABILITIES}.litellm.get_model_info",
            return_value={"supports_reasoning": True},
        ),
        pytest.raises(ProviderRejectedRequestException),
    ):
        route.prepare_provider_kwargs(ModelKwargs(reasoning_effort="none"))


# The stored model offers xhigh and temperature; the model a personal-chat
# policy chooses offers only low/medium/high.
_STORED_MODEL_SNAPSHOT = persist_discovered_model_kwargs_capabilities(
    SupportedModelKwargs(
        temperature=ModelKwargCapability(
            supported=True, control="slider", minimum=0, maximum=2, step=0.01
        ),
        reasoning_effort=ModelKwargCapability(
            supported=True,
            control="select",
            options=["none", "low", "medium", "high", "xhigh"],
        ),
    )
)
_GOVERNED_MODEL_SNAPSHOT = persist_discovered_model_kwargs_capabilities(
    SupportedModelKwargs(reasoning_effort=_LOW_MEDIUM_HIGH)
)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["assistant", "space-assistant"])
async def test_stored_settings_are_filtered_against_the_model_a_policy_chose(
    path: str, user: UserInDB
) -> None:
    stored_row = _model_row(capabilities=_STORED_MODEL_SNAPSHOT, reasoning=True)
    governed_row = _model_row(capabilities=_GOVERNED_MODEL_SNAPSHOT, reasoning=True)

    with patch(f"{_CAPABILITIES}.logger") as logger:
        _, outbound = await _send(
            path,
            stored_row,
            {"reasoning_effort": "xhigh", "temperature": 0.3},
            user,
            governed=governed_row,
        )
    _, unset = await _send(path, stored_row, {}, user, governed=governed_row)

    # xhigh and temperature suit the stored model, not the one the request
    # goes to: they are left out, as if unset, and the omission names the
    # chosen model.
    assert outbound == unset
    logger.warning.assert_called_once()
    assert logger.warning.call_args.kwargs["extra"]["completion_model_id"] == str(
        governed_row.id
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["assistant", "space-assistant"])
@pytest.mark.parametrize("policy_effort", ["high", None])
async def test_a_policy_effort_replaces_the_stored_one_without_a_report(
    path: str, policy_effort: str | None, user: UserInDB
) -> None:
    stored_row = _model_row(capabilities=_STORED_MODEL_SNAPSHOT, reasoning=True)
    governed_row = _model_row(capabilities=_GOVERNED_MODEL_SNAPSHOT, reasoning=True)

    with patch(f"{_CAPABILITIES}.logger") as logger:
        _, outbound = await _send(
            path,
            stored_row,
            # "none" is offered by the stored model only; the policy's effort
            # replaces it, so it is neither sent nor reported.
            {"reasoning_effort": "none", "temperature": 0.3},
            user,
            governed=governed_row,
            policy_effort=policy_effort,
        )

    expected = {"reasoning_effort": policy_effort or "low"}
    assert outbound == expected
    logger.warning.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_kwargs", "outcome"),
    [
        # A value for an offered control, outside its advertised range:
        # refused, never silently changed.
        (ModelKwargs(temperature=2.5), "refused"),
        (ModelKwargs(temperature=-0.1), "refused"),
        (ModelKwargs(verbosity="max"), "refused"),
        # In range: sent unchanged.
        (ModelKwargs(temperature=2.0), {"temperature": 2.0}),
        # A control the model does not offer is left out, as before.
        (ModelKwargs(top_p=0.4), {}),
    ],
    ids=["above-range", "below-range", "not-an-option", "at-maximum", "not-offered"],
)
async def test_a_request_value_the_model_does_not_offer_is_refused(
    request_kwargs: ModelKwargs, outcome: str | dict[str, object]
) -> None:
    row = _model_row(capabilities=_SNAPSHOT, reasoning=True)
    adapter = _OutboundAdapter(row.name)
    service = CompletionService(
        context_builder=_ContextBuilder(),  # pyright: ignore[reportArgumentType]
        tenant=SimpleNamespace(id=uuid4()),  # pyright: ignore[reportArgumentType]
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)  # pyright: ignore[reportAttributeAccessIssue]
    request = service.get_response(
        model=_domain_model(row),  # pyright: ignore[reportArgumentType]
        text_input="hi",
        model_kwargs=request_kwargs,
    )

    with patch(f"{_CAPABILITIES}.get_supported_openai_params", return_value=[]):
        if outcome == "refused":
            with pytest.raises(ProviderRejectedRequestException) as refused:
                await request
            assert refused.value.details is not None
            assert refused.value.details["reason"] == "model_setting_not_offered"
            assert adapter.outbound == []
        else:
            await request
            assert adapter.outbound == [outcome]


def test_a_route_refuses_a_request_value_outside_its_offered_range() -> None:
    route = ResolvedCompletionModelRoute(
        litellm_model="openai/gpt-5-mini",
        provider_type="openai",
        litellm_kwargs={},
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(
                supported=True, control="slider", minimum=1, maximum=2
            )
        ),
    )

    with (
        patch(f"{_CAPABILITIES}.get_supported_openai_params", return_value=[]),
        pytest.raises(ProviderRejectedRequestException),
    ):
        route.prepare_provider_kwargs(ModelKwargs(temperature=0.4))


@pytest.mark.parametrize(
    ("minimum", "expected"),
    [(1.0, {}), (0.0, {"temperature": 0.4})],
    ids=["temperature-minimum-1", "temperature-minimum-0"],
)
def test_the_ai_builder_leaves_out_its_own_temperature_when_the_route_does_not_offer_it(
    minimum: float, expected: dict[str, object]
) -> None:
    # The planner's 0.4 is the Builder's choice, not a user's: on a route
    # whose slider starts at 1 it is left out and one warning names the route.
    from eneo.flows.ai_builder.ai_builder_error_contract import (
        prepare_ai_builder_provider_kwargs,
    )
    from eneo.flows.ai_builder.ai_builder_service import PLANNER_TEMPERATURE

    route = ResolvedCompletionModelRoute(
        litellm_model="openai/gpt-5-mini",
        provider_type="openai",
        litellm_kwargs={},
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(
                supported=True, control="slider", minimum=minimum, maximum=2
            )
        ),
    )

    with (
        patch(f"{_CAPABILITIES}.get_supported_openai_params", return_value=[]),
        patch("eneo.flows.ai_builder.ai_builder_error_contract.logger") as logger,
    ):
        sent = prepare_ai_builder_provider_kwargs(
            route,
            ModelKwargs(temperature=PLANNER_TEMPERATURE),
            stage="proposal_completion",
        )

    assert sent == expected
    if expected:
        logger.warning.assert_not_called()
    else:
        logger.warning.assert_called_once()
        extra = logger.warning.call_args.kwargs["extra"]
        assert extra["litellm_model"] == "openai/gpt-5-mini"
        assert (extra["parameter"], extra["value"]) == ("temperature", 0.4)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize(
    "field", ["temperature", "top_p", "presence_penalty", "frequency_penalty"]
)
def test_model_settings_refuse_non_finite_numbers(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        ModelKwargs.model_validate({field: value})
