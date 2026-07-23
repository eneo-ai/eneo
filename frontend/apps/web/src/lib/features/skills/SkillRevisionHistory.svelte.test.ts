import type {
  SkillRevisionPublic,
  SkillRevisionRestorePublic,
  SkillRevisionSummaryPage,
  SkillRevisionSummaryPublic
} from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import SkillRevisionHistory from "./SkillRevisionHistory.svelte";

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

function summary(value: SkillRevisionPublic): SkillRevisionSummaryPublic {
  return {
    id: value.id,
    skill_id: value.skill_id,
    revision_number: value.revision_number,
    display_name: value.display_name,
    created_at: value.created_at
  };
}

function revisionPage(
  items: SkillRevisionSummaryPublic[],
  nextCursor: string | null
): SkillRevisionSummaryPage {
  return {
    items,
    count: items.length,
    limit: 2,
    next_cursor: nextCursor,
    previous_cursor: null,
    total_count: 4
  };
}

describe("SkillRevisionHistory", () => {
  test("reuses the current body and lazily fetches historical bodies", async () => {
    const current = revision(3);
    const historical = revision(2);
    const onView = vi.fn(async () => historical);

    render(SkillRevisionHistory, {
      currentRevision: current,
      initialPage: revisionPage([summary(current), summary(historical)], null),
      canRestore: false,
      hasUnsavedChanges: false,
      onLoadMore: vi.fn(),
      onView,
      onRestore: vi.fn(),
      onLoadCurrent: vi.fn(async () => current)
    });

    await page
      .getByRole("button", {
        name: m.skills_library_view_revision_aria({ revision: "3" })
      })
      .click();
    await expect.element(page.getByText(current.instructions)).toBeVisible();
    expect(onView).not.toHaveBeenCalled();
    await page.getByRole("button", { name: m.close() }).first().click();

    await page
      .getByRole("button", {
        name: m.skills_library_view_revision_aria({ revision: "2" })
      })
      .click();

    await vi.waitFor(() => expect(onView).toHaveBeenCalledWith(historical.id));
    await expect.element(page.getByText(historical.instructions)).toBeVisible();
  });

  test("previews and safely restores a historical revision as the next revision", async () => {
    const current = revision(3);
    const historical = revision(2);
    const restored = revision(4);
    const outcome: SkillRevisionRestorePublic = {
      revision: restored,
      created: true,
      restored_from_revision_id: historical.id,
      restored_from_revision_number: historical.revision_number
    };
    const onRestore = vi.fn(async () => outcome);
    const onView = vi.fn(async () => historical);
    const onAnnounce = vi.fn();
    const onRestored = vi.fn();

    render(SkillRevisionHistory, {
      currentRevision: current,
      initialPage: revisionPage([summary(current), summary(historical)], null),
      canRestore: true,
      hasUnsavedChanges: true,
      onLoadMore: vi.fn(),
      onView,
      onRestore,
      onLoadCurrent: vi.fn(async () => current),
      onAnnounce,
      onRestored
    });

    const viewRevisionTrigger = page.getByRole("button", {
      name: m.skills_library_view_revision_aria({ revision: "2" })
    });
    await viewRevisionTrigger.click();
    await vi.waitFor(() => expect(onView).toHaveBeenCalledWith(historical.id));
    await expect.element(page.getByText(historical.instructions)).toBeVisible();
    await expect.element(page.getByText(current.instructions)).toBeVisible();
    const comparisonDialog = page.getByRole("dialog");
    expect(comparisonDialog.element().querySelectorAll('[data-changed="true"]')).toHaveLength(3);
    await page
      .getByRole("button", { name: m.skills_library_restore_revision_from_preview() })
      .click();

    await expect
      .element(page.getByText(m.skills_library_restore_description({ revision: "2" })))
      .toBeVisible();
    await expect.element(page.getByText(m.skills_library_restore_unsaved_warning())).toBeVisible();
    await page.getByRole("button", { name: m.skills_library_restore_action() }).click();

    await vi.waitFor(() => expect(onRestore).toHaveBeenCalledWith(historical.id, current.id));
    await vi.waitFor(() =>
      expect(onAnnounce).toHaveBeenCalledWith(
        m.skills_library_restore_success({
          sourceRevision: "2",
          newRevision: "4"
        })
      )
    );
    await vi.waitFor(() => expect(onRestored).toHaveBeenCalledWith(outcome));
    await expect.element(viewRevisionTrigger).toHaveFocus();
  });

  test("returns focus to the viewed revision after cancelling restore", async () => {
    const current = revision(2);
    const historical = revision(1);

    render(SkillRevisionHistory, {
      currentRevision: current,
      initialPage: revisionPage([summary(current), summary(historical)], null),
      canRestore: true,
      hasUnsavedChanges: false,
      onLoadMore: vi.fn(),
      onView: vi.fn(async () => historical),
      onRestore: vi.fn(),
      onLoadCurrent: vi.fn(async () => current)
    });

    const viewRevisionTrigger = page.getByRole("button", {
      name: m.skills_library_view_revision_aria({ revision: "1" })
    });
    await viewRevisionTrigger.click();
    await page
      .getByRole("button", { name: m.skills_library_restore_revision_from_preview() })
      .click();
    await page.getByRole("button", { name: m.cancel() }).click();

    await expect.element(viewRevisionTrigger).toHaveFocus();
  });

  test("keeps the current form when restore is a no-op on the visible revision", async () => {
    const current = revision(2);
    const historical = revision(1);
    const outcome: SkillRevisionRestorePublic = {
      revision: current,
      created: false,
      restored_from_revision_id: historical.id,
      restored_from_revision_number: historical.revision_number
    };
    const onAnnounce = vi.fn();
    const onRestored = vi.fn();

    render(SkillRevisionHistory, {
      currentRevision: current,
      initialPage: revisionPage([summary(current), summary(historical)], null),
      canRestore: true,
      hasUnsavedChanges: true,
      onLoadMore: vi.fn(),
      onView: vi.fn(async () => historical),
      onRestore: vi.fn(async () => outcome),
      onLoadCurrent: vi.fn(async () => current),
      onAnnounce,
      onRestored
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

    await vi.waitFor(() =>
      expect(onAnnounce).toHaveBeenCalledWith(m.skills_library_restore_noop())
    );
    expect(onRestored).not.toHaveBeenCalled();
  });

  test("refreshes when a concurrent writer created a newer current revision", async () => {
    const visibleCurrent = revision(2);
    const historical = revision(1);
    const newerCurrent = revision(3);
    const outcome: SkillRevisionRestorePublic = {
      revision: newerCurrent,
      created: false,
      restored_from_revision_id: historical.id,
      restored_from_revision_number: historical.revision_number
    };
    const onRestored = vi.fn();

    render(SkillRevisionHistory, {
      currentRevision: visibleCurrent,
      initialPage: revisionPage([summary(visibleCurrent), summary(historical)], null),
      canRestore: true,
      hasUnsavedChanges: false,
      onLoadMore: vi.fn(),
      onView: vi.fn(async () => historical),
      onRestore: vi.fn(async () => outcome),
      onLoadCurrent: vi.fn(async () => newerCurrent),
      onRestored
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

    await vi.waitFor(() => expect(onRestored).toHaveBeenCalledWith(outcome));
  });

  test("loads each older cursor page once and appends it in revision order", async () => {
    const current = revision(4);
    const onLoadMore = vi.fn(async () =>
      revisionPage([summary(revision(2)), summary(revision(1))], null)
    );

    render(SkillRevisionHistory, {
      currentRevision: current,
      initialPage: revisionPage([summary(current), summary(revision(3))], "3"),
      canRestore: false,
      hasUnsavedChanges: false,
      onLoadMore,
      onView: vi.fn(),
      onRestore: vi.fn(),
      onLoadCurrent: vi.fn(async () => current)
    });

    await page.getByRole("button", { name: m.skills_library_load_older() }).click();

    await vi.waitFor(() => expect(onLoadMore).toHaveBeenCalledWith("3"));
    await expect.element(page.getByText(m.skills_revision_label({ revision: "1" }))).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: m.skills_library_load_older() }))
      .not.toBeInTheDocument();
  });

  test("labels the fixed-width revision table as a keyboard-scrollable region", async () => {
    const current = revision(2);

    render(SkillRevisionHistory, {
      currentRevision: current,
      initialPage: revisionPage([summary(current), summary(revision(1))], null),
      canRestore: false,
      hasUnsavedChanges: false,
      onLoadMore: vi.fn(),
      onView: vi.fn(),
      onRestore: vi.fn(),
      onLoadCurrent: vi.fn(async () => current)
    });

    const region = page.getByRole("region", {
      name: m.skills_library_history_heading()
    });
    await expect.element(region).toBeVisible();
    const regionElement = region.element();
    expect(regionElement.getAttribute("tabindex")).toBe("0");
    expect(regionElement).toBeInstanceOf(HTMLElement);
    if (!(regionElement instanceof HTMLElement))
      throw new Error("Expected a scrollable HTML region");
    regionElement.style.width = "320px";
    expect(regionElement.scrollWidth).toBeGreaterThan(regionElement.clientWidth);
  });

  test("keeps history usable when an older page fails and allows retry", async () => {
    const current = revision(2);
    const onLoadMore = vi
      .fn()
      .mockRejectedValueOnce(new Error("History unavailable"))
      .mockResolvedValueOnce(revisionPage([summary(revision(1))], null));

    render(SkillRevisionHistory, {
      currentRevision: current,
      initialPage: revisionPage([summary(current)], "2"),
      canRestore: false,
      hasUnsavedChanges: false,
      onLoadMore,
      onView: vi.fn(),
      onRestore: vi.fn(),
      onLoadCurrent: vi.fn(async () => current)
    });

    await page.getByRole("button", { name: m.skills_library_load_older() }).click();
    await expect.element(page.getByText(m.request_failed())).toBeVisible();
    await page.getByRole("button", { name: m.skills_library_load_older() }).click();

    await vi.waitFor(() => expect(onLoadMore).toHaveBeenCalledTimes(2));
    await expect.element(page.getByText(m.skills_revision_label({ revision: "1" }))).toBeVisible();
  });

  test("keeps the confirmation open when restore fails", async () => {
    const current = revision(2);
    const historical = revision(1);

    render(SkillRevisionHistory, {
      currentRevision: current,
      initialPage: revisionPage([summary(current), summary(historical)], null),
      canRestore: true,
      hasUnsavedChanges: false,
      onLoadMore: vi.fn(),
      onView: vi.fn(async () => historical),
      onRestore: vi.fn().mockRejectedValue(new Error("Restore unavailable")),
      onLoadCurrent: vi.fn(async () => current)
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

    await expect.element(page.getByText(m.request_failed())).toBeVisible();
    await expect
      .element(
        page.getByRole("heading", {
          name: m.skills_library_restore_title({ revision: "1" })
        })
      )
      .toBeVisible();
  });

  test("reloads the comparison after a restore conflict without discarding dirty edits", async () => {
    const visibleCurrent = revision(2);
    const historical = revision(1);
    const latestCurrent = revision(3);
    const conflict = Object.assign(new Error("The Skill changed after you reviewed it."), {
      status: 409
    });
    const onRestore = vi.fn().mockRejectedValue(conflict);
    const onLoadCurrent = vi.fn(async () => latestCurrent);

    render(SkillRevisionHistory, {
      currentRevision: visibleCurrent,
      initialPage: revisionPage([summary(visibleCurrent), summary(historical)], null),
      canRestore: true,
      hasUnsavedChanges: true,
      onLoadMore: vi.fn(),
      onView: vi.fn(async () => historical),
      onRestore,
      onLoadCurrent
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

    await vi.waitFor(() =>
      expect(onRestore).toHaveBeenCalledWith(historical.id, visibleCurrent.id)
    );
    await vi.waitFor(() => expect(onLoadCurrent).toHaveBeenCalledOnce());
    await expect.element(page.getByText(latestCurrent.instructions)).toBeVisible();
    await expect.element(page.getByText(historical.instructions)).toBeVisible();
    await expect.element(page.getByText(m.skills_library_restore_unsaved_warning())).toBeVisible();
  });

  test("keeps history usable when one revision preview cannot be loaded", async () => {
    const current = revision(2);
    const historical = revision(1);

    render(SkillRevisionHistory, {
      currentRevision: current,
      initialPage: revisionPage([summary(current), summary(historical)], null),
      canRestore: true,
      hasUnsavedChanges: false,
      onLoadMore: vi.fn(),
      onView: vi.fn().mockRejectedValue(new Error("Preview unavailable")),
      onRestore: vi.fn(),
      onLoadCurrent: vi.fn(async () => current)
    });

    await page
      .getByRole("button", {
        name: m.skills_library_view_revision_aria({ revision: "1" })
      })
      .click();

    await expect.element(page.getByText(m.request_failed())).toBeVisible();
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
  });
});
