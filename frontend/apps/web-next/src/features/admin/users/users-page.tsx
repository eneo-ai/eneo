"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { cn } from "@/lib/utils";
import { UserEditorDialog } from "./user-editor";
import { UserTable } from "./user-table";
import { adminUsersQueryOptions, MIN_SEARCH_LENGTH, type StateFilter } from "./users";

const SEARCH_DEBOUNCE_MS = 250;
const numberFormat = new Intl.NumberFormat("sv-SE");

/** Sync the current filter state into the URL for shareable links. */
function syncUrl(stateFilter: StateFilter, search: string, page: number) {
  const params = new URLSearchParams();
  if (stateFilter !== "active") params.set("tab", stateFilter);
  if (search) params.set("search", search);
  if (page > 1) params.set("page", String(page));
  const query = params.toString();
  window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
}

export function AdminUsersPage() {
  const t = useTranslations();
  const searchParams = useSearchParams();

  const initialTab = searchParams.get("tab") === "inactive" ? "inactive" : "active";
  const initialSearch = searchParams.get("search") ?? "";
  const initialPage = Math.max(1, Number(searchParams.get("page")) || 1);

  const [stateFilter, setStateFilter] = useState<StateFilter>(initialTab);
  const [searchInput, setSearchInput] = useState(initialSearch);
  const [search, setSearch] = useState(initialSearch);
  const [page, setPage] = useState(initialPage);
  const [showCreate, setShowCreate] = useState(false);

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
    syncUrl(stateFilter, search, page);
  }, [stateFilter, search, page]);

  const { data, isPending, isPlaceholderData } = useQuery({
    ...adminUsersQueryOptions(browserApi, { page, stateFilter, search }),
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

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("users")}>
        <Button onClick={() => setShowCreate(true)}>{t("create_user")}</Button>
      </PageHeader>

      <Tabs value={stateFilter} onValueChange={(value) => selectTab(value as StateFilter)}>
        <TabsList>
          <TabsTrigger value="active">
            {t("active_users")}
            {counts.active != null && (
              <span className="text-muted-foreground ml-1.5">
                ({numberFormat.format(counts.active)})
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="inactive">
            {t("inactive_users")}
            {counts.inactive != null && (
              <span className="text-muted-foreground ml-1.5">
                ({numberFormat.format(counts.inactive)})
              </span>
            )}
          </TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="relative max-w-sm">
        <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
        <Input
          value={searchInput}
          placeholder={t("search")}
          className="pl-9"
          onChange={(event) => setSearchInput(event.target.value)}
        />
      </div>

      <div className={cn(isPlaceholderData && "opacity-60 transition-opacity")}>
        {isPending ? (
          <EmptyState title={t("loading")} />
        ) : users.length === 0 ? (
          <EmptyState title={t("no_users_found")} />
        ) : (
          <UserTable users={users} />
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground text-sm">
            {t("page")} {metadata?.page ?? page} / {totalPages}
            {metadata?.total_count != null && ` · ${numberFormat.format(metadata.total_count)}`}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!metadata?.has_previous || isPlaceholderData}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              {t("previous")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!metadata?.has_next || isPlaceholderData}
              onClick={() => setPage((current) => current + 1)}
            >
              {t("next")}
            </Button>
          </div>
        </div>
      )}

      <UserEditorDialog open={showCreate} onOpenChange={setShowCreate} />
    </div>
  );
}
