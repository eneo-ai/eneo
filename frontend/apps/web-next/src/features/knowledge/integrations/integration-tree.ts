import type { IntegrationKnowledge } from "../knowledge";
import { matchesSearch, searchTerms } from "@/lib/search";

export type IntegrationTreeNode = {
  item: IntegrationKnowledge;
  children: IntegrationTreeNode[];
};

export type IntegrationTreeRow = {
  item: IntegrationKnowledge;
  depth: number;
  hasChildren: boolean;
  expanded: boolean;
};

/** A comparable form of a SharePoint folder path; null when the item has none (whole site). */
export function folderPathKey(path: string | null | undefined): string | null {
  const trimmed = (path ?? "").trim().replace(/\\/g, "/").replace(/\/+$/, "");
  if (trimmed === "" || trimmed === "/") return null;
  const withRoot = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  return withRoot.toLowerCase();
}

/**
 * Items nested by their SharePoint folder path: an item sits under the item
 * whose path is its longest strict prefix. Whole-site imports (no path) come
 * first; an identical path twice makes siblings, never a parent. Siblings are
 * in `compare`'s order: the locale's collator (Astryx `useCollator().compare`),
 * so the server's HTML and the browser's render agree.
 */
export function buildIntegrationTree(
  items: IntegrationKnowledge[],
  compare: Intl.Collator["compare"]
): IntegrationTreeNode[] {
  const byName = (a: IntegrationTreeNode, b: IntegrationTreeNode) =>
    compare(a.item.name, b.item.name);
  const siteRoots: IntegrationTreeNode[] = [];
  const keyed: { key: string; node: IntegrationTreeNode }[] = [];

  for (const item of items) {
    const key = folderPathKey(item.folder_path);
    const node: IntegrationTreeNode = { item, children: [] };
    if (key === null) siteRoots.push(node);
    else keyed.push({ key, node });
  }
  // Parents are shorter than their children, so placing short keys first
  // guarantees every parent exists before its children look for it.
  keyed.sort((a, b) => a.key.length - b.key.length || byName(a.node, b.node));

  const pathRoots: IntegrationTreeNode[] = [];
  const placed: { key: string; node: IntegrationTreeNode }[] = [];
  for (const entry of keyed) {
    let parent: { key: string; node: IntegrationTreeNode } | null = null;
    for (const candidate of placed) {
      if (!entry.key.startsWith(`${candidate.key}/`)) continue;
      if (!parent || candidate.key.length > parent.key.length) parent = candidate;
    }
    (parent ? parent.node.children : pathRoots).push(entry.node);
    placed.push(entry);
  }

  const sortChildren = (node: IntegrationTreeNode) => {
    node.children.sort(byName);
    node.children.forEach(sortChildren);
  };
  siteRoots.sort(byName);
  pathRoots.sort(byName);
  pathRoots.forEach(sortChildren);
  return [...siteRoots, ...pathRoots];
}

/** Nodes whose name matches, plus the ancestors needed to reach a matching descendant. */
export function filterIntegrationTree(
  nodes: IntegrationTreeNode[],
  query: string
): IntegrationTreeNode[] {
  if (searchTerms(query).length === 0) return nodes;
  const result: IntegrationTreeNode[] = [];
  for (const node of nodes) {
    const children = filterIntegrationTree(node.children, query);
    if (matchesSearch([node.item.name], query) || children.length > 0) {
      result.push({ item: node.item, children });
    }
  }
  return result;
}

/** The rows to render top-down; collapsed parents hide their subtree. */
export function flattenIntegrationTree(
  nodes: IntegrationTreeNode[],
  isExpanded: (item: IntegrationKnowledge) => boolean,
  depth = 0
): IntegrationTreeRow[] {
  const rows: IntegrationTreeRow[] = [];
  for (const node of nodes) {
    const hasChildren = node.children.length > 0;
    const expanded = hasChildren && isExpanded(node.item);
    rows.push({ item: node.item, depth, hasChildren, expanded });
    if (expanded) rows.push(...flattenIntegrationTree(node.children, isExpanded, depth + 1));
  }
  return rows;
}
