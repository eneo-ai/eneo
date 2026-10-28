"use client";

import { createStaticSource, type SearchableItem } from "@astryxdesign/core/Typeahead";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo } from "react";
import { Typeahead } from "@/components/astryx/typeahead";
import { browserApi } from "@/lib/api/browser";
import {
  apiKeyScopeResourcesQueryOptions,
  type ResourceScopeType,
  type ScopeResource
} from "./api-keys";

function itemOf(resource: ScopeResource): SearchableItem {
  return {
    id: resource.id,
    label: resource.spaceName ? `${resource.name} · ${resource.spaceName}` : resource.name
  };
}

/** The names of the spaces, assistants and apps keys can be scoped to, by id. */
export function useScopeResourceNames(): Map<string, string> {
  const { data } = useQuery(apiKeyScopeResourcesQueryOptions(browserApi));
  return useMemo(
    () =>
      new Map(
        Object.values(data ?? {})
          .flat()
          .map((resource) => [resource.id, resource.name])
      ),
    [data]
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
  const resources = useQuery(apiKeyScopeResourcesQueryOptions(browserApi));
  const items = useMemo(
    () => (resources.data?.[scopeType] ?? []).map(itemOf),
    [resources.data, scopeType]
  );
  const source = useMemo(() => createStaticSource(items), [items]);
  const selected = items.find((item) => item.id === value) ?? null;

  return (
    <Typeahead
      label={label}
      placeholder={t("api_keys_select_resource", {
        scopeType: t(`api_keys_scope_${scopeType}`).toLocaleLowerCase()
      })}
      searchSource={source}
      value={selected}
      onChange={(item) => onChange(item?.id ?? null)}
      hasEntriesOnFocus
      hasClear
      debounceMs={0}
      emptySearchResultsText={t("no_results")}
      isDisabled={isDisabled || resources.isPending}
      status={
        problem
          ? { type: "error", message: problem }
          : resources.isError
            ? { type: "warning", message: t("query_error_title") }
            : undefined
      }
      width="100%"
    />
  );
}
