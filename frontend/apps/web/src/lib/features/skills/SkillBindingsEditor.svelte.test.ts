import type { SkillBindingSummary, SkillPublic, SkillSparse } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import SkillBindingsEditor from "./SkillBindingsEditor.svelte";

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

function makeSummary(skill: SkillSparse, revision: number, position: number): SkillBindingSummary {
  return {
    skill_id: skill.id,
    skill_revision_id: `${skill.id}-revision-${revision}`,
    slug: skill.slug,
    revision_number: revision,
    display_name: skill.display_name,
    description: skill.description,
    content_digest: `digest-${skill.id}-${revision}`,
    position,
    is_active: skill.is_active
  };
}

function makePublicSkill(id: string, displayName: string): SkillPublic {
  const sparse = makeSkill(id);
  return {
    ...sparse,
    display_name: displayName,
    current_revision: {
      id: sparse.current_revision_id,
      skill_id: sparse.id,
      revision_number: sparse.current_revision_number,
      display_name: displayName,
      description: sparse.description,
      instructions: "Follow these instructions.",
      content_digest: sparse.content_digest,
      created_by_user_id: sparse.created_by_user_id,
      created_at: sparse.created_at
    }
  };
}

describe("SkillBindingsEditor", () => {
  test("exposes disabled order boundaries and upgrades only after an explicit action", async () => {
    const first = makeSkill("first", 2);
    const second = makeSkill("second", 1, false);
    const firstSummary = makeSummary(first, 1, 0);
    const secondSummary = makeSummary(second, 1, 1);

    render(SkillBindingsEditor, {
      bindings: [
        { skill_id: first.id, skill_revision_id: firstSummary.skill_revision_id },
        { skill_id: second.id, skill_revision_id: secondSummary.skill_revision_id }
      ],
      availableSkills: [first, second],
      bindingSummaries: [firstSummary, secondSummary],
      canEditBindings: true,
      canCreateSkills: true,
      onCreateSkill: vi.fn()
    });

    await expect
      .element(
        page.getByRole("button", { name: m.skills_move_up_aria({ name: first.display_name }) })
      )
      .toBeDisabled();
    await expect
      .element(
        page.getByRole("button", { name: m.skills_move_down_aria({ name: first.display_name }) })
      )
      .toBeEnabled();
    await expect
      .element(
        page.getByRole("button", { name: m.skills_move_down_aria({ name: second.display_name }) })
      )
      .toBeDisabled();
    await expect
      .element(page.getByText(m.skills_revision_label({ revision: "1" })).first())
      .toBeVisible();
    await expect
      .element(page.getByText(m.skills_newer_revision_available({ revision: "2" })))
      .toBeVisible();
    await expect.element(page.getByText(m.skills_inactive_status())).toBeVisible();
    await expect.element(page.getByText(m.skills_inactive_binding_explanation())).toBeVisible();

    await page
      .getByRole("button", {
        name: m.skills_use_latest_revision_aria({ name: first.display_name, revision: "2" })
      })
      .click();

    await expect
      .element(page.getByText(m.skills_newer_revision_available({ revision: "2" })))
      .not.toBeInTheDocument();
    await expect
      .element(
        page.getByText(m.skills_revision_label({ revision: "2" }), {
          exact: true
        })
      )
      .toBeVisible();
    await expect.element(page.getByRole("listitem").first()).toHaveFocus();
  });

  test("keeps a populated create dialog open until discard is confirmed", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(SkillBindingsEditor, {
      bindings: [],
      availableSkills: [],
      bindingSummaries: [],
      canEditBindings: true,
      canCreateSkills: true,
      onCreateSkill: vi.fn()
    });

    try {
      await page.getByRole("button", { name: m.skills_create_new() }).click();
      const nameInput = page.getByLabelText(m.skills_display_name_label());
      await nameInput.fill("Budget support");
      await page.getByRole("button", { name: m.close() }).click();

      expect(confirm).toHaveBeenCalledWith(m.unsaved_changes_warning());
      await expect.element(nameInput).toHaveValue("Budget support");
      await expect.element(page.getByRole("dialog")).toBeVisible();

      confirm.mockReturnValue(true);
      await page.getByRole("button", { name: m.close() }).click();
      await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
    } finally {
      confirm.mockRestore();
    }
  });

  test("creates immediately, adds the exact revision to the draft, and restores focus", async () => {
    const created = makePublicSkill("created", "Budget support");
    const onCreateSkill = vi.fn().mockResolvedValue(created);

    render(SkillBindingsEditor, {
      bindings: [],
      availableSkills: [],
      bindingSummaries: [],
      canEditBindings: true,
      canCreateSkills: true,
      onCreateSkill
    });

    await page.getByRole("button", { name: m.skills_create_new() }).click();
    await expect.element(page.getByText(m.skills_create_immediate_description())).toBeVisible();
    await page.getByLabelText(m.skills_display_name_label()).fill("Budget support");
    await page.getByLabelText(m.skills_description_label()).fill("Answers budget questions.");
    await page.getByLabelText(m.skills_instructions_label()).fill("Use approved budget sources.");
    await page.getByRole("button", { name: m.skills_create_action() }).click();

    await expect.element(page.getByText("Budget support", { exact: true })).toBeVisible();
    expect(onCreateSkill).toHaveBeenCalledWith({
      display_name: "Budget support",
      description: "Answers budget questions.",
      instructions: "Use approved budget sources.",
      slug: "budget-support"
    });

    await page
      .getByRole("button", { name: m.skills_remove_aria({ name: "Budget support" }) })
      .click();
    const addExisting = page.getByRole("combobox", { name: m.skills_add_existing() });
    await expect.element(addExisting).toHaveFocus();
    await addExisting.click();
    const searchInput = page.getByPlaceholder(m.skills_search_existing());
    await expect.element(searchInput).toBeVisible();
    expect(searchInput.element().getAttribute("aria-label")).toBe(m.skills_search_existing());
    await expect.element(page.getByText("Budget support", { exact: true })).toBeVisible();
  });
});
