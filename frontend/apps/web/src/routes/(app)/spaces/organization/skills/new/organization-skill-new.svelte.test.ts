import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const goto = vi.hoisted(() => vi.fn());

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  disableScrollHandling: vi.fn(),
  goto,
  invalidate: vi.fn(),
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadCode: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  refreshAll: vi.fn(),
  replaceState: vi.fn()
}));

import OrganizationSkillNewPage from "./+page.svelte";

describe("organisation Skill creation page", () => {
  test("keeps a committed creation successful when navigation fails", async () => {
    const create = vi.fn(async () => ({ id: "created-skill" }));
    goto.mockRejectedValueOnce(new Error("Navigation failed"));

    render(OrganizationSkillNewPage, {
      data: {
        eneo: {
          skills: {
            organization: { create }
          }
        }
      } as never
    });

    await page.getByLabelText(m.skills_display_name_label()).fill("HR support");
    await page.getByLabelText(m.skills_description_label()).fill("Answers HR questions.");
    await page.getByLabelText(m.skills_instructions_label()).fill("Use approved HR sources.");
    await page.getByRole("button", { name: m.skills_create_action() }).click();

    await vi.waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        display_name: "HR support",
        description: "Answers HR questions.",
        instructions: "Use approved HR sources.",
        slug: "hr-support"
      })
    );
    await expect.element(page.getByText(m.organization_skills_created_title())).toBeVisible();
    await expect
      .element(
        page.getByRole("link", {
          name: m.organization_skills_open_created_action()
        })
      )
      .toHaveAttribute("href", "/spaces/organization/skills/created-skill");
    await expect
      .element(page.getByRole("button", { name: m.skills_create_action() }))
      .not.toBeInTheDocument();
  });
});
