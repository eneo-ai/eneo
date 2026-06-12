import type { IntegrationKnowledge } from "../knowledge";

/** Pure wrapper-grouping logic for the integrations list (unit-tested). */

export type SharePointItemTypeCounts = {
  files: number;
  folders: number;
  sites: number;
  unknown: number;
  total: number;
};

export function countSharePointItemTypes(items: IntegrationKnowledge[]): SharePointItemTypeCounts {
  const counts = { files: 0, folders: 0, sites: 0, unknown: 0, total: items.length };
  for (const item of items) {
    const itemType = (item.selected_item_type ?? "").toLowerCase();
    if (itemType === "file") counts.files += 1;
    else if (itemType === "folder") counts.folders += 1;
    else if (itemType === "site_root" || itemType === "site") counts.sites += 1;
    else counts.unknown += 1;
  }
  return counts;
}

export type IntegrationRow =
  | {
      kind: "wrapper";
      wrapperId: string;
      wrapperName: string;
      items: IntegrationKnowledge[];
      counts: SharePointItemTypeCounts;
      embeddingModelId: string;
    }
  | { kind: "item"; item: IntegrationKnowledge; embeddingModelId: string };

export function wrapperDisplayName(item: IntegrationKnowledge): string {
  return typeof item.wrapper_name === "string" && item.wrapper_name.trim().length > 0
    ? item.wrapper_name
    : item.name;
}

/**
 * SharePoint items sharing a wrapper_id collapse into one folder row once the
 * wrapper holds at least two items; everything else stays a plain row. Rows
 * come back sorted alphabetically. Ported from IntegrationsTable.svelte.
 */
export function groupIntegrationRows(items: IntegrationKnowledge[]): IntegrationRow[] {
  const wrappers = new Map<string, IntegrationKnowledge[]>();
  const standalone: IntegrationKnowledge[] = [];

  for (const item of items) {
    if (item.wrapper_id && item.integration_type === "sharepoint") {
      const group = wrappers.get(item.wrapper_id) ?? [];
      group.push(item);
      wrappers.set(item.wrapper_id, group);
    } else {
      standalone.push(item);
    }
  }

  const rows: { sortKey: string; row: IntegrationRow }[] = [];

  for (const [wrapperId, wrapperItems] of wrappers) {
    const first = wrapperItems[0];
    if (first && wrapperItems.length >= 2) {
      const wrapperName = wrapperDisplayName(first);
      rows.push({
        sortKey: wrapperName.toLowerCase(),
        row: {
          kind: "wrapper",
          wrapperId,
          wrapperName,
          items: wrapperItems,
          counts: countSharePointItemTypes(wrapperItems),
          embeddingModelId: first.embedding_model.id
        }
      });
    } else {
      for (const item of wrapperItems) standalone.push(item);
    }
  }

  for (const item of standalone) {
    rows.push({
      sortKey: item.name.toLowerCase(),
      row: { kind: "item", item, embeddingModelId: item.embedding_model.id }
    });
  }

  rows.sort((a, b) => a.sortKey.localeCompare(b.sortKey));
  return rows.map((entry) => entry.row);
}
