import type {
  SkillBindingReferenceInput,
  SkillBindingSummary,
  SkillPublic,
  SkillSparse
} from "@eneo/eneo-js";
import { describe, expect, test } from "vitest";
import {
  appendSkillRevisionBinding,
  getAvailableSkills,
  getSkillCandidateRevisionNumber,
  getSkillBindingRows,
  mergeSkillCatalog,
  moveSkillBinding,
  removeSkillBinding,
  upgradeSkillBinding
} from "./skillBindings";
import type { SkillBindingCandidate } from "./skillBindings";

function makeSkill(id: string, revision = 1, isActive = true): SkillSparse & { source: "space" } {
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
    updated_at: "2026-07-15T12:00:00Z",
    source: "space"
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
    attachable_revision_id: skill.current_revision_id,
    attachable_revision_number: skill.current_revision_number,
    execution_blocked: false,
    source: "space"
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
    const bindings = appendSkillRevisionBinding([], {
      id: bound.id,
      revisionId: bound.current_revision_id
    });

    expect(getAvailableSkills([bound, inactive, available], bindings)).toEqual([available]);
    expect(
      appendSkillRevisionBinding(bindings, {
        id: bound.id,
        revisionId: bound.current_revision_id
      })
    ).toBe(bindings);
  });

  test("excludes blocked organisation Skills from new bindings", () => {
    const blocked: SkillBindingCandidate = {
      id: "blocked",
      slug: "blocked",
      revision_id: "blocked-revision-1",
      revision_number: 1,
      display_name: "Blocked Skill",
      description: "Unavailable during an incident.",
      content_digest: "digest-blocked-1",
      first_published_at: "2026-07-20T12:00:00Z",
      execution_blocked: true,
      source: "organization"
    };

    expect(getAvailableSkills([blocked], [])).toEqual([]);
  });

  test("adds the exact current revision, reorders deterministically, and removes by identity", () => {
    const first = makeSkill("first", 2);
    const second = makeSkill("second", 4);
    const added = appendSkillRevisionBinding(
      appendSkillRevisionBinding([], { id: first.id, revisionId: first.current_revision_id }),
      { id: second.id, revisionId: second.current_revision_id }
    );

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
    expect(row.attachableRevisionNumber).toBe(3);
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
    expect(row.attachableRevisionId).toBe(current.current_revision_id);
    expect(row.attachableRevisionNumber).toBe(3);
    expect(row.hasNewerRevision).toBe(true);
  });

  test("upgrades only the selected row to the latest active revision", () => {
    const current = makeSkill("versioned", 3);
    const other = makeSkill("other", 2);
    const bindings = [
      { skill_id: current.id, skill_revision_id: `${current.id}-revision-1` },
      { skill_id: other.id, skill_revision_id: other.current_revision_id }
    ];

    const upgraded = upgradeSkillBinding(bindings, 0, {
      id: current.id,
      attachableRevisionId: current.current_revision_id,
      isActive: current.is_active
    });

    expect(upgraded).toEqual([
      { skill_id: current.id, skill_revision_id: current.current_revision_id },
      bindings[1]
    ]);
    expect(
      upgradeSkillBinding(upgraded, 0, {
        id: current.id,
        attachableRevisionId: current.current_revision_id,
        isActive: true
      })
    ).toBe(upgraded);
    expect(
      upgradeSkillBinding(bindings, 0, {
        id: current.id,
        attachableRevisionId: current.current_revision_id,
        isActive: false
      })
    ).toBe(bindings);
  });

  test("shows the attachable revision metadata immediately after an organisation binding upgrade", () => {
    const skill = makeSkill("renamed", 1);
    skill.display_name = "Previous name";
    skill.description = "Previous description";
    const pinnedSummary = makeSummary(skill, 1);
    pinnedSummary.source = "organization";
    pinnedSummary.attachable_revision_id = "renamed-revision-2";
    pinnedSummary.attachable_revision_number = 2;
    const publishedRevision: SkillBindingCandidate = {
      id: skill.id,
      slug: "renamed-skill",
      revision_id: "renamed-revision-2",
      revision_number: 2,
      display_name: "Current name",
      description: "Current description",
      content_digest: "digest-renamed-2",
      first_published_at: "2026-07-20T12:00:00Z",
      execution_blocked: false,
      source: "organization"
    };
    const pinnedBindings = [
      {
        skill_id: skill.id,
        skill_revision_id: pinnedSummary.skill_revision_id
      }
    ];

    const upgradedBindings = upgradeSkillBinding(pinnedBindings, 0, {
      id: skill.id,
      attachableRevisionId: publishedRevision.revision_id,
      isActive: true
    });
    const [row] = getSkillBindingRows(upgradedBindings, [pinnedSummary], [publishedRevision]);

    expect(row.reference.skill_revision_id).toBe(publishedRevision.revision_id);
    expect(row.pinnedRevision).toBe(2);
    expect(row.displayName).toBe(publishedRevision.display_name);
    expect(row.description).toBe(publishedRevision.description);
    expect(row.slug).toBe(publishedRevision.slug);
  });

  test("offers only the published organisation revision and no draft or unpublished upgrade", () => {
    const skill = makeSkill("organization", 3);
    const pinned = makeSummary(skill, 1);
    pinned.attachable_revision_id = "organization-revision-1";
    pinned.attachable_revision_number = 1;

    let [row] = getSkillBindingRows(
      [{ skill_id: skill.id, skill_revision_id: "organization-revision-1" }],
      [pinned],
      []
    );
    expect(row.hasNewerRevision).toBe(false);

    pinned.attachable_revision_id = "organization-revision-3";
    pinned.attachable_revision_number = 3;
    [row] = getSkillBindingRows(
      [{ skill_id: skill.id, skill_revision_id: "organization-revision-1" }],
      [pinned],
      []
    );
    expect(row.hasNewerRevision).toBe(true);
    expect(row.attachableRevisionNumber).toBe(3);

    pinned.attachable_revision_id = null;
    pinned.attachable_revision_number = null;
    pinned.is_active = false;
    [row] = getSkillBindingRows(
      [{ skill_id: skill.id, skill_revision_id: "organization-revision-1" }],
      [pinned],
      []
    );
    expect(row.hasNewerRevision).toBe(false);
    expect(row.isActive).toBe(false);
  });

  test("keeps a blocked exact pin visible while preventing a revision change", () => {
    const skill = makeSkill("blocked-pinned", 2);
    const summary = makeSummary(skill, 1);
    summary.source = "organization";
    summary.execution_blocked = true;
    summary.attachable_revision_id = skill.current_revision_id;
    summary.attachable_revision_number = skill.current_revision_number;

    const [row] = getSkillBindingRows(
      [{ skill_id: skill.id, skill_revision_id: summary.skill_revision_id }],
      [summary],
      []
    );

    expect(row.executionBlocked).toBe(true);
    expect(row.hasNewerRevision).toBe(true);
  });

  test("adds a created Skill to the local catalog and binding draft", () => {
    const created = makePublicSkill("created");
    const candidate = { ...created, source: "space" as const };
    const catalog = mergeSkillCatalog([], [candidate]);
    const bindings = appendSkillRevisionBinding([], {
      id: created.id,
      revisionId: created.current_revision_id
    });

    expect(catalog).toEqual([candidate]);
    expect(bindings).toEqual([
      { skill_id: created.id, skill_revision_id: created.current_revision_id }
    ]);
    expect(getAvailableSkills(catalog, bindings)).toEqual([]);
    expect(getAvailableSkills(catalog, removeSkillBinding(bindings, created.id))).toEqual([
      candidate
    ]);
  });

  test("binds the exact approved revision from an organisation catalogue candidate", () => {
    const published: SkillBindingCandidate = {
      id: "approved",
      slug: "approved",
      revision_id: "approved-revision-4",
      revision_number: 4,
      display_name: "Approved Skill",
      description: "Approved content only",
      content_digest: "digest-approved-4",
      first_published_at: "2026-07-20T12:00:00Z",
      execution_blocked: false,
      source: "organization"
    };

    expect(
      appendSkillRevisionBinding([], {
        id: published.id,
        revisionId: published.revision_id
      })
    ).toEqual([
      {
        skill_id: published.id,
        skill_revision_id: published.revision_id
      }
    ]);
    expect(getSkillCandidateRevisionNumber(published)).toBe(4);
    expect(getAvailableSkills([published], [])).toEqual([published]);
  });
});
