import type { SkillBindingSummary, SkillPublic, SkillSparse } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import SkillBindingsEditor from "./SkillBindingsEditor.svelte";
import type { SkillBindingCatalogPage, SkillBindingPreview } from "./skillBindingCatalog";
import { SKILL_CATALOG_PAGE_SIZE } from "./skillCatalog";
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
    is_active: skill.is_active,
    attachable_revision_id: skill.current_revision_id,
    attachable_revision_number: skill.current_revision_number,
    source: "space"
  };
}

function makePage(
  items: SkillBindingCandidate[],
  nextCursor: string | null = null
): SkillBindingCatalogPage {
  return {
    items,
    count: items.length,
    limit: SKILL_CATALOG_PAGE_SIZE,
    next_cursor: nextCursor
  };
}

function previewFor(skill: SkillBindingCandidate): SkillBindingPreview {
  const revisionId = skill.source === "space" ? skill.current_revision_id : skill.revision_id;
  const revisionNumber =
    skill.source === "space" ? skill.current_revision_number : skill.revision_number;
  return {
    id: skill.id,
    source: skill.source,
    slug: skill.slug,
    revisionId,
    revisionNumber,
    displayName: skill.display_name,
    description: skill.description,
    instructions: `Exact instructions for ${skill.slug}.`
  };
}

function getPreview(skill: SkillBindingCandidate): Promise<SkillBindingPreview> {
  return Promise.resolve(previewFor(skill));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
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
  test("searches and loads more from the server-owned catalog", async () => {
    const first = makeSkill("first");
    const second = makeSkill("second");
    const searched = makeSkill("searched");
    const onListSkills = vi.fn(
      async ({ cursor, query }: { cursor?: string | null; query?: string | null }) => {
        if (query === "payroll") return makePage([searched]);
        if (cursor === "skill-first") return makePage([first, second]);
        return makePage([first], "skill-first");
      }
    );

    render(SkillBindingsEditor, {
      bindings: [],
      initialCatalogPage: makePage([first], "skill-first"),
      bindingSummaries: [],
      canEditBindings: true,
      canCreateSkills: false,
      onListCatalog: onListSkills,
      onGetSkillPreview: getPreview,
      onCreateSkill: vi.fn()
    });

    await page.getByRole("combobox", { name: m.skills_add_existing() }).click();
    await page.getByRole("button", { name: m.load_more() }).click();

    expect(onListSkills).toHaveBeenCalledWith({
      limit: SKILL_CATALOG_PAGE_SIZE,
      cursor: "skill-first",
      query: null
    });
    await expect.element(page.getByText(second.display_name, { exact: true })).toBeVisible();

    await page.getByPlaceholder(m.skills_search_existing()).fill("payroll");
    await vi.waitFor(
      () =>
        expect(onListSkills).toHaveBeenCalledWith({
          limit: SKILL_CATALOG_PAGE_SIZE,
          cursor: null,
          query: "payroll"
        }),
      { timeout: 1_000 }
    );
    await expect.element(page.getByText(searched.display_name, { exact: true })).toBeVisible();
    await expect
      .element(page.getByText(first.display_name, { exact: true }))
      .not.toBeInTheDocument();
  });

  test("previews the exact published revision before adding it to the draft", async () => {
    const published: SkillBindingCandidate = {
      id: "published",
      slug: "approved-guidance",
      revision_id: "published-revision-4",
      revision_number: 4,
      display_name: "Approved guidance",
      description: "Approved organisation instructions.",
      content_digest: "published-digest",
      first_published_at: "2026-07-20T12:00:00Z",
      source: "organization"
    };
    const onGetSkillPreview = vi.fn(getPreview);

    render(SkillBindingsEditor, {
      bindings: [],
      initialCatalogPage: makePage([published]),
      bindingSummaries: [],
      canEditBindings: true,
      canCreateSkills: false,
      onListCatalog: vi.fn(),
      onGetSkillPreview
    });

    await page.getByRole("combobox", { name: m.skills_add_existing() }).click();
    await page.getByText(published.display_name, { exact: true }).click();

    await expect.element(page.getByRole("dialog")).toBeVisible();
    await expect
      .element(page.getByText(m.skills_source_organization(), { exact: true }))
      .toBeVisible();
    await expect.element(page.getByText(published.slug, { exact: true })).toBeVisible();
    await expect
      .element(
        page.getByText(m.skills_revision_label({ revision: "4" }), {
          exact: true
        })
      )
      .toBeVisible();
    await expect
      .element(page.getByText("Exact instructions for approved-guidance.", { exact: true }))
      .toBeVisible();
    expect(onGetSkillPreview).toHaveBeenCalledWith(published);

    await page.getByRole("button", { name: m.cancel() }).click();
    const pickerTrigger = page.getByRole("combobox", { name: m.skills_add_existing() });
    await expect.element(pickerTrigger).toHaveFocus();
    await pickerTrigger.click();
    await page.getByText(published.display_name, { exact: true }).click();
    await page.getByRole("button", { name: m.skills_add_to_draft() }).click();
    await expect
      .element(
        page.getByRole("button", {
          name: m.skills_remove_aria({ name: published.display_name })
        })
      )
      .toBeVisible();
  });

  test("ignores a stale preview response after closing and reopening the same Skill", async () => {
    const skill = makeSkill("reopened");
    const firstRequest = deferred<SkillBindingPreview>();
    const secondRequest = deferred<SkillBindingPreview>();
    const onGetSkillPreview = vi
      .fn()
      .mockReturnValueOnce(firstRequest.promise)
      .mockReturnValueOnce(secondRequest.promise);

    render(SkillBindingsEditor, {
      bindings: [],
      initialCatalogPage: makePage([skill]),
      bindingSummaries: [],
      canEditBindings: true,
      canCreateSkills: false,
      onListCatalog: vi.fn(),
      onGetSkillPreview
    });

    const pickerTrigger = page.getByRole("combobox", { name: m.skills_add_existing() });
    await pickerTrigger.click();
    await page.getByText(skill.display_name, { exact: true }).click();
    await page.getByRole("button", { name: m.cancel() }).click();

    await pickerTrigger.click();
    await page.getByText(skill.display_name, { exact: true }).click();
    expect(onGetSkillPreview).toHaveBeenCalledTimes(2);

    secondRequest.resolve({ ...previewFor(skill), instructions: "Fresh preview instructions." });
    await expect
      .element(page.getByText("Fresh preview instructions.", { exact: true }))
      .toBeVisible();

    firstRequest.resolve({ ...previewFor(skill), instructions: "Stale preview instructions." });
    await expect
      .element(page.getByText("Fresh preview instructions.", { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText("Stale preview instructions.", { exact: true }))
      .not.toBeInTheDocument();
  });

  test("upgrades a bound Skill that is outside the current catalog page", async () => {
    const bound = makeSkill("bound", 2);
    const summary = makeSummary(bound, 1, 0);

    render(SkillBindingsEditor, {
      bindings: [{ skill_id: bound.id, skill_revision_id: summary.skill_revision_id }],
      initialCatalogPage: makePage([]),
      bindingSummaries: [summary],
      canEditBindings: true,
      canCreateSkills: false,
      onListCatalog: vi.fn(),
      onGetSkillPreview: getPreview,
      onCreateSkill: vi.fn()
    });

    await expect
      .element(page.getByText(m.skills_newer_revision_available({ revision: "2" })))
      .toBeVisible();
    await page
      .getByRole("button", {
        name: m.skills_use_latest_revision_aria({ name: bound.display_name, revision: "2" })
      })
      .click();

    await expect
      .element(page.getByText(m.skills_revision_label({ revision: "2" }), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.skills_newer_revision_available({ revision: "2" })))
      .not.toBeInTheDocument();
  });

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
      initialCatalogPage: makePage([first, second]),
      bindingSummaries: [firstSummary, secondSummary],
      canEditBindings: true,
      canCreateSkills: true,
      onListCatalog: vi.fn(),
      onGetSkillPreview: getPreview,
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
    await expect
      .element(page.getByText(m.skills_unavailable_status(), { exact: true }))
      .toBeVisible();
    await expect.element(page.getByText(m.skills_unavailable_binding_explanation())).toBeVisible();
    await expect.element(page.getByText(m.skills_binding_count({ count: "2" }))).toBeVisible();

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
      initialCatalogPage: makePage([]),
      bindingSummaries: [],
      canEditBindings: true,
      canCreateSkills: true,
      onListCatalog: vi.fn(),
      onGetSkillPreview: getPreview,
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
      initialCatalogPage: makePage([]),
      bindingSummaries: [],
      canEditBindings: true,
      canCreateSkills: true,
      onListCatalog: vi.fn(),
      onGetSkillPreview: getPreview,
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

  test("keeps twenty attached Skills in one keyboard-scrollable instruction list", async () => {
    const skills = Array.from({ length: 20 }, (_, index) => makeSkill(String(index + 1)));
    const summaries = skills.map((skill, index) => makeSummary(skill, 1, index));

    render(SkillBindingsEditor, {
      bindings: summaries.map((summary) => ({
        skill_id: summary.skill_id,
        skill_revision_id: summary.skill_revision_id
      })),
      initialCatalogPage: makePage(skills),
      bindingSummaries: summaries,
      canEditBindings: true,
      canCreateSkills: false,
      onListCatalog: vi.fn(),
      onGetSkillPreview: getPreview
    });

    const region = page.getByRole("region", {
      name: m.skills_binding_scroll_region_label({ count: "20" })
    });
    await expect.element(region).toBeVisible();
    expect(region.element().getAttribute("tabindex")).toBe("0");
    expect(region.element().querySelectorAll("li")).toHaveLength(20);
    await expect.element(page.getByText(m.skills_binding_count({ count: "20" }))).toBeVisible();
  });

  test("explains when the existing-Skill picker has no available Skills", async () => {
    render(SkillBindingsEditor, {
      bindings: [],
      initialCatalogPage: makePage([]),
      bindingSummaries: [],
      canEditBindings: true,
      canCreateSkills: false,
      onListCatalog: vi.fn(),
      onGetSkillPreview: getPreview
    });

    const trigger = page.getByRole("combobox", { name: m.skills_add_existing() });
    await trigger.click();
    await expect.element(page.getByText(m.skills_no_available())).toBeVisible();
    await trigger.click();
  });

  test("explains when every available Skill is already attached", async () => {
    const attached = makeSkill("attached");
    const attachedSummary = makeSummary(attached, 1, 0);
    render(SkillBindingsEditor, {
      bindings: [{ skill_id: attached.id, skill_revision_id: attachedSummary.skill_revision_id }],
      initialCatalogPage: makePage([attached]),
      bindingSummaries: [attachedSummary],
      canEditBindings: true,
      canCreateSkills: false,
      onListCatalog: vi.fn(),
      onGetSkillPreview: getPreview
    });

    const trigger = page.getByRole("combobox", { name: m.skills_add_existing() });
    await trigger.click();
    await expect.element(page.getByText(m.skills_all_attached())).toBeVisible();
    await trigger.click();
  });

  test("explains when no available Skills match the search", async () => {
    const searchable = makeSkill("searchable");
    render(SkillBindingsEditor, {
      bindings: [],
      initialCatalogPage: makePage([searchable]),
      bindingSummaries: [],
      canEditBindings: true,
      canCreateSkills: false,
      onListCatalog: vi.fn().mockResolvedValue(makePage([])),
      onGetSkillPreview: getPreview
    });

    const trigger = page.getByRole("combobox", { name: m.skills_add_existing() });
    await trigger.click();
    await page.getByPlaceholder(m.skills_search_existing()).fill("does not exist");
    await expect.element(page.getByText(m.skills_search_no_results())).toBeVisible();
    await trigger.click();
  });
});
