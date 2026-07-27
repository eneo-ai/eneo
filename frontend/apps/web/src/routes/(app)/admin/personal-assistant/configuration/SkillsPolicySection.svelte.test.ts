import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { emptySkillBindingCatalogPage } from "$lib/features/skills/skillBindingCatalog";
import { m } from "$lib/paraglide/messages";
import SkillsPolicySection from "./SkillsPolicySection.svelte";

describe("SkillsPolicySection", () => {
  test("lets an admin configure Personal Chat Skills without a Space Skill permission", async () => {
    render(SkillsPolicySection, {
      skillBindings: [],
      initialCatalogPage: emptySkillBindingCatalogPage(),
      bindingSummaries: [],
      summary: "0 Skills",
      onListCatalog: vi.fn(),
      onGetSkillPreview: vi.fn()
    });

    await expect
      .element(page.getByRole("combobox", { name: m.skills_add_existing() }))
      .toBeEnabled();
  });

  test("presents the Personal Chat scope as guidance rather than an urgent alert", async () => {
    render(SkillsPolicySection, {
      skillBindings: [],
      initialCatalogPage: emptySkillBindingCatalogPage(),
      bindingSummaries: [],
      summary: "0 Skills",
      onListCatalog: vi.fn(),
      onGetSkillPreview: vi.fn()
    });

    const scopeNote = page.getByRole("note");
    await expect
      .element(scopeNote.getByText(m.governance_skills_scope_title(), { exact: true }))
      .toBeVisible();
    await expect.element(page.getByRole("alert")).not.toBeInTheDocument();
    await expect
      .element(page.getByRole("link", { name: m.governance_manage_skills_action() }))
      .toHaveAttribute("href", "/spaces/organization/skills");
  });
});
