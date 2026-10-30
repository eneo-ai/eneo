"use client";

import { useNow, useTranslations } from "use-intl";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Button } from "@astryxdesign/core/Button";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useId, useRef, useState, type ReactNode } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ClientTime } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadMore, QueryStateBoundary } from "@/components/composites/query-state";
import { SecretRevealDialog } from "@/components/composites/secret-reveal";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { RemovalFocusScope } from "@/features/spaces/removal";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { cursorPagination, flattenPages } from "@/lib/api/pagination";
import { ApiKeyActions } from "./api-key-actions";
import {
  API_KEY_STATE_BADGE_VARIANT,
  API_KEY_STATE_FILTERS,
  API_KEYS_KEY,
  rateLimitLabel,
  stateFilterLabelKey,
  type ApiKey,
  type ApiKeyStateFilter,
  type ResourceScopeType
} from "./api-keys";
import { expiringCounts } from "./expiration-utils";
import { useScopeResourceNames } from "./scope-resource-picker";

/**
 * The one-time secret dialog for a page's created and rotated keys:
 * `reveal(title)` gives the callback that shows a secret under that title.
 */
export function useSecretReveal() {
  const t = useTranslations();
  // The title stays after closing, so the closing dialog keeps its name.
  const [title, setTitle] = useState(() => t("api_keys_created_title"));
  const [secret, setSecret] = useState<string | null>(null);
  return {
    reveal: (nextTitle: string) => (nextSecret: string) => {
      setTitle(nextTitle);
      setSecret(nextSecret);
    },
    dialog: <SecretRevealDialog title={title} secret={secret} onClose={() => setSecret(null)} />
  };
}

/**
 * Says how many of the listed keys have expired or expire within 14 days, as
 * the Svelte resource section's compact banner does. A lasting state, so not
 * announced each time the list is shown.
 */
function ExpiringInView({ keys }: { keys: ApiKey[] }) {
  const t = useTranslations();
  const { expired, urgent, warning } = expiringCounts(keys);
  const count = (n: number, one: string, many: string) =>
    n === 1 ? t(one) : t(many, { count: n });
  const parts = [
    expired > 0 &&
      count(expired, "api_keys_expiring_expired_one", "api_keys_expiring_expired_many"),
    urgent > 0 && count(urgent, "api_keys_expiring_urgent_one", "api_keys_expiring_urgent_many"),
    warning > 0 && count(warning, "api_keys_expiring_warning_one", "api_keys_expiring_warning_many")
  ].filter(Boolean);
  if (parts.length === 0) return null;
  return (
    <Banner
      status={expired + urgent > 0 ? "error" : "warning"}
      title={`${parts.join(", ")} ${t("api_keys_expiring_in_view")}`}
    />
  );
}

function KeyRow({
  apiKey,
  scopeName,
  now,
  onRotated
}: {
  apiKey: ApiKey;
  scopeName?: string;
  now: number;
  onRotated: (secret: string) => void;
}) {
  const t = useTranslations();
  const stateChange =
    apiKey.state === "suspended"
      ? {
          date: apiKey.suspended_at,
          code: apiKey.suspended_reason_code,
          text: apiKey.suspended_reason_text
        }
      : apiKey.state === "revoked"
        ? {
            date: apiKey.revoked_at,
            code: apiKey.revoked_reason_code,
            text: apiKey.revoked_reason_text
          }
        : null;
  const reason = [
    stateChange?.code ? t(`api_keys_reason_${stateChange.code}`) : null,
    stateChange?.text
  ]
    .filter(Boolean)
    .join(" · ");
  const restrictions = apiKey.key_type === "pk_" ? apiKey.allowed_origins : apiKey.allowed_ips;
  return (
    <TableRow>
      <TableCell className="max-w-64 wrap-anywhere whitespace-normal">
        <div className="flex flex-col gap-1">
          <span className="font-medium">{apiKey.name}</span>
          <code className="text-ax-text-secondary font-mono text-xs">
            {apiKey.key_prefix}…{apiKey.key_suffix}
          </code>
          {apiKey.description && (
            <p className="text-ax-text-secondary text-xs">{apiKey.description}</p>
          )}
          {apiKey.ownership === "service" && (
            <Badge variant="outline">{t("api_keys_ownership_service")}</Badge>
          )}
        </div>
      </TableCell>
      <TableCell className="max-w-56 wrap-anywhere whitespace-normal">
        <div className="flex flex-col items-start gap-1">
          <Badge variant={API_KEY_STATE_BADGE_VARIANT[apiKey.state]}>
            {t(`api_keys_status_${apiKey.state}`)}
          </Badge>
          {stateChange?.date && (
            <span className="text-ax-text-secondary text-xs">
              <ClientTime value={stateChange.date} format="date_time" />
            </span>
          )}
          {reason && <p className="text-ax-text-secondary text-xs">{reason}</p>}
          {apiKey.rotation_grace_until && new Date(apiKey.rotation_grace_until).getTime() > now && (
            <span className="text-ax-text-secondary text-xs">
              {t("api_keys_rotate_grace_period_label")}:{" "}
              <ClientTime value={apiKey.rotation_grace_until} format="date_time" />
            </span>
          )}
        </div>
      </TableCell>
      <TableCell className="max-w-48 wrap-anywhere whitespace-normal">
        {t(`api_keys_scope_${apiKey.scope_type}`)}
        {apiKey.scope_id && (
          <span className="text-ax-text-secondary block text-xs">
            {scopeName ?? apiKey.scope_id}
          </span>
        )}
      </TableCell>
      <TableCell className="max-w-64 wrap-anywhere whitespace-normal">
        <div className="flex flex-col gap-1">
          <span>{t(`api_keys_permission_${apiKey.permission}`)}</span>
          <span className="text-ax-text-secondary text-xs">
            {t("api_keys_rate_limit_label")}: <span>{rateLimitLabel(apiKey.rate_limit, t)}</span>
          </span>
          {restrictions && restrictions.length > 0 && (
            <div className="text-ax-text-secondary text-xs">
              {t(apiKey.key_type === "pk_" ? "api_keys_allowed_origins" : "api_keys_allowed_ips")}
              <ul>
                {restrictions.map((value) => (
                  <li key={value} className="font-mono">
                    {value}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </TableCell>
      <TableCell>
        {apiKey.last_used_at ? (
          <ClientTime value={apiKey.last_used_at} format="auto" />
        ) : (
          t("api_keys_never")
        )}
      </TableCell>
      <TableCell>
        {apiKey.expires_at ? (
          <div className="flex flex-col gap-1">
            <ClientTime value={apiKey.expires_at} format="date_time" />
            <span className="text-ax-text-secondary text-xs">
              <ClientTime value={apiKey.expires_at} format="relative" />
            </span>
          </div>
        ) : (
          t("api_keys_never")
        )}
      </TableCell>
      <TableCell>
        {apiKey.created_at ? <ClientTime value={apiKey.created_at} format="date" /> : "—"}
      </TableCell>
      <TableCell className="text-end">
        <ApiKeyActions apiKey={apiKey} mode="user" scopeName={scopeName} onRotated={onRotated} />
      </TableCell>
    </TableRow>
  );
}

/**
 * A user's keys, all of them or one resource's (`scope`): state tabs over a
 * paged table, which keys expire soon among those shown, and the shared
 * actions menu on each row. The page around it adds its own header.
 */
export function UserApiKeyList({
  scope,
  limit,
  toolbar,
  onRotated
}: {
  scope?: { type: ResourceScopeType; id: string; name: string };
  limit: number;
  /** Beside the state tabs (the account page's Create). */
  toolbar?: ReactNode;
  onRotated: (secret: string) => void;
}) {
  const t = useTranslations();
  const [stateFilter, setStateFilter] = useState<ApiKeyStateFilter>("active");
  const now = useNow({ updateInterval: 60_000 });
  const [search, setSearch] = useState("");
  const panelRef = useRef<HTMLDivElement>(null);
  const tabsId = useId();
  const panelId = `${tabsId}-panel`;

  const keys = useInfiniteQuery({
    queryKey: [...API_KEYS_KEY, "list", scope?.type, scope?.id, stateFilter, limit],
    ...cursorPagination,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        browserApi.GET("/api/v1/api-keys", {
          signal,
          params: {
            query: {
              scope_type: scope?.type,
              scope_id: scope?.id,
              state: stateFilter === "all" ? null : stateFilter,
              cursor: pageParam ?? null,
              limit
            }
          }
        })
      )
  });
  const loadedKeys = flattenPages(keys.data?.pages);
  const searchTerm = search.trim().toLocaleLowerCase();
  const visibleKeys = loadedKeys.filter((key) =>
    [key.name, key.description, key.key_suffix].some((value) =>
      value?.toLocaleLowerCase().includes(searchTerm)
    )
  );
  const scopeNames = useScopeResourceNames({
    enabled: !scope && loadedKeys.some((key) => key.scope_type !== "tenant"),
    withApplications: loadedKeys.some(
      (key) => key.scope_type === "assistant" || key.scope_type === "app"
    )
  });

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <TabList
          role="tablist"
          aria-label={t("api_keys")}
          value={stateFilter}
          onChange={(value) => setStateFilter(value as ApiKeyStateFilter)}
          className="max-w-full min-w-0"
          hasDivider
        >
          {API_KEY_STATE_FILTERS.map((state) => (
            <Tab
              key={state}
              id={`${tabsId}-${state}`}
              value={state}
              label={t(stateFilterLabelKey(state))}
              panelId={panelId}
            />
          ))}
        </TabList>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            label={t("api_keys_refresh")}
            variant="secondary"
            isLoading={keys.isFetching}
            isInterruptible
            onClick={() => {
              if (!keys.isFetching) void keys.refetch();
            }}
          />
          {toolbar}
        </div>
      </div>

      {(loadedKeys.length > 3 || search !== "") && (
        <TextInput
          label={t("api_keys_search_label")}
          value={search}
          onChange={setSearch}
          placeholder={t("api_keys_search_placeholder")}
          description={t("api_keys_search_loaded_hint")}
          width="100%"
        />
      )}

      {/* The keys in the selected state: the state tabs' panel. */}
      <div
        ref={panelRef}
        role="tabpanel"
        id={panelId}
        aria-labelledby={`${tabsId}-${stateFilter}`}
        tabIndex={0}
        className="focus-visible:outline-ring flex flex-col gap-4 rounded-md focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        <RemovalFocusScope target={panelRef}>
          <QueryStateBoundary query={keys} errorTitle={t("api_keys")}>
            {() =>
              loadedKeys.length === 0 ? (
                <EmptyState
                  title={t("api_keys_no_keys")}
                  description={t("api_keys_no_keys_desc")}
                />
              ) : (
                <>
                  <ExpiringInView keys={visibleKeys} />
                  {searchTerm && (
                    <p className="text-ax-text-secondary text-sm">
                      {t("api_keys_filtered", {
                        filtered: visibleKeys.length,
                        total: loadedKeys.length
                      })}
                    </p>
                  )}
                  {visibleKeys.length === 0 ? (
                    <EmptyState title={t("api_keys_no_search_matches")} />
                  ) : (
                    <Table aria-label={t("api_keys")} className="min-w-[52rem]">
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t("name")}</TableHead>
                          <TableHead>{t("status")}</TableHead>
                          <TableHead>{t("api_keys_scope")}</TableHead>
                          <TableHead>{t("api_keys_permission_level")}</TableHead>
                          <TableHead>{t("api_keys_last_used")}</TableHead>
                          <TableHead>{t("api_keys_expires")}</TableHead>
                          <TableHead>{t("api_keys_created")}</TableHead>
                          <TableHead className="w-14 min-w-14" />
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {visibleKeys.map((apiKey) => (
                          <KeyRow
                            key={apiKey.id}
                            apiKey={apiKey}
                            now={now.getTime()}
                            scopeName={
                              scope?.name ??
                              (apiKey.scope_id ? scopeNames.get(apiKey.scope_id) : undefined)
                            }
                            onRotated={onRotated}
                          />
                        ))}
                      </TableBody>
                    </Table>
                  )}
                  <LoadMore query={keys} label={t("load_more")} />
                </>
              )
            }
          </QueryStateBoundary>
        </RemovalFocusScope>
      </div>
    </div>
  );
}
