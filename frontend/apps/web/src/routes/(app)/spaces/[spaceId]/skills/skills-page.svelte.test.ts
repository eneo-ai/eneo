import type { AssistantSkillBindingSummary, SkillSparse } from "@eneo/eneo-js";
import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  disableScrollHandling: vi.fn(),
  goto: vi.fn(),
  invalidate: vi.fn(),
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadCode: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  refreshAll: vi.fn(),
  replaceState: vi.fn()
}));

import SkillsPage from "./+page.svelte";

function skill(id: string, name: string): SkillSparse {
  return {
    id,
    space_id: "personal-space",
    slug: id,
    is_active: true,
    current_revision_id: `${id}-r1`,
    current_revision_number: 1,
    display_name: name,
    description: `About ${name}`,
    content_digest: "digest",
    created_by_user_id: "user-1",
    created_at: "2026-10-21T08:00:00Z",
    updated_at: "2026-10-21T08:00:00Z"
  };
}

function binding(id: string): AssistantSkillBindingSummary {
  return {
    skill_id: id,
    skill_revision_id: `${id}-r1`,
    attachable_revision_id: `${id}-r1`,
    slug: id,
    revision_number: 1,
    attachable_revision_number: 1,
    display_name: id,
    description: "",
    content_digest: "digest",
    position: 0,
    is_active: true,
    source: "space",
    execution_blocked: false,
    activation_mode: "on_demand"
  };
}

describe("Skills library page", () => {
  test("marks the Skills the personal chat uses, with their mode", async () => {
    render(SkillsPage, {
      data: {
        currentSpace: {
          id: "personal-space",
          personal: true,
          organization: false,
          skill_permissions: ["read"]
        },
        skills: {
          items: [
            skill("minutes", "Mötesanteckningar"),
            skill("translate", "Engelsk översättning")
          ],
          count: 2,
          total_count: 2,
          limit: 25,
          next_cursor: null,
          previous_cursor: null
        },
        personalChatSkills: {
          bindings: [binding("minutes")],
          organisation_bindings: [],
          runtime: null,
          personal_layer: { status: "applied", reason: null, detail: null }
        },
        eneo: { skills: { list: vi.fn(), delete: vi.fn() } }
      } as never
    });

    const badge = m.personal_chat_skills_status_badge({
      mode: m.skills_activation_mode_on_demand()
    });
    await expect
      .element(page.getByRole("row", { name: /Mötesanteckningar/ }).getByText(badge))
      .toBeVisible();
    expect(page.getByText(badge).elements()).toHaveLength(1);
  });
});
