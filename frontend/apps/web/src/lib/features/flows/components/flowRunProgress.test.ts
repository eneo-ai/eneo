import { describe, expect, test } from "vitest";

import { buildFlowRunProgressSnapshot, getFlowRunFocusedStepOrder } from "./flowRunProgress";

describe("flowRunProgress helpers", () => {
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
        resultFiles: [],
        startedAt: null,
        finishedAt: null,
        createdAt: "2026-01-01T00:00:00Z",
        updatedAt: "2026-01-01T00:00:00Z"
      }
    ]);
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
