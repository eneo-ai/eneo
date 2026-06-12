import type { Collection, IntegrationKnowledge, Website } from "../knowledge";

/**
 * Pure logic for the knowledge picker (unit-tested), ported from the Svelte
 * knowledgeOrigin.ts + knowledgeIntegration.ts + getAvailableKnowledge.ts.
 */

// --- Origin (personal vs organization) ---

type SpaceOwned = { space_id?: string | null };

export function isPersonalItem(item: SpaceOwned, currentSpaceId: string | undefined): boolean {
  const owner = item.space_id ?? undefined;
  return !owner || owner === currentSpaceId;
}

export function isOrgItem(
  item: SpaceOwned,
  currentSpaceId: string | undefined,
  orgSpaceId: string | undefined
): boolean {
  const owner = item.space_id ?? undefined;
  if (orgSpaceId) return owner === orgSpaceId;
  if (!currentSpaceId) return false;
  return Boolean(owner) && owner !== currentSpaceId;
}

export type KnowledgeOrigin = "personal" | "organization";

export function byOrigin<T extends SpaceOwned>(
  items: T[],
  origin: KnowledgeOrigin,
  currentSpaceId: string | undefined,
  orgSpaceId: string | undefined
): T[] {
  return items.filter((item) =>
    origin === "personal"
      ? isPersonalItem(item, currentSpaceId)
      : isOrgItem(item, currentSpaceId, orgSpaceId)
  );
}

// --- Integration wrappers ---

export type IntegrationWrapperOption = {
  id: string;
  name: string;
  items: IntegrationKnowledge[];
  integration_type: IntegrationKnowledge["integration_type"];
};

export type IntegrationEntry =
  | { type: "single"; key: string; knowledge: IntegrationKnowledge }
  | { type: "wrapper"; key: string; wrapper: IntegrationWrapperOption };

export function dedupeById<T extends { id: string }>(items: T[] = []): T[] {
  const seen = new Set<string>();
  return items.filter((item) => (seen.has(item.id) ? false : (seen.add(item.id), true)));
}

function wrapperName(knowledge: IntegrationKnowledge): string {
  const name = knowledge.wrapper_name;
  return typeof name === "string" && name.trim().length > 0 ? name : knowledge.name;
}

function groupByWrapper(items: IntegrationKnowledge[]): {
  wrappers: Map<string, IntegrationKnowledge[]>;
  singles: IntegrationKnowledge[];
} {
  const wrappers = new Map<string, IntegrationKnowledge[]>();
  const singles: IntegrationKnowledge[] = [];
  for (const knowledge of items) {
    if (!knowledge.wrapper_id) {
      singles.push(knowledge);
      continue;
    }
    const group = wrappers.get(knowledge.wrapper_id) ?? [];
    group.push(knowledge);
    wrappers.set(knowledge.wrapper_id, group);
  }
  return { wrappers, singles };
}

function sortEntries(entries: IntegrationEntry[]): IntegrationEntry[] {
  return entries.sort((a, b) => {
    const nameA = a.type === "wrapper" ? a.wrapper.name : a.knowledge.name;
    const nameB = b.type === "wrapper" ? b.wrapper.name : b.knowledge.name;
    return nameA.localeCompare(nameB);
  });
}

/**
 * Picker options for not-yet-selected integration knowledge. A wrapper is
 * offered as one option until every item under it is selected.
 */
export function integrationOptions(
  items: IntegrationKnowledge[],
  selected: ReadonlyArray<{ id: string }>
): IntegrationEntry[] {
  const selectedIds = new Set(selected.map((item) => item.id));
  const { wrappers, singles } = groupByWrapper(items);
  const options: IntegrationEntry[] = [];

  for (const [wrapperId, wrapperItems] of wrappers) {
    const first = wrapperItems[0];
    if (!first) continue;
    if (wrapperItems.every((item) => selectedIds.has(item.id))) continue;
    options.push({
      type: "wrapper",
      key: `wrapper:${wrapperId}`,
      wrapper: {
        id: wrapperId,
        name: wrapperName(first),
        items: wrapperItems,
        integration_type: first.integration_type
      }
    });
  }
  for (const knowledge of singles) {
    if (selectedIds.has(knowledge.id)) continue;
    options.push({ type: "single", key: `integration:${knowledge.id}`, knowledge });
  }
  return sortEntries(options);
}

/**
 * How to render the currently selected integration knowledge: a fully
 * selected wrapper collapses into one row, otherwise items show individually.
 */
export function selectedIntegrationDisplay(
  selected: IntegrationKnowledge[],
  allInOrigin: IntegrationKnowledge[]
): IntegrationEntry[] {
  const { wrappers: allWrappers } = groupByWrapper(allInOrigin);
  const { wrappers: selectedWrappers, singles } = groupByWrapper(selected);
  const display: IntegrationEntry[] = [];

  for (const [wrapperId, selectedItems] of selectedWrappers) {
    const first = selectedItems[0];
    if (!first) continue;
    const allItems = allWrappers.get(wrapperId) ?? [];
    const fullySelected = allItems.length > 0 && selectedItems.length >= allItems.length;
    if (!fullySelected) {
      for (const item of selectedItems) {
        display.push({ type: "single", key: `integration:${item.id}`, knowledge: item });
      }
      continue;
    }
    display.push({
      type: "wrapper",
      key: `wrapper:${wrapperId}`,
      wrapper: {
        id: wrapperId,
        name: wrapperName(first),
        items: allItems,
        integration_type: first.integration_type
      }
    });
  }
  for (const knowledge of singles) {
    display.push({ type: "single", key: `integration:${knowledge.id}`, knowledge });
  }
  return sortEntries(display);
}

// --- Available knowledge, sectioned per embedding model ---

export type KnowledgeSection = {
  modelId: string;
  name: string;
  isEnabled: boolean;
  isCompatible: boolean;
  collections: Collection[];
  websites: Website[];
  integrationKnowledge: IntegrationKnowledge[];
};

export type KnowledgeSelections = {
  collections: Collection[];
  websites: Website[];
  integrationKnowledge: IntegrationKnowledge[];
};

/**
 * Group the space's knowledge per embedding model, marking sections that are
 * incompatible with the dominant model of the current selection (knowledge on
 * one resource must share an embedding model) or not enabled in the space.
 * Already-selected and filter-mismatched items are dropped.
 */
export function availableKnowledge(
  space: {
    knowledge: {
      collections: Collection[];
      websites: Website[];
      integrationKnowledge: IntegrationKnowledge[];
    };
    embeddingModelIds: string[];
  },
  selected: KnowledgeSelections,
  filter?: string
): { sections: KnowledgeSection[]; showHeaders: boolean } {
  const matches = (value?: string | null) =>
    !filter || (value ?? "").toLowerCase().includes(filter.toLowerCase());

  const dominantModelId =
    selected.collections[0]?.embedding_model.id ??
    selected.websites[0]?.embedding_model.id ??
    selected.integrationKnowledge[0]?.embedding_model.id ??
    null;

  const selectedIds = new Set([
    ...selected.collections.map((item) => item.id),
    ...selected.websites.map((item) => item.id),
    ...selected.integrationKnowledge.map((item) => item.id)
  ]);

  const sections = new Map<string, KnowledgeSection>();
  function sectionFor(model: { id: string; name: string }): KnowledgeSection {
    let section = sections.get(model.id);
    if (!section) {
      section = {
        modelId: model.id,
        name: model.name,
        isEnabled: space.embeddingModelIds.includes(model.id),
        isCompatible: dominantModelId ? dominantModelId === model.id : true,
        collections: [],
        websites: [],
        integrationKnowledge: []
      };
      sections.set(model.id, section);
    }
    return section;
  }

  for (const collection of space.knowledge.collections) {
    const section = sectionFor(collection.embedding_model);
    if (!section.isCompatible || selectedIds.has(collection.id)) continue;
    if (!matches(collection.name)) continue;
    section.collections.push(collection);
  }
  for (const website of space.knowledge.websites) {
    const section = sectionFor(website.embedding_model);
    if (!section.isCompatible || selectedIds.has(website.id)) continue;
    if (!(matches(website.url) || matches(website.name))) continue;
    section.websites.push(website);
  }
  for (const knowledge of space.knowledge.integrationKnowledge) {
    const section = sectionFor(knowledge.embedding_model);
    if (!section.isCompatible || selectedIds.has(knowledge.id)) continue;
    if (!(matches(knowledge.name) || matches(knowledge.wrapper_name))) continue;
    section.integrationKnowledge.push(knowledge);
  }

  return { sections: [...sections.values()], showHeaders: sections.size > 1 };
}
