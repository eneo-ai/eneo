"use client";

import { Button } from "@astryxdesign/core/Button";
import { Pagination } from "@astryxdesign/core/Pagination";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { TextInput } from "@astryxdesign/core/TextInput";
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
  const totalPages = metadata?.total_pages ?? 1;

  function selectTab(next: StateFilter) {
    setStateFilter(next);
    setPage(1);
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
          {/* The result count, announced politely when a search changes it. */}
          <p role="status" className="text-ax-text-secondary ms-auto text-sm">
            {metadata?.total_count != null && !isPlaceholderData
              ? t("admin_users_count", { count: metadata.total_count })
              : ""}
          </p>
        </div>

        <div aria-busy={isPlaceholderData || undefined}>{results}</div>

        {totalPages > 1 && (
          <Pagination
            page={metadata?.page ?? page}
            totalPages={totalPages}
            onChange={setPage}
            isDisabled={isPlaceholderData}
          />
        )}
      </div>

      <UserEditorDialog open={showCreate} onOpenChange={setShowCreate} />
    </div>
  );
}
