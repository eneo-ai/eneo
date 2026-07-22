import type {
  SkillRevisionPublic,
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
      onLoadMore: vi.fn(),
      onView
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

  test("loads each older cursor page once and appends it", async () => {
    const current = revision(4);
    const onLoadMore = vi.fn(async () =>
      revisionPage([summary(revision(2)), summary(revision(1))], null)
    );

    render(SkillRevisionHistory, {
      currentRevision: current,
      initialPage: revisionPage([summary(current), summary(revision(3))], "3"),
      onLoadMore,
      onView: vi.fn()
    });

    await page.getByRole("button", { name: m.skills_library_load_older() }).click();

    await vi.waitFor(() => expect(onLoadMore).toHaveBeenCalledWith("3"));
    await expect.element(page.getByText(m.skills_revision_label({ revision: "1" }))).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: m.skills_library_load_older() }))
      .not.toBeInTheDocument();
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
      onLoadMore,
      onView: vi.fn()
    });

    await page.getByRole("button", { name: m.skills_library_load_older() }).click();
    await expect.element(page.getByText(m.request_failed())).toBeVisible();
    await page.getByRole("button", { name: m.skills_library_load_older() }).click();

    await vi.waitFor(() => expect(onLoadMore).toHaveBeenCalledTimes(2));
    await expect.element(page.getByText(m.skills_revision_label({ revision: "1" }))).toBeVisible();
  });

  test("shows a scoped error when one historical preview cannot load", async () => {
    const current = revision(2);

    render(SkillRevisionHistory, {
      currentRevision: current,
      initialPage: revisionPage([summary(current), summary(revision(1))], null),
      onLoadMore: vi.fn(),
      onView: vi.fn().mockRejectedValue(new Error("Preview unavailable"))
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
