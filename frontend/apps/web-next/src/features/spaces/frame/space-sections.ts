import type { ResourcePermission, Space, SpaceResource, SpaceRouteId } from "../space";

/**
 * The space tabs, in display order. Each id is also the route segment and the
 * translation key of the tab label.
 */
export const SPACE_SECTION_IDS = [
  "overview",
  "assistants",
  "apps",
  "knowledge",
  "skills",
  "services",
  "members",
  "settings"
] as const;

export type SpaceSectionId = (typeof SPACE_SECTION_IDS)[number];

export type SpaceSection = {
  id: SpaceSectionId;
  href: string;
  /** Item count shown next to the label, when the space object carries it. */
  count?: number;
};

type Can = (action: ResourcePermission, resource: SpaceResource) => boolean;

function isSectionId(value: string | undefined): value is SpaceSectionId {
  return (SPACE_SECTION_IDS as readonly string[]).includes(value ?? "");
}

/** Knowledge items that belong to this space (shared-in items are listed elsewhere). */
export function ownKnowledgeCount(space: Space): number {
  const own = (item: { space_id: string }) => item.space_id === space.id;
  return (
    space.knowledge.groups.items.filter(own).length +
    space.knowledge.websites.items.filter(own).length +
    space.knowledge.integration_knowledge_list.items.filter(own).length
  );
}

/**
 * The tabs a user may see, gated exactly like the former space sidebar: the
 * organization space only has knowledge, skills, services and settings, and
 * every tab needs the matching read (or, for settings, edit) permission.
 */
export function spaceSections(space: Space, can: Can, routeId: SpaceRouteId): SpaceSection[] {
  const base = `/spaces/${routeId}`;
  const isOrg = space.organization;
  const sections: SpaceSection[] = [];
  const add = (id: SpaceSectionId, count?: number) =>
    sections.push({ id, href: `${base}/${id}`, ...(count === undefined ? {} : { count }) });

  if (!isOrg) add("overview");
  if (!isOrg && can("read", "assistant")) {
    add(
      "assistants",
      (space.applications?.assistants.count ?? 0) + (space.applications?.group_chats.count ?? 0)
    );
  }
  if (!isOrg && can("read", "app")) add("apps", space.applications?.apps.count ?? 0);
  if (can("read", "website") || can("read", "collection")) {
    add("knowledge", ownKnowledgeCount(space));
  }
  if (can("read", "skill")) add("skills");
  if (can("read", "service")) add("services");
  if (!isOrg && can("read", "member")) add("members", space.members.items.length);
  if (can("edit", "space")) add("settings");
  return sections;
}

export type SpaceRoute =
  | { kind: "chat" }
  | {
      kind: "page";
      /** The tab the route belongs to, or null for routes outside the tabs. */
      section: SpaceSectionId | null;
      /** A tab's own page (`/spaces/x/knowledge`), not a detail or editor below it. */
      isSectionRoot: boolean;
    };

/**
 * Classifies the route below `/spaces/[spaceId]` from its layout segments
 * (`useSelectedLayoutSegments()`). The chat renders full-bleed with its own
 * header; every other route gets the space header and tabs.
 */
export function spaceRoute(segments: readonly string[]): SpaceRoute {
  const [first, ...rest] = segments;
  if (first === "chat") return { kind: "chat" };
  // Group chats are edited from the assistants tab.
  if (first === "group-chats") return { kind: "page", section: "assistants", isSectionRoot: false };
  if (!isSectionId(first)) return { kind: "page", section: null, isSectionRoot: false };
  return { kind: "page", section: first, isSectionRoot: rest.length === 0 };
}

/** Where the space crumb in the breadcrumbs points: the overview, or the first tab. */
export function spaceLandingHref(sections: SpaceSection[], routeId: SpaceRouteId): string {
  return sections[0]?.href ?? `/spaces/${routeId}/overview`;
}
