"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce, useMediaQuery } from "@astryxdesign/core/hooks";
import { Pagination } from "@astryxdesign/core/Pagination";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { TextInput } from "@/components/astryx/text-input";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search, UserPlus } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { rolesQueryOptions } from "@/features/admin/roles/roles";
import { rescueFocus } from "@/lib/focus-rescue";
import { UserEditorDialog } from "./user-editor";
import { UserTable } from "./user-table";
import { adminUsersQueryOptions, MIN_SEARCH_LENGTH, type StateFilter } from "./users";

const SEARCH_DEBOUNCE_MS = 250;
const STATE_TABS: StateFilter[] = ["active", "inactive"];
/** Below Tailwind's `sm`, page numbers at 44 px touch sizes overflow a phone. */
const NARROW_QUERY = "(width < 40rem)";

/** Sync the current filter state into the URL for shareable links. */
function syncUrl(stateFilter: StateFilter, search: string, page: number, roleId: string | null) {
  const params = new URLSearchParams();
  if (stateFilter !== "active") params.set("tab", stateFilter);
  if (search) params.set("search", search);
  if (page > 1) params.set("page", String(page));
  if (roleId) params.set("role_id", roleId);
  const query = params.toString();
  window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
}

export function AdminUsersPage() {
  const t = useTranslations();
  const format = useFormatter();
  const searchParams = useSearchParams();

  const initialTab = searchParams.get("tab") === "inactive" ? "inactive" : "active";
  const initialSearch = searchParams.get("search") ?? "";
  const initialPage = Math.max(1, Number(searchParams.get("page")) || 1);
  const [roleId, setRoleId] = useState(searchParams.get("role_id"));

  const [stateFilter, setStateFilter] = useState<StateFilter>(initialTab);
  const [searchInput, setSearchInput] = useState(initialSearch);
  const [search, setSearch] = useState(initialSearch);
  const [page, setPage] = useState(initialPage);
  const [showCreate, setShowCreate] = useState(false);

  const baseId = useId();
  const panelId = `${baseId}-panel`;
  const tabId = (value: StateFilter) => `${baseId}-tab-${value}`;
  const tabLabel = (value: StateFilter) =>
    value === "active" ? t("active_users") : t("inactive_users");
  const panelRef = useRef<HTMLDivElement>(null);
  const announce = useAnnounce();
  const isNarrow = useMediaQuery(NARROW_QUERY);

  // Debounce the search box; only commit at 0 or ≥3 chars (backend rule).
  const debounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      const trimmed = searchInput.trim();
      if (trimmed.length > 0 && trimmed.length < MIN_SEARCH_LENGTH) return;
      if (trimmed !== search) {
        setSearch(trimmed);
        setPage(1);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(debounce.current);
  }, [searchInput, search]);

  useEffect(() => {
    syncUrl(stateFilter, search, page, roleId);
  }, [stateFilter, search, page, roleId]);

  const roles = useQuery(rolesQueryOptions(browserApi));
  const selectedRole = [...(roles.data?.custom ?? []), ...(roles.data?.predefined ?? [])].find(
    (role) => role.id === roleId
  );

  const { data, isPending, isPlaceholderData } = useQuery({
    ...adminUsersQueryOptions(browserApi, {
      page,
      stateFilter,
      search,
      roleId: roleId ?? undefined
    }),
    placeholderData: keepPreviousData
  });

  const users = data?.items ?? [];
  const metadata = data?.metadata;
  const counts = metadata?.counts ?? {};
  const totalPages = Math.max(1, metadata?.total_pages ?? 1);
  const total = isPlaceholderData ? undefined : metadata?.total_count;

  // A page past the end (its last user was deactivated or deleted, or an old
  // link): show the last page rather than an empty list.
  if (metadata && !isPlaceholderData && page > totalPages) setPage(totalPages);

  // Announce the result count once the results of a new search, tab or role
  // filter are in (WCAG 4.1.3); not on first load, not for page changes
  // (Pagination announces those).
  const resultsFor = `${stateFilter}|${search}|${roleId ?? ""}`;
  const announcedFor = useRef(resultsFor);
  useEffect(() => {
    if (total == null || announcedFor.current === resultsFor) return;
    announcedFor.current = resultsFor;
    announce(t("admin_users_count", { count: total }));
  }, [announce, resultsFor, t, total]);

  function selectTab(next: StateFilter) {
    setStateFilter(next);
    setPage(1);
  }

  function changePage(next: number) {
    setPage(next);
    // The pressed button stays focused, except "next"/"previous" at the last
    // or first page, which becomes disabled: then focus moves to the panel.
    rescueFocus(panelRef.current);
  }

  let results: React.ReactNode;
  if (isPending) {
    results = <LoadingState rows={5} />;
  } else if (users.length === 0) {
    results = <EmptyState title={t("no_users_found")} />;
  } else {
    results = (
      <div className="bg-ax-card border-ax-border rounded-ax-container overflow-hidden border">
        <UserTable
          users={users}
          label={tabLabel(stateFilter)}
          onRemoved={() => rescueFocus(panelRef.current)}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
      <PageHeader
        title={t("users")}
        description={t("admin_users_description")}
        breadcrumbs={[
          { label: t("admin_breadcrumb_root"), href: "/admin" },
          { label: t("admin_section_access") }
        ]}
        tour="admin-users"
        actions={
          <Button
            variant="primary"
            label={t("create_user")}
            icon={<UserPlus className="size-4" aria-hidden="true" />}
            onClick={() => setShowCreate(true)}
          />
        }
      />

      <TabList
        role="tablist"
        aria-label={t("admin_users_tabs_label")}
        value={stateFilter}
        onChange={(value) => selectTab(value as StateFilter)}
        hasDivider
      >
        {STATE_TABS.map((value) => {
          const count = counts[value];
          return (
            <Tab
              key={value}
              id={tabId(value)}
              value={value}
              label={tabLabel(value)}
              panelId={panelId}
              endContent={
                count != null ? (
                  <span className="text-ax-text-secondary tabular-nums">
                    {format.number(count)}
                  </span>
                ) : undefined
              }
            />
          );
        })}
      </TabList>

      {/* One panel for both tabs; it takes focus when an action removed the
          focused row (see rescueFocus). */}
      <div
        ref={panelRef}
        role="tabpanel"
        id={panelId}
        aria-labelledby={tabId(stateFilter)}
        tabIndex={-1}
        className="focus-visible:outline-ring rounded-ax-element flex flex-col gap-4 focus-visible:outline-2 focus-visible:outline-offset-4"
      >
        <div className="flex flex-wrap items-center gap-2.5">
          <TextInput
            label={t("admin_users_search")}
            isLabelHidden
            placeholder={t("admin_users_search_placeholder")}
            startIcon={Search}
            value={searchInput}
            onChange={setSearchInput}
            hasClear
            autoComplete="off"
            className="w-full sm:w-80"
          />
          {roleId && (
            <div className="bg-ax-muted rounded-ax-element flex items-center gap-2 py-1 ps-3 pe-1 text-sm">
              <span>
                {t("roles_filter_label")}:{" "}
                <strong className="font-semibold">{selectedRole?.name ?? roleId}</strong>
              </span>
              <Button
                variant="ghost"
                size="sm"
                label={t("roles_clear_filter")}
                onClick={() => {
                  setRoleId(null);
                  setPage(1);
                }}
              />
            </div>
          )}
          <p className="text-ax-text-secondary ms-auto text-sm">
            {total != null ? t("admin_users_count", { count: total }) : ""}
          </p>
        </div>

        <div aria-busy={isPlaceholderData || undefined}>{results}</div>

        {/* Never disabled while a page loads: that would take focus from the
            pressed button. The previous page stays visible (aria-busy) and
            the requested page is shown as current. */}
        {totalPages > 1 && (
          <Pagination
            page={Math.min(page, totalPages)}
            totalPages={totalPages}
            onChange={changePage}
            variant={isNarrow ? "compact" : "pages"}
          />
        )}
      </div>

      <UserEditorDialog open={showCreate} onOpenChange={setShowCreate} />
    </div>
  );
}
