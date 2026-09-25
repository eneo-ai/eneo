import { describe, expect, it } from "vitest";
import type { AcceptedFormat } from "./AttachmentManager";
import { summarizeFileFormats } from "./fileFormatSummary";

const format = (mimetype: string, extensions: string[], maxSize = 1024): AcceptedFormat => ({
  mimetype,
  extensions,
  maxSize
});

describe("summarizeFileFormats", () => {
  it("groups formats by family in a fixed order and dedupes extensions", () => {
    const groups = summarizeFileFormats([
      format("audio/mpeg", [".mp3", ".mpga"], 50),
      format("text/plain", [".txt", ".text"]),
      format("application/pdf", [".pdf"]),
      format("text/csv", [".csv"]),
      format("application/csv", [".csv"]),
      format("video/webm", [".webm"], 50),
      format("audio/mp3", [".mp3"], 50),
      format("image/jpeg", [".jpeg", ".jpg"], 7)
    ]);

    expect(groups).toEqual([
      {
        kind: "documents",
        extensions: [".csv", ".pdf", ".text", ".txt"],
        maxSizeBytes: 1024
      },
      { kind: "images", extensions: [".jpeg", ".jpg"], maxSizeBytes: 7 },
      { kind: "audio", extensions: [".mp3", ".mpga", ".webm"], maxSizeBytes: 50 }
    ]);
  });

  it("normalizes extension spelling and skips empty ones", () => {
    const groups = summarizeFileFormats([format("text/markdown", ["MD", " .Markdown ", ""])]);
    expect(groups).toEqual([
      { kind: "documents", extensions: [".markdown", ".md"], maxSizeBytes: 1024 }
    ]);
  });

  it("reports no size when formats in a group have different limits", () => {
    const groups = summarizeFileFormats([
      format("text/plain", [".txt"], 10),
      format("application/pdf", [".pdf"], 20)
    ]);
    expect(groups[0].maxSizeBytes).toBeNull();
  });

  it("omits empty groups and falls back to other for unknown families", () => {
    const groups = summarizeFileFormats([format("model/gltf-binary", [".glb"])]);
    expect(groups).toEqual([{ kind: "other", extensions: [".glb"], maxSizeBytes: 1024 }]);
  });

  it("returns nothing for no formats", () => {
    expect(summarizeFileFormats([])).toEqual([]);
  });
});
