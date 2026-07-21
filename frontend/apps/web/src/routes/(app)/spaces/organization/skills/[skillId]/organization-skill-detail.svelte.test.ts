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

describe("organisation Skill detail page", () => {
  beforeEach(() => {
    invalidate.mockClear();
  });

  test("unpublishes an approved revision while a newer draft remains pending", async () => {
    const publish = vi.fn(async () => {});
    const unpublish = vi.fn(async () => {});

    render(OrganizationSkillDetailPage, {
      data: {
        mode: "manage",
        canManage: true,
        canPublish: true,
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        eneo: {
          skills: {
            organization: {
              createRevision: vi.fn(),
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
});
