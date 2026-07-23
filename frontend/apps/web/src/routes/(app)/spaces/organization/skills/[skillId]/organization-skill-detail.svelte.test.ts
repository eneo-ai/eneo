import type {
  OrganizationSkillPublic,
  PublishedSkillPublic,
  SkillRevisionPublic
} from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const invalidate = vi.hoisted(() => vi.fn(async () => {}));

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  disableScrollHandling: vi.fn(),
  goto: vi.fn(),
  invalidate,
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadCode: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  refreshAll: vi.fn(),
  replaceState: vi.fn()
}));

import OrganizationSkillDetailPage from "./+page.svelte";

function revision(revisionNumber: number): SkillRevisionPublic {
  return {
    id: `revision-${revisionNumber}`,
    skill_id: "skill-1",
    revision_number: revisionNumber,
    display_name: "HR support",
    description: `Revision ${revisionNumber}`,
    instructions: `Follow revision ${revisionNumber}.`,
    content_digest: String(revisionNumber).repeat(64),
    created_by_user_id: "user-1",
    created_at: `2026-07-${18 + revisionNumber}T08:00:00Z`
  };
}

function updatePendingSkill(): OrganizationSkillPublic {
  const currentRevision = revision(2);
  return {
    id: "skill-1",
    space_id: "organization-space",
    slug: "hr-support",
    is_active: true,
    current_revision_id: currentRevision.id,
    current_revision_number: currentRevision.revision_number,
    display_name: currentRevision.display_name,
    description: currentRevision.description,
    content_digest: currentRevision.content_digest,
    created_by_user_id: "user-1",
    created_at: "2026-07-19T08:00:00Z",
    updated_at: "2026-07-20T08:00:00Z",
    published_revision_number: 1,
    first_published_at: "2026-07-19T09:00:00Z",
    publication_state: "update_pending",
    current_revision: currentRevision
  };
}

function publishedSkill(): PublishedSkillPublic {
  const publishedRevision = revision(1);
  return {
    id: "skill-1",
    slug: "hr-support",
    revision_id: publishedRevision.id,
    revision_number: publishedRevision.revision_number,
    display_name: publishedRevision.display_name,
    description: publishedRevision.description,
    content_digest: publishedRevision.content_digest,
    first_published_at: "2026-07-19T09:00:00Z",
    revision: publishedRevision
  };
}

function adoptionPage() {
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

describe("organisation Skill detail page", () => {
  beforeEach(() => {
    invalidate.mockReset();
    invalidate.mockResolvedValue(undefined);
  });

  test("keeps a created revision saved when refreshing the page data fails", async () => {
    const createRevision = vi.fn(async () => {});
    invalidate.mockRejectedValueOnce(new Error("Refresh failed"));

    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        eneo: {
          skills: {
            organization: {
              createRevision,
              getAdoption: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    await page.getByLabelText(m.skills_description_label()).fill("Updated description");
    await page.getByRole("button", { name: m.save(), exact: true }).click();

    await vi.waitFor(() =>
      expect(createRevision).toHaveBeenCalledWith({
        skillId: "skill-1",
        display_name: "HR support",
        description: "Updated description",
        instructions: "Follow revision 2."
      })
    );
    await expect
      .element(page.getByRole("status").getByText(m.skills_form_saved_status(), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_refresh_after_mutation_warning()))
      .toBeVisible();
    await expect
      .element(page.getByText(m.skills_revision_form_error_title()))
      .not.toBeInTheDocument();
    expect(createRevision).toHaveBeenCalledTimes(1);
  });

  test("places adoption oversight after publication and before revision history", async () => {
    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        eneo: {
          skills: {
            organization: {
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              get: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    const content = document
      .querySelector("#organization-skill-content-heading")
      ?.closest("section");
    const approved = document
      .querySelector("#organization-skill-approved-heading")
      ?.closest("section");
    const publication = document.querySelector("aside[aria-labelledby]");
    await expect
      .element(
        page.getByRole("heading", {
          name: m.organization_skills_adoption_heading()
        })
      )
      .toBeVisible();
    const adoption = document
      .querySelector("#organization-skill-adoption-heading")
      ?.closest("section");
    const history = document
      .querySelector("#organization-skill-history-heading")
      ?.closest("section");

    expect(content).not.toBeNull();
    expect(approved).not.toBeNull();
    expect(publication).not.toBeNull();
    expect(adoption).not.toBeNull();
    expect(history).not.toBeNull();
    expect(content?.compareDocumentPosition(approved as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
    expect(approved?.compareDocumentPosition(publication as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
    expect(publication?.compareDocumentPosition(adoption as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
    expect(adoption?.compareDocumentPosition(history as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
  });

  test("unpublishes an approved revision while a newer draft remains pending", async () => {
    const publish = vi.fn(async () => {});
    const unpublish = vi.fn(async () => {});

    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        eneo: {
          skills: {
            organization: {
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish,
              restoreRevision: vi.fn(),
              unpublish
            }
          }
        }
      } as never
    });

    await expect
      .element(page.getByRole("button", { name: m.organization_skills_publish_update_action() }))
      .toBeVisible();
    await page
      .getByRole("button", { name: m.organization_skills_unpublish_action(), exact: true })
      .click();
    await expect
      .element(page.getByRole("heading", { name: m.organization_skills_unpublish_title() }))
      .toBeVisible();

    await page
      .getByRole("button", { name: m.organization_skills_unpublish_action(), exact: true })
      .last()
      .click();

    await vi.waitFor(() =>
      expect(unpublish).toHaveBeenCalledWith({
        skillId: "skill-1"
      })
    );
    expect(publish).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith("organization:skills"));
  });

  test("keeps a publication change committed when refreshing the page data fails", async () => {
    const unpublish = vi.fn(async () => {});
    invalidate.mockRejectedValueOnce(new Error("Refresh failed"));

    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        eneo: {
          skills: {
            organization: {
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish
            }
          }
        }
      } as never
    });

    await page
      .getByRole("button", { name: m.organization_skills_unpublish_action(), exact: true })
      .click();
    await page
      .getByRole("button", { name: m.organization_skills_unpublish_action(), exact: true })
      .last()
      .click();

    await vi.waitFor(() => expect(unpublish).toHaveBeenCalledTimes(1));
    await expect
      .element(page.getByText(m.organization_skills_refresh_after_mutation_warning()))
      .toBeVisible();
    await expect
      .element(page.getByRole("heading", { name: m.organization_skills_unpublish_title() }))
      .not.toBeInTheDocument();
  });
});
