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
    expect(fetch.mock.calls[0][1].requestBody["application/json"]).toEqual({
      expected_flow_version: 7,
      input_payload_json: { text: "test" },
      step_inputs: {
        "step-1": { file_ids: ["file-1"] }
      }
    });
  });
});
