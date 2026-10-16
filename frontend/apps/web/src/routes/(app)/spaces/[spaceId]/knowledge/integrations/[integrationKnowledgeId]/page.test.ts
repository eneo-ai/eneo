import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { load } from "./+page";

const spaceId = "00000000-0000-4000-8000-000000000020";

function item(id: string) {
  return { id, name: id, space_id: spaceId };
}

function createLoadEvent(loadedItems: object[], freshItems: object[]) {
  const listKnowledge = vi
    .fn()
    .mockResolvedValue({ integration_knowledge_list: { items: freshItems } });
  const listDocuments = vi.fn().mockResolvedValue({ items: [], total_count: 0 });
  const listSkippedDocuments = vi.fn().mockResolvedValue(null);
  const event = {
    params: { integrationKnowledgeId: "ik-new" },
    url: new URL(`http://localhost:3000/spaces/${spaceId}/knowledge/integrations/ik-new`),
    parent: vi.fn().mockResolvedValue({
      currentSpace: {
        id: spaceId,
        knowledge: { integration_knowledge_list: { items: loadedItems } }
      },
      eneo: {
        spaces: { listKnowledge },
        integrations: { knowledge: { listDocuments, listSkippedDocuments } }
      }
    })
  } as unknown as Parameters<typeof load>[0];
  return { event, listKnowledge, listDocuments };
}

describe("integration documents page load", () => {
  it("re-reads the space's knowledge for an item the cached layout space lacks", async () => {
    const { event, listKnowledge, listDocuments } = createLoadEvent(
      [item("ik-old")],
      [item("ik-old"), item("ik-new")]
    );

    const result = await load(event);

    expect(listKnowledge).toHaveBeenCalledWith(expect.objectContaining({ id: spaceId }));
    expect(result.knowledge).toMatchObject({ id: "ik-new" });
    expect(listDocuments).toHaveBeenCalledWith(
      expect.objectContaining({ knowledge: expect.objectContaining({ id: "ik-new" }) })
    );
  });

  it("renders the page with an empty list and the error when the documents cannot be listed", async () => {
    const { event, listDocuments } = createLoadEvent([item("ik-new")], []);
    listDocuments.mockRejectedValue(new Error("boom"));

    const result = await load(event);

    expect(result.knowledge).toMatchObject({ id: "ik-new" });
    expect(result.documents).toMatchObject({ items: [], total_count: 0 });
    expect(result.documentsError).toBe(m.request_failed());
  });

  it("answers 404 only after the fresh lookup also lacks the item", async () => {
    const { event, listKnowledge, listDocuments } = createLoadEvent([item("ik-old")], []);

    await expect(load(event)).rejects.toMatchObject({ status: 404 });

    expect(listKnowledge).toHaveBeenCalledOnce();
    expect(listDocuments).not.toHaveBeenCalled();
  });
});
