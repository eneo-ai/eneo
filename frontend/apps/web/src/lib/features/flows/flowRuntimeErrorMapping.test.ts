import { describe, expect, it } from "vitest";
import { IntricError } from "@intric/intric-js";

import {
  getFlowRuntimeErrorMessage,
  classifyUploadError,
  getUploadErrorHint,
  friendlyMimeNames
} from "./flowRuntimeErrorMapping";

describe("flowRuntimeErrorMapping", () => {
  it("maps template access code to Swedish text", () => {
    const error = new IntricError(
      "forbidden",
      "RESPONSE",
      403,
      0,
      { code: "flow_template_not_accessible" },
      { endpoint: "POST@test" }
    );

    expect(getFlowRuntimeErrorMessage(error, "fallback")).toBe(
      "Mallen är inte tillgänglig för dig i detta flow eller space."
    );
  });

  it("maps rerun unsupported code", () => {
    const error = new IntricError(
      "rerun unsupported",
      "RESPONSE",
      400,
      0,
      { code: "flow_run_rerun_step_inputs_unsupported" },
      { endpoint: "POST@test" }
    );

    expect(getFlowRuntimeErrorMessage(error, "fallback")).toBe(
      "Denna körning kan inte köras om med stegindata. Starta en ny körning i stället."
    );
  });
});

describe("classifyUploadError", () => {
  it("detects timeout errors", () => {
    expect(classifyUploadError("Upload timed out after 120s")).toBe("timeout");
    expect(classifyUploadError("Request timeout")).toBe("timeout");
  });

  it("detects file size errors", () => {
    expect(classifyUploadError("File too large")).toBe("file_too_large");
    expect(classifyUploadError("Max filstorlek: 195 MB")).toBe("file_too_large");
  });

  it("detects network errors", () => {
    expect(classifyUploadError("Network error")).toBe("network");
    expect(classifyUploadError("Failed to fetch")).toBe("network");
  });

  it("returns unknown for unrecognised errors", () => {
    expect(classifyUploadError("Something went wrong")).toBe("unknown");
  });
});

describe("getUploadErrorHint", () => {
  it("returns a hint for timeout", () => {
    expect(getUploadErrorHint("timeout")).toContain("Försök igen");
  });

  it("returns empty string for unknown", () => {
    expect(getUploadErrorHint("unknown")).toBe("");
  });
});

describe("friendlyMimeNames", () => {
  it("maps known MIME types to friendly names", () => {
    expect(friendlyMimeNames(["application/pdf", "text/csv"])).toEqual(["PDF", "CSV"]);
  });

  it("passes through unknown MIME types", () => {
    expect(friendlyMimeNames(["application/x-custom"])).toEqual(["application/x-custom"]);
  });
});
