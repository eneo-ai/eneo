import type { SkillSparse } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { SKILL_CATALOG_PAGE_SIZE, type SkillCatalogPage } from "./skillCatalog";
import { SkillCatalogQuery } from "./skillCatalogQuery.svelte";

function makeSkill(id: string): SkillSparse {
  return {
    id,
    space_id: "space-1",
    slug: `skill-${id}`,
    is_active: true,
    current_revision_id: `${id}-revision-1`,
    current_revision_number: 1,
    display_name: `Skill ${id}`,
    description: `Description ${id}`,
    content_digest: `digest-${id}`,
    created_by_user_id: "user-1",
    created_at: "2026-07-15T12:00:00Z",
    updated_at: "2026-07-15T12:00:00Z"
  };
}

function makePage(items: SkillSparse[], nextCursor: string | null = null): SkillCatalogPage {
  return {
    items,
    count: items.length,
    total_count: items.length,
    limit: SKILL_CATALOG_PAGE_SIZE,
    next_cursor: nextCursor,
    previous_cursor: null
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("SkillCatalogQuery", () => {
  test("uses bounded server search and ignores an older response", async () => {
    vi.useFakeTimers();
    let catalog: SkillCatalogQuery<SkillSparse> | undefined;
    try {
      const older = deferred<SkillCatalogPage>();
      const newer = deferred<SkillCatalogPage>();
      const list = vi.fn(({ query }: { query?: string | null }) => {
        return query === "older" ? older.promise : newer.promise;
      });
      catalog = new SkillCatalogQuery(makePage([makeSkill("initial")]), list);

      catalog.setQuery("older");
      await vi.advanceTimersByTimeAsync(250);
      catalog.setQuery("newer");
      await vi.advanceTimersByTimeAsync(250);

      newer.resolve(makePage([makeSkill("newer")]));
      await newer.promise;
      older.resolve(makePage([makeSkill("older")]));
      await older.promise;
      await Promise.resolve();

      expect(list).toHaveBeenNthCalledWith(1, {
        limit: SKILL_CATALOG_PAGE_SIZE,
        cursor: null,
        query: "older"
      });
      expect(list).toHaveBeenNthCalledWith(2, {
        limit: SKILL_CATALOG_PAGE_SIZE,
        cursor: null,
        query: "newer"
      });
      expect(catalog.items.map((skill) => skill.id)).toEqual(["newer"]);
    } finally {
      catalog?.dispose();
      vi.useRealTimers();
    }
  });

  test("appends a page once even when it overlaps the previous page", async () => {
    const first = makeSkill("first");
    const second = makeSkill("second");
    const list = vi.fn().mockResolvedValue(makePage([first, second]));
    const catalog = new SkillCatalogQuery(makePage([first], "skill-first"), list);

    await catalog.loadMore();

    expect(list).toHaveBeenCalledWith({
      limit: SKILL_CATALOG_PAGE_SIZE,
      cursor: "skill-first",
      query: null
    });
    expect(catalog.items.map((skill) => skill.id)).toEqual(["first", "second"]);
    expect(catalog.nextCursor).toBeNull();
  });

  test("resets stale local results when loader data changes", () => {
    const catalog = new SkillCatalogQuery(makePage([makeSkill("removed")]), vi.fn());

    catalog.reset(makePage([makeSkill("remaining")]));

    expect(catalog.items.map((skill) => skill.id)).toEqual(["remaining"]);
    expect(catalog.query).toBe("");
    expect(catalog.error).toBeNull();
  });

  test("keeps a failed request retryable", async () => {
    const recovered = makeSkill("recovered");
    const list = vi
      .fn()
      .mockRejectedValueOnce(new Error("Catalog unavailable"))
      .mockResolvedValueOnce(makePage([recovered]));
    const catalog = new SkillCatalogQuery(makePage([]), list);

    await catalog.reload();
    expect(catalog.error).not.toBeNull();
    expect(catalog.loading).toBe(false);

    await catalog.retry();
    expect(catalog.error).toBeNull();
    expect(catalog.items).toEqual([recovered]);
  });
});
