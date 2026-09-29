import { describe, expect, it, vi } from "vitest";
import { load } from "./+layout";

function createLoadEvent(url: string, personal: boolean) {
  const currentSpace = {
    id: "00000000-0000-4000-8000-000000000020",
    personal
  };
  const listForSpace = vi.fn().mockResolvedValue([]);

  return {
    event: {
      url: new URL(url),
      parent: vi.fn().mockResolvedValue({
        currentSpace,
        eneo: {
          integrations: {
            user: { listForSpace }
          }
        }
      })
    } as unknown as Parameters<typeof load>[0],
    listForSpace
  };
}

describe("knowledge integration availability", () => {
  it.each([
    [true, "user_oauth"],
    [false, "tenant_app"]
  ] as const)(
    "offers SharePoint fixture data without a configured provider (personal=%s)",
    async (personal, expectedAuthType) => {
      const { event, listForSpace } = createLoadEvent(
        "http://localhost:3000/spaces/example/knowledge?sharepoint_fixture=representative",
        personal
      );

      const result = await load(event);

      expect(listForSpace).toHaveBeenCalledOnce();
      expect(result.availableIntegrations).toEqual([
        expect.objectContaining({
          name: "SharePoint test data",
          integration_type: "sharepoint",
          connected: true,
          auth_type: expectedAuthType
        })
      ]);
    }
  );

  it("keeps the provider gate in the normal integration flow", async () => {
    const { event } = createLoadEvent("http://localhost:3000/spaces/example/knowledge", true);

    const result = await load(event);

    expect(result.availableIntegrations).toEqual([]);
  });
});
