import { NEW_CONVERSATION_HREF } from "@/components/shell/routes";
import type { Dashboard } from "./queries";

/** Something the user can open from the catalog ("Assistenter") or the ⌘K palette. */
export type CatalogEntry = {
  id: string;
  kind: "personal-assistant" | "assistant" | "app";
  name: string;
  href: string;
};

export type CatalogGroup = {
  id: string;
  name: string;
  personal: boolean;
  entries: CatalogEntry[];
};

/**
 * Assistants and apps per space, personal space first: the one mapping from
 * the dashboard to what users can open, shared by the "Assistenter" page and
 * the ⌘K palette. The personal space's default assistant is not part of
 * `applications`; it opens the personal chat, like "Ny konversation". Spaces
 * with nothing to open are left out.
 */
export function catalogGroups(
  dashboard: Dashboard,
  labels: { personal: string; personalAssistant: string }
): CatalogGroup[] {
  const groups = dashboard.spaces.items.map((space) => ({
    id: space.id,
    name: space.personal ? labels.personal : space.name,
    personal: space.personal,
    entries: [
      ...(space.personal && space.default_assistant
        ? [
            {
              id: space.default_assistant.id,
              kind: "personal-assistant" as const,
              name: labels.personalAssistant,
              href: NEW_CONVERSATION_HREF
            }
          ]
        : []),
      ...(space.applications?.assistants.items ?? []).map((assistant) => ({
        id: assistant.id,
        kind: "assistant" as const,
        name: assistant.name,
        href: `/dashboard/${assistant.id}?tab=chat`
      })),
      ...(space.applications?.apps.items ?? []).map((app) => ({
        id: app.id,
        kind: "app" as const,
        name: app.name,
        href: `/dashboard/app/${app.id}`
      }))
    ]
  }));
  return groups
    .filter((group) => group.entries.length > 0)
    .sort((a, b) => Number(b.personal) - Number(a.personal));
}

/** Keeps entries whose name, or whose space's name, contains the query. */
export function filterCatalog(groups: CatalogGroup[], query: string): CatalogGroup[] {
  const needle = query.toLocaleLowerCase("sv").trim();
  if (!needle) return groups;
  return groups
    .map((group) =>
      group.name.toLocaleLowerCase("sv").includes(needle)
        ? group
        : {
            ...group,
            entries: group.entries.filter((entry) =>
              entry.name.toLocaleLowerCase("sv").includes(needle)
            )
          }
    )
    .filter((group) => group.entries.length > 0);
}
