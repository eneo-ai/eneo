import { describe, expect, it } from "vitest";
import {
  activateBinding,
  appBindingPayload,
  appendBinding,
  bindingsFromSummaries,
  moveBinding,
  removeBinding,
  reviseBinding
} from "./skill-bindings";
import type { SkillCandidate } from "./skill-binding-catalog";

const local = { id: "skill", current_revision_id: "r2", source: "space" } as SkillCandidate;

describe("Skill binding draft", () => {
  it("keeps the saved version, order, and activation mode when loading", () => {
    const bindings = bindingsFromSummaries([
      { skill_id: "second", skill_revision_id: "r1", position: 2, activation_mode: "on_demand" },
      { skill_id: "first", skill_revision_id: "r0", position: 1, activation_mode: "always" }
    ] as Parameters<typeof bindingsFromSummaries>[0]);
    expect(bindings).toEqual([
      { skill_id: "first", skill_revision_id: "r0", activation_mode: "always" },
      { skill_id: "second", skill_revision_id: "r1", activation_mode: "on_demand" }
    ]);
  });

  it("adds exact versions once, then changes only the requested binding", () => {
    const added = appendBinding([], local, true);
    expect(appendBinding(added, local, true)).toBe(added);
    expect(reviseBinding(added, "skill", "r3")).toEqual([
      { skill_id: "skill", skill_revision_id: "r3", activation_mode: "always" }
    ]);
    expect(activateBinding(added, "skill", "on_demand")).toEqual([
      { skill_id: "skill", skill_revision_id: "r2", activation_mode: "on_demand" }
    ]);
    expect(appBindingPayload(added)).toEqual([{ skill_id: "skill", skill_revision_id: "r2" }]);
  });

  it("preserves ordering through move and removal", () => {
    const draft = [
      { skill_id: "a", skill_revision_id: "1" },
      { skill_id: "b", skill_revision_id: "2" }
    ];
    expect(moveBinding(draft, 0, -1)).toBe(draft);
    expect(moveBinding(draft, 1, -1).map((binding) => binding.skill_id)).toEqual(["b", "a"]);
    expect(removeBinding(draft, "a")).toEqual([{ skill_id: "b", skill_revision_id: "2" }]);
  });
});
