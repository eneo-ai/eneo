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
 * organization space only has knowledge, skills and settings, and
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
    add("assistants", space.applications?.assistants.count ?? 0);
  }
  if (!isOrg && can("read", "app")) add("apps", space.applications?.apps.count ?? 0);
  if (can("read", "website") || can("read", "collection")) {
    add("knowledge", ownKnowledgeCount(space));
  }
  if (can("read", "skill")) add("skills");
  if (!isOrg && can("read", "member")) add("members", space.members.items.length);
  if (can("edit", "space")) add("settings");
  return sections;
}

export type SpaceRoute =
  | { kind: "chat" }
  /** An assistant or app editor: it owns the surface with its own header. */
  | { kind: "editor" }
  | {
      kind: "page";
      /** The tab the route belongs to, or null for routes outside the tabs. */
      section: SpaceSectionId | null;
      /** A tab's own page (`/spaces/x/knowledge`), not a detail or editor below it. */
      isSectionRoot: boolean;
    };

/**
 * `/spaces/x/assistants/<id>/edit`, `/apps/<id>/edit`, and an assistant's
 * `/widget` page, which owns its surface the same way.
 */
function isEditorRoute(first: string | undefined, rest: readonly string[]): boolean {
  if (rest.length !== 2) return false;
  if (first === "assistants") return rest[1] === "edit" || rest[1] === "widget";
  return first === "apps" && rest[1] === "edit";
}

/**
 * Classifies the route below `/spaces/[spaceId]` from its path segments
 * (`useSpaceSegments()`). The chat and the editors render full-bleed
 * with headers of their own; every other route gets the space header and tabs.
 */
export function spaceRoute(segments: readonly string[]): SpaceRoute {
  const [first, ...rest] = segments;
  if (first === "chat") return { kind: "chat" };
  if (isEditorRoute(first, rest)) return { kind: "editor" };
  if (!isSectionId(first)) return { kind: "page", section: null, isSectionRoot: false };
  return { kind: "page", section: first, isSectionRoot: rest.length === 0 };
}

/** A row of the space's sidebar: a section, or the personal space's chat. */
export type SpaceNavItem = { id: SpaceSectionId | "chat"; href: string };

/**
 * The space's sidebar in groups, each set apart by a divider, as Svelte's
 * `SpaceMenu.svelte` draws it: the personal space's Chatt on its own, the
 * sections, then Medlemmar with what follows it. Gating stays with
 * `spaceSections`; empty groups are dropped.
 */
export function spaceNavGroups(space: Space, can: Can, routeId: SpaceRouteId): SpaceNavItem[][] {
  const sections = spaceSections(space, can, routeId);
  const members = sections.findIndex((section) => section.id === "members");
  const groups: SpaceNavItem[][] = [
    space.personal && !space.organization
      ? [{ id: "chat", href: `/spaces/${routeId}/chat?tab=chat` }]
      : [],
    members === -1 ? sections : sections.slice(0, members),
    members === -1 ? [] : sections.slice(members)
  ];
  return groups
    .map((group) => group.map(({ id, href }) => ({ id, href })))
    .filter((group) => group.length > 0);
}

/** Where the space crumb in the breadcrumbs points: the overview, or the first tab. */
export function spaceLandingHref(sections: SpaceSection[], routeId: SpaceRouteId): string {
  return sections[0]?.href ?? `/spaces/${routeId}/overview`;
}

/** What a phone keeps as tabs: the space's content. */
const CONTENT_SECTION_IDS: readonly SpaceSectionId[] = [
  "overview",
  "assistants",
  "apps",
  "knowledge"
];
/** What manages the space, in the order "Hantera ytan" lists it. */
const MANAGE_SECTION_IDS: readonly SpaceSectionId[] = ["members", "settings", "skills"];

/**
 * The sections as a phone shows them (decision 24): the content as tabs, the
 * rest in "Hantera ytan" on Översikt. A space without Översikt (the
 * organisation space) has nowhere to list them, so it keeps every tab (F4).
 */
export function phoneSections(sections: SpaceSection[]): {
  tabs: SpaceSection[];
  manage: SpaceSection[];
} {
  if (!sections.some((section) => section.id === "overview")) return { tabs: sections, manage: [] };
  return {
    tabs: sections.filter((section) => CONTENT_SECTION_IDS.includes(section.id)),
    manage: MANAGE_SECTION_IDS.flatMap((id) => sections.filter((section) => section.id === id))
  };
}
