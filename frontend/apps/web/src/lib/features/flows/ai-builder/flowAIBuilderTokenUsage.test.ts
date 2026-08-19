import { describe, expect, it } from "vitest";

import backendTelemetryContract from "./__fixtures__/sessionTelemetrySummary.json";
import { buildAIBuilderTokenUsageView, formatAIBuilderTokenCount } from "./flowAIBuilderTokenUsage";
import type { AIBuilderTelemetrySummary } from "./protocol";

const telemetryContractKeys = [
  "planner_request_count",
  "clarification_question_count",
  "prompt_tokens_total",
  "completion_tokens_total",
  "total_tokens_total",
  "tool_call_count_total",
  "auxiliary_llm_call_count",
  "architecture_commit_count",
  "repair_attempts_total",
  "parse_repair_attempts_total",
  "wall_clock_ms_total",
  "llm_calls_made_total",
  "token_usage_estimated",
  "last_request_id",
  "last_model",
  "last_finish_reason",
  "last_outcome_kind",
  "last_token_usage_source",
  "last_token_usage_estimated"
] as const satisfies readonly (keyof AIBuilderTelemetrySummary)[];

type ContractKey = (typeof telemetryContractKeys)[number];
type MissingTelemetryContractKey = Exclude<keyof AIBuilderTelemetrySummary, ContractKey>;
type UnexpectedTelemetryContractKey = Exclude<ContractKey, keyof AIBuilderTelemetrySummary>;
type AssertNever<T extends never> = T;
type _TelemetryContractKeyCoverage = AssertNever<
  MissingTelemetryContractKey | UnexpectedTelemetryContractKey
>;

function makeTelemetry(
  overrides: Partial<AIBuilderTelemetrySummary> = {}
): AIBuilderTelemetrySummary {
  return {
    planner_request_count: 1,
    clarification_question_count: 0,
    prompt_tokens_total: 1200,
    completion_tokens_total: 300,
    total_tokens_total: 1500,
    tool_call_count_total: 1,
    auxiliary_llm_call_count: 0,
    architecture_commit_count: 0,
    repair_attempts_total: 1,
    parse_repair_attempts_total: 0,
    wall_clock_ms_total: 2500,
    llm_calls_made_total: 2,
    token_usage_estimated: false,
    last_request_id: "request-1",
    last_model: "gpt-5.4-nano",
    last_finish_reason: "tool_calls",
    last_outcome_kind: "dispatched",
    last_token_usage_source: "provider",
    last_token_usage_estimated: false,
    ...overrides
  };
}

describe("flowAIBuilderTokenUsage", () => {
  it("does not create a display model for empty usage", () => {
    expect(buildAIBuilderTokenUsageView(null)).toBeNull();
    expect(buildAIBuilderTokenUsageView(makeTelemetry({ total_tokens_total: 0 }))).toBeNull();
  });

  it("normalizes provider usage for the UI", () => {
    const view = buildAIBuilderTokenUsageView(makeTelemetry());

    expect(view).toMatchObject({
      total: 1500,
      prompt: 1200,
      completion: 300,
      llmCalls: 2,
      estimated: false,
      model: "gpt-5.4-nano"
    });
  });

  it("keeps estimated fallback visible to the UI", () => {
    const view = buildAIBuilderTokenUsageView(
      makeTelemetry({
        token_usage_estimated: true,
        last_token_usage_estimated: true,
        last_model: "gpt-5.4-mini"
      })
    );

    expect(view?.estimated).toBe(true);
    expect(view?.model).toBe("gpt-5.4-mini");
  });

  it("accepts the backend SessionTelemetrySummary wire shape", () => {
    const backendPayload = backendTelemetryContract as AIBuilderTelemetrySummary;

    expect(buildAIBuilderTokenUsageView(backendPayload)).toMatchObject({
      total: 1440,
      prompt: 1200,
      completion: 240,
      llmCalls: 2,
      estimated: false,
      model: "openai/gpt-5.4-nano"
    });
  });

  it("keeps the frontend telemetry contract in sync with the backend fixture", () => {
    expect(Object.keys(backendTelemetryContract).sort()).toEqual([...telemetryContractKeys].sort());
  });

  it("formats compact and full token counts without a UI runtime", () => {
    expect(formatAIBuilderTokenCount(1500, "en", { compact: true })).toBe("1.5K");
    expect(formatAIBuilderTokenCount(1500, "en")).toBe("1,500");
  });
});
