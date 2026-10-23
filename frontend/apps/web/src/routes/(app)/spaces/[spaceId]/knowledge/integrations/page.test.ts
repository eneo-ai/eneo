import { describe, expect, it } from "vitest";
import { load } from "./+page";

describe("integrations route", () => {
  it("sends the bare address to the knowledge page's integrations tab", () => {
    expect(() => load({ params: { spaceId: "personal" } })).toThrow(
      expect.objectContaining({
        status: 307,
        location: "/spaces/personal/knowledge?tab=integrations"
      })
    );
  });
});
