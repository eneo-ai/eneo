import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { emptySkillBindingCatalogPage } from "$lib/features/skills/skillBindingCatalog";
import { m } from "$lib/paraglide/messages";
import SkillsPolicySection from "./SkillsPolicySection.svelte";

const badgeVariant = (enabled: boolean, valid: boolean) =>
  enabled ? (valid ? ("default" as const) : ("destructive" as const)) : ("outline" as const);

describe("SkillsPolicySection", () => {
  test("lets an admin configure Personal Chat Skills without a Space Skill permission", async () => {
    render(SkillsPolicySection, {
      skillBindings: [],
      initialCatalogPage: emptySkillBindingCatalogPage(),
      bindingSummaries: [],
      summary: "0 Skills",
      skillsValid: true,
      canSelectOnDemand: false,
      selectiveActivationEnabled: true,
      badgeVariant,
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
      skillsValid: true,
      canSelectOnDemand: false,
      selectiveActivationEnabled: true,
      badgeVariant,
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

  test("enables activation modes when the policy has a bounded model set", async () => {
    render(SkillsPolicySection, {
      skillBindings: [],
      initialCatalogPage: emptySkillBindingCatalogPage(),
      bindingSummaries: [],
      summary: "0 Skills",
      skillsValid: true,
      canSelectOnDemand: true,
      selectiveActivationEnabled: true,
      badgeVariant,
      onListCatalog: vi.fn(),
      onGetSkillPreview: vi.fn()
    });

    await expect
      .element(
        page.getByText(m.skills_activation_runtime_policy_selective(), {
          exact: true
        })
      )
      .toBeVisible();
  });

  test("explains that the tenant runtime, not the model set, blocks On demand", async () => {
    render(SkillsPolicySection, {
      skillBindings: [],
      initialCatalogPage: emptySkillBindingCatalogPage(),
      bindingSummaries: [],
      summary: "0 Skills",
      skillsValid: true,
      canSelectOnDemand: false,
      selectiveActivationEnabled: false,
      badgeVariant,
      onListCatalog: vi.fn(),
      onGetSkillPreview: vi.fn()
    });

    await expect
      .element(page.getByText(m.skills_activation_runtime_disabled(), { exact: true }))
      .toBeVisible();
  });

  test("marks an on-demand policy invalid when its model selection is unbounded", async () => {
    render(SkillsPolicySection, {
      skillBindings: [
        {
          skill_id: "00000000-0000-0000-0000-000000000001",
          skill_revision_id: "00000000-0000-0000-0000-000000000002",
          activation_mode: "on_demand"
        }
      ],
      initialCatalogPage: emptySkillBindingCatalogPage(),
      bindingSummaries: [],
      summary: "1 Skill",
      skillsValid: false,
      canSelectOnDemand: false,
      selectiveActivationEnabled: true,
      badgeVariant,
      onListCatalog: vi.fn(),
      onGetSkillPreview: vi.fn()
    });

    await expect
      .element(page.getByText("1 Skill", { exact: true }))
      .toHaveClass(/text-destructive/);
  });
});
