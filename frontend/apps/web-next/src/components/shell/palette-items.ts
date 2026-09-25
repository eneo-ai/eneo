import { createStaticSource } from "@astryxdesign/core/Typeahead";
import type { Schema } from "@/lib/api/models";
import type { AdminNavGroup } from "./admin-nav-items";
import { conversationHref, NEW_CONVERSATION_HREF } from "./routes";

/** Result groups, in the order the palette shows them. */
export const PALETTE_GROUPS = [
  "assistants",
  "spaces",
  "conversations",
  "knowledge",
  "actions"
] as const;
export type PaletteGroup = (typeof PALETTE_GROUPS)[number];

export type PaletteVisual =
  | { type: "entity"; id: string; name: string }
  | {
      type: "icon";
      icon: "personal" | "conversation" | "collection" | "website" | "compose" | "create" | "admin";
    };

export type PaletteEntry = {
  id: string;
  label: string;
  /** Secondary line: where the result lives. */
  subtitle?: string;
  group: PaletteGroup;
  action: { type: "navigate"; href: string } | { type: "create-space" };
  visual: PaletteVisual;
  /** Extra text the query also matches (e.g. the space an assistant lives in). */
  keywords?: string[];
  /** Only offered once the user types (keeps the empty palette short). */
  searchOnly?: boolean;
};

type Translate = (key: string, values?: Record<string, string>) => string;

export type PaletteData = {
  dashboard: Schema<"Dashboard"> | null;
  spaces: Schema<"SpaceSparse">[] | null;
  conversations: Schema<"SessionMetadataPublic">[];
  /** The space the user is in, for its collections and websites ("Kunskap"). */
  currentSpace: { routeId: string; space: Schema<"SpacePublic"> } | null;
};

export type PalettePermissions = {
  canCreateSpace: boolean;
  isAdmin: boolean;
  adminGroups: AdminNavGroup[];
};

function spaceLabel(space: { personal: boolean; name: string }, t: Translate) {
  return space.personal ? t("personal") : space.name;
}

/**
 * Everything the ⌘K palette can find, in group order. Built from queries the
 * app already has (dashboard, spaces list, personal conversations, the
 * current space); no search endpoint is involved.
 */
export function buildPaletteEntries(
  data: PaletteData,
  permissions: PalettePermissions,
  t: Translate
): PaletteEntry[] {
  const entries: PaletteEntry[] = [];

  for (const space of data.dashboard?.spaces.items ?? []) {
    const spaceName = spaceLabel(space, t);
    if (space.personal && space.default_assistant) {
      entries.push({
        id: `assistant:${space.default_assistant.id}`,
        label: t("personal_assistant"),
        subtitle: t("personal"),
        group: "assistants",
        action: { type: "navigate", href: NEW_CONVERSATION_HREF },
        visual: { type: "icon", icon: "personal" }
      });
    }
    for (const assistant of space.applications?.assistants.items ?? []) {
      entries.push({
        id: `assistant:${assistant.id}`,
        label: assistant.name,
        subtitle: t("shell_palette_assistant_in_space", { space: spaceName }),
        group: "assistants",
        action: { type: "navigate", href: `/dashboard/${assistant.id}?tab=chat` },
        visual: { type: "entity", id: assistant.id, name: assistant.name },
        keywords: [spaceName]
      });
    }
  }

  entries.push({
    id: "space:personal",
    label: t("personal"),
    group: "spaces",
    action: { type: "navigate", href: "/spaces/personal/overview" },
    visual: { type: "icon", icon: "personal" }
  });
  for (const space of data.spaces ?? []) {
    if (space.personal || space.organization) continue;
    entries.push({
      id: `space:${space.id}`,
      label: space.name,
      subtitle: space.description?.trim() || undefined,
      group: "spaces",
      action: { type: "navigate", href: `/spaces/${space.id}/overview` },
      visual: { type: "entity", id: space.id, name: space.name }
    });
  }
  if (permissions.isAdmin) {
    entries.push({
      id: "space:organization",
      label: t("organization"),
      group: "spaces",
      action: { type: "navigate", href: "/spaces/organization/knowledge" },
      visual: { type: "icon", icon: "admin" }
    });
  }

  for (const conversation of data.conversations) {
    entries.push({
      id: `conversation:${conversation.id}`,
      label: conversation.name.trim() || t("shell_untitled_conversation"),
      group: "conversations",
      action: { type: "navigate", href: conversationHref(conversation.id) },
      visual: { type: "icon", icon: "conversation" }
    });
  }

  if (data.currentSpace) {
    const { routeId, space } = data.currentSpace;
    const spaceName = spaceLabel(space, t);
    for (const collection of space.knowledge.groups.items) {
      entries.push({
        id: `collection:${collection.id}`,
        label: collection.name,
        subtitle: t("shell_palette_collection_in_space", { space: spaceName }),
        group: "knowledge",
        action: {
          type: "navigate",
          href: `/spaces/${routeId}/knowledge/collections/${collection.id}`
        },
        visual: { type: "icon", icon: "collection" }
      });
    }
    for (const website of space.knowledge.websites.items) {
      entries.push({
        id: `website:${website.id}`,
        label: website.name?.trim() || website.url,
        subtitle: t("shell_palette_website_in_space", { space: spaceName }),
        group: "knowledge",
        action: { type: "navigate", href: `/spaces/${routeId}/knowledge/websites/${website.id}` },
        visual: { type: "icon", icon: "website" },
        keywords: [website.url]
      });
    }
  }

  entries.push({
    id: "action:new-conversation",
    label: t("new_conversation"),
    group: "actions",
    action: { type: "navigate", href: NEW_CONVERSATION_HREF },
    visual: { type: "icon", icon: "compose" }
  });
  if (permissions.canCreateSpace) {
    entries.push({
      id: "action:create-space",
      label: t("create_space"),
      group: "actions",
      action: { type: "create-space" },
      visual: { type: "icon", icon: "create" }
    });
  }
  if (permissions.isAdmin) {
    for (const group of permissions.adminGroups) {
      for (const item of group.items) {
        entries.push({
          id: `admin:${item.href}`,
          label: t("shell_palette_admin_page", { page: t(item.labelKey) }),
          group: "actions",
          action: { type: "navigate", href: item.href },
          visual: { type: "icon", icon: "admin" },
          searchOnly: true
        });
      }
    }
  }

  return entries;
}

/** Caps each group so one long list cannot push the others out of view. */
function limitPerGroup(entries: PaletteEntry[], perGroup: number): PaletteEntry[] {
  const counts = new Map<PaletteGroup, number>();
  return entries.filter((entry) => {
    const count = counts.get(entry.group) ?? 0;
    counts.set(entry.group, count + 1);
    return count < perGroup;
  });
}

/** What the palette shows before anything is typed. */
export function bootstrapEntries(entries: PaletteEntry[], perGroup = 5): PaletteEntry[] {
  return limitPerGroup(
    entries.filter((entry) => !entry.searchOnly && entry.group !== "knowledge"),
    perGroup
  );
}

/**
 * Matches for a query, in group order: Astryx's static source matches the
 * label, and the subtitle and keywords as extra search terms.
 */
export async function searchEntries(
  entries: PaletteEntry[],
  query: string,
  perGroup = 6
): Promise<PaletteEntry[]> {
  if (!query.trim()) return bootstrapEntries(entries);
  const source = createStaticSource(entries, {
    keywords: (entry) => [entry.subtitle ?? "", ...(entry.keywords ?? [])]
  });
  return limitPerGroup(await source.search(query), perGroup);
}

/** Splits text around the first occurrence of the query, for match highlighting. */
export function splitMatch(
  text: string,
  query: string
): { before: string; match: string; after: string } | null {
  const needle = query.toLowerCase().trim();
  if (!needle) return null;
  const index = text.toLowerCase().indexOf(needle);
  if (index < 0) return null;
  return {
    before: text.slice(0, index),
    match: text.slice(index, index + needle.length),
    after: text.slice(index + needle.length)
  };
}
