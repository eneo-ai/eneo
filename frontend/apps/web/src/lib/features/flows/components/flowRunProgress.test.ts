import { describe, expect, test } from "vitest";

import {
  buildFlowRunProgressSnapshot,
  formatFlowRunDuration,
  getFlowRunFocusedStepOrder
} from "./flowRunProgress";

describe("flowRunProgress helpers", () => {
  test("rounds a duration to whole seconds before splitting minutes", () => {
    expect(formatFlowRunDuration(4 * 60_000 + 59_600, "en")).toBe("5 min");
    expect(formatFlowRunDuration(4 * 60_000 + 59_400, "en")).toBe("4 min 59 sec");
    expect(formatFlowRunDuration(61_000, "sv")).toBe("1 min 1 s");
  });

  test("names durations in the reader's language and carries the round-up into the larger unit", () => {
    expect(formatFlowRunDuration(350, "sv")).toBe("350 ms");
    expect(formatFlowRunDuration(59_600, "sv")).toBe("1 min");
    expect(formatFlowRunDuration(3_599_700, "sv")).toBe("1 tim");
    expect(formatFlowRunDuration(3_900_000, "sv")).toBe("1 tim 5 min");
    expect(formatFlowRunDuration(2 * 86_400_000 + 3 * 3_600_000, "sv")).toBe("2 d 3 tim");
  });

  test("trusts the step list over an older graph when both come from one detail read", () => {
    const snapshot = buildFlowRunProgressSnapshot(
      {
        nodes: [
          { id: "step-1", label: "Summarize", type: "llm", step_order: 1, run_status: "running" }
        ],
        edges: []
      },
      [
        {
          input_text_aliases: [],
          flow_run_id: "run-1",
          flow_id: "flow-1",
          tenant_id: "tenant-1",
          step_id: "step-1",
          step_order: 1,
          status: "completed",
          error_message: null,
          output_payload_json: { text: "done" },
          num_tokens_input: 5,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:09Z"
        }
      ]
    );

    expect(snapshot.steps[0]).toMatchObject({
      status: "completed",
      outputPayload: { text: "done" },
      numTokensInput: 5
    });
    expect(snapshot.steps[0].detailsStale).toBeUndefined();
  });

  test("withholds a step's outputs and end time when a status poll moved past the step list", () => {
    const snapshot = buildFlowRunProgressSnapshot(
      {
        nodes: [
          { id: "step-1", label: "Summarize", type: "llm", step_order: 1, run_status: "completed" }
        ],
        edges: []
      },
      [
        {
          input_text_aliases: [],
          flow_run_id: "run-1",
          flow_id: "flow-1",
          tenant_id: "tenant-1",
          step_id: "step-1",
          step_order: 1,
          status: "running",
          error_message: null,
          output_payload_json: { text: "partial" },
          started_at: "2026-01-01T00:00:00Z",
          finished_at: "2026-01-01T00:00:09Z",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:09Z"
        }
      ],
      { statusOverlay: true }
    );

    expect(snapshot.steps[0]).toMatchObject({
      status: "completed",
      detailsStale: true,
      outputPayload: null,
      finishedAt: null,
      updatedAt: null,
      startedAt: "2026-01-01T00:00:00Z"
    });
  });

  test("takes the status and token counts from a status poll over the older step list", () => {
    const snapshot = buildFlowRunProgressSnapshot(
      {
        nodes: [
          {
            id: "step-1",
            label: "Summarize",
            type: "llm",
            step_order: 1,
            run_status: "completed",
            num_tokens_input: 12,
            num_tokens_output: 34
          }
        ],
        edges: []
      },
      [
        {
          input_text_aliases: [],
          flow_run_id: "run-1",
          flow_id: "flow-1",
          tenant_id: "tenant-1",
          step_id: "step-1",
          step_order: 1,
          status: "running",
          error_message: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:01Z"
        }
      ],
      { statusOverlay: true }
    );

    expect(snapshot.steps[0]).toMatchObject({
      status: "completed",
      numTokensInput: 12,
      numTokensOutput: 34
    });
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
          input_text_aliases: [],
          flow_run_id: "run-1",
          flow_id: "flow-1",
          tenant_id: "tenant-1",
          step_id: "step-1",
          step_order: 1,
          status: "completed",
          error_message: null,
          num_tokens_input: 10,
          num_tokens_output: 20,
          result_files: [
            {
              flow_run_id: "run-1",
              flow_id: "flow-1",
              tenant_id: "tenant-1",
              step_result_id: "result-1",
              step_id: "step-1",
              step_order: 1,
              attempt_no: 1,
              file_id: "file-1",
              ordinal: 0,
              source: "declared_artifact",
              name: "summary.pdf",
              checksum: "checksum",
              size: 14012,
              mimetype: "application/pdf",
              file_type: "document",
              availability: "available"
            }
          ],
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:01Z"
        },
        {
          input_text_aliases: [],
          flow_run_id: "run-1",
          flow_id: "flow-1",
          tenant_id: "tenant-1",
          step_id: "step-2",
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
        errorCode: null,
        numTokensInput: 10,
        numTokensOutput: 20,
        inputPayload: null,
        outputPayload: null,
        resultFiles: [
          {
            flow_run_id: "run-1",
            flow_id: "flow-1",
            tenant_id: "tenant-1",
            step_result_id: "result-1",
            step_id: "step-1",
            step_order: 1,
            attempt_no: 1,
            file_id: "file-1",
            ordinal: 0,
            source: "declared_artifact",
            name: "summary.pdf",
            checksum: "checksum",
            size: 14012,
            mimetype: "application/pdf",
            file_type: "document",
            availability: "available"
          }
        ],
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
        errorCode: null,
        numTokensInput: null,
        numTokensOutput: null,
        inputPayload: null,
        outputPayload: null,
        resultFiles: [],
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
        input_text_aliases: [],
        flow_run_id: "run-1",
        flow_id: "flow-1",
        tenant_id: "tenant-1",
        step_id: "step-3",
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
        errorCode: null,
        numTokensInput: null,
        numTokensOutput: null,
        inputPayload: null,
        outputPayload: null,
        resultFiles: [],
        startedAt: null,
        finishedAt: null,
        createdAt: "2026-01-01T00:00:00Z",
        updatedAt: "2026-01-01T00:00:00Z"
      }
    ]);
  });

  test("carries live step error codes for localized step-card failures", () => {
    const snapshot = buildFlowRunProgressSnapshot(
      {
        nodes: [
          {
            id: "step-1",
            label: "Extract text",
            type: "llm",
            step_order: 1,
            error_message: "Graph fallback error"
          }
        ],
        edges: []
      },
      [
        {
          input_text_aliases: [],
          flow_run_id: "run-1",
          flow_id: "flow-1",
          tenant_id: "tenant-1",
          step_id: "step-1",
          step_order: 1,
          status: "failed",
          error_code: "flow_step_execution_failed",
          error_message: "Step failed during execution.",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:01Z"
        }
      ]
    );

    expect(snapshot.steps[0]).toMatchObject({
      errorMessage: "Step failed during execution.",
      errorCode: "flow_step_execution_failed"
    });
  });

  test("does not invent an error code for graph-only fallback errors", () => {
    const snapshot = buildFlowRunProgressSnapshot(
      {
        nodes: [
          {
            id: "step-1",
            label: "Extract text",
            type: "llm",
            step_order: 1,
            error_message: "Graph fallback error"
          }
        ],
        edges: []
      },
      []
    );

    expect(snapshot.steps[0]).toMatchObject({
      errorMessage: "Graph fallback error",
      errorCode: null
    });
  });

  test("focuses the running step while a run progresses", () => {
    expect(
      getFlowRunFocusedStepOrder({
        steps: [
          { stepOrder: 1, label: "Transcribe", status: "completed", resultFiles: [] },
          { stepOrder: 2, label: "Structure", status: "running", resultFiles: [] },
          { stepOrder: 3, label: "Summarize", status: "queued", resultFiles: [] }
        ]
      })
    ).toBe(2);
  });

  test("focuses the next queued step when no step is running", () => {
    expect(
      getFlowRunFocusedStepOrder({
        steps: [
          { stepOrder: 1, label: "Transcribe", status: "completed", resultFiles: [] },
          { stepOrder: 2, label: "Structure", status: "completed", resultFiles: [] },
          { stepOrder: 3, label: "Summarize", status: "queued", resultFiles: [] }
        ]
      })
    ).toBe(3);
  });

  test("focuses the failed step before queued work", () => {
    expect(
      getFlowRunFocusedStepOrder({
        steps: [
          { stepOrder: 1, label: "Transcribe", status: "completed", resultFiles: [] },
          { stepOrder: 2, label: "Structure", status: "failed", resultFiles: [] },
          { stepOrder: 3, label: "Summarize", status: "queued", resultFiles: [] }
        ]
      })
    ).toBe(2);
  });
});
