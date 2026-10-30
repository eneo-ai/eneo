import { describe, expect, it } from "vitest";
import { releasableUploads } from "./editor-uploads";
import { makeAssistant, makeFlow, makeStep } from "./testing/fixtures";

describe("releasableUploads", () => {
  it("keeps every upload the saved flow or step assistant references", () => {
    const flow = makeFlow({
      steps: [
        makeStep({
          output_mode: "template_fill",
          output_type: "docx",
          output_config: { template_asset_id: "asset-kept" }
        })
      ]
    });
    const assistant = makeAssistant({
      attachments: [{ id: "file-kept", name: "a.txt", size: 1 }] as never
    });
    expect(
      releasableUploads(
        [
          { kind: "template", id: "asset-kept" },
          { kind: "template", id: "asset-dropped" },
          { kind: "file", id: "file-kept" },
          { kind: "file", id: "file-dropped" }
        ],
        { flows: [flow, undefined], assistant }
      )
    ).toEqual([
      { kind: "template", id: "asset-dropped" },
      { kind: "file", id: "file-dropped" }
    ]);
  });
});
