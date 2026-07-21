import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

function makeEvent({
  partnerType = "assistant",
  skillPermissions = ["read"]
}: {
  partnerType?: "assistant" | "default-assistant";
  skillPermissions?: string[];
}) {
  const listAssistantBindings = vi.fn().mockResolvedValue([
    {
      skill_id: "skill-1",
      skill_revision_id: "revision-3",
      slug: "decision-support",
      revision_number: 3,
      display_name: "Decision support",
      description: "Structures decision material.",
      content_digest: "digest",
      position: 0,
      is_active: true
    }
  ]);
  const partner = {
    id: "assistant-1",
    type: partnerType,
    permissions: ["read"]
  };

  return {
    event: {
      url: new URL(
        `http://localhost/spaces/space-1/chat?type=${partnerType}${
          partnerType === "assistant" ? "&id=assistant-1" : ""
        }`
      ),
      parent: vi.fn().mockResolvedValue({
        currentSpace: {
          id: "space-1",
          personal: false,
          organization: false,
          default_assistant: partnerType === "default-assistant" ? partner : null,
          skill_permissions: skillPermissions
        },
        eneo: {
          assistants: { get: vi.fn().mockResolvedValue(partner) },
          conversations: {
            list: vi.fn().mockResolvedValue({
              items: [],
              total_count: 0,
              count: 0,
              next_cursor: null
            }),
            get: vi.fn()
          },
          skills: { listAssistantBindings }
        }
      })
    },
    listAssistantBindings
  };
}

describe("chat page loader", () => {
  test("loads the exact ordered Skill bindings shown in a regular Assistant chat", async () => {
    const { event, listAssistantBindings } = makeEvent({});

    const result = await load(event as never);

    if (!result) {
      throw new Error("Expected the chat page loader to return page data");
    }

    expect(listAssistantBindings).toHaveBeenCalledWith({
      spaceId: "space-1",
      assistantId: "assistant-1"
    });
    expect(result.skillBindings).toEqual([
      expect.objectContaining({
        skill_id: "skill-1",
        skill_revision_id: "revision-3",
        revision_number: 3,
        position: 0
      })
    ]);
  });

  test.each([
    { partnerType: "default-assistant" as const, skillPermissions: ["read"] },
    { partnerType: "assistant" as const, skillPermissions: [] }
  ])(
    "does not expose direct Skill bindings for $partnerType without a supported scope",
    async (setup) => {
      const { event, listAssistantBindings } = makeEvent(setup);

      const result = await load(event as never);

      if (!result) {
        throw new Error("Expected the chat page loader to return page data");
      }

      expect(result.skillBindings).toEqual([]);
      expect(listAssistantBindings).not.toHaveBeenCalled();
    }
  );

  test("keeps chat available when the optional Skill summary cannot be loaded", async () => {
    const { event, listAssistantBindings } = makeEvent({});
    listAssistantBindings.mockRejectedValueOnce(new Error("Skills service unavailable"));

    const result = await load(event as never);

    if (!result) {
      throw new Error("Expected the chat page loader to return page data");
    }

    expect(result.chatPartner).toEqual(expect.objectContaining({ id: "assistant-1" }));
    expect(result.skillBindings).toEqual([]);
  });
});
