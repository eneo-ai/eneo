"use client";

import type { SearchableItem, SearchSource } from "@astryxdesign/core/Typeahead";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Settings, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useMemo, useRef, useState } from "react";
import { Switch } from "@/components/astryx/switch";
import { Typeahead } from "@/components/astryx/typeahead";
import { ClientTime } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import { SecretRevealDialog } from "@/components/composites/secret-reveal";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ActionSwitch } from "@/features/admin/audit/audit-config";
import {
  AUDIT_ACTION_CONFIG_KEY,
  AUDIT_CONFIG_KEY,
  auditActionConfigQueryOptions
} from "@/features/admin/audit/audit";
import { useSettingSwitch } from "@/features/admin/use-setting-switch";
import { adminUsersQueryOptions, MIN_SEARCH_LENGTH } from "@/features/admin/users/users";
import { ApiKeyActions } from "@/features/api-keys/api-key-actions";
import { userLabel } from "@/features/api-keys/api-key-details";
import { CreateApiKeyDialog } from "@/features/api-keys/api-key-form";
import {
  ADMIN_API_KEYS_KEY,
  API_KEY_STATE_BADGE_VARIANT,
  API_KEY_STATE_FILTERS,
  formatApiKeyDate,
  stateFilterLabelKey,
  type ApiKey,
  type ApiKeyScopeType,
  type ApiKeyStateFilter,
  type ApiKeyType
} from "@/features/api-keys/api-keys";
import {
  ScopeResourcePicker,
  useScopeResourceNames
} from "@/features/api-keys/scope-resource-picker";
import { RemovalFocusScope } from "@/features/spaces/removal";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { useFocusRescue } from "@/lib/focus-rescue";
import { SEARCH_DEBOUNCE_MS } from "@/lib/hooks/use-debounced-value";
import { usePaginatedQuery } from "@/lib/hooks/use-paginated-query";
import Link from "@/lib/link";
import {
  DEFAULT_ADMIN_KEY_FILTERS,
  RESULT_LIMITS,
  activeFilterCount,
  adminKeyListQuery,
  isFullApiKeySecret,
  secretSuffix,
  type AdminKeyFilters
} from "./admin-key-filters";
import { NotificationPolicyDialog } from "./notification-policy-dialog";
import { ApiKeyPolicyDialog } from "./policy-panel";

/** A pasted full key: looking it up, the key it found (by id), or why it could not. */
type Lookup =
  | { status: "pending" }
  | { status: "found"; id: string }
  | { status: "failed"; error: unknown; retrying?: boolean };

const SCOPE_FILTERS: (ApiKeyScopeType | "all")[] = ["all", "tenant", "space", "assistant", "app"];
const KEY_TYPE_FILTERS = [
  { value: "all", key: "api_keys_admin_key_type_all" },
  { value: "pk_", key: "api_keys_admin_key_type_public" },
  { value: "sk_", key: "api_keys_admin_key_type_secret" }
] as const;

/**
 * The tenant's API keys for an admin, as the Svelte admin page: search by
 * name or suffix, or paste a whole key to find exactly it (it is posted to the
 * lookup endpoint, never put in a URL or a cache key); narrow by owner or
 * creator, scope and resource, key type and "expires within"; every state or
 * one; each row with its owner, scope, rate limit and last use, and the
 * shared actions menu. Below: the tenant's switch for expiry notifications
 * and the audit switches for key use and failed key authentication.
 */
export function OrgApiKeysPage() {
  const t = useTranslations();
  const [state, setState] = useState<ApiKeyStateFilter>("active");
  const [applied, setApplied] = useState(DEFAULT_ADMIN_KEY_FILTERS);
  // Remounts the filter form on "Clear all", so its fields start over.
  const [formKey, setFormKey] = useState(0);
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const lookupRun = useRef(0);
  const [secret, setSecret] = useState<string | null>(null);
  const [secretTitle, setSecretTitle] = useState("");
  const [showPolicy, setShowPolicy] = useState(false);
  const [showConstraintPolicy, setShowConstraintPolicy] = useState(false);
  const headingId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const rescueFocus = useFocusRescue();
  const scopeNames = useScopeResourceNames();

  function showSecret(title: string) {
    return (value: string) => {
      setSecretTitle(title);
      setSecret(value);
    };
  }

  const list = usePaginatedQuery<ApiKey>({
    queryKey: [...ADMIN_API_KEYS_KEY, "list", state, adminKeyListQuery(applied, state, undefined)],
    limit: applied.limit,
    enabled: lookup === null,
    fetchPage: ({ cursor }) =>
      unwrap(
        browserApi.GET("/api/v1/admin/api-keys", {
          params: { query: adminKeyListQuery(applied, state, cursor) }
        })
      )
  });
  // Keyed by id, so the found key refreshes after an action like any list.
  const foundId = lookup?.status === "found" ? lookup.id : null;
  const found = useQuery({
    queryKey: [...ADMIN_API_KEYS_KEY, "key", foundId],
    enabled: foundId !== null,
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/admin/api-keys/{id}", {
          params: { path: { id: foundId ?? "" } }
        })
      )
  });

  /**
   * Applies the filters; a whole key is looked up first. A retry keeps the
   * failure (and its focused Retry button) on screen until the answer comes;
   * when the answer replaces it, focus goes to the list's panel.
   */
  async function apply(filters: AdminKeyFilters, { retry = false } = {}) {
    const run = ++lookupRun.current;
    setApplied(filters);
    if (!isFullApiKeySecret(filters.search)) {
      setLookup(null);
      return;
    }
    setLookup((current) =>
      retry && current?.status === "failed" ? { ...current, retrying: true } : { status: "pending" }
    );
    const settled = () => {
      if (retry) rescueFocus(() => panelRef.current);
    };
    try {
      const result = await unwrap(
        browserApi.POST("/api/v1/admin/api-keys/lookup", {
          body: { secret: filters.search.trim() }
        })
      );
      if (run !== lookupRun.current) return;
      setLookup({ status: "found", id: result.api_key.id });
      settled();
    } catch (error) {
      if (run !== lookupRun.current) return;
      if (error instanceof EneoApiError && error.status === 404) {
        // No exact match: its suffix still finds the candidates.
        setLookup(null);
        setApplied({ ...filters, search: secretSuffix(filters.search) });
        settled();
      } else {
        setLookup({ status: "failed", error });
      }
    }
  }

  function clear() {
    lookupRun.current++;
    setLookup(null);
    setState("active");
    setApplied(DEFAULT_ADMIN_KEY_FILTERS);
    setFormKey((key) => key + 1);
  }

  const count = activeFilterCount(applied, state);
  const shown = foundId
    ? found.data && { filtered: 1, total: 1 }
    : lookup === null &&
      list.data && { filtered: list.items.length, total: list.totalCount ?? list.items.length };

  function refresh() {
    if (lookup?.status === "failed") void apply(applied, { retry: true });
    else if (foundId) void found.refetch();
    else if (lookup === null) void list.refetch();
  }

  const table = (keys: ApiKey[]) =>
    keys.length === 0 ? (
      <EmptyState
        title={t("api_keys_admin_no_keys_found")}
        description={count > 0 ? t("api_keys_admin_no_keys_match") : undefined}
      />
    ) : (
      <KeyTable
        keys={keys}
        labelledBy={headingId}
        scopeNames={scopeNames}
        onRotated={showSecret(t("api_keys_rotated_title"))}
      />
    );

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <PageHeader title={t("api_keys")} headingId={headingId}>
        <Button
          variant="ghost"
          aria-busy={
            list.isFetching || found.isFetching || lookup?.status === "pending" || undefined
          }
          onClick={refresh}
        >
          <RefreshCw className="size-4" /> {t("api_keys_refresh")}
        </Button>
        <Button variant="outline" onClick={() => setShowConstraintPolicy(true)}>
          <ShieldCheck className="size-4" /> {t("api_keys_admin_tenant_policy")}
        </Button>
        <Button variant="outline" onClick={() => setShowPolicy(true)}>
          <Settings className="size-4" /> {t("notification_policy")}
        </Button>
        <CreateApiKeyDialog
          idPrefix="org"
          defaultOwnership="service"
          trigger={
            <Button>
              <Plus className="size-4" /> {t("api_keys_create_short")}
            </Button>
          }
          onCreated={showSecret(t("api_keys_created_title"))}
        />
      </PageHeader>
      <NotificationPolicyDialog open={showPolicy} onOpenChange={setShowPolicy} />
      <ApiKeyPolicyDialog open={showConstraintPolicy} onOpenChange={setShowConstraintPolicy} />

      <KeyFilterForm
        key={formKey}
        initial={applied}
        activeCount={count}
        pending={lookup?.status === "pending"}
        onApply={(filters) => void apply(filters)}
        onClear={clear}
      />

      <Tabs
        value={state}
        onValueChange={(value) => setState(value as ApiKeyStateFilter)}
        className="gap-4"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <TabsList>
            {API_KEY_STATE_FILTERS.map((value) => (
              <TabsTrigger key={value} value={value}>
                {t(stateFilterLabelKey(value))}
              </TabsTrigger>
            ))}
          </TabsList>
          {shown && (
            <p className="text-muted-foreground text-sm">
              {t("api_keys_admin_showing_keys", shown)}
            </p>
          )}
        </div>

        {/* The keys in the selected state: the state tabs' panel. */}
        <TabsContent ref={panelRef} value={state} className="flex flex-col gap-4">
          <RemovalFocusScope target={panelRef}>
            {lookup?.status === "pending" ? (
              <LoadingState rows={3} />
            ) : lookup?.status === "failed" ? (
              <ListError
                error={lookup.error}
                isRetrying={lookup.retrying}
                onRetry={() => void apply(applied, { retry: true })}
              />
            ) : foundId ? (
              <QueryStateBoundary query={found} rows={3}>
                {(key) => table([{ ...key, search_match_reasons: ["exact_secret"] }])}
              </QueryStateBoundary>
            ) : (
              <QueryStateBoundary query={list} rows={3}>
                {() => table(list.items)}
              </QueryStateBoundary>
            )}
          </RemovalFocusScope>
        </TabsContent>
      </Tabs>

      {lookup === null && (list.hasPreviousPage || list.hasNextPage) && (
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!list.hasPreviousPage}
            onClick={list.previousPage}
          >
            {t("previous")}
          </Button>
          <Button variant="outline" size="sm" disabled={!list.hasNextPage} onClick={list.nextPage}>
            {t("next")}
          </Button>
        </div>
      )}

      <SettingsGroup title={t("api_keys_admin_runtime_settings_title")}>
        <ExpiryNotificationsSwitch />
      </SettingsGroup>
      <SettingsGroup title={t("api_keys_admin_tracking_title")}>
        <KeyTrackingSwitches />
      </SettingsGroup>

      <SecretRevealDialog title={secretTitle} secret={secret} onClose={() => setSecret(null)} />
    </div>
  );
}

/**
 * The filters, applied together (a lookup of a pasted key is a request, so
 * nothing is sent while typing). The search field is kept out of the
 * browser's form history: it may hold a whole key.
 */
function KeyFilterForm({
  initial,
  activeCount,
  pending,
  onApply,
  onClear
}: {
  initial: AdminKeyFilters;
  activeCount: number;
  pending: boolean;
  onApply: (filters: AdminKeyFilters) => void;
  onClear: () => void;
}) {
  const t = useTranslations();
  const id = useId();
  const [filters, setFilters] = useState(initial);
  // A space, assistant or app the admin is not a member of is given by id.
  const [manualScopeId, setManualScopeId] = useState("");
  const update = (patch: Partial<AdminKeyFilters>) =>
    setFilters((current) => ({ ...current, ...patch }));
  const queryClient = useQueryClient();
  const users = useMemo<SearchSource<SearchableItem>>(
    () => ({
      search: async (query) => {
        const search = query.trim();
        if (search.length < MIN_SEARCH_LENGTH) return [];
        // A key's owner or creator may since have been deactivated.
        const pages = await Promise.all(
          (["active", "inactive"] as const).map((stateFilter) =>
            queryClient.query(adminUsersQueryOptions(browserApi, { page: 1, stateFilter, search }))
          )
        );
        return pages
          .flatMap((page) => page.items)
          .map((user) => ({ id: user.id, label: user.email }));
      },
      bootstrap: () => []
    }),
    [queryClient]
  );
  const scopeType = filters.scopeType;

  return (
    <form
      aria-labelledby={`${id}-title`}
      className="flex flex-col gap-4 rounded-xl border p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!pending) onApply({ ...filters, scopeId: manualScopeId.trim() || filters.scopeId });
      }}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={`${id}-title`} className="text-base font-semibold">
          {t("api_keys_admin_filters_search")}
        </h2>
        <p className="text-muted-foreground text-sm">
          {activeCount > 0
            ? t(
                activeCount === 1
                  ? "api_keys_admin_filters_active"
                  : "api_keys_admin_filters_active_plural",
                { count: activeCount }
              )
            : t("api_keys_admin_filters_description")}
        </p>
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor={`${id}-search`}>{t("search")}</Label>
        <Input
          id={`${id}-search`}
          type="search"
          autoComplete="off"
          spellCheck={false}
          value={filters.search}
          placeholder={t("api_keys_admin_search_placeholder")}
          onChange={(event) => update({ search: event.target.value })}
        />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Typeahead
          label={t("user")}
          description={t("audit_user_search_hint", { count: MIN_SEARCH_LENGTH })}
          placeholder={t("audit_search_placeholder_user")}
          searchSource={users}
          value={filters.user}
          onChange={(user) => update({ user })}
          minQueryLength={MIN_SEARCH_LENGTH}
          debounceMs={SEARCH_DEBOUNCE_MS}
          emptySearchResultsText={t("audit_user_search_empty")}
          hasClear
          width="100%"
        />
        <fieldset className="flex flex-col gap-2">
          <legend id={`${id}-relation`} className="mb-2 text-sm font-medium">
            {t("api_keys_admin_user_relation_label")}
          </legend>
          <RadioGroup
            value={filters.userRelation}
            onValueChange={(value) => update({ userRelation: value as "owner" | "creator" })}
            aria-labelledby={`${id}-relation`}
            className="flex gap-5"
          >
            {(["owner", "creator"] as const).map((relation) => (
              <div key={relation} className="flex items-center gap-2">
                <RadioGroupItem id={`${id}-relation-${relation}`} value={relation} />
                <Label htmlFor={`${id}-relation-${relation}`} className="font-normal">
                  {t(`api_keys_admin_user_relation_${relation}`)}
                </Label>
              </div>
            ))}
          </RadioGroup>
        </fieldset>
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${id}-scope`}>{t("api_keys_admin_label_scope_type")}</Label>
          <Select
            value={scopeType}
            onValueChange={(value) => {
              setManualScopeId("");
              update({ scopeType: value as ApiKeyScopeType | "all", scopeId: null });
            }}
          >
            <SelectTrigger id={`${id}-scope`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SCOPE_FILTERS.map((value) => (
                <SelectItem key={value} value={value}>
                  {t(`api_keys_admin_scope_${value}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {scopeType !== "all" && scopeType !== "tenant" ? (
          <div className="flex flex-col gap-3">
            <ScopeResourcePicker
              key={scopeType}
              scopeType={scopeType}
              value={filters.scopeId}
              onChange={(scopeId) => update({ scopeId })}
              label={t("api_keys_admin_label_scope_target")}
            />
            <div className="flex flex-col gap-2">
              <Label htmlFor={`${id}-scope-id`}>
                {t("api_keys_enter_id_manually", {
                  scopeType: t(`api_keys_scope_${scopeType}`).toLocaleLowerCase()
                })}
              </Label>
              <Input
                id={`${id}-scope-id`}
                className="font-mono"
                value={manualScopeId}
                placeholder={t("api_keys_enter_uuid")}
                onChange={(event) => setManualScopeId(event.target.value)}
              />
            </div>
          </div>
        ) : (
          <div className="hidden md:block" />
        )}
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${id}-type`}>{t("api_keys_admin_label_key_type")}</Label>
          <Select
            value={filters.keyType}
            onValueChange={(value) => update({ keyType: value as ApiKeyType | "all" })}
          >
            <SelectTrigger id={`${id}-type`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {KEY_TYPE_FILTERS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {t(option.key)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-expires`}>{t("api_keys_admin_expires_within_label")}</Label>
            <Input
              id={`${id}-expires`}
              type="number"
              inputMode="numeric"
              min={1}
              value={filters.expiresWithinDays}
              onChange={(event) => update({ expiresWithinDays: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={`${id}-limit`}>{t("api_keys_admin_label_results_limit")}</Label>
            <Select
              value={String(filters.limit)}
              onValueChange={(value) => update({ limit: Number(value) })}
            >
              <SelectTrigger id={`${id}-limit`} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RESULT_LIMITS.map((limit) => (
                  <SelectItem key={limit} value={String(limit)}>
                    {limit}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onClear}>
          {t("api_keys_admin_clear_all")}
        </Button>
        {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
        <Button type="submit" aria-busy={pending || undefined}>
          {t("api_keys_admin_apply_filters")}
        </Button>
      </div>
    </form>
  );
}

const MATCH_REASON_LABEL: Record<string, string> = {
  exact_secret: "api_keys_admin_match_reason_exact_secret",
  key_suffix: "api_keys_admin_match_reason_key_suffix",
  name_or_description: "api_keys_admin_match_reason_text",
  owner: "api_keys_admin_match_reason_owner",
  creator: "api_keys_admin_match_reason_creator"
};

/** The keys as rows: who owns each, its scope, access, state, rate limit, last use and expiry. */
function KeyTable({
  keys,
  labelledBy,
  scopeNames,
  onRotated
}: {
  keys: ApiKey[];
  labelledBy: string;
  scopeNames: Map<string, string>;
  onRotated: (secret: string) => void;
}) {
  const t = useTranslations();
  return (
    <Table aria-labelledby={labelledBy} className="min-w-[64rem]">
      <TableHeader>
        <TableRow>
          <TableHead>{t("name")}</TableHead>
          <TableHead>{t("api_keys_admin_owner_label")}</TableHead>
          <TableHead>{t("api_keys_scope")}</TableHead>
          <TableHead>{t("api_keys_permission_level")}</TableHead>
          <TableHead>{t("status")}</TableHead>
          <TableHead>{t("api_keys_admin_rate_limit")}</TableHead>
          <TableHead>{t("api_keys_last_used")}</TableHead>
          <TableHead>{t("api_keys_expires")}</TableHead>
          <TableHead className="w-14 min-w-14" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {keys.map((apiKey) => {
          const scopeName = apiKey.scope_id ? scopeNames.get(apiKey.scope_id) : undefined;
          return (
            <TableRow key={apiKey.id}>
              <TableCell>
                <div className="flex flex-col gap-1">
                  <span className="font-medium">{apiKey.name}</span>
                  <code className="text-muted-foreground font-mono text-xs">
                    {apiKey.key_prefix}…{apiKey.key_suffix}
                  </code>
                  {apiKey.search_match_reasons?.length ? (
                    <span className="flex flex-wrap gap-1">
                      {apiKey.search_match_reasons.map((reason) => (
                        <Badge key={reason} variant="outline">
                          {t(MATCH_REASON_LABEL[reason] ?? "api_keys_admin_match_reason_text")}
                        </Badge>
                      ))}
                    </span>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="text-sm">
                {apiKey.owner_user_id ? (
                  apiKey.owner_user?.email ? (
                    <Link
                      href={`/admin/users?search=${encodeURIComponent(apiKey.owner_user.email)}`}
                      className="underline"
                    >
                      {userLabel(apiKey.owner_user, apiKey.owner_user_id)}
                    </Link>
                  ) : (
                    userLabel(apiKey.owner_user, apiKey.owner_user_id)
                  )
                ) : (
                  t("api_keys_ownership_service")
                )}
              </TableCell>
              <TableCell className="text-sm">
                {t(`api_keys_admin_scope_${apiKey.scope_type}`)}
                {apiKey.scope_id ? (
                  <span className="text-muted-foreground block text-xs">
                    {scopeName ?? `${apiKey.scope_id.slice(0, 8)}…`}
                  </span>
                ) : null}
              </TableCell>
              <TableCell>{t(`api_keys_permission_${apiKey.permission}`)}</TableCell>
              <TableCell>
                <Badge variant={API_KEY_STATE_BADGE_VARIANT[apiKey.state]}>
                  {t(`api_keys_status_${apiKey.state}`)}
                </Badge>
              </TableCell>
              <TableCell className="text-sm">
                {apiKey.rate_limit
                  ? t("api_keys_rate_limit_value", { count: apiKey.rate_limit })
                  : t("api_keys_default")}
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">
                {apiKey.last_used_at ? (
                  <ClientTime value={apiKey.last_used_at} format="auto" />
                ) : (
                  t("api_keys_never")
                )}
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">
                {apiKey.expires_at ? formatApiKeyDate(apiKey.expires_at) : t("api_keys_never")}
              </TableCell>
              <TableCell className="text-end">
                <ApiKeyActions
                  apiKey={apiKey}
                  mode="admin"
                  scopeName={scopeName}
                  onRotated={onRotated}
                />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/** The tenant's master switch for API key expiry notifications: saves on toggle, reverts on error. */
function ExpiryNotificationsSwitch() {
  const t = useTranslations();
  const { settings } = useAppContext();
  const [value, setValue] = useSettingSwitch(
    "api-key-expiry-notifications",
    settings.api_key_expiry_notifications !== false,
    (enabled) =>
      unwrap(
        browserApi.PATCH("/api/v1/settings/api-key-expiry-notifications", { body: { enabled } })
      )
  );
  return (
    <Switch
      label={t("api_keys_notifications_feature_flag_title")}
      description={t("api_keys_notifications_feature_flag_description")}
      labelPosition="start"
      labelSpacing="spread"
      value={value}
      onChange={setValue}
    />
  );
}

const TRACKED_ACTIONS = [
  {
    action: "api_key_used",
    fallback: false,
    title: "api_keys_admin_tracking_used_title",
    description: "api_keys_admin_tracking_used_description"
  },
  {
    action: "api_key_auth_failed",
    fallback: true,
    title: "api_keys_admin_tracking_failed_title",
    description: "api_keys_admin_tracking_failed_description"
  }
] as const;

/** Whether the audit log records key use and failed key authentication (the audit config's switches). */
function KeyTrackingSwitches() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const actions = useQuery(auditActionConfigQueryOptions(browserApi));
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: AUDIT_CONFIG_KEY });
    void queryClient.invalidateQueries({ queryKey: AUDIT_ACTION_CONFIG_KEY });
  };
  return (
    <QueryStateBoundary query={actions} rows={2}>
      {(configs) => (
        <ul className="flex flex-col gap-3">
          {TRACKED_ACTIONS.map((row) => (
            <li key={row.action}>
              <Label className="flex items-start justify-between gap-4 font-normal">
                <span className="flex flex-col gap-0.5">
                  <span className="text-sm font-medium">{t(row.title)}</span>
                  <span className="text-muted-foreground text-xs">{t(row.description)}</span>
                </span>
                <ActionSwitch
                  action={row.action}
                  enabled={
                    configs.find((config) => config.action === row.action)?.enabled ?? row.fallback
                  }
                  onSaved={invalidate}
                />
              </Label>
            </li>
          ))}
        </ul>
      )}
    </QueryStateBoundary>
  );
}
