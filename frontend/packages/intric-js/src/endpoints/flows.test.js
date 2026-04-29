import { describe, expect, it, vi } from "vitest";

import { initFlows } from "./flows";

describe("flows templates endpoint", () => {
  it("uploads template files to the Flow template route", async () => {
    const fetch = vi.fn(async () => ({ id: "file-1" }));
    const flows = initFlows({ fetch });
    const file = new File(["docx"], "template.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    });

    await flows.templates.upload({ id: "flow-1", file });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/flow-1/template-files/");
    expect(fetch.mock.calls[0][1].method).toBe("post");
    expect(fetch.mock.calls[0][1].requestBody["multipart/form-data"]).toBeInstanceOf(FormData);
  });

  it("lists template assets from flow template route", async () => {
    const fetch = vi.fn(async () => ({ items: [] }));
    const flows = initFlows({ fetch });

    await flows.templates.list({ id: "flow-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/flow-1/template-files/");
    expect(fetch.mock.calls[0][1].method).toBe("get");
  });

  it("loads run contract from canonical runtime route", async () => {
    const fetch = vi.fn(async () => ({ published_flow_version: 7, steps_requiring_input: [] }));
    const flows = initFlows({ fetch });

    await flows.runContract.get({ id: "flow-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/flow-1/run-contract/");
    expect(fetch.mock.calls[0][1].method).toBe("get");
  });

  it("loads the published runtime projection from the canonical route", async () => {
    const fetch = vi.fn(async () => ({
      id: "flow-1",
      published_version: 7,
      runtime_paths: {}
    }));
    const flows = initFlows({ fetch });

    await flows.published.get({ id: "flow-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/flow-1/published/");
    expect(fetch.mock.calls[0][1].method).toBe("get");
  });

  it("generates template signed url from flow route", async () => {
    const fetch = vi.fn(async () => ({ url: "https://example.com" }));
    const flows = initFlows({ fetch });

    await flows.templates.signedUrl({ id: "flow-1", fileId: "file-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/flow-1/template-files/file-1/signed-url/");
    expect(fetch.mock.calls[0][1].method).toBe("post");
  });

  it("uploads runtime files to step-scoped route", async () => {
    const fetch = vi.fn(async () => ({ id: "runtime-file-1" }));
    const flows = initFlows({ fetch });
    const file = new File(["doc"], "source.txt", { type: "text/plain" });

    await flows.steps.runtimeFiles.upload({ id: "flow-1", stepId: "step-1", file });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/flow-1/steps/step-1/runtime-files/");
    expect(fetch.mock.calls[0][1].method).toBe("post");
  });

  it("generates artifact signed url from flow run route", async () => {
    const fetch = vi.fn(async () => ({ url: "https://example.com/download", expires_at: 9999 }));
    const flows = initFlows({ fetch });

    await flows.runs.artifactSignedUrl({ flowId: "flow-1", runId: "run-1", fileId: "file-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe(
      "/api/v1/flows/flow-1/runs/run-1/artifacts/file-1/signed-url/"
    );
    expect(fetch.mock.calls[0][1].method).toBe("post");
  });

  it("exports evidence from the canonical flow run route", async () => {
    const fetch = vi.fn(async () => ({
      schema_version: "flow-evidence-export.v2",
      content_hash: "abc123"
    }));
    const flows = initFlows({ fetch });

    await flows.runs.exportEvidence({ id: "run-1", flowId: "flow-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/flow-1/runs/run-1/evidence/export");
    expect(fetch.mock.calls[0][1]).toMatchObject({
      method: "get",
      params: { query: { format: "json" } }
    });
  });

  it("creates flow run with canonical step_inputs payload", async () => {
    const fetch = vi.fn(async () => ({ id: "run-1" }));
    const flows = initFlows({ fetch });

    await flows.runs.create({
      flow: { id: "flow-1" },
      expected_flow_version: 7,
      input_payload_json: { text: "test" },
      step_inputs: {
        "step-1": { file_ids: ["file-1"] }
      }
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/flow-1/runs/");
    expect(fetch.mock.calls[0][1].requestBody["application/json"]).not.toHaveProperty("flow_id");
    expect(fetch.mock.calls[0][1].requestBody["application/json"]).toEqual({
      expected_flow_version: 7,
      input_payload_json: { text: "test" },
      step_inputs: {
        "step-1": { file_ids: ["file-1"] }
      }
    });
  });

  it("normalizes file id ordering before creating flow runs", async () => {
    const fetch = vi.fn(async () => ({ id: "run-1" }));
    const flows = initFlows({ fetch });

    await flows.runs.create({
      flow: { id: "flow-1" },
      file_ids: ["file-3", "file-1", "file-2"],
      step_inputs: {
        "step-b": { file_ids: ["file-5", "file-4"] },
        "step-a": { file_ids: ["file-9"] }
      }
    });

    expect(fetch.mock.calls[0][1].requestBody["application/json"]).toEqual({
      file_ids: ["file-1", "file-2", "file-3"],
      step_inputs: {
        "step-a": { file_ids: ["file-9"] },
        "step-b": { file_ids: ["file-4", "file-5"] }
      }
    });
  });

  it("forwards flow run idempotency header when provided", async () => {
    const fetch = vi.fn(async () => ({ id: "run-1" }));
    const flows = initFlows({ fetch });

    await flows.runs.create({
      flow: { id: "flow-1" },
      idempotencyKey: "flow-run:test-key",
      file_ids: ["file-1"]
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1].headers).toEqual({
      "Idempotency-Key": "flow-run:test-key"
    });
  });

  it("derives a stable upload-intent idempotency key", async () => {
    const flows = initFlows({ fetch: vi.fn() });

    const keyA = await flows.runs.deriveUploadIntentIdempotencyKey({
      flowId: "flow-1",
      expectedFlowVersion: 7,
      input_payload_json: { b: 2, a: 1, nested: { y: 2, x: 1 } },
      step_inputs: {
        "step-b": { file_ids: ["file-3", "file-2"] },
        "step-a": { file_ids: ["file-1"] }
      },
      file_ids: ["file-9", "file-4"]
    });
    const keyB = await flows.runs.deriveUploadIntentIdempotencyKey({
      flowId: "flow-1",
      expectedFlowVersion: 7,
      input_payload_json: { nested: { x: 1, y: 2 }, a: 1, b: 2 },
      step_inputs: {
        "step-a": { file_ids: ["file-1"] },
        "step-b": { file_ids: ["file-2", "file-3"] }
      },
      file_ids: ["file-4", "file-9"]
    });

    expect(keyA).toBe(keyB);
    expect(keyA).toMatch(/^flow-run:[a-f0-9]{64}$/);
  });

  it("derives different upload-intent idempotency keys when the run intent changes", async () => {
    const flows = initFlows({ fetch: vi.fn() });

    const keyA = await flows.runs.deriveUploadIntentIdempotencyKey({
      flowId: "flow-1",
      file_ids: ["file-1"]
    });
    const keyB = await flows.runs.deriveUploadIntentIdempotencyKey({
      flowId: "flow-1",
      file_ids: ["file-2"]
    });
    const keyC = await flows.runs.deriveUploadIntentIdempotencyKey({
      flowId: "flow-2",
      file_ids: ["file-1"]
    });

    expect(new Set([keyA, keyB, keyC]).size).toBe(3);
  });
});
