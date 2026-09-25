"use client";

import { ClickableCard } from "@astryxdesign/core/ClickableCard";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useSuspenseQuery } from "@tanstack/react-query";
import { AppWindow, Bot, Search, User } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { browserApi } from "@/lib/api/browser";
import { dashboardQueryOptions, type Dashboard } from "./queries";

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
 * Assistants and apps per space, personal space first. The personal space's
 * default assistant is not part of `applications`; it opens the personal
 * chat, like "Ny konversation". Spaces with nothing to open are left out.
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
              href: "/spaces/personal/chat"
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

function EntryCard({ entry, spaceName }: { entry: CatalogEntry; spaceName: string }) {
  const t = useTranslations();
  const subtitle =
    entry.kind === "app" ? t("shell_catalog_app_in_space", { space: spaceName }) : spaceName;
  const icon =
    entry.kind === "app" ? <AppWindow /> : entry.kind === "personal-assistant" ? <User /> : null;

  return (
    <ClickableCard
      label={t("shell_catalog_card_label", { name: entry.name, space: subtitle })}
      href={entry.href}
      padding={3}
      className="h-full"
    >
      {/* The card's link carries the same text as its name (read once). */}
      <span aria-hidden="true" className="flex min-w-0 items-center gap-3">
        <EntityAvatar id={entry.id} name={entry.name} icon={icon ?? undefined} size="lg" />
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate font-semibold">{entry.name}</span>
          <span className="text-ax-text-secondary truncate text-xs">{subtitle}</span>
        </span>
      </span>
    </ClickableCard>
  );
}

export function DashboardList() {
  const t = useTranslations();
  const headingId = useId();
  const { data } = useSuspenseQuery(dashboardQueryOptions(browserApi));
  const [query, setQuery] = useState("");
  const announce = useAnnounce();

  const groups = catalogGroups(data, {
    personal: t("personal"),
    personalAssistant: t("personal_assistant")
  });
  const visible = filterCatalog(groups, query);

  // The result count is announced politely as the user types (WCAG 4.1.3).
  function search(value: string) {
    setQuery(value);
    const count = filterCatalog(groups, value).reduce(
      (sum, group) => sum + group.entries.length,
      0
    );
    announce(value.trim() ? t("shell_catalog_result_count", { count }) : "");
  }

  if (groups.length === 0) {
    return (
      <EmptyState
        icon={<Bot />}
        title={t("shell_catalog_empty_title")}
        description={t("shell_catalog_empty_description")}
      />
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="w-full max-w-sm">
        <TextInput
          label={t("shell_catalog_search_label")}
          isLabelHidden
          startIcon={Search}
          hasClear
          value={query}
          onChange={search}
          placeholder={t("shell_catalog_search_placeholder")}
          width="100%"
        />
      </div>
      {visible.length === 0 ? (
        <EmptyState
          icon={<Search />}
          title={t("shell_catalog_no_matches_title")}
          description={t("shell_catalog_no_matches_description", { query: query.trim() })}
        />
      ) : (
        visible.map((group) => (
          <section
            key={group.id}
            aria-labelledby={`${headingId}-${group.id}`}
            className="flex flex-col gap-3"
          >
            <h2
              id={`${headingId}-${group.id}`}
              className="text-ax-text flex items-center gap-2 text-base font-semibold"
            >
              <EntityAvatar
                id={group.id}
                name={group.name}
                icon={group.personal ? <User /> : undefined}
                size="sm"
              />
              {group.name}
            </h2>
            <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {group.entries.map((entry) => (
                <li key={`${entry.kind}:${entry.id}`}>
                  <EntryCard entry={entry} spaceName={group.name} />
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}
