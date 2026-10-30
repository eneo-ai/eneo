"use client";

import { useTranslations } from "use-intl";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useId, useRef, useState, type ReactNode } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { EmptyState } from "@/components/composites/empty-state";
import { SecretRevealDialog } from "@/components/composites/secret-reveal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { usePaginatedQuery } from "@/lib/hooks/use-paginated-query";
import { ApiKeyActions } from "./api-key-actions";
import {
  API_KEY_STATE_BADGE_VARIANT,
  API_KEY_STATE_FILTERS,
  API_KEYS_KEY,
  formatApiKeyDate,
  stateFilterLabelKey,
  type ApiKey,
  type ApiKeyStateFilter,
  type ResourceScopeType
} from "./api-keys";
import { expiringCounts } from "./expiration-utils";

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
  const panelRef = useRef<HTMLDivElement>(null);
  const tabsId = useId();
  const panelId = `${tabsId}-panel`;

  const keys = usePaginatedQuery({
    queryKey: [...API_KEYS_KEY, scope?.type, scope?.id, stateFilter],
    limit,
    fetchPage: async ({ cursor, limit: pageSize }) => {
      const page = await unwrap(
        browserApi.GET("/api/v1/api-keys", {
          params: {
            query: {
              scope_type: scope?.type,
              scope_id: scope?.id,
              state: stateFilter === "all" ? null : stateFilter,
              cursor: cursor ?? null,
              limit: pageSize
            }
          }
        })
      );
      return { ...page, total_count: page.total_count ?? 0 };
    }
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
        {toolbar}
      </div>

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
          {keys.items.length === 0 && !keys.isPending ? (
            <EmptyState title={t("api_keys_no_keys")} description={t("api_keys_no_keys_desc")} />
          ) : (
            <>
              <ExpiringInView keys={keys.items} />
              <Table aria-label={t("api_keys")}>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("name")}</TableHead>
                    <TableHead>{t("status")}</TableHead>
                    <TableHead>{t("api_keys_permission_level")}</TableHead>
                    <TableHead>{t("api_keys_expires")}</TableHead>
                    <TableHead>{t("api_keys_created")}</TableHead>
                    <TableHead className="w-14 min-w-14" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {keys.items.map((apiKey) => (
                    <TableRow key={apiKey.id}>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-medium">{apiKey.name}</span>
                          <code className="text-muted-foreground font-mono text-xs">
                            {apiKey.key_prefix}…{apiKey.key_suffix}
                          </code>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={API_KEY_STATE_BADGE_VARIANT[apiKey.state]}>
                          {t(`api_keys_status_${apiKey.state}`)}
                        </Badge>
                      </TableCell>
                      <TableCell>{t(`api_keys_permission_${apiKey.permission}`)}</TableCell>
                      <TableCell>
                        {apiKey.expires_at
                          ? formatApiKeyDate(apiKey.expires_at)
                          : t("api_keys_never")}
                      </TableCell>
                      <TableCell>{formatApiKeyDate(apiKey.created_at)}</TableCell>
                      <TableCell className="text-end">
                        <ApiKeyActions
                          apiKey={apiKey}
                          mode="user"
                          scopeName={scope?.name}
                          onRotated={onRotated}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {(keys.hasPreviousPage || keys.hasNextPage) && (
                <div className="flex justify-end gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!keys.hasPreviousPage}
                    onClick={keys.previousPage}
                  >
                    {t("previous")}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!keys.hasNextPage}
                    onClick={keys.nextPage}
                  >
                    {t("next")}
                  </Button>
                </div>
              )}
            </>
          )}
        </RemovalFocusScope>
      </div>
    </div>
  );
}
