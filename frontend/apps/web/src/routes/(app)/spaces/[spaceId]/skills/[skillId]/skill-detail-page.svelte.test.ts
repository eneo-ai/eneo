import type {
  SkillPublic,
  SkillRevisionPublic,
  SkillRevisionRestorePublic,
  SkillRevisionSummaryPage
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

import SkillDetailPage from "./+page.svelte";

function revision(revisionNumber: number): SkillRevisionPublic {
  return {
    id: `revision-${revisionNumber}`,
    skill_id: "skill-1",
    revision_number: revisionNumber,
    display_name: `HR guidance ${revisionNumber}`,
    description: `Description ${revisionNumber}`,
    instructions: `Instructions ${revisionNumber}`,
    content_digest: String(revisionNumber).repeat(64),
    created_by_user_id: "user-1",
    created_at: `2026-07-${String(revisionNumber).padStart(2, "0")}T12:00:00Z`
  };
}

function revisionPage(
  current: SkillRevisionPublic,
  historical: SkillRevisionPublic
): SkillRevisionSummaryPage {
  return {
    items: [current, historical].map((item) => ({
      id: item.id,
      skill_id: item.skill_id,
      revision_number: item.revision_number,
      display_name: item.display_name,
      created_at: item.created_at
    })),
    count: 2,
    limit: 25,
    next_cursor: null,
    previous_cursor: null,
    total_count: 2
  };
}

function skill(currentRevision: SkillRevisionPublic): SkillPublic {
  return {
    id: currentRevision.skill_id,
    space_id: "space-1",
    slug: "hr-guidance",
    is_active: true,
    current_revision_id: currentRevision.id,
    current_revision_number: currentRevision.revision_number,
    display_name: currentRevision.display_name,
    description: currentRevision.description,
    content_digest: currentRevision.content_digest,
    created_by_user_id: "user-1",
    created_at: "2026-07-01T12:00:00Z",
    updated_at: currentRevision.created_at,
    current_revision: currentRevision
  };
}

describe("Skill detail page", () => {
  beforeEach(() => {
    invalidate.mockClear();
  });

  test("refreshes when restore reports a concurrent newer current revision", async () => {
    const visibleCurrent = revision(2);
    const historical = revision(1);
    const newerCurrent = revision(3);
    const outcome: SkillRevisionRestorePublic = {
      revision: newerCurrent,
      created: false,
      restored_from_revision_id: historical.id,
      restored_from_revision_number: historical.revision_number
    };

    render(SkillDetailPage, {
      data: {
        currentSpace: {
          id: "space-1",
          personal: false,
          organization: false,
          skill_permissions: ["read", "edit"]
        },
        skill: skill(visibleCurrent),
        revisionPage: revisionPage(visibleCurrent, historical),
        eneo: {
          skills: {
            createRevision: vi.fn(),
            getRevision: vi.fn(async () => historical),
            listRevisionSummaries: vi.fn(),
            restoreRevision: vi.fn(async () => outcome),
            setActive: vi.fn()
          }
        }
      } as never
    });

    await page
      .getByRole("button", {
        name: m.skills_library_view_revision_aria({ revision: "1" })
      })
      .click();
    await page
      .getByRole("button", { name: m.skills_library_restore_revision_from_preview() })
      .click();
    await page.getByRole("button", { name: m.skills_library_restore_action() }).click();

    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith("space:skills"));
  });
});
