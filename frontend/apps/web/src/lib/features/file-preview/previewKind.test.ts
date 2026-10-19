import { describe, expect, it } from "vitest";
import { previewKindOf } from "./previewKind";

describe("previewKindOf", () => {
  it("lets the extension decide over a loose mimetype", () => {
    expect(previewKindOf({ name: "Anteckningar.MD", mimetype: "text/plain" })).toBe("markdown");
    expect(previewKindOf({ name: "export.csv", mimetype: "application/octet-stream" })).toBe("csv");
  });

  it("falls back to the mimetype when the name says nothing", () => {
    expect(previewKindOf({ name: "rapport", mimetype: "application/pdf" })).toBe("pdf");
    expect(previewKindOf({ name: "data.bin", mimetype: "text/csv; charset=utf-8" })).toBe("csv");
  });

  it("has no renderer for other files", () => {
    expect(previewKindOf({ name: "bild.png", mimetype: "image/png" })).toBeNull();
    expect(previewKindOf({ name: "bildspel.pptx", mimetype: "application/zip" })).toBeNull();
  });
});
