import type { SkillAdoptionProjectionPagePublic } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import SkillAdoptionProjection from "./SkillAdoptionProjection.svelte";

function adoptionPage({
  items = [
    {
      kind: "assistant" as const,
      resource_id: "assistant-1",
      name: "HR Assistant",
      space_id: "space-1",
      space_name: "People and culture",
      revision_id: "revision-1",
      revision_number: 1,
      drift: "behind" as const
    }
  ],
  nextCursor = null,
  includeSummary = true
}: {
  items?: SkillAdoptionProjectionPagePublic["items"];
  nextCursor?: string | null;
  includeSummary?: boolean;
} = {}): SkillAdoptionProjectionPagePublic {
  const assistantCount = items.filter((item) => item.kind === "assistant").length;
  const appCount = items.filter((item) => item.kind === "app").length + (nextCursor ? 1 : 0);

  return {
    summary: includeSummary
      ? {
          assistant_count: assistantCount,
          app_count: appCount,
          distinct_space_count: new Set(items.map((item) => item.space_id)).size,
          behind_published_count: items.filter((item) => item.drift === "behind").length + 1,
          personal_chat: {
            revision_id: "revision-1",
            revision_number: 1,
            drift: "behind"
          },
          revision_counts: [
            {
              revision_id: "revision-1",
              revision_number: 1,
              assistant_count: items.filter((item) => item.kind === "assistant").length,
              app_count: items.filter((item) => item.kind === "app").length,
              personal_chat_pinned: true
            }
          ]
        }
      : null,
    items,
    limit: 25,
    next_cursor: nextCursor
  };
}

function emptyAdoptionPage(): SkillAdoptionProjectionPagePublic {
  return {
    summary: {
      assistant_count: 0,
      app_count: 0,
      distinct_space_count: 0,
      behind_published_count: 0,
      personal_chat: null,
      revision_counts: []
    },
    items: [],
    limit: 25,
    next_cursor: null
  };
}

describe("Skill adoption projection", () => {
  test("shows server-owned summary, Personal Chat pin, revision counts, and resource drift", async () => {
    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: adoptionPage(),
      getOrganizationSkillAdoption: vi.fn()
    });

    await expect
      .element(page.getByRole("heading", { name: m.organization_skills_adoption_heading() }))
      .toBeVisible();
    await expect.element(page.getByText("HR Assistant")).toBeVisible();
    await expect.element(page.getByText("People and culture")).toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_adoption_drift_behind()).first())
      .toBeVisible();
    await expect
      .element(
        page.getByText(
          m.organization_skills_adoption_personal_chat_pinned({
            version: "1"
          })
        )
      )
      .toBeVisible();
    await expect
      .element(
        page.getByRole("heading", {
          name: m.organization_skills_adoption_revision_breakdown_heading()
        })
      )
      .toBeVisible();
    await expect
      .element(
        page.getByRole("group", {
          name: m.organization_skills_adoption_revision_breakdown_heading()
        })
      )
      .toBeVisible();
  });

  test("distinguishes an empty structural projection from runtime usage", async () => {
    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: emptyAdoptionPage(),
      getOrganizationSkillAdoption: vi.fn()
    });

    await expect
      .element(page.getByRole("heading", { name: m.organization_skills_adoption_empty_title() }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_adoption_empty_description()))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_adoption_description()))
      .toBeVisible();
  });

  test("labels an unpublished source without relying on colour", async () => {
    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: adoptionPage({
        items: [
          {
            kind: "app",
            resource_id: "app-1",
            name: "Policy App",
            space_id: "space-1",
            space_name: "Operations",
            revision_id: "revision-1",
            revision_number: 1,
            drift: "unpublished"
          }
        ]
      }),
      getOrganizationSkillAdoption: vi.fn()
    });

    await expect
      .element(page.getByText(m.organization_skills_adoption_drift_unpublished()))
      .toBeVisible();
  });

  test("announces the initial loading state", async () => {
    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: null,
      initialLoading: true,
      getOrganizationSkillAdoption: vi.fn()
    });

    await expect
      .element(
        page.getByRole("status", {
          name: m.organization_skills_adoption_loading()
        })
      )
      .toBeVisible();
  });

  test("keeps an initial failure local to adoption and allows retry", async () => {
    const getOrganizationSkillAdoption = vi.fn().mockResolvedValue(emptyAdoptionPage());

    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: null,
      initialError: true,
      getOrganizationSkillAdoption
    });

    await expect
      .element(page.getByText(m.organization_skills_adoption_error_title()))
      .toBeVisible();
    await page.getByRole("button", { name: m.retry() }).click();

    await vi.waitFor(() =>
      expect(getOrganizationSkillAdoption).toHaveBeenCalledWith("skill-1", {
        limit: 25,
        cursor: null
      })
    );
    await expect
      .element(page.getByRole("heading", { name: m.organization_skills_adoption_empty_title() }))
      .toBeVisible();
  });

  test("retains a failed page cursor and appends resources after retry", async () => {
    const secondPage = adoptionPage({
      items: [
        {
          kind: "app",
          resource_id: "app-1",
          name: "Onboarding App",
          space_id: "space-2",
          space_name: "Employee services",
          revision_id: "revision-2",
          revision_number: 2,
          drift: "current"
        }
      ],
      includeSummary: false
    });
    const getOrganizationSkillAdoption = vi
      .fn()
      .mockRejectedValueOnce(new Error("Unavailable"))
      .mockResolvedValueOnce(secondPage);

    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: adoptionPage({ nextCursor: "next-page" }),
      getOrganizationSkillAdoption
    });

    await page.getByRole("button", { name: m.organization_skills_adoption_load_more() }).click();
    await expect.element(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: m.retry() }).click();

    await vi.waitFor(() => expect(getOrganizationSkillAdoption).toHaveBeenCalledTimes(2));
    expect(getOrganizationSkillAdoption).toHaveBeenLastCalledWith("skill-1", {
      limit: 25,
      cursor: "next-page"
    });
    await expect.element(page.getByText("HR Assistant")).toBeVisible();
    await expect.element(page.getByText("Onboarding App")).toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_adoption_drift_current()))
      .toBeVisible();
    await expect
      .element(
        page.getByText(
          m.organization_skills_adoption_resources_shown({
            shown: "2",
            total: "2"
          })
        )
      )
      .toBeInTheDocument();
  });
});
