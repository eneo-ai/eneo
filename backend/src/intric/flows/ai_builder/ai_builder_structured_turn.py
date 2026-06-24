"""Typed retry runner for one structured LLM output schema."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_litellm_completion import CompletionMetadata
from intric.flows.ai_builder.ai_builder_token_usage import (
    CompletionTokenUsage,
    combine_token_usage,
)

Message = dict[str, Any]

OutputT = TypeVar("OutputT")
DiagnosticT = TypeVar("DiagnosticT")

StructuredTurnKind = Literal["accepted", "rejected", "parse_failed"]


@dataclass(frozen=True, slots=True)
class StructuredCompletion:
    raw_content: str
    metadata: CompletionMetadata


StructuredCompletionFn = Callable[[list[Message]], Awaitable[StructuredCompletion]]
StructuredParser = Callable[[str], OutputT]
StructuredNormalizer = Callable[[OutputT], OutputT]
StructuredValidator = Callable[[OutputT], DiagnosticT | None]
StructuredRetryEligibility = Callable[[DiagnosticT], bool]
StructuredSemanticRetryMessages = Callable[[OutputT, DiagnosticT], list[Message]]
StructuredParseRetryMessages = Callable[[list[Message], str, str], list[Message]]
StructuredParseFailureSummarizer = Callable[[str, Exception], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class StructuredTurnResult(Generic[OutputT, DiagnosticT]):
    kind: StructuredTurnKind
    accepted_output: OutputT | None = None
    rejection: DiagnosticT | None = None
    llm_calls_made: int = 0
    semantic_repair_attempts: int = 0
    parse_repair_attempts: int = 0
    final_completion: CompletionMetadata | None = None
    cumulative_token_usage: CompletionTokenUsage | None = None
    parse_error_raw: str | None = None
    parse_error_message: str | None = None
    parse_failure_diagnostics: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class _Parsed(Generic[OutputT]):
    output: OutputT | None
    error_message: str | None
    diagnostics: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class _ParseRepairResult(Generic[OutputT]):
    attempts: int
    repaired_output: OutputT | None
    final_metadata: CompletionMetadata
    token_usages: tuple[CompletionTokenUsage, ...]
    failed_raw: str
    failed_error: str
    failed_diagnostics: dict[str, Any] | None


async def run_structured_turn(
    *,
    initial_messages: list[Message],
    complete: StructuredCompletionFn,
    parse: StructuredParser[OutputT],
    normalize: StructuredNormalizer[OutputT],
    validate: StructuredValidator[OutputT, DiagnosticT],
    can_retry_semantic: StructuredRetryEligibility[DiagnosticT],
    build_semantic_retry_messages: StructuredSemanticRetryMessages[
        OutputT, DiagnosticT
    ],
    build_parse_retry_messages: StructuredParseRetryMessages,
    summarize_parse_failure: StructuredParseFailureSummarizer,
    max_semantic_retries: int,
    max_parse_retries: int,
) -> StructuredTurnResult[OutputT, DiagnosticT]:
    initial_completion = await complete(initial_messages)
    llm_calls_made = 1
    semantic_repair_attempts = 0
    parse_repair_attempts = 0
    final_metadata = initial_completion.metadata
    token_usages: list[CompletionTokenUsage] = [initial_completion.metadata.usage]

    def cumulative_usage() -> CompletionTokenUsage:
        return combine_token_usage(token_usages)

    parsed = _parse_raw(
        raw=initial_completion.raw_content,
        parse=parse,
        summarize_parse_failure=summarize_parse_failure,
    )
    if parsed.output is None:
        if final_metadata.finish_reason == "length":
            return StructuredTurnResult(
                kind="parse_failed",
                llm_calls_made=llm_calls_made,
                semantic_repair_attempts=semantic_repair_attempts,
                parse_repair_attempts=parse_repair_attempts,
                final_completion=final_metadata,
                cumulative_token_usage=cumulative_usage(),
                parse_error_raw=initial_completion.raw_content,
                parse_error_message=parsed.error_message,
                parse_failure_diagnostics=parsed.diagnostics,
            )
        parse_repair_result = await _run_parse_repair_loop(
            complete=complete,
            base_messages=initial_messages,
            failed_raw=initial_completion.raw_content,
            failed_error=parsed.error_message or "",
            parse=parse,
            build_parse_retry_messages=build_parse_retry_messages,
            summarize_parse_failure=summarize_parse_failure,
            max_parse_retries=max_parse_retries,
        )
        llm_calls_made += parse_repair_result.attempts
        parse_repair_attempts = parse_repair_result.attempts
        final_metadata = parse_repair_result.final_metadata
        token_usages.extend(parse_repair_result.token_usages)
        if parse_repair_result.repaired_output is None:
            return StructuredTurnResult(
                kind="parse_failed",
                llm_calls_made=llm_calls_made,
                semantic_repair_attempts=semantic_repair_attempts,
                parse_repair_attempts=parse_repair_attempts,
                final_completion=final_metadata,
                cumulative_token_usage=cumulative_usage(),
                parse_error_raw=parse_repair_result.failed_raw,
                parse_error_message=parse_repair_result.failed_error,
                parse_failure_diagnostics=parse_repair_result.failed_diagnostics,
            )
        output = normalize(parse_repair_result.repaired_output)
    else:
        output = normalize(parsed.output)

    while True:
        rejection = validate(output)
        if rejection is None:
            return StructuredTurnResult(
                kind="accepted",
                accepted_output=output,
                llm_calls_made=llm_calls_made,
                semantic_repair_attempts=semantic_repair_attempts,
                parse_repair_attempts=parse_repair_attempts,
                final_completion=final_metadata,
                cumulative_token_usage=cumulative_usage(),
            )
        if semantic_repair_attempts >= max_semantic_retries:
            return StructuredTurnResult(
                kind="rejected",
                rejection=rejection,
                llm_calls_made=llm_calls_made,
                semantic_repair_attempts=semantic_repair_attempts,
                parse_repair_attempts=parse_repair_attempts,
                final_completion=final_metadata,
                cumulative_token_usage=cumulative_usage(),
            )
        if not can_retry_semantic(rejection):
            return StructuredTurnResult(
                kind="rejected",
                rejection=rejection,
                llm_calls_made=llm_calls_made,
                semantic_repair_attempts=semantic_repair_attempts,
                parse_repair_attempts=parse_repair_attempts,
                final_completion=final_metadata,
                cumulative_token_usage=cumulative_usage(),
            )

        repair_messages = build_semantic_retry_messages(output, rejection)
        repair_completion = await complete(repair_messages)
        llm_calls_made += 1
        final_metadata = repair_completion.metadata
        token_usages.append(final_metadata.usage)

        parsed_repair = _parse_raw(
            raw=repair_completion.raw_content,
            parse=parse,
            summarize_parse_failure=summarize_parse_failure,
        )
        if parsed_repair.output is None:
            if final_metadata.finish_reason == "length":
                return StructuredTurnResult(
                    kind="parse_failed",
                    llm_calls_made=llm_calls_made,
                    semantic_repair_attempts=semantic_repair_attempts,
                    parse_repair_attempts=parse_repair_attempts,
                    final_completion=final_metadata,
                    cumulative_token_usage=cumulative_usage(),
                    parse_error_raw=repair_completion.raw_content,
                    parse_error_message=parsed_repair.error_message,
                    parse_failure_diagnostics=parsed_repair.diagnostics,
                )
            parse_repair_result = await _run_parse_repair_loop(
                complete=complete,
                base_messages=repair_messages,
                failed_raw=repair_completion.raw_content,
                failed_error=parsed_repair.error_message or "",
                parse=parse,
                build_parse_retry_messages=build_parse_retry_messages,
                summarize_parse_failure=summarize_parse_failure,
                max_parse_retries=max_parse_retries,
            )
            llm_calls_made += parse_repair_result.attempts
            parse_repair_attempts += parse_repair_result.attempts
            final_metadata = parse_repair_result.final_metadata
            token_usages.extend(parse_repair_result.token_usages)
            if parse_repair_result.repaired_output is None:
                return StructuredTurnResult(
                    kind="parse_failed",
                    llm_calls_made=llm_calls_made,
                    semantic_repair_attempts=semantic_repair_attempts,
                    parse_repair_attempts=parse_repair_attempts,
                    final_completion=final_metadata,
                    cumulative_token_usage=cumulative_usage(),
                    parse_error_raw=parse_repair_result.failed_raw,
                    parse_error_message=parse_repair_result.failed_error,
                    parse_failure_diagnostics=parse_repair_result.failed_diagnostics,
                )
            output = normalize(parse_repair_result.repaired_output)
            semantic_repair_attempts += 1
            continue

        output = normalize(parsed_repair.output)
        semantic_repair_attempts += 1


def _parse_raw(
    *,
    raw: str,
    parse: StructuredParser[OutputT],
    summarize_parse_failure: StructuredParseFailureSummarizer,
) -> _Parsed[OutputT]:
    try:
        return _Parsed(output=parse(raw), error_message=None, diagnostics=None)
    except (ValidationError, json.JSONDecodeError) as exc:
        return _Parsed(
            output=None,
            error_message=str(exc),
            diagnostics=summarize_parse_failure(raw, exc),
        )


async def _run_parse_repair_loop(
    *,
    complete: StructuredCompletionFn,
    base_messages: list[Message],
    failed_raw: str,
    failed_error: str,
    parse: StructuredParser[OutputT],
    build_parse_retry_messages: StructuredParseRetryMessages,
    summarize_parse_failure: StructuredParseFailureSummarizer,
    max_parse_retries: int,
) -> _ParseRepairResult[OutputT]:
    attempts = 0
    last_raw = failed_raw
    last_error = failed_error
    last_diagnostics: dict[str, Any] | None = None
    last_metadata = CompletionMetadata(
        finish_reason=None,
        usage=CompletionTokenUsage(),
    )
    token_usages: list[CompletionTokenUsage] = []
    while attempts < max_parse_retries:
        completion = await complete(
            build_parse_retry_messages(base_messages, last_raw, last_error)
        )
        attempts += 1
        last_metadata = completion.metadata
        token_usages.append(last_metadata.usage)
        parsed = _parse_raw(
            raw=completion.raw_content,
            parse=parse,
            summarize_parse_failure=summarize_parse_failure,
        )
        if parsed.output is not None:
            return _ParseRepairResult(
                attempts=attempts,
                repaired_output=parsed.output,
                final_metadata=last_metadata,
                token_usages=tuple(token_usages),
                failed_raw=last_raw,
                failed_error=last_error,
                failed_diagnostics=None,
            )
        last_raw = completion.raw_content
        last_error = parsed.error_message or ""
        last_diagnostics = parsed.diagnostics
        if last_metadata.finish_reason == "length":
            return _ParseRepairResult(
                attempts=attempts,
                repaired_output=None,
                final_metadata=last_metadata,
                token_usages=tuple(token_usages),
                failed_raw=last_raw,
                failed_error=last_error,
                failed_diagnostics=last_diagnostics,
            )
    return _ParseRepairResult(
        attempts=attempts,
        repaired_output=None,
        final_metadata=last_metadata,
        token_usages=tuple(token_usages),
        failed_raw=last_raw,
        failed_error=last_error,
        failed_diagnostics=last_diagnostics if attempts > 0 else None,
    )
