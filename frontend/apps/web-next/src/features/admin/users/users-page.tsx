import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce, useMediaQuery } from "@astryxdesign/core/hooks";
import { Pagination } from "@astryxdesign/core/Pagination";
import { Selector, type SelectorOptionType } from "@astryxdesign/core/Selector";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { TextInput } from "@/components/astryx/text-input";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ListFilter, Search, UserPlus } from "lucide-react";
import { replaceUrl, usePathname, useSearchParams } from "@/lib/navigation";
import { useFormatter, useTranslations } from "use-intl";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { MEDIA } from "@/lib/breakpoints";
import { rolesQueryOptions } from "@/features/admin/roles/roles";
import { useFocusRescue } from "@/lib/focus-rescue";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { useSearchDraft } from "@/lib/hooks/use-search-draft";
import { cn } from "@/lib/utils";
import { PasswordPolicyPanel } from "./password-policy-panel";
import { IssuedPasswordDialog, UserEditorDialog, type IssuedPassword } from "./user-editor";
import { UserActionScope } from "./user-actions";
import { UserList } from "./user-table";
import {
  adminUsersQueryOptions,
  isSearchable,
  readUsersFilters,
  usersFiltersSearchParams,
  type StateFilter,
  type UsersFilters
} from "./users";
import { KEYBOARD } from "@/components/astryx/keyboard-hints";

const STATE_TABS: StateFilter[] = ["active", "inactive"];
/** Below Tailwind's `sm`, page numbers at 44 px touch sizes overflow a phone. */
const NARROW_QUERY = `not all and ${MEDIA.sm}`;
/** The role filter's "all roles" option (role ids are UUIDs). */
const ALL_ROLES = "all";

export function AdminUsersPage() {
  const t = useTranslations();
  const format = useFormatter();
  const searchParams = useSearchParams();

  const pathname = usePathname();
  const filters = useMemo(() => readUsersFilters(searchParams), [searchParams]);
  const { stateFilter, search, searchName, page, roleId } = filters;
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
  const emailBox = useSearchDraft(search);
  const nameBox = useSearchDraft(searchName);
  const nextEmail = isSearchable(emailBox.settled) ? emailBox.settled : search;
  const nextName = isSearchable(nameBox.settled) ? nameBox.settled : searchName;
  useEffect(() => {
    if (nextEmail !== filters.search || nextName !== filters.searchName) {
      const query = usersFiltersSearchParams({
        ...filters,
        search: nextEmail,
        searchName: nextName,
        page: 1
      }).toString();
      replaceUrl(query ? `${pathname}?${query}` : pathname);
    }
  }, [filters, nextEmail, nextName, pathname]);

  function changeFilters(next: Partial<UsersFilters>) {
    const query = usersFiltersSearchParams({ ...filters, ...next }).toString();
    replaceUrl(query ? `${pathname}?${query}` : pathname);
  }

  const baseId = useId();
  const panelId = `${baseId}-panel`;
  const hintId = `${baseId}-search-hint`;
  const tabId = (value: StateFilter) => `${baseId}-tab-${value}`;
  const tabLabel = (value: StateFilter) =>
    value === "active" ? t("active_users") : t("inactive_users");
  // Under the "Användare" heading a tab says only which ones (both fit a 320
  // px phone); the table keeps the full name.
  const tabName = (value: StateFilter) =>
    value === "active" ? t("admin_users_tab_active") : t("admin_users_tab_inactive");
  const panelRef = useRef<HTMLDivElement>(null);
  const rescue = useFocusRescue();
  const announce = useAnnounce();
  const isNarrow = useMediaQuery(NARROW_QUERY);
  // A phone searches by e-mail and keeps username and role in a sheet, so
  // its first screen shows users rather than filters.
  const phone = useMediaMatch(PHONE_QUERY);
  const [filtersOpen, setFiltersOpen] = useState(false);
  // The sheet goes with a turn past 768 px; turning back must not reopen it.
  if (!phone && filtersOpen) setFiltersOpen(false);
  const sheetHintId = `${baseId}-sheet-hint`;

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
  useEffect(() => {
    if (metadata && !isPlaceholderData && filters.page > totalPages) {
      const query = usersFiltersSearchParams({ ...filters, page: totalPages }).toString();
      replaceUrl(query ? `${pathname}?${query}` : pathname);
    }
  }, [metadata, isPlaceholderData, filters, totalPages, pathname]);

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

  // The sheet's filters as applied, so the button's count matches the list.
  const sheetFilterCount = (searchName ? 1 : 0) + (roleId ? 1 : 0);

  function selectTab(next: StateFilter) {
    changeFilters({ stateFilter: next, page: 1 });
  }

  function selectRole(next: string) {
    changeFilters({ roleId: next === ALL_ROLES ? null : next, page: 1 });
  }

  const filtered = Boolean(emailBox.draft || nameBox.draft || search || searchName || roleId);

  function clearFilters() {
    emailBox.setDraft("");
    nameBox.setDraft("");
    changeFilters({ search: "", searchName: "", roleId: null, page: 1 });
    // The pressed button leaves with the filters: focus goes to the list.
    rescue(panelRef.current);
  }

  function changePage(next: number) {
    changeFilters({ page: next });
    // The pressed button stays focused, except "next"/"previous" at the last
    // or first page, which becomes disabled: then focus moves to the panel.
    rescue(panelRef.current);
  }

  let results: React.ReactNode;
  if (isPending) {
    results = <LoadingState rows={5} />;
  } else if (users.length === 0) {
    results = <EmptyState isAnnounced={false} title={t("no_users_found")} />;
  } else {
    results = (
      <UserList
        users={users}
        label={tabLabel(stateFilter)}
        onRemoved={() => rescue(panelRef.current)}
      />
    );
  }

  const nameField = (describedBy: string) => (
    <TextInput
      label={t("username")}
      {...KEYBOARD.identifier}
      value={nameBox.draft}
      onChange={nameBox.setDraft}
      hasClear
      autoComplete="off"
      aria-describedby={describedBy}
      width="100%"
    />
  );
  const roleField = (
    <Selector
      label={t("roles_filter_label")}
      options={roleOptions}
      value={roleId ?? ALL_ROLES}
      onChange={selectRole}
      isLoading={roles.isPending}
      width="100%"
    />
  );

  return (
    <div className="flex w-full flex-col gap-5">
      <PageHeader
        title={t("users")}
        description={t("admin_users_description")}
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
              label={tabName(value)}
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
          {/* One e-mail field for both layouts: a turn across 768 px keeps it,
              with the focus and what was typed. */}
          <div
            className={
              phone ? "flex flex-wrap items-end gap-2" : "grid gap-3 sm:grid-cols-2 md:grid-cols-3"
            }
          >
            <div className={phone ? "min-w-40 flex-1" : undefined}>
              <TextInput
                label={phone ? t("admin_users_email_search") : t("email")}
                isLabelHidden={phone}
                placeholder={phone ? t("admin_users_email_search") : undefined}
                startIcon={phone ? Search : undefined}
                {...(phone ? KEYBOARD.search : KEYBOARD.email)}
                value={emailBox.draft}
                onChange={emailBox.setDraft}
                hasClear
                autoComplete="off"
                aria-describedby={hintId}
                width="100%"
              />
            </div>
            {phone ? (
              <>
                <Button
                  label={
                    sheetFilterCount > 0
                      ? t("audit_filters_button_count", { count: sheetFilterCount })
                      : t("audit_filters_button")
                  }
                  icon={<ListFilter aria-hidden="true" />}
                  aria-haspopup="dialog"
                  aria-expanded={filtersOpen}
                  onClick={() => setFiltersOpen(true)}
                />
                <BottomSheet
                  isOpen={filtersOpen}
                  onOpenChange={setFiltersOpen}
                  label={t("audit_filters_button")}
                  height="tall"
                >
                  {/* Each change applies at once, as in the fields above the table. */}
                  <div className="flex flex-col gap-4 p-4">
                    <p id={sheetHintId} className="text-ax-text-secondary text-sm">
                      {t("admin_users_filters_description")}
                    </p>
                    {nameField(sheetHintId)}
                    {roleField}
                    <div className="flex justify-end">
                      <Button
                        variant="primary"
                        label={t("done")}
                        onClick={() => setFiltersOpen(false)}
                      />
                    </div>
                  </div>
                </BottomSheet>
              </>
            ) : (
              <>
                {nameField(hintId)}
                {roleField}
              </>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {/* On a phone for screen readers only, so the first screen keeps its room
                for users, and for the e-mail field alone; the sheet states the rule
                for usernames. */}
            <p
              id={hintId}
              className={cn("text-ax-text-secondary max-w-xl text-sm", phone && "sr-only")}
            >
              {phone ? t("admin_users_email_search_hint") : t("admin_users_search_hint")}
            </p>
            {/* Only while there is something to clear, as the crawler's filters. */}
            {filtered ? (
              <Button label={t("admin_users_clear_filters")} size="sm" onClick={clearFilters} />
            ) : null}
            <p className="text-ax-text-secondary ms-auto text-sm">
              {total != null ? t("admin_users_count", { count: total }) : ""}
            </p>
          </div>
        </div>

        <UserActionScope focusTarget={panelRef} onIssued={showIssued}>
          <div aria-busy={isPlaceholderData || undefined}>{results}</div>
        </UserActionScope>

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
