import type { IntegrationKnowledge } from "@intric/intric-js";

/** A group of integration-knowledge items that share a wrapper (e.g. a SharePoint site). */
export type IntegrationWrapperOption = {
  id: string;
  name: string;
  items: IntegrationKnowledge[];
  integration_type: IntegrationKnowledge["integration_type"];
};

/** A single integration item or a whole wrapper, as shown in the picker / selected list. */
export type IntegrationEntry =
  | { type: "single"; key: string; knowledge: IntegrationKnowledge }
  | { type: "wrapper"; key: string; wrapper: IntegrationWrapperOption };

/** Structured (i18n-agnostic) count badge; the rendering component maps `type` to a message. */
export type WrapperCountBadge = {
  type: "files" | "folders" | "sites" | "items";
  count: number;
};

export function getSortedWrapperItems(items: IntegrationKnowledge[]): IntegrationKnowledge[] {
  return [...items].sort((a, b) => a.name.localeCompare(b.name));
}

/** Drop duplicate-by-id entries, keeping the first occurrence and preserving order. */
export function dedupeById<T extends { id: string }>(arr: T[] = []): T[] {
  const seen = new Set<string>();
  return arr.filter((x) => (seen.has(x.id) ? false : (seen.add(x.id), true)));
}

export function isWrapperFolderItem(item: IntegrationKnowledge): boolean {
  const itemType = (item.selected_item_type ?? "").toLowerCase();
  return itemType === "folder" || itemType === "site_root";
}

export function getWrapperItemTypeCounts(items: IntegrationKnowledge[]) {
  let files = 0;
  let folders = 0;
  let sites = 0;
  let unknown = 0;

  for (const item of items) {
    const itemType = (item.selected_item_type ?? "").toLowerCase();
    if (itemType === "file") {
      files += 1;
    } else if (itemType === "folder") {
      folders += 1;
    } else if (itemType === "site_root" || itemType === "site") {
      sites += 1;
    } else {
      unknown += 1;
    }
  }

  return { files, folders, sites, unknown, total: items.length };
}

/**
 * Build the count badges for a wrapper. Falls back to a generic "items" badge when the
 * contents are untyped or no other badge applies, so a wrapper never renders without a count.
 */
export function getWrapperCountBadges(items: IntegrationKnowledge[]): WrapperCountBadge[] {
  const counts = getWrapperItemTypeCounts(items);
  const badges: WrapperCountBadge[] = [];

  if (counts.files > 0) badges.push({ type: "files", count: counts.files });
  if (counts.folders > 0) badges.push({ type: "folders", count: counts.folders });
  if (counts.sites > 0) badges.push({ type: "sites", count: counts.sites });
  if (counts.unknown > 0 || badges.length === 0) {
    badges.push({ type: "items", count: counts.unknown > 0 ? counts.unknown : counts.total });
  }

  return badges;
}

export function getWrapperId(knowledge: IntegrationKnowledge): string | undefined {
  return knowledge.wrapper_id ?? undefined;
}

export function getWrapperName(knowledge: IntegrationKnowledge): string {
  const wrapperName = knowledge.wrapper_name;
  if (typeof wrapperName === "string" && wrapperName.trim().length > 0) {
    return wrapperName;
  }
  return knowledge.name;
}

/** Partition items into wrapper groups (keyed by wrapper id) and ungrouped singles. */
export function groupIntegrationByWrapper(knowledgeItems: IntegrationKnowledge[]): {
  wrappers: Map<string, IntegrationKnowledge[]>;
  singles: IntegrationKnowledge[];
} {
  const wrappers = new Map<string, IntegrationKnowledge[]>();
  const singles: IntegrationKnowledge[] = [];

  for (const knowledge of knowledgeItems) {
    const wrapperId = getWrapperId(knowledge);
    if (!wrapperId) {
      singles.push(knowledge);
      continue;
    }
    const existing = wrappers.get(wrapperId) ?? [];
    existing.push(knowledge);
    wrappers.set(wrapperId, existing);
  }

  return { wrappers, singles };
}

function sortEntriesByName(entries: IntegrationEntry[]): IntegrationEntry[] {
  return entries.sort((a, b) => {
    const nameA = a.type === "wrapper" ? a.wrapper.name : a.knowledge.name;
    const nameB = b.type === "wrapper" ? b.wrapper.name : b.knowledge.name;
    return nameA.localeCompare(nameB);
  });
}

/**
 * Picker options for the available (not-yet-selected) integration knowledge. A wrapper is offered
 * as a single option until every item under it is selected, after which it drops out entirely.
 */
export function getIntegrationKnowledgeOptions(
  knowledgeItems: IntegrationKnowledge[],
  selectedItems: ReadonlyArray<{ id: string }>
): IntegrationEntry[] {
  const selectedIds = new Set(selectedItems.map((item) => item.id));
  const { wrappers, singles } = groupIntegrationByWrapper(knowledgeItems);
  const options: IntegrationEntry[] = [];

  for (const [wrapperId, items] of wrappers.entries()) {
    if (items.length === 0) continue;
    if (items.every((item) => selectedIds.has(item.id))) continue;

    const first = items[0];
    options.push({
      type: "wrapper",
      key: `wrapper:${wrapperId}`,
      wrapper: {
        id: wrapperId,
        name: getWrapperName(first),
        items,
        integration_type: first.integration_type
      }
    });
  }

  for (const knowledge of singles) {
    if (selectedIds.has(knowledge.id)) continue;
    options.push({ type: "single", key: `integration:${knowledge.id}`, knowledge });
  }

  return sortEntriesByName(options);
}

/**
 * How to render the currently selected integration knowledge: a wrapper that is fully selected
 * collapses into a single wrapper row, otherwise its selected items are shown individually.
 */
export function getSelectedIntegrationDisplay(
  selectedItems: IntegrationKnowledge[],
  allItemsInOrigin: IntegrationKnowledge[]
): IntegrationEntry[] {
  const { wrappers: allWrapperGroups } = groupIntegrationByWrapper(allItemsInOrigin);
  const { wrappers: selectedWrapperGroups, singles } = groupIntegrationByWrapper(selectedItems);
  const display: IntegrationEntry[] = [];

  for (const [wrapperId, selectedGroupItems] of selectedWrapperGroups.entries()) {
    const allGroupItems = allWrapperGroups.get(wrapperId) ?? [];
    const isFullySelected =
      allGroupItems.length > 0 && selectedGroupItems.length >= allGroupItems.length;

    if (!isFullySelected) {
      for (const item of selectedGroupItems) {
        display.push({ type: "single", key: `integration:${item.id}`, knowledge: item });
      }
      continue;
    }

    const first = selectedGroupItems[0];
    display.push({
      type: "wrapper",
      key: `wrapper:${wrapperId}`,
      wrapper: {
        id: wrapperId,
        name: getWrapperName(first),
        items: allGroupItems,
        integration_type: first.integration_type
      }
    });
  }

  for (const knowledge of singles) {
    display.push({ type: "single", key: `integration:${knowledge.id}`, knowledge });
  }

  return sortEntriesByName(display);
}
