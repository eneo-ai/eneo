import { describe, expect, test } from "vitest";

import {
  buildFlowRunProgressSnapshot,
  isFlowRunActive,
  isFlowRunTerminal
} from "./flowRunProgress";

describe("flowRunProgress helpers", () => {
  test("identifies active and terminal run states", () => {
    expect(isFlowRunActive("queued")).toBe(true);
    expect(isFlowRunActive("running")).toBe(true);
    expect(isFlowRunActive("completed")).toBe(false);

    expect(isFlowRunTerminal("completed")).toBe(true);
    expect(isFlowRunTerminal("failed")).toBe(true);
    expect(isFlowRunTerminal("cancelled")).toBe(true);
    expect(isFlowRunTerminal("running")).toBe(false);
  });

  test("prefers version-pinned graph labels and overlays live step status", () => {
    const snapshot = buildFlowRunProgressSnapshot(
      {
        nodes: [
          {
            id: "step-1",
            label: "Extract text",
            type: "llm",
            step_order: 1,
            input_source: "flow_input",
            output_mode: "pass_through",
            output_type: "text"
          },
          {
            id: "step-2",
            label: "Summarize",
            type: "llm",
            step_order: 2,
            input_source: "previous_step",
            output_mode: "pass_through",
            output_type: "text"
          }
        ],
        edges: []
      },
      [
        {
          step_order: 1,
          status: "completed",
          error_message: null,
          num_tokens_input: 10,
          num_tokens_output: 20,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:01Z"
        },
        {
          step_order: 2,
          status: "running",
          error_message: null,
          created_at: "2026-01-01T00:00:01Z",
          updated_at: "2026-01-01T00:00:02Z"
        }
      ]
    );

    expect(snapshot.steps).toEqual([
      {
        stepOrder: 1,
        label: "Extract text",
        status: "completed",
        inputSource: "flow_input",
        outputMode: "pass_through",
        outputType: "text",
        errorMessage: null,
        numTokensInput: 10,
        numTokensOutput: 20,
        inputPayload: null,
        outputPayload: null,
        startedAt: null,
        finishedAt: null,
        createdAt: "2026-01-01T00:00:00Z",
        updatedAt: "2026-01-01T00:00:01Z"
      },
      {
        stepOrder: 2,
        label: "Summarize",
        status: "running",
        inputSource: "previous_step",
        outputMode: "pass_through",
        outputType: "text",
        errorMessage: null,
        numTokensInput: null,
        numTokensOutput: null,
        inputPayload: null,
        outputPayload: null,
        startedAt: null,
        finishedAt: null,
        createdAt: "2026-01-01T00:00:01Z",
        updatedAt: "2026-01-01T00:00:02Z"
      }
    ]);
  });

  test("falls back to generic step labels when graph data is missing", () => {
    const snapshot = buildFlowRunProgressSnapshot(null, [
      {
        step_order: 3,
        status: "pending",
        error_message: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z"
      }
    ]);

    expect(snapshot.steps).toEqual([
      {
        stepOrder: 3,
        label: "Step 3",
        status: "pending",
        errorMessage: null,
        numTokensInput: null,
        numTokensOutput: null,
        inputPayload: null,
        outputPayload: null,
        startedAt: null,
        finishedAt: null,
        createdAt: "2026-01-01T00:00:00Z",
        updatedAt: "2026-01-01T00:00:00Z"
      }
    ]);
  });
});
