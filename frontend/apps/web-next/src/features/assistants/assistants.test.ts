import { describe, expect, it } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { spaceChatItems } from "./assistants";

const space = makeSpace({
  assistants: [
    { id: "a1", type: "assistant", name: "Ärendehjälpen" },
    { id: "a2", type: "assistant", name: "Budget" }
  ],
  groupChats: [{ id: "g1", type: "group-chat", name: "Avtalsgruppen" }]
});

describe("spaceChatItems", () => {
  it("merges assistants and group chats, sorted with the collator it is given", () => {
    const english = spaceChatItems(space, new Intl.Collator("en").compare);
    expect(english.map((item) => item.name)).toEqual(["Ärendehjälpen", "Avtalsgruppen", "Budget"]);
  });

  it("sorts in Swedish without one, the same on server and client", () => {
    expect(spaceChatItems(space).map((item) => item.name)).toEqual([
      "Avtalsgruppen",
      "Budget",
      "Ärendehjälpen"
    ]);
  });
});
