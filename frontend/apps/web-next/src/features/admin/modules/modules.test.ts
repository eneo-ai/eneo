import { describe, expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import { initialServiceKeySelection, parseRedirectUris } from "./modules";

const installation: Schema<"ModuleInstallation"> = {
  module_id: "module-id",
  module_key: "reports",
  service_key_id: "old-key",
  configured: true,
  redirect_uris: ["https://reports.example/auth/callback"]
};

describe("module installation form", () => {
  it("trims and deduplicates callback URLs while preserving their order", () => {
    expect(
      parseRedirectUris(" https://a.test/cb \r\n\nhttps://b.test/cb\nhttps://a.test/cb ")
    ).toEqual(["https://a.test/cb", "https://b.test/cb"]);
  });

  it("requires a fresh choice when a previously bound service key is no longer eligible", () => {
    expect(initialServiceKeySelection(installation, [])).toEqual({ selection: "", missing: true });
    expect(
      initialServiceKeySelection(installation, [{ id: "old-key" } as Schema<"ApiKeyV2">])
    ).toEqual({ selection: "old-key", missing: false });
    expect(initialServiceKeySelection({ ...installation, service_key_id: null }, [])).toEqual({
      selection: "__unbound__",
      missing: false
    });
  });
});
