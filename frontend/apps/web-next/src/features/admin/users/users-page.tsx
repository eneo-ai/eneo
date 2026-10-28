"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce, useMediaQuery } from "@astryxdesign/core/hooks";
import { Pagination } from "@astryxdesign/core/Pagination";
import { Selector, type SelectorOptionType } from "@astryxdesign/core/Selector";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { TextInput } from "@/components/astryx/text-input";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { useSearchParams } from "@/lib/navigation";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { TableFrame } from "@/components/composites/table-frame";
import { browserApi } from "@/lib/api/browser";
import { MEDIA } from "@/lib/breakpoints";
import { rolesQueryOptions } from "@/features/admin/roles/roles";
import { useFocusRescue } from "@/lib/focus-rescue";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { PasswordPolicyPanel } from "./password-policy-panel";
import { IssuedPasswordDialog, UserEditorDialog, type IssuedPassword } from "./user-editor";
import { UserTable } from "./user-table";
import { adminUsersQueryOptions, isSearchable, type StateFilter } from "./users";

const STATE_TABS: StateFilter[] = ["active", "inactive"];
/** Below Tailwind's `sm`, page numbers at 44 px touch sizes overflow a phone. */
const NARROW_QUERY = `not all and ${MEDIA.sm}`;
/** The role filter's "all roles" option (role ids are UUIDs). */
const ALL_ROLES = "all";

type Filters = {
  stateFilter: StateFilter;
  search: string;
  searchName: string;
  page: number;
  roleId: string | null;
};

/** Sync the current filter state into the URL for shareable links. */
function syncUrl({ stateFilter, search, searchName, page, roleId }: Filters) {
  const params = new URLSearchParams();
  if (stateFilter !== "active") params.set("tab", stateFilter);
  if (search) params.set("search", search);
  if (searchName) params.set("search_name", searchName);
  if (page > 1) params.set("page", String(page));
  if (roleId) params.set("role_id", roleId);
  const query = params.toString();
  window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
}

/**
 * A search box: the draft, and the search it commits once typing pauses at 0
 * or ≥3 characters (backend rule), calling `onCommit`. `clear` empties both
 * at once; the debounced draft still holds the old text then, so a commit
 * waits until it has caught up with the draft.
 */
function useSearchBox(initial: string, onCommit: () => void) {
  const [draft, setDraft] = useState(initial);
  const [value, setValue] = useState(initial);
  const debounced = useDebouncedValue(draft.trim());
  if (debounced === draft.trim() && isSearchable(debounced) && debounced !== value) {
    setValue(debounced);
    onCommit();
  }
  return {
    draft,
    setDraft,
    value,
    clear() {
      setDraft("");
      setValue("");
    }
  };
}

export function AdminUsersPage() {
  const t = useTranslations();
  const format = useFormatter();
  const searchParams = useSearchParams();

  const initialTab = searchParams.get("tab") === "inactive" ? "inactive" : "active";
  const initialPage = Math.max(1, Number(searchParams.get("page")) || 1);
  const [roleId, setRoleId] = useState(searchParams.get("role_id"));

  const [stateFilter, setStateFilter] = useState<StateFilter>(initialTab);
  const [page, setPage] = useState(initialPage);
  const [showCreate, setShowCreate] = useState(false);
  // Passwords the editor set, shown one at a time in the order the saves
  // landed. Held here, not in the row whose editor set them: a refetch may
  // drop that row mid-save, and the save then lands with its editor gone. A
  // queue, as the admin may save another user meanwhile, so a second password
  // can land before the first has been handed over.
  const [issued, setIssued] = useState<{ key: number; password: IssuedPassword }[]>([]);
  const issuedCount = useRef(0);
  function showIssued(password: IssuedPassword) {
    const key = ++issuedCount.current;
    setIssued((queue) => [...queue, { key, password }]);
  }
  // E-mail and username searches combine (AND); a new search starts over at page 1.
  const emailBox = useSearchBox((searchParams.get("search") ?? "").trim(), () => setPage(1));
  const nameBox = useSearchBox((searchParams.get("search_name") ?? "").trim(), () => setPage(1));
  const search = emailBox.value;
  const searchName = nameBox.value;

  const baseId = useId();
  const panelId = `${baseId}-panel`;
  const hintId = `${baseId}-search-hint`;
  const tabId = (value: StateFilter) => `${baseId}-tab-${value}`;
  const tabLabel = (value: StateFilter) =>
    value === "active" ? t("active_users") : t("inactive_users");
  const panelRef = useRef<HTMLDivElement>(null);
  const rescue = useFocusRescue();
  const announce = useAnnounce();
  const isNarrow = useMediaQuery(NARROW_QUERY);

  useEffect(() => {
    syncUrl({ stateFilter, search, searchName, page, roleId });
  }, [stateFilter, search, searchName, page, roleId]);

  const roles = useQuery(rolesQueryOptions(browserApi));
  const predefined = roles.data?.predefined ?? [];
  const custom = roles.data?.custom ?? [];
  const roleKnown = [...predefined, ...custom].some((role) => role.id === roleId);
  const roleOptions: SelectorOptionType[] = [
    { value: ALL_ROLES, label: t("admin_users_all_roles") },
    ...[
      { title: t("default_roles"), roles: predefined },
      { title: t("custom_roles"), roles: custom }
    ]
      .filter((section) => section.roles.length > 0)
      .map((section) => ({
        type: "section" as const,
        title: section.title,
        options: section.roles.map((role) => ({ value: role.id, label: role.name }))
      })),
    // A role from an old link that no longer exists still shows as the filter.
    ...(roleId && roles.data && !roleKnown
      ? [{ value: roleId, label: t("admin_users_unknown_role") }]
      : [])
  ];

  const { data, isPending, isPlaceholderData } = useQuery({
    ...adminUsersQueryOptions(browserApi, {
      page,
      stateFilter,
      search,
      searchName: searchName || undefined,
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

  // Past the backend's page cap the rest can only be reached by filtering.
  const capped =
    metadata != null &&
    !isPlaceholderData &&
    metadata.total_count > metadata.total_pages * metadata.page_size;

  // Announce the result count once the results of a new search, tab or role
  // filter are in (WCAG 4.1.3); not on first load, not for page changes
  // (Pagination announces those).
  const resultsFor = `${stateFilter}|${search}|${searchName}|${roleId ?? ""}`;
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

  function selectRole(next: string) {
    setRoleId(next === ALL_ROLES ? null : next);
    setPage(1);
  }

  function clearFilters() {
    emailBox.clear();
    nameBox.clear();
    setRoleId(null);
    setPage(1);
  }

  function changePage(next: number) {
    setPage(next);
    // The pressed button stays focused, except "next"/"previous" at the last
    // or first page, which becomes disabled: then focus moves to the panel.
    rescue(panelRef.current);
  }

  let results: React.ReactNode;
  if (isPending) {
    results = <LoadingState rows={5} />;
  } else if (users.length === 0) {
    results = <EmptyState title={t("no_users_found")} />;
  } else {
    results = (
      <TableFrame>
        <UserTable
          users={users}
          label={tabLabel(stateFilter)}
          onRemoved={() => rescue(panelRef.current)}
          onIssued={showIssued}
        />
      </TableFrame>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
      <PageHeader
        title={t("users")}
        description={t("admin_users_description")}
        breadcrumbs={[
          { label: t("admin_breadcrumb_root"), href: "/admin" },
          { label: t("admin_section_organisation") }
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
          focused row (see useFocusRescue). */}
      <div
        ref={panelRef}
        role="tabpanel"
        id={panelId}
        aria-labelledby={tabId(stateFilter)}
        tabIndex={-1}
        className="focus-visible:outline-ring rounded-ax-element flex flex-col gap-4 focus-visible:outline-2 focus-visible:outline-offset-4"
      >
        {/* The filters search the whole list (the backend filters), not the page. */}
        <div role="search" aria-label={t("users")} className="flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <TextInput
              label={t("email")}
              value={emailBox.draft}
              onChange={emailBox.setDraft}
              hasClear
              autoComplete="off"
              aria-describedby={hintId}
              width="100%"
            />
            <TextInput
              label={t("username")}
              value={nameBox.draft}
              onChange={nameBox.setDraft}
              hasClear
              autoComplete="off"
              aria-describedby={hintId}
              width="100%"
            />
            <Selector
              label={t("roles_filter_label")}
              options={roleOptions}
              value={roleId ?? ALL_ROLES}
              onChange={selectRole}
              isLoading={roles.isPending}
              width="100%"
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <p id={hintId} className="text-ax-text-secondary max-w-xl text-sm">
              {t("admin_users_search_hint")}
            </p>
            <Button label={t("admin_users_clear_filters")} size="sm" onClick={clearFilters} />
            <p className="text-ax-text-secondary ms-auto text-sm">
              {total != null ? t("admin_users_count", { count: total }) : ""}
            </p>
          </div>
        </div>

        <div aria-busy={isPlaceholderData || undefined}>{results}</div>

        {capped ? (
          <p className="text-ax-text-secondary text-sm">{t("admin_users_refine_search")}</p>
        ) : null}

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

      <PasswordPolicyPanel />

      <UserEditorDialog open={showCreate} onOpenChange={setShowCreate} onIssued={showIssued} />
      <IssuedPasswordDialog
        // A fresh view for each password.
        key={issued[0]?.key}
        issued={issued[0]?.password ?? null}
        onClose={() => {
          setIssued((queue) => queue.slice(1));
          // The row whose menu opened the editor may have gone meanwhile.
          rescue(panelRef.current);
        }}
      />
    </div>
  );
}
