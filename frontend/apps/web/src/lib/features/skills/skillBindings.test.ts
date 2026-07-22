import type {
  SkillBindingReferenceInput,
  SkillBindingSummary,
  SkillPublic,
  SkillSparse
} from "@eneo/eneo-js";
import { describe, expect, test } from "vitest";
import {
  appendSkillBinding,
  getAvailableSkills,
  getSkillBindingRows,
  mergeSkillCatalog,
  moveSkillBinding,
  removeSkillBinding,
  upgradeSkillBinding
} from "./skillBindings";

function makeSkill(id: string, revision = 1, isActive = true): SkillSparse {
  return {
    id,
    space_id: "space-1",
    slug: `skill-${id}`,
    is_active: isActive,
    current_revision_id: `${id}-revision-${revision}`,
    current_revision_number: revision,
    display_name: `Skill ${id}`,
    description: `Description ${id}`,
    content_digest: `digest-${id}-${revision}`,
    created_by_user_id: "user-1",
    created_at: "2026-07-15T12:00:00Z",
    updated_at: "2026-07-15T12:00:00Z"
  };
}

function makeSummary(skill: SkillSparse, revision: number): SkillBindingSummary {
  return {
    skill_id: skill.id,
    skill_revision_id: `${skill.id}-revision-${revision}`,
    slug: skill.slug,
    revision_number: revision,
    display_name: skill.display_name,
    description: skill.description,
    content_digest: `digest-${skill.id}-${revision}`,
    position: 0,
    is_active: skill.is_active,
    current_revision_id: skill.current_revision_id,
    current_revision_number: skill.current_revision_number
  };
}

function makePublicSkill(id: string): SkillPublic {
  const sparse = makeSkill(id);
  return {
    ...sparse,
    current_revision: {
      id: sparse.current_revision_id,
      skill_id: sparse.id,
      revision_number: sparse.current_revision_number,
      display_name: sparse.display_name,
      description: sparse.description,
      instructions: "Follow these instructions.",
      content_digest: sparse.content_digest,
      created_by_user_id: sparse.created_by_user_id,
      created_at: sparse.created_at
    }
  };
}

describe("Skill binding draft state", () => {
  test("excludes inactive and already-bound Skills from the add-existing choices", () => {
    const bound = makeSkill("bound");
    const available = makeSkill("available");
    const inactive = makeSkill("inactive", 1, false);
    const bindings = appendSkillBinding([], bound);

    expect(getAvailableSkills([bound, inactive, available], bindings)).toEqual([available]);
    expect(appendSkillBinding(bindings, bound)).toBe(bindings);
  });

  test("adds the exact current revision, reorders deterministically, and removes by identity", () => {
    const first = makeSkill("first", 2);
    const second = makeSkill("second", 4);
    const added = appendSkillBinding(appendSkillBinding([], first), second);

    expect(added).toEqual([
      { skill_id: first.id, skill_revision_id: first.current_revision_id },
      { skill_id: second.id, skill_revision_id: second.current_revision_id }
    ] satisfies SkillBindingReferenceInput[]);

    const reordered = moveSkillBinding(added, 0, "down");
    expect(reordered.map((binding) => binding.skill_id)).toEqual([second.id, first.id]);
    expect(moveSkillBinding(reordered, 0, "up")).toBe(reordered);
    expect(removeSkillBinding(reordered, second.id)).toEqual([
      { skill_id: first.id, skill_revision_id: first.current_revision_id }
    ]);
  });

  test("keeps the pinned summary when a newer immutable revision exists", () => {
    const current = makeSkill("versioned", 3);
    const pinnedSummary = makeSummary(current, 1);
    const pinnedReference = {
      skill_id: current.id,
      skill_revision_id: pinnedSummary.skill_revision_id
    };

    const [row] = getSkillBindingRows([pinnedReference], [pinnedSummary], [current]);

    expect(row.reference).toEqual(pinnedReference);
    expect(row.pinnedRevision).toBe(1);
    expect(row.hasNewerRevision).toBe(true);
    expect(row.currentRevisionNumber).toBe(3);
  });

  test("keeps upgrade metadata for a bound Skill outside the current catalog page", () => {
    const current = makeSkill("outside-page", 3);
    const pinnedSummary = makeSummary(current, 1);
    const pinnedReference = {
      skill_id: current.id,
      skill_revision_id: pinnedSummary.skill_revision_id
    };

    const [row] = getSkillBindingRows([pinnedReference], [pinnedSummary], []);

    expect(row.displayName).toBe(current.display_name);
    expect(row.currentRevisionId).toBe(current.current_revision_id);
    expect(row.currentRevisionNumber).toBe(3);
    expect(row.hasNewerRevision).toBe(true);
  });

  test("upgrades only the selected row to the latest active revision", () => {
    const current = makeSkill("versioned", 3);
    const other = makeSkill("other", 2);
    const bindings = [
      { skill_id: current.id, skill_revision_id: `${current.id}-revision-1` },
      { skill_id: other.id, skill_revision_id: other.current_revision_id }
    ];

    const upgraded = upgradeSkillBinding(bindings, 0, current);

    expect(upgraded).toEqual([
      { skill_id: current.id, skill_revision_id: current.current_revision_id },
      bindings[1]
    ]);
    expect(upgradeSkillBinding(upgraded, 0, current)).toBe(upgraded);
    expect(upgradeSkillBinding(bindings, 0, { ...current, is_active: false })).toBe(bindings);
  });

  test("adds a created Skill to the local catalog and binding draft", () => {
    const created = makePublicSkill("created");
    const catalog = mergeSkillCatalog([], [created]);
    const bindings = appendSkillBinding([], created);

    expect(catalog).toEqual([created]);
    expect(bindings).toEqual([
      { skill_id: created.id, skill_revision_id: created.current_revision_id }
    ]);
    expect(getAvailableSkills(catalog, bindings)).toEqual([]);
    expect(getAvailableSkills(catalog, removeSkillBinding(bindings, created.id))).toEqual([
      created
    ]);
  });
});
