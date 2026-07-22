import type { SkillBindingSummary } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test } from "vitest";
import { m } from "$lib/paraglide/messages";
import ChatSkillSummary from "./ChatSkillSummary.svelte";

function binding({
  id,
  name,
  revision,
  position
}: {
  id: string;
  name: string;
  revision: number;
  position: number;
}): SkillBindingSummary {
  return {
    skill_id: id,
    skill_revision_id: `${id}-revision-${revision}`,
    current_revision_id: `${id}-revision-${revision}`,
    slug: id,
    revision_number: revision,
    current_revision_number: revision,
    display_name: name,
    description: `${name} description`,
    content_digest: `${id}-digest`,
    position,
    is_active: true
  };
}

describe("ChatSkillSummary", () => {
  test("shows exact pinned revisions in their instruction order", async () => {
    render(ChatSkillSummary, {
      bindings: [
        binding({ id: "citizen-info", name: "Citizen information", revision: 1, position: 1 }),
        binding({ id: "decision-support", name: "Decision support", revision: 3, position: 0 })
      ]
    });

    const trigger = page.getByRole("button", {
      name: m.skills_chat_summary_count({ count: "2" })
    });
    await trigger.click();

    await expect.element(page.getByText(m.skills_chat_summary_description())).toBeVisible();
    const items = page.getByRole("listitem");
    await expect.element(items.nth(0)).toHaveTextContent("Decision support");
    await expect
      .element(items.nth(0))
      .toHaveTextContent(m.skills_revision_label({ revision: "3" }));
    await expect.element(items.nth(1)).toHaveTextContent("Citizen information");
    await expect
      .element(items.nth(1))
      .toHaveTextContent(m.skills_revision_label({ revision: "1" }));
    await expect
      .element(page.getByRole("link", { name: m.skills_manage_bindings_action() }))
      .not.toBeInTheDocument();
    await trigger.click();
  });

  test("offers resource-level management only when an edit destination is provided", async () => {
    render(ChatSkillSummary, {
      bindings: [
        binding({ id: "decision-support", name: "Decision support", revision: 3, position: 0 })
      ],
      manageHref: "/spaces/space-1/assistants/assistant-1/edit#skills"
    });

    const trigger = page.getByRole("button", {
      name: m.skills_chat_summary_count({ count: "1" })
    });
    await trigger.click();

    const manageLink = page.getByRole("link", { name: m.skills_manage_bindings_action() });
    await expect.element(manageLink).toBeVisible();
    expect(manageLink.element().getAttribute("href")).toBe(
      "/spaces/space-1/assistants/assistant-1/edit#skills"
    );
    await trigger.click();
  });

  test("keeps a long Skill set in one ordered, accessible list", async () => {
    const bindings = Array.from({ length: 20 }, (_, index) =>
      binding({
        id: `skill-${index + 1}`,
        name: `Skill ${index + 1}`,
        revision: index + 1,
        position: 19 - index
      })
    );

    render(ChatSkillSummary, { bindings });

    const trigger = page.getByRole("button", {
      name: m.skills_chat_summary_count({ count: "20" })
    });
    await trigger.click();

    const region = page.getByRole("region", {
      name: m.skills_binding_scroll_region_label({ count: "20" })
    });
    await expect.element(region).toBeVisible();
    expect(region.element().getAttribute("tabindex")).toBe("0");
    const items = region.getByRole("listitem");
    expect(region.element().querySelectorAll("li")).toHaveLength(20);
    await expect.element(items.nth(0)).toHaveTextContent("Skill 20");
    await expect.element(items.nth(19)).toHaveTextContent("Skill 1");
    await trigger.click();
  });
});
