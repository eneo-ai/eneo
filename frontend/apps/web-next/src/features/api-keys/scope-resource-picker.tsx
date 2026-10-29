"use client";

import { createStaticSource, type SearchableItem } from "@astryxdesign/core/Typeahead";
import { queryOptions, useQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useMemo } from "react";
import { Typeahead } from "@/components/astryx/typeahead";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { settleWithLimit } from "@/lib/settle-with-limit";
import type { ResourceScopeType } from "./api-keys";

/** A space, assistant or app a key can be scoped to. */
type ScopeResource = { id: string; name: string; spaceName?: string };
type ScopeSpace = { id: string; name: string; applications: Schema<"Applications"> | null };

/** Application lists read at once: a tenant can have many spaces. */
const APPLICATIONS_CONCURRENCY = 4;

/** The user's spaces, the personal and the organization's included. */
function scopeSpacesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["api-key-scope-resources", "spaces"],
    queryFn: async ({ signal }): Promise<ScopeSpace[]> => {
      const listed = await unwrap(
        api.GET("/api/v1/spaces/", {
          params: { query: { include_personal: true, include_applications: true } },
          signal
        })
      );
      const spaces = listed.items.map(({ id, name, applications }) => ({
        id,
        name,
        applications: applications ?? null
      }));
      const organization = await unwrap(
        api.GET("/api/v1/spaces/type/organization/", { signal })
      ).catch(() => null);
      if (organization && !spaces.some((space) => space.id === organization.id)) {
        spaces.push({ id: organization.id, name: organization.name, applications: null });
      }
      return spaces;
    }
  });
}

/**
 * Each space's assistants and apps, published or not (the Svelte app's
 * listing), a few spaces at a time. A space whose applications cannot be read
 * keeps the published ones the spaces list held.
 */
function scopeApplicationsQueryOptions(api: EneoClient, spaces: ScopeSpace[]) {
  return queryOptions({
    queryKey: ["api-key-scope-resources", "applications", spaces.map((space) => space.id)],
    queryFn: async ({ signal }): Promise<Record<"assistant" | "app", ScopeResource[]>> => {
      const results = await settleWithLimit(spaces, APPLICATIONS_CONCURRENCY, (space) =>
        unwrap(
          api.GET("/api/v1/spaces/{id}/applications/", {
            params: { path: { id: space.id } },
            signal
          })
        )
      );
      const lists = results.map((result, index) =>
        result.status === "fulfilled" ? result.value : spaces[index]?.applications
      );
      const of = (pick: (applications: Schema<"Applications">) => { id: string; name: string }[]) =>
        spaces.flatMap((space, index) => {
          const applications = lists[index];
          return applications
            ? pick(applications).map(({ id, name }) => ({ id, name, spaceName: space.name }))
            : [];
        });
      return {
        assistant: of((applications) => applications.assistants.items),
        app: of((applications) => applications.apps.items)
      };
    }
  });
}

/**
 * What keys can be scoped to: the spaces as soon as they are listed, the
 * assistants and apps (one request per space) only when `withApplications`.
 */
function useScopeResources(withApplications: boolean) {
  const spaces = useQuery(scopeSpacesQueryOptions(browserApi));
  const applications = useQuery({
    ...scopeApplicationsQueryOptions(browserApi, spaces.data ?? []),
    enabled: withApplications && spaces.data !== undefined
  });
  return { spaces, applications };
}

/** The names of the spaces, assistants and apps keys can be scoped to, by id. */
export function useScopeResourceNames(): Map<string, string> {
  const { spaces, applications } = useScopeResources(true);
  return useMemo(
    () =>
      new Map(
        [
          ...(spaces.data ?? []),
          ...(applications.data?.assistant ?? []),
          ...(applications.data?.app ?? [])
        ].map((resource) => [resource.id, resource.name])
      ),
    [spaces.data, applications.data]
  );
}

/**
 * Picks the space, assistant or app a key is scoped to (or filtered by), by
 * name, from those the user can reach. A resource the list does not hold can
 * still be given by id next to it.
 */
export function ScopeResourcePicker({
  scopeType,
  value,
  onChange,
  label,
  problem = null,
  isDisabled = false
}: {
  scopeType: ResourceScopeType;
  value: string | null;
  onChange: (id: string | null) => void;
  label: string;
  problem?: string | null;
  isDisabled?: boolean;
}) {
  const t = useTranslations();
  const { spaces, applications } = useScopeResources(scopeType !== "space");
  const source = scopeType === "space" ? spaces : applications;
  const resources = useMemo<ScopeResource[]>(
    () => (scopeType === "space" ? (spaces.data ?? []) : (applications.data?.[scopeType] ?? [])),
    [scopeType, spaces.data, applications.data]
  );
  const items = useMemo<SearchableItem[]>(
    () =>
      resources.map((resource) => ({
        id: resource.id,
        label: resource.spaceName ? `${resource.name} · ${resource.spaceName}` : resource.name
      })),
    [resources]
  );
  const searchSource = useMemo(() => createStaticSource(items), [items]);
  const selected = items.find((item) => item.id === value) ?? null;
  const failed = spaces.isError || source.isError;

  return (
    <Typeahead
      label={label}
      placeholder={t("api_keys_select_resource", {
        scopeType: t(`api_keys_scope_${scopeType}`).toLocaleLowerCase()
      })}
      searchSource={searchSource}
      value={selected}
      onChange={(item) => onChange(item?.id ?? null)}
      hasEntriesOnFocus
      hasClear
      debounceMs={0}
      emptySearchResultsText={t("no_results")}
      isDisabled={isDisabled || (source.isPending && !failed)}
      status={
        problem
          ? { type: "error", message: problem }
          : failed
            ? { type: "warning", message: t("query_error_title") }
            : undefined
      }
      width="100%"
    />
  );
}
