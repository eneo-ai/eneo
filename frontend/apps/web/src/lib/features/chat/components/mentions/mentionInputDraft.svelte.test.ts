import { get } from "svelte/store";
import { describe, expect, it } from "vitest";
import { createMentionInput } from "./MentionInput";

// The composer clears itself on send and puts the draft back if the send
// fails before streaming. That round-trip must keep the mention chips and the
// mention list the tools payload is built from, not just the plain text.
describe("MentionInput draft snapshot", () => {
  function setup() {
    const node = document.createElement("div");
    node.contentEditable = "true";
    document.body.appendChild(node);
    const input = createMentionInput({ triggerCharacter: "@", tools: () => ({ assistants: [] }) });
    input.elements.input(node);
    return { node, input };
  }

  const bob = { id: "assistant-bob", handle: "bob", head: "", match: "bob", tail: "" };

  it("restores markup, mentions and question after a reset", async () => {
    const { node, input } = setup();
    // No selection in the editor, so only the mention list is updated; the
    // chip markup is written directly as the editor would have rendered it.
    input.insertMentionNode(bob);
    node.innerHTML = 'Ask <span class="mention">@bob</span> about lunch';
    await new Promise((r) => setTimeout(r, 0));
    expect(get(input.states.question)).toBe("Ask [[@bob]] about lunch");

    const snapshot = input.snapshotMentionInput();
    input.resetMentionInput();
    expect(input.isMentionInputEmpty()).toBe(true);
    expect(get(input.states.mentions)).toEqual([]);

    input.restoreMentionInput(snapshot);
    await new Promise((r) => setTimeout(r, 0));
    expect(node.querySelector(".mention")?.textContent).toBe("@bob");
    expect(get(input.states.mentions)).toEqual([bob]);
    expect(get(input.states.question)).toBe("Ask [[@bob]] about lunch");
    node.remove();
  });

  it("reports the editor as non-empty once a new draft has been typed", async () => {
    const { node, input } = setup();
    node.textContent = "new draft";
    await new Promise((r) => setTimeout(r, 0));
    expect(input.isMentionInputEmpty()).toBe(false);
    node.remove();
  });
});
