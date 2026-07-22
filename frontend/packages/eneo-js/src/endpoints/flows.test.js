import { describe, expect, it, vi } from "vitest";

import { createClient } from "../client/client";
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
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/{id}/template-files/");
    expect(fetch.mock.calls[0][1].method).toBe("post");
    expect(fetch.mock.calls[0][1].params).toEqual({ path: { id: "flow-1" } });
    expect(fetch.mock.calls[0][1].requestBody["multipart/form-data"]).toBeInstanceOf(FormData);
  });

  it("lists template assets from flow template route", async () => {
    const fetch = vi.fn(async () => ({ items: [] }));
    const flows = initFlows({ fetch });

    await flows.templates.list({ id: "flow-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/{id}/template-files/");
    expect(fetch.mock.calls[0][1].method).toBe("get");
    expect(fetch.mock.calls[0][1].params).toEqual({ path: { id: "flow-1" } });
  });

  it("deletes template assets through the flow template route", async () => {
    const fetch = vi.fn(async () => undefined);
    const flows = initFlows({ fetch });

    await flows.templates.delete({ id: "flow-1", fileId: "template-asset-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/{id}/template-files/{file_id}/");
    expect(fetch.mock.calls[0][1].method).toBe("delete");
    expect(fetch.mock.calls[0][1].params).toEqual({
      path: { id: "flow-1", file_id: "template-asset-1" }
    });
  });

  it("loads run contract from canonical runtime route", async () => {
    const fetch = vi.fn(async () => ({ published_flow_version: 7, steps_requiring_input: [] }));
    const flows = initFlows({ fetch });

    await flows.runContract.get({ id: "flow-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/{id}/run-contract/");
    expect(fetch.mock.calls[0][1].method).toBe("get");
    expect(fetch.mock.calls[0][1].params).toEqual({ path: { id: "flow-1" } });
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
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/{id}/published/");
    expect(fetch.mock.calls[0][1].method).toBe("get");
    expect(fetch.mock.calls[0][1].params).toEqual({ path: { id: "flow-1" } });
  });

  it("loads the published runtime projection from a string id", async () => {
    const fetch = vi.fn(async () => ({
      id: "flow-1",
      published_version: 7,
      runtime_paths: {}
    }));
    const flows = initFlows({ fetch });

    await flows.published.get("flow-1");

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/{id}/published/");
    expect(fetch.mock.calls[0][1].method).toBe("get");
    expect(fetch.mock.calls[0][1].params).toEqual({ path: { id: "flow-1" } });
  });

  it("loads canonical run status capabilities for client lifecycle logic", async () => {
    const fetch = vi.fn(async () => ({
      statuses: [],
      filter_order: []
    }));
    const flows = initFlows({ fetch });

    await flows.runs.statusCapabilities.get();

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/runs/status-capabilities/");
    expect(fetch.mock.calls[0][1].method).toBe("get");
  });

  it("lists runs with repeated status filters in caller order", async () => {
    const fetch = vi.fn(
      async () => new Response(JSON.stringify({ items: [], count: 0, has_more: false }))
    );
    const flows = initFlows(createClient({ baseUrl: "https://api.example.test", fetch }));
    /** @type {NonNullable<NonNullable<import("../types/schema").operations["list_flow_runs"]["parameters"]["query"]>["status"]>} */
    const status = ["completed", "queued", "completed"];

    await flows.runs.list({ flowId: "flow-1", limit: 25, offset: 5, status });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe(
      "https://api.example.test/api/v1/flows/flow-1/runs/?limit=25&offset=5&status=completed&status=queued&status=completed"
    );
    expect(status).toEqual(["completed", "queued", "completed"]);
  });

  it("validates portable flow packages through multipart upload", async () => {
    const fetch = vi.fn(async () => ({ package_id: "se.demo.report" }));
    const flows = initFlows({ fetch });
    const file = new File(["pkg"], "report.eneopkg", {
      type: "application/vnd.eneo.package+zip"
    });

    await flows.packages.validate({ file });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flow-packages/validate/");
    expect(fetch.mock.calls[0][1].method).toBe("post");
    const formData = fetch.mock.calls[0][1].requestBody["multipart/form-data"];
    expect(formData).toBeInstanceOf(FormData);
    expectFlowPackageFile(formData.get("package_file"), {
      name: "report.eneopkg",
      type: "application/vnd.eneo.package+zip",
      size: 3
    });
  });

  it("creates package import plans for a target space", async () => {
    const fetch = vi.fn(async () => ({ package_id: "se.demo.report" }));
    const flows = initFlows({ fetch });
    const file = new File(["pkg"], "report.eneopkg");

    await flows.packages.createImportPlan({ spaceId: "space-1", file });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/spaces/{id}/flow-packages/import-plan/");
    expect(fetch.mock.calls[0][1]).toMatchObject({
      method: "post",
      params: { path: { id: "space-1" } }
    });
    expectFlowPackageFile(
      fetch.mock.calls[0][1].requestBody["multipart/form-data"].get("package_file"),
      {
        name: "report.eneopkg",
        type: "",
        size: 3
      }
    );
  });

  it("imports packages as drafts with selected resource bindings", async () => {
    const fetch = vi.fn(async () => ({ flow_id: "flow-1" }));
    const flows = initFlows({ fetch });
    const selectedBindings = [
      {
        slot_ref: { kind: "model", slot: "structured", label: "Structured model" },
        local_kind: "completion_model",
        local_id: "model-1"
      }
    ];

    await flows.packages.importDraft({
      spaceId: "space-1",
      packageBase64: "UEsDBAo=",
      expectedContentChecksum: "0".repeat(64),
      expectedTargetState: {
        audio_transcription_required: false,
        default_transcription_model_id: null
      },
      selectedBindings
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/spaces/{id}/flow-packages/imports/");
    expect(fetch.mock.calls[0][1]).toEqual({
      method: "post",
      params: { path: { id: "space-1" } },
      requestBody: {
        "application/json": {
          package_base64: "UEsDBAo=",
          expected_content_checksum: "0".repeat(64),
          expected_target_state: {
            audio_transcription_required: false,
            default_transcription_model_id: null
          },
          selected_bindings: selectedBindings
        }
      }
    });
  });

  it("exports packages through binary fetch", async () => {
    const fetch = vi.fn();
    const binaryFetch = vi.fn(async () => ({
      blob: new Blob(["pkg"]),
      contentType: "application/octet-stream",
      filename: "report.eneopkg",
      headers: new Headers({
        "Eneo-Package-Omitted-Mcp-Assistant-Count": "2"
      })
    }));
    const flows = initFlows({ fetch, binaryFetch });

    const response = await flows.packages.export({
      id: "flow-1",
      packageId: "se.demo.report",
      packageVersion: "1.0.0",
      name: "Report",
      description: "Reusable report flow"
    });

    expect(fetch).not.toHaveBeenCalled();
    expect(binaryFetch).toHaveBeenCalledTimes(1);
    expect(binaryFetch.mock.calls[0][0]).toBe("/api/v1/flows/{id}/package-exports/");
    expect(binaryFetch.mock.calls[0][1]).toEqual({
      method: "post",
      params: { path: { id: "flow-1" } },
      requestBody: {
        "application/json": {
          package_id: "se.demo.report",
          package_version: "1.0.0",
          name: "Report",
          description: "Reusable report flow"
        }
      },
      signal: undefined
    });
    expect(response.omissions).toEqual([{ kind: "mcp_attachment", count: 2 }]);
  });

  it("returns no package omissions when the binary response omits the header", async () => {
    const binaryFetch = vi.fn(async () => ({
      blob: new Blob(["pkg"]),
      contentType: "application/octet-stream",
      filename: "report.eneopkg",
      headers: new Headers()
    }));
    const flows = initFlows({ fetch: vi.fn(), binaryFetch });

    const response = await flows.packages.export({
      id: "flow-1",
      packageId: "se.demo.report",
      packageVersion: "1.0.0",
      name: "Report"
    });

    expect(binaryFetch).toHaveBeenCalledTimes(1);
    expect(response.omissions).toEqual([]);
  });

  it("rejects an invalid package omission header after one binary request", async () => {
    const binaryFetch = vi.fn(async () => ({
      blob: new Blob(["pkg"]),
      contentType: "application/octet-stream",
      filename: "report.eneopkg",
      headers: new Headers({
        "Eneo-Package-Omitted-Mcp-Assistant-Count": "0"
      })
    }));
    const flows = initFlows({ fetch: vi.fn(), binaryFetch });

    await expect(
      flows.packages.export({
        id: "flow-1",
        packageId: "se.demo.report",
        packageVersion: "1.0.0",
        name: "Report"
      })
    ).rejects.toThrow("invalid MCP omission count");
    expect(binaryFetch).toHaveBeenCalledTimes(1);
  });

  it("generates template signed url from flow route", async () => {
    const fetch = vi.fn(async () => ({ url: "https://example.com" }));
    const flows = initFlows({ fetch });

    await flows.templates.signedUrl({ id: "flow-1", fileId: "file-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/{id}/template-files/{file_id}/signed-url/");
    expect(fetch.mock.calls[0][1].method).toBe("post");
    expect(fetch.mock.calls[0][1].params).toEqual({
      path: { id: "flow-1", file_id: "file-1" }
    });
  });

  it("uploads runtime files to step-scoped route", async () => {
    const fetch = vi.fn(async () => ({ id: "runtime-file-1" }));
    const flows = initFlows({ fetch });
    const file = new File(["doc"], "source.txt", { type: "text/plain" });

    await flows.steps.runtimeFiles.upload({ id: "flow-1", stepId: "step-1", file });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/{id}/steps/{step_id}/runtime-files/");
    expect(fetch.mock.calls[0][1].method).toBe("post");
    expect(fetch.mock.calls[0][1].params).toEqual({
      path: { id: "flow-1", step_id: "step-1" }
    });
  });

  it("tracks runtime upload progress through the XHR client when requested", async () => {
    const fetch = vi.fn();
    const xhr = vi.fn(async () => ({ id: "runtime-file-1" }));
    const flows = initFlows({ fetch, xhr });
    const file = new File(["doc"], "source.txt", { type: "text/plain" });
    const onProgress = vi.fn();
    const abortController = new AbortController();

    await flows.steps.runtimeFiles.upload({
      id: "flow-1",
      stepId: "step-1",
      file,
      onProgress,
      abortController
    });

    expect(fetch).not.toHaveBeenCalled();
    expect(xhr).toHaveBeenCalledTimes(1);
    expect(xhr.mock.calls[0][0]).toBe("/api/v1/flows/{id}/steps/{step_id}/runtime-files/");
    expect(xhr.mock.calls[0][1].method).toBe("post");
    expect(xhr.mock.calls[0][1].params).toEqual({
      path: { id: "flow-1", step_id: "step-1" }
    });
    expect(xhr.mock.calls[0][2]).toEqual({ onProgress });
    expect(xhr.mock.calls[0][3]).toBe(abortController);
  });

  it("deletes orphan runtime files through the flow-scoped route", async () => {
    const fetch = vi.fn(async () => undefined);
    const flows = initFlows({ fetch });

    await flows.steps.runtimeFiles.delete({ id: "flow-1", fileId: "file-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/{id}/runtime-files/{file_id}/");
    expect(fetch.mock.calls[0][1].method).toBe("delete");
    expect(fetch.mock.calls[0][1].params).toEqual({
      path: { id: "flow-1", file_id: "file-1" }
    });
  });

  it("generates artifact signed url from flow run route", async () => {
    const fetch = vi.fn(async () => ({ url: "https://example.com/download", expires_at: 9999 }));
    const flows = initFlows({ fetch });

    await flows.runs.artifactSignedUrl({ flowId: "flow-1", runId: "run-1", fileId: "file-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe(
      "/api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/"
    );
    expect(fetch.mock.calls[0][1].method).toBe("post");
    expect(fetch.mock.calls[0][1].params).toEqual({
      path: { id: "flow-1", run_id: "run-1", file_id: "file-1" }
    });
  });

  it("exports evidence from the canonical flow run route", async () => {
    const fetch = vi.fn(async () => ({
      schema_version: "flow-evidence-export.v9",
      content_hash: "abc123"
    }));
    const flows = initFlows({ fetch });

    await flows.runs.exportEvidence({ id: "run-1", flowId: "flow-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/{id}/runs/{run_id}/evidence/export");
    expect(fetch.mock.calls[0][1]).toMatchObject({
      method: "get",
      params: { path: { id: "flow-1", run_id: "run-1" }, query: { format: "json" } }
    });
  });

  it("serializes evidence export detail and reason options", async () => {
    const fetch = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ schema_version: "flow-evidence-export.v9", content_hash: "abc123" })
        )
    );
    const flows = initFlows(createClient({ baseUrl: "https://api.example.test", fetch }));

    await flows.runs.exportEvidence({
      id: "run-1",
      flowId: "flow-1",
      detail: "raw",
      reason: "incident review"
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe(
      "https://api.example.test/api/v1/flows/flow-1/runs/run-1/evidence/export?format=json&detail=raw&reason=incident+review"
    );
  });

  it("reruns a step with the generated operation body", async () => {
    const fetch = vi.fn(
      async () =>
        new Response(JSON.stringify({ status: "queued", rerun_step_id: "step-1" }), {
          status: 202
        })
    );
    const flows = initFlows(createClient({ baseUrl: "https://api.example.test", fetch }));

    await flows.runs.rerunStep({
      flowId: "flow-1",
      runId: "run-1",
      stepId: "step-1",
      expected_run_revision: 7,
      reason: "Reviewer accepted the corrected source.",
      input_payload_json: { reviewer_note: "Use the corrected source." },
      step_inputs: { "step-1": { file_ids: ["file-2", "file-1"] } }
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe(
      "https://api.example.test/api/v1/flows/flow-1/runs/run-1/steps/step-1/rerun/"
    );
    expect(fetch.mock.calls[0][1]).toMatchObject({
      method: "POST",
      headers: { "Content-Type": "application/json" }
    });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      expected_run_revision: 7,
      reason: "Reviewer accepted the corrected source.",
      input_payload_json: { reviewer_note: "Use the corrected source." },
      step_inputs: { "step-1": { file_ids: ["file-2", "file-1"] } }
    });
  });

  it("serializes existing create and review-resume idempotency headers", async () => {
    let requestCount = 0;
    const fetch = vi.fn(async () => {
      requestCount += 1;
      return new Response(JSON.stringify({ id: requestCount === 1 ? "run-1" : "checkpoint-1" }), {
        status: requestCount === 1 ? 201 : 202
      });
    });
    const flows = initFlows(createClient({ baseUrl: "https://api.example.test", fetch }));

    await flows.runs.create({
      flow: { id: "flow-1" },
      expected_flow_version: 7,
      idempotencyKey: "flow-run:client-request-1",
      input_payload_json: { case_id: "CASE-1" }
    });
    await flows.runs.reviewCheckpoints.resume({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      expectedCheckpointRevision: 3,
      idempotencyKey: "flow-review-resume:checkpoint-1:3"
    });

    expect(fetch.mock.calls.map((call) => call[0])).toEqual([
      "https://api.example.test/api/v1/flows/flow-1/runs/",
      "https://api.example.test/api/v1/flows/flow-1/runs/run-1/review-checkpoints/checkpoint-1/resume/"
    ]);
    expect(fetch.mock.calls[0][1].headers).toMatchObject({
      "Content-Type": "application/json",
      "Idempotency-Key": "flow-run:client-request-1"
    });
    expect(fetch.mock.calls[1][1].headers).toMatchObject({
      "Content-Type": "application/json",
      "Idempotency-Key": "flow-review-resume:checkpoint-1:3"
    });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      expected_flow_version: 7,
      input_payload_json: { case_id: "CASE-1" }
    });
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
      expected_checkpoint_revision: 3
    });
  });

  it("supports the minimal create/poll/read runtime consumer sequence", async () => {
    const fetch = vi.fn(async () => ({ id: "run-1", flow_id: "flow-1" }));
    const flows = initFlows({ fetch });

    await flows.runContract.get({ id: "flow-1" });
    const createdRun = await flows.runs.create({
      flow: { id: "flow-1" },
      expected_flow_version: 7,
      idempotencyKey: "flow-run:test-key",
      input_payload_json: { text: "test" },
      step_inputs: {
        "step-1": { file_ids: ["file-1"] }
      }
    });
    await flows.runs.get(createdRun);
    await flows.runs.steps({ flowId: createdRun.flow_id, runId: createdRun.id });
    await flows.runs.evidence(createdRun);
    await flows.runs.exportEvidence(createdRun);

    expect(fetch.mock.calls).toEqual([
      ["/api/v1/flows/{id}/run-contract/", { method: "get", params: { path: { id: "flow-1" } } }],
      [
        "/api/v1/flows/{id}/runs/",
        {
          method: "post",
          params: {
            path: { id: "flow-1" },
            header: { "Idempotency-Key": "flow-run:test-key" }
          },
          requestBody: {
            "application/json": {
              expected_flow_version: 7,
              input_payload_json: { text: "test" },
              step_inputs: {
                "step-1": { file_ids: ["file-1"] }
              }
            }
          }
        }
      ],
      [
        "/api/v1/flows/{id}/runs/{run_id}/",
        { method: "get", params: { path: { id: "flow-1", run_id: "run-1" } } }
      ],
      [
        "/api/v1/flows/{id}/runs/{run_id}/steps/",
        { method: "get", params: { path: { id: "flow-1", run_id: "run-1" } } }
      ],
      [
        "/api/v1/flows/{id}/runs/{run_id}/evidence/",
        { method: "get", params: { path: { id: "flow-1", run_id: "run-1" } } }
      ],
      [
        "/api/v1/flows/{id}/runs/{run_id}/evidence/export",
        {
          method: "get",
          params: {
            path: { id: "flow-1", run_id: "run-1" },
            query: { format: "json", detail: undefined, reason: undefined }
          }
        }
      ]
    ]);
  });

  it("calls review checkpoint endpoints from flow-run routes", async () => {
    const fetch = vi.fn(async () => ({ id: "checkpoint-1" }));
    const flows = initFlows({ fetch });

    await flows.runs.reviewCheckpoints.active({ flowId: "flow-1", runId: "run-1" });
    await flows.runs.reviewCheckpoints.edit({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      expectedCheckpointRevision: 1,
      currentPayloadJson: { z: 2, a: 1 }
    });
    await flows.runs.reviewCheckpoints.approve({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      expectedCheckpointRevision: 2
    });
    await flows.runs.reviewCheckpoints.reject({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      expectedCheckpointRevision: 2,
      reason: "Rejected by reviewer."
    });
    await flows.runs.reviewCheckpoints.resume({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      expectedCheckpointRevision: 3,
      idempotencyKey: "flow-review-resume:checkpoint-1:3"
    });

    expect(fetch.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/",
      "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/",
      "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/",
      "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/",
      "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/"
    ]);
    expect(fetch.mock.calls[1][1]).toMatchObject({
      method: "patch",
      params: {
        path: { id: "flow-1", run_id: "run-1", checkpoint_id: "checkpoint-1" }
      },
      requestBody: {
        "application/json": {
          expected_checkpoint_revision: 1,
          current_payload_json: { a: 1, z: 2 }
        }
      }
    });
    expect(fetch.mock.calls[4][1]).toMatchObject({
      method: "post",
      params: {
        path: { id: "flow-1", run_id: "run-1", checkpoint_id: "checkpoint-1" },
        header: { "Idempotency-Key": "flow-review-resume:checkpoint-1:3" }
      },
      requestBody: {
        "application/json": {
          expected_checkpoint_revision: 3
        }
      }
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
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/flows/{id}/runs/");
    expect(fetch.mock.calls[0][1].params.path).toEqual({ id: "flow-1" });
    expect(fetch.mock.calls[0][1].requestBody["application/json"]).not.toHaveProperty("flow_id");
    expect(fetch.mock.calls[0][1].requestBody["application/json"]).toEqual({
      expected_flow_version: 7,
      input_payload_json: { text: "test" },
      step_inputs: {
        "step-1": { file_ids: ["file-1"] }
      }
    });
  });

  it("forwards step input file ids in caller order for API-side normalization", async () => {
    const fetch = vi.fn(async () => ({ id: "run-1" }));
    const flows = initFlows({ fetch });

    await flows.runs.create({
      flow: { id: "flow-1" },
      step_inputs: {
        "step-b": { file_ids: ["file-5", "file-4", "file-5"] },
        "step-a": { file_ids: ["file-9"] }
      }
    });

    expect(fetch.mock.calls[0][1].requestBody["application/json"]).toEqual({
      step_inputs: {
        "step-a": { file_ids: ["file-9"] },
        "step-b": { file_ids: ["file-5", "file-4", "file-5"] }
      }
    });
  });

  it("forwards flow run idempotency header when provided", async () => {
    const fetch = vi.fn(async () => ({ id: "run-1" }));
    const flows = initFlows({ fetch });

    await flows.runs.create({
      flow: { id: "flow-1" },
      idempotencyKey: "flow-run:test-key",
      step_inputs: {
        "step-1": { file_ids: ["file-1"] }
      }
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1].params).toEqual({
      path: { id: "flow-1" },
      header: { "Idempotency-Key": "flow-run:test-key" }
    });
  });

  it("derives a stable upload-intent idempotency key", async () => {
    const flows = initFlows({ fetch: vi.fn() });

    const keyA = await flows.runs.deriveUploadIntentIdempotencyKey({
      flowId: "flow-1",
      expectedFlowVersion: 7,
      input_payload_json: { b: 2, a: 1, nested: { y: 2, x: 1 } },
      step_inputs: {
        "step-b": { file_ids: ["file-2", "file-3"] },
        "step-a": { file_ids: ["file-1"] }
      }
    });
    const keyB = await flows.runs.deriveUploadIntentIdempotencyKey({
      flowId: "flow-1",
      expectedFlowVersion: 7,
      input_payload_json: { nested: { x: 1, y: 2 }, a: 1, b: 2 },
      step_inputs: {
        "step-a": { file_ids: ["file-1"] },
        "step-b": { file_ids: ["file-2", "file-3"] }
      }
    });

    expect(keyA).toBe(keyB);
    expect(keyA).toMatch(/^flow-run:[a-f0-9]{64}$/);
  });

  it("derives different upload-intent keys for different step file ordering", async () => {
    const flows = initFlows({ fetch: vi.fn() });

    const keyA = await flows.runs.deriveUploadIntentIdempotencyKey({
      flowId: "flow-1",
      step_inputs: { "step-1": { file_ids: ["file-1", "file-2"] } }
    });
    const keyB = await flows.runs.deriveUploadIntentIdempotencyKey({
      flowId: "flow-1",
      step_inputs: { "step-1": { file_ids: ["file-2", "file-1"] } }
    });

    expect(keyA).not.toBe(keyB);
  });

  it("derives different upload-intent idempotency keys when the run intent changes", async () => {
    const flows = initFlows({ fetch: vi.fn() });

    const keyA = await flows.runs.deriveUploadIntentIdempotencyKey({
      flowId: "flow-1",
      step_inputs: { "step-1": { file_ids: ["file-1"] } }
    });
    const keyB = await flows.runs.deriveUploadIntentIdempotencyKey({
      flowId: "flow-1",
      step_inputs: { "step-1": { file_ids: ["file-2"] } }
    });
    const keyC = await flows.runs.deriveUploadIntentIdempotencyKey({
      flowId: "flow-2",
      step_inputs: { "step-1": { file_ids: ["file-1"] } }
    });

    expect(new Set([keyA, keyB, keyC]).size).toBe(3);
  });

  it("rejects top-level file_ids before creating a flow run", async () => {
    const fetch = vi.fn(async () => ({ id: "run-1" }));
    const flows = initFlows({ fetch });

    await expect(
      flows.runs.create({
        flow: { id: "flow-1" },
        file_ids: ["file-1"]
      })
    ).rejects.toMatchObject({
      code: "flow_run_top_level_file_ids_not_supported",
      status: 400
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects top-level file_ids before deriving upload-intent idempotency keys", async () => {
    const flows = initFlows({ fetch: vi.fn() });

    await expect(
      flows.runs.deriveUploadIntentIdempotencyKey({
        flowId: "flow-1",
        file_ids: ["file-1"]
      })
    ).rejects.toMatchObject({
      code: "flow_run_top_level_file_ids_not_supported",
      status: 400
    });
  });

  it("rejects reserved orchestration keys inside input payloads before creating a flow run", async () => {
    const fetch = vi.fn(async () => ({ id: "run-1" }));
    const flows = initFlows({ fetch });

    await expect(
      flows.runs.create({
        flow: { id: "flow-1" },
        input_payload_json: {
          step_inputs: { "step-1": { file_ids: ["file-1"] } }
        }
      })
    ).rejects.toMatchObject({
      code: "flow_run_reserved_input_payload_key",
      status: 400,
      keys: ["step_inputs"]
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects backend-reserved transcription key before creating a flow run", async () => {
    const fetch = vi.fn(async () => ({ id: "run-1" }));
    const flows = initFlows({ fetch });

    await expect(
      flows.runs.create({
        flow: { id: "flow-1" },
        input_payload_json: { transkribering: "spoofed transcript" }
      })
    ).rejects.toMatchObject({
      code: "flow_run_reserved_input_payload_key",
      status: 400,
      keys: ["transkribering"]
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects reserved orchestration keys before deriving upload-intent idempotency keys", async () => {
    const flows = initFlows({ fetch: vi.fn() });

    await expect(
      flows.runs.deriveUploadIntentIdempotencyKey({
        flowId: "flow-1",
        input_payload_json: { file_ids: ["file-1"] }
      })
    ).rejects.toMatchObject({
      code: "flow_run_reserved_input_payload_key",
      status: 400,
      keys: ["file_ids"]
    });
  });

  it("rejects backend-reserved transcription key before deriving upload-intent idempotency keys", async () => {
    const flows = initFlows({ fetch: vi.fn() });

    await expect(
      flows.runs.deriveUploadIntentIdempotencyKey({
        flowId: "flow-1",
        input_payload_json: { transkribering: "spoofed transcript" }
      })
    ).rejects.toMatchObject({
      code: "flow_run_reserved_input_payload_key",
      status: 400,
      keys: ["transkribering"]
    });
  });
});

function expectFlowPackageFile(file, expected) {
  expect(file).toBeInstanceOf(File);
  expect(file.name).toBe(expected.name);
  expect(file.type).toBe(expected.type);
  expect(file.size).toBe(expected.size);
}
