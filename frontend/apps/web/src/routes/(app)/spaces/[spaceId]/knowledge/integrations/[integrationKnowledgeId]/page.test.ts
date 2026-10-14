import { describe, expect, it, vi } from "vitest";
import { load } from "./+page";

function eventFor(itemId: string, search = "") {
  const items = [
    { id: "ik-wrapped", space_id: "s1", integration_type: "sharepoint", wrapper_id: "w1" },
    { id: "ik-alone", space_id: "s1", integration_type: "sharepoint", wrapper_id: null },
    { id: "ik-other-space", space_id: "s2", integration_type: "sharepoint", wrapper_id: null }
  ];
  return {
    params: { spaceId: "personal", integrationKnowledgeId: itemId },
    url: new URL(`http://localhost/spaces/personal/knowledge/integrations/${itemId}${search}`),
    parent: vi.fn().mockResolvedValue({
      currentSpace: { id: "s1", knowledge: { integration_knowledge_list: { items } } }
    })
  } as unknown as Parameters<typeof load>[0];
}

async function outcome(itemId: string, search = "") {
  try {
    return { data: await load(eventFor(itemId, search)) };
  } catch (thrown) {
    return { thrown };
  }
}

describe("integration item route", () => {
  it.each([
    ["", "/spaces/personal/knowledge/integrations/wrapper/w1?folder=ik-wrapped"],
    [
      "?tab=skipped",
      "/spaces/personal/knowledge/integrations/wrapper/w1?folder=ik-wrapped&tab=problems"
    ],
    [
      "?tab=problems",
      "/spaces/personal/knowledge/integrations/wrapper/w1?folder=ik-wrapped&tab=problems"
    ]
  ])(
    "sends a wrapped item %s to its wrapper with the folder selected",
    async (search, location) => {
      expect(await outcome("ik-wrapped", search)).toEqual({
        thrown: expect.objectContaining({ status: 307, location })
      });
    }
  );

  it("moves an old link to the skipped files onto the problems tab", async () => {
    expect(await outcome("ik-alone", "?tab=skipped")).toEqual({
      thrown: expect.objectContaining({
        status: 307,
        location: "/spaces/personal/knowledge/integrations/ik-alone?tab=problems"
      })
    });
  });

  it("shows an item imported on its own", async () => {
    expect(await outcome("ik-alone")).toEqual({ data: { knowledgeId: "ik-alone" } });
  });

  it.each(["ik-missing", "ik-other-space"])("is not found for %s", async (itemId) => {
    expect(await outcome(itemId)).toEqual({ thrown: expect.objectContaining({ status: 404 }) });
  });
});
