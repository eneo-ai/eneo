import { describe, expect, it } from "vitest";
import { chatPartnerSwitcherItems } from "./partner-switcher";

describe("chatPartnerSwitcherItems", () => {
  it("includes personal assistant first and marks the active partner", () => {
    const items = chatPartnerSwitcherItems({
      routeId: "personal",
      activeType: "assistant",
      activeId: "assistant-1",
      space: {
        default_assistant: { id: "default-1", name: "Personal", icon_id: null },
        applications: {
          assistants: {
            items: [{ id: "assistant-1", name: "Build", type: "assistant", icon_id: "icon-1" }]
          },
          group_chats: {
            items: [{ id: "group-1", name: "Team", type: "group-chat", icon_id: null }]
          }
        }
      } as never
    });

    expect(items.map((item) => [item.type, item.name, item.active])).toEqual([
      ["default-assistant", "Personal", false],
      ["assistant", "Build", true],
      ["group-chat", "Team", false]
    ]);
    expect(items[1]?.href).toBe("/spaces/personal/chat?type=assistant&id=assistant-1");
  });
});
