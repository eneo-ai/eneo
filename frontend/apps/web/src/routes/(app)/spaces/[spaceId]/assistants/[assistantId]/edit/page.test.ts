import type { ResourcePermission } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

const READ_SKILL_PERMISSION: ResourcePermission = "read";

describe("Assistant edit loader", () => {
  test("loads Skill bindings for a reader of a non-default Assistant", async () => {
    const bindings = [{ skill_id: "skill-1" }];
    const listAssistantBindings = vi.fn().mockResolvedValue(bindings);
    const event = {
      depends: vi.fn(),
      params: { assistantId: "assistant-1" },
      parent: vi.fn().mockResolvedValue({
        currentSpace: {
          id: "space-1",
          default_assistant: { id: "default-assistant" },
          skill_permissions: [READ_SKILL_PERMISSION]
        },
        eneo: {
          assistants: {
            get: vi.fn().mockResolvedValue({ id: "assistant-1" }),
            listMCPServers: vi.fn().mockResolvedValue({ items: [] })
          },
          helpAssistants: {
            runs: { availability: vi.fn().mockResolvedValue(null) }
          },
          skills: {
            list: vi.fn().mockResolvedValue([]),
            listAssistantBindings
          }
        }
      })
    };

    const result = await load(event as never);

    expect(listAssistantBindings).toHaveBeenCalledWith({
      spaceId: "space-1",
      assistantId: "assistant-1"
    });
    expect(result.skillBindings).toEqual(bindings);
  });
});
