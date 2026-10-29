import { describe, expect, it } from "vitest";
import { previewEmbedPath, readPreviewToken } from "./preview";

describe("preview token transport", () => {
  it("round-trips through the fragment", () => {
    const path = previewEmbedPath("wgt_abc", "tok/en+x", "en");
    expect(path).toBe("/en/embed/wgt_abc?preview=1#preview=tok%2Fen%2Bx");
    expect(readPreviewToken(new URL(`http://localhost${path}`).hash)).toBe("tok/en+x");
  });

  it("returns null without a token", () => {
    expect(readPreviewToken("")).toBeNull();
    expect(readPreviewToken("#preview=")).toBeNull();
    expect(readPreviewToken("#other=1")).toBeNull();
  });
});
