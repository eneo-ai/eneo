import { describe, expect, it, vi } from "vitest";
import { load } from "./+page";

const items = [
  { id: "ik-wrapped", space_id: "s1", integration_type: "sharepoint", wrapper_id: "w1" },
  { id: "ik-alone", space_id: "s1", integration_type: "sharepoint", wrapper_id: null },
  { id: "ik-other-space", space_id: "s2", integration_type: "sharepoint", wrapper_id: null }
];

type Items = typeof items;

function eventFor(itemId: string, search = "", loaded: Items = items, fresh: Items = items) {
  const listKnowledge = vi.fn().mockResolvedValue({ integration_knowledge_list: { items: fresh } });
  const event = {
    params: { spaceId: "personal", integrationKnowledgeId: itemId },
    url: new URL(`http://localhost/spaces/personal/knowledge/integrations/${itemId}${search}`),
    parent: vi.fn().mockResolvedValue({
      currentSpace: { id: "s1", knowledge: { integration_knowledge_list: { items: loaded } } },
      eneo: { spaces: { listKnowledge } }
    })
  } as unknown as Parameters<typeof load>[0];
  return { event, listKnowledge };
}

async function outcome(itemId: string, search = "", loaded: Items = items, fresh: Items = items) {
  const { event } = eventFor(itemId, search, loaded, fresh);
  try {
    return { data: await load(event) };
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
    ],
    [
      "?tab=activity",
      "/spaces/personal/knowledge/integrations/wrapper/w1?folder=ik-wrapped&tab=activity"
    ],
    [
      "?tab=content",
      "/spaces/personal/knowledge/integrations/wrapper/w1?folder=ik-wrapped&tab=content"
    ],
    ["?tab=unknown", "/spaces/personal/knowledge/integrations/wrapper/w1?folder=ik-wrapped"]
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
    expect(await outcome("ik-alone")).toEqual({
      data: { knowledge: expect.objectContaining({ id: "ik-alone" }) }
    });
  });

  it("re-reads the space's knowledge for an item the cached layout space lacks", async () => {
    const loaded = items.filter((item) => item.id !== "ik-alone");
    const { event, listKnowledge } = eventFor("ik-alone", "", loaded, items);

    const result = await load(event);

    expect(listKnowledge).toHaveBeenCalledWith(expect.objectContaining({ id: "s1" }));
    expect(result.knowledge).toMatchObject({ id: "ik-alone" });
  });

  it("answers 404 only after the fresh lookup also lacks the item", async () => {
    const { event, listKnowledge } = eventFor("ik-missing", "", items, items);

    await expect(load(event)).rejects.toMatchObject({ status: 404 });

    expect(listKnowledge).toHaveBeenCalledOnce();
  });

  it("is not found for an item of another space", async () => {
    expect(await outcome("ik-other-space")).toEqual({
      thrown: expect.objectContaining({ status: 404 })
    });
  });
});
