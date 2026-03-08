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
});
