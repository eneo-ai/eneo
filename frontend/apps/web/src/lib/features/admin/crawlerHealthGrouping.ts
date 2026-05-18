/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
 * See the LICENSE file at the repository root for the full license text.
 */

export type CrawlerHealthGroup<T> = {
  readonly representative: T;
  readonly count: number;
  readonly firstFinishedAt: string;
  readonly latestFinishedAt: string;
};

export function groupCrawlerHealthRows<
  T extends { readonly website_id: string; readonly finished_at: string }
>(items: readonly T[], outcomeKey: (item: T) => string): readonly CrawlerHealthGroup<T>[] {
  type MutableGroup = {
    representative: T;
    count: number;
    firstFinishedAt: string;
    latestFinishedAt: string;
  };
  const byKey = new Map<string, MutableGroup>();
  for (const item of items) {
    const key = `${item.website_id}|${outcomeKey(item)}`;
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, {
        representative: item,
        count: 1,
        firstFinishedAt: item.finished_at,
        latestFinishedAt: item.finished_at
      });
      continue;
    }
    existing.count++;
    if (item.finished_at > existing.latestFinishedAt) {
      existing.latestFinishedAt = item.finished_at;
      existing.representative = item;
    }
    if (item.finished_at < existing.firstFinishedAt) {
      existing.firstFinishedAt = item.finished_at;
    }
  }
  return [...byKey.values()].sort((a, b) => b.latestFinishedAt.localeCompare(a.latestFinishedAt));
}
