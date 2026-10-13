"""The digest glue: effective model and effort, budgets, the bounded and
retried provider call, and the result shape with its coverage account."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.completion_models.application.map_reduce import (
    DigestBudgets,
    DigestDeadlineExceeded,
    DigestItem,
    DigestResult,
    ItemProgress,
    Usage,
)
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.internal_mcp import digest as digest_module
from eneo.internal_mcp.constants import CITE_KEY_META
from eneo.internal_mcp.digest import (
    CitationStub,
    Deadline,
    DigestModel,
    DigestRefused,
    ProviderCalls,
    ProviderCallTimeout,
    SetAside,
    cited_keys,
    compute_budgets,
    coverage_line,
    digest_meta,
    format_digest,
    is_retryable,
    plan_or_refuse,
    prepare_digest_model,
    validate_instruction,
)
from eneo.internal_mcp.foundation import DigestClaims
from eneo.main.exceptions import OpenAIException


def _count(text: str) -> int:
    return len(text.split())


def _reasoning_select(options=("low", "medium", "high")) -> ModelKwargCapability:
    return ModelKwargCapability(supported=True, control="select", options=list(options))


def _model(*, reasoning=True, window=128_000, name="gpt-x"):
    supported = SupportedModelKwargs(
        temperature=ModelKwargCapability(supported=True, control="slider"),
        reasoning_effort=_reasoning_select() if reasoning else ModelKwargCapability(),
    )
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        max_input_tokens=window,
        get_supported_model_kwargs=lambda: supported,
        get_model_route=lambda: name,
    )


def _tool_ctx(*, claimed_model=None, adapter=None):
    async def one(model_id):
        assert claimed_model is not None and model_id == claimed_model.id
        return claimed_model

    async def build_adapter(model):
        return adapter or SimpleNamespace(model=model)

    container = SimpleNamespace(
        completion_model_repo2=lambda: SimpleNamespace(one=one),
        completion_service=lambda: SimpleNamespace(build_adapter=build_adapter),
    )
    return SimpleNamespace(container=container, user=SimpleNamespace(tenant_id=uuid4()))


def _assistant(model, **kwargs):
    return SimpleNamespace(
        completion_model=model,
        completion_model_kwargs=ModelKwargs(**kwargs),
    )


def _digest_model(*, window=128_000, body_cap=9_000) -> DigestModel:
    model = _model(window=window)
    return DigestModel(
        model=model,
        adapter=None,
        model_kwargs={},
        count=_count,
        budgets=compute_budgets(
            window=window, count=_count, instruction="sum", body_cap=body_cap
        ),
        body_cap_chars=body_cap,
    )


# --------------------------------------------------------------------------- #
# Instruction and budgets
# --------------------------------------------------------------------------- #
class TestValidation:
    def test_empty_and_oversized_instructions_are_refused(self):
        with pytest.raises(DigestRefused):
            validate_instruction("   ")
        with pytest.raises(DigestRefused, match="characters"):
            validate_instruction("x" * (digest_module.INSTRUCTION_MAX_CHARS + 1))
        assert validate_instruction("  Summarise the decisions ") == (
            "Summarise the decisions"
        )


class TestBudgets:
    def test_budgets_are_net_of_prompt_overhead_and_clamped(self):
        budgets = compute_budgets(
            window=128_000, count=_count, instruction="sum", body_cap=9_000
        )

        assert budgets.segment_tokens == 12_000
        assert budgets.reduce_input_tokens == 60_000
        assert budgets.final_words == 9_000 // 7
        assert budgets.final_max_tokens == 9_000 // 3 + 200

    def test_small_windows_get_smaller_segments_and_tiny_ones_are_refused(self):
        budgets = compute_budgets(
            window=16_000, count=_count, instruction="sum", body_cap=9_000
        )
        assert 1_000 <= budgets.segment_tokens < 12_000
        assert budgets.segment_tokens + 600 + 200 < 16_000

        with pytest.raises(DigestRefused, match="too small"):
            compute_budgets(
                window=4_000, count=_count, instruction="sum", body_cap=9_000
            )

    def test_plan_refuses_above_the_segment_ceiling_naming_the_largest(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            digest_module,
            "get_settings",
            lambda: SimpleNamespace(
                digest_max_segments=3, mcp_tool_output_max_chars=32768
            ),
        )
        digest_model = _digest_model(window=20_000)
        words = digest_model.budgets.segment_tokens * 4
        items = [
            DigestItem("D1", "Big", " ".join(["w"] * words)),
            DigestItem("D2", "Small", "a b c"),
        ]

        with pytest.raises(DigestRefused) as refused:
            plan_or_refuse(items, digest_model, narrow_hint="Narrow it.")

        message = refused.value.message
        assert "limit is 3" in message
        assert "[D1] Big" in message
        assert message.endswith("Narrow it.")


# --------------------------------------------------------------------------- #
# Model and effort resolution
# --------------------------------------------------------------------------- #
class TestPrepareDigestModel:
    async def test_claimed_model_wins_over_the_assistants_stored_one(self):
        claimed, stored = _model(name="policy-model"), _model(name="stored-model")
        tool_ctx = _tool_ctx(claimed_model=claimed)

        digest_model = await prepare_digest_model(
            tool_ctx,
            _assistant(stored, temperature=0.4),
            DigestClaims(claimed.id, None, False),
            instruction="sum",
        )

        assert digest_model.model is claimed
        assert digest_model.adapter.model is claimed

    async def test_falls_back_to_the_assistant_model_without_a_claim(self):
        stored = _model()

        digest_model = await prepare_digest_model(
            _tool_ctx(),
            _assistant(stored),
            DigestClaims(None, None, False),
            instruction="s",
        )

        assert digest_model.model is stored

    async def test_enforced_effort_is_kept_and_unenforced_effort_is_lowered(self):
        model = _model()
        assistant = _assistant(model, reasoning_effort="high", response_format={"a": 1})

        enforced = await prepare_digest_model(
            _tool_ctx(), assistant, DigestClaims(None, "medium", True), instruction="s"
        )
        cheap = await prepare_digest_model(
            _tool_ctx(), assistant, DigestClaims(None, "medium", False), instruction="s"
        )

        assert enforced.model_kwargs["reasoning_effort"] == "medium"
        assert cheap.model_kwargs["reasoning_effort"] == "low"
        assert "response_format" not in enforced.model_kwargs
        assert "response_format" not in cheap.model_kwargs

    async def test_models_without_reasoning_get_no_effort_at_all(self):
        model = _model(reasoning=False)

        digest_model = await prepare_digest_model(
            _tool_ctx(),
            _assistant(model, reasoning_effort="high"),
            DigestClaims(None, "high", True),
            instruction="s",
        )

        assert "reasoning_effort" not in digest_model.model_kwargs

    async def test_assistant_without_a_model_is_refused(self):
        with pytest.raises(DigestRefused):
            await prepare_digest_model(
                _tool_ctx(),
                _assistant(None),
                DigestClaims(None, None, False),
                instruction="s",
            )


# --------------------------------------------------------------------------- #
# The provider call
# --------------------------------------------------------------------------- #
def _provider_error(reason: str, *, retryable: bool = True) -> OpenAIException:
    return OpenAIException(
        reason, code=reason, details={"reason": reason, "retryable": retryable}
    )


class TestRetryPredicate:
    def test_only_rate_limits_and_outages_are_retried(self):
        assert is_retryable(_provider_error("provider_rate_limited"))
        assert is_retryable(_provider_error("provider_unavailable"))
        assert not is_retryable(_provider_error("provider_error"))
        assert not is_retryable(
            _provider_error("provider_rejected_request", retryable=False)
        )
        assert not is_retryable(RuntimeError("boom"))


class _Adapter:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    async def get_response(self, context, kwargs):
        self.calls.append({"prompt": context.prompt, "input": context.input, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return await outcome()
        return SimpleNamespace(
            text=outcome, usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4)
        )


def _calls(adapter, *, seconds=30.0, sleep=None, process_slots=None) -> ProviderCalls:
    digest_model = DigestModel(
        model=_model(),
        adapter=adapter,
        model_kwargs={"temperature": 0.2},
        count=_count,
        budgets=DigestBudgets(segment_tokens=100, reduce_input_tokens=200),
        body_cap_chars=9_000,
    )
    slept: list[float] = []

    async def record_sleep(delay):
        slept.append(delay)

    calls = ProviderCalls(
        digest_model,
        deadline=Deadline(seconds),
        concurrency=2,
        process_slots=process_slots or asyncio.Semaphore(8),
        sleep=sleep or record_sleep,
        rng=lambda low, high: high,
    )
    calls.slept = slept  # type: ignore[attr-defined]
    return calls


class TestProviderCalls:
    async def test_passes_prompts_kwargs_and_max_tokens_and_returns_usage(self):
        adapter = _Adapter(["note"])

        text, usage = await _calls(adapter)("system", "user", 123)

        assert (text, usage) == ("note", Usage(10, 4))
        assert adapter.calls[0]["prompt"] == "system"
        assert adapter.calls[0]["input"] == "user"
        assert adapter.calls[0]["max_tokens"] == 123
        assert adapter.calls[0]["temperature"] == 0.2

    async def test_rate_limit_is_retried_with_bounded_backoff(self):
        adapter = _Adapter([_provider_error("provider_rate_limited"), "note"])
        calls = _calls(adapter)

        text, _ = await calls("s", "u", 10)

        assert text == "note"
        assert calls.slept == [2.0]

    async def test_gives_up_after_the_last_attempt(self):
        adapter = _Adapter([_provider_error("provider_unavailable")] * 3)

        with pytest.raises(OpenAIException):
            await _calls(adapter)("s", "u", 10)
        assert len(adapter.calls) == 3

    async def test_non_retryable_errors_propagate_at_once(self):
        adapter = _Adapter([_provider_error("provider_error"), "never"])

        with pytest.raises(OpenAIException):
            await _calls(adapter)("s", "u", 10)
        assert len(adapter.calls) == 1

    async def test_backoff_past_the_deadline_is_a_deadline(self):
        adapter = _Adapter([_provider_error("provider_rate_limited"), "never"])

        with pytest.raises(DigestDeadlineExceeded):
            await _calls(adapter, seconds=1.0)("s", "u", 10)
        assert len(adapter.calls) == 1

    async def test_saturated_process_slots_end_at_the_deadline_not_later(self):
        adapter = _Adapter(["never"])
        taken = asyncio.Semaphore(0)

        with pytest.raises(DigestDeadlineExceeded):
            await _calls(adapter, seconds=0.05, process_slots=taken)("s", "u", 10)
        assert adapter.calls == []

    async def test_hung_call_is_a_failed_call_when_time_remains(self, monkeypatch):
        monkeypatch.setattr(digest_module, "CALL_TIMEOUT_SECONDS", 0.01)

        async def hang():
            await asyncio.sleep(1)

        adapter = _Adapter([hang])

        with pytest.raises(ProviderCallTimeout):
            await _calls(adapter, seconds=30.0)("s", "u", 10)

    async def test_hung_call_at_the_deadline_is_a_deadline(self):
        async def hang():
            await asyncio.sleep(1)

        adapter = _Adapter([hang])

        with pytest.raises(DigestDeadlineExceeded):
            await _calls(adapter, seconds=0.02)("s", "u", 10)


# --------------------------------------------------------------------------- #
# Result shape
# --------------------------------------------------------------------------- #
def _result(**overrides) -> DigestResult:
    defaults = dict(
        output="Decisions [D1] and [D2].",
        coverage="complete",
        item_progress={"D1": ItemProgress(1, 1), "D2": ItemProgress(3, 3)},
        llm_calls=5,
        usage=Usage(500, 80),
        levels=1,
    )
    defaults.update(overrides)
    return DigestResult(**defaults)


class TestResultShape:
    def test_cited_keys_keeps_only_known_keys_in_first_seen_order(self):
        assert cited_keys("x [D2] y [D9] z [D1] [D2]", ["D1", "D2", "D3"]) == [
            "D2",
            "D1",
        ]

    def test_coverage_line_complete_and_partial(self):
        complete = coverage_line(_result(not_relevant=["D2"]), item_word="documents")
        partial = coverage_line(
            _result(
                coverage="partial",
                item_progress={"D1": ItemProgress(2, 1), "D2": ItemProgress(1, 1)},
                failed=["D1 segment 2"],
                reasons=["failed segments"],
            ),
            item_word="documents",
        )

        assert complete.startswith("Coverage: complete.")
        assert "1 with no relevant content ([D2])" in complete
        assert partial.startswith("Coverage: partial (failed segments).")
        assert "1 failed" in partial
        assert partial.endswith("Not fully covered: [D1].")

    def test_format_digest_builds_header_body_and_keyed_stubs(self, monkeypatch):
        monkeypatch.setattr(
            digest_module,
            "get_settings",
            lambda: SimpleNamespace(mcp_tool_output_max_chars=32768),
        )
        items = [DigestItem("D1", "Minutes 1", "x"), DigestItem("D2", "Minutes 2", "y")]
        stubs = [
            CitationStub("D1", "eneo://info-blob/1", "[D1] Minutes 1", {"title": "M1"})
        ]

        content = format_digest(
            heading="Digest of X.",
            items=items,
            result=_result(),
            set_aside=[SetAside("budget.xlsx", "table; use the table tools")],
            omitted=2,
            stubs=stubs,
            body_cap=9_000,
            item_word="documents",
        )

        text = content[0].text
        assert text.startswith("Digest of X.\n[D1] Minutes 1\n[D2] Minutes 2\n")
        assert (
            "Not digested (tables):\n- budget.xlsx: table; use the table tools" in text
        )
        assert "Omitted by max_documents: 2 documents." in text
        assert "Coverage: complete." in text
        assert text.endswith("\n\nDecisions [D1] and [D2].")
        resource = content[1].resource
        assert str(resource.uri) == "eneo://info-blob/1"
        assert resource.text == "[D1] Minutes 1"
        assert resource.meta == {"title": "M1", CITE_KEY_META: "D1"}

    def test_payload_rule_shrinks_the_body_never_the_stubs(self, monkeypatch):
        monkeypatch.setattr(
            digest_module,
            "get_settings",
            lambda: SimpleNamespace(mcp_tool_output_max_chars=2_000),
        )
        stubs = [
            CitationStub(f"D{i}", f"eneo://info-blob/{i}", f"[D{i}] " + "t" * 100)
            for i in range(1, 6)
        ]
        result = _result(output="b" * 5_000)

        content = format_digest(
            heading="H",
            items=[DigestItem("D1", "T", "x")],
            result=result,
            set_aside=[],
            omitted=0,
            stubs=stubs,
            body_cap=9_000,
            item_word="documents",
        )

        body = content[0].text.split("\n\n", 1)[1]
        assert "[Digest body truncated at" in body
        assert len(body) < 1_500
        assert len(content) == 6

    def test_empty_and_cancelled_bodies_say_so(self, monkeypatch):
        monkeypatch.setattr(
            digest_module,
            "get_settings",
            lambda: SimpleNamespace(mcp_tool_output_max_chars=32768),
        )
        empty = format_digest(
            heading="H",
            items=[],
            result=_result(output=""),
            set_aside=[],
            omitted=0,
            stubs=[],
            body_cap=9_000,
            item_word="files",
        )
        cancelled = format_digest(
            heading="H",
            items=[],
            result=_result(output="", coverage="cancelled", reasons=["cancelled"]),
            set_aside=[],
            omitted=0,
            stubs=[],
            body_cap=9_000,
            item_word="files",
        )

        assert "No content relevant to the instruction was found." in empty[0].text
        assert "Digest cancelled" in cancelled[0].text

    def test_meta_carries_usage_model_and_coverage(self):
        digest_model = _digest_model()
        meta = digest_meta(
            _result(
                coverage="partial", excluded=["D2"], reasons=["excluded at reduce"]
            ),
            digest_model,
        )

        assert meta["gen_ai.usage.input_tokens"] == 500
        assert meta["gen_ai.usage.output_tokens"] == 80
        assert meta["eneo.completion_model_id"] == str(digest_model.model.id)
        assert meta["eneo.segments_planned"] == 4
        assert meta["eneo.segments_processed"] == 4
        assert meta["eneo.coverage"] == "partial"
        assert meta["eneo.items_partial"] == ["D2"]
        assert meta["eneo.llm_calls"] == 5
