"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { replaceUrl, usePathname, useSearchParams } from "@/lib/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { useSearchDraft } from "@/lib/hooks/use-search-draft";
import { cn } from "@/lib/utils";
import { auditLogsQueryOptions, type AuditFilters } from "./audit";
import { AuditConfig } from "./audit-config";
import { AuditFilterBar } from "./audit-filters";
import { AuditTable } from "./audit-table";
import { auditFiltersSearchParams, parseAuditFilters } from "./audit-url-filters";
import { ExportDialog } from "./export-dialog";
import { JustificationForm } from "./justification-form";

function LogsTab() {
  const t = useTranslations();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const filters = useMemo(() => parseAuditFilters(searchParams), [searchParams]);
  const search = useSearchDraft(filters.search);
  const [showExport, setShowExport] = useState(false);
  const [paging, setPaging] = useState<"previous" | "next" | null>(null);

  useEffect(() => {
    if (search.settled !== filters.search) {
      const query = auditFiltersSearchParams({
        ...filters,
        search: search.settled,
        page: 1
      }).toString();
      replaceUrl(query ? `${pathname}?${query}` : pathname);
    }
  }, [filters, search.settled, pathname]);

  const logsQuery = useQuery({
    ...auditLogsQueryOptions(browserApi, filters),
    placeholderData: keepPreviousData
  });
  const { data, error, isPlaceholderData } = logsQuery;

  // 401 = no active access session; show the justification gate instead.
  if (error instanceof EneoApiError && error.status === 401) {
    return <JustificationForm />;
  }

  function patchFilters(next: Partial<AuditFilters>) {
    const query = auditFiltersSearchParams({
      ...filters,
      ...next,
      page: next.page ?? 1
    }).toString();
    replaceUrl(query ? `${pathname}?${query}` : pathname);
  }

  const totalPages = data?.total_pages ?? 1;

  // While the next page loads, the pressed button stays enabled so it keeps
  // focus (aria-busy), and presses are ignored.
  function turnPage(direction: "previous" | "next") {
    if (isPlaceholderData) return;
    setPaging(direction);
    patchFilters({ page: filters.page + (direction === "next" ? 1 : -1) });
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex justify-end">
        <Button variant="outline" onClick={() => setShowExport(true)}>
          <Download className="size-4" /> {t("audit_export_csv")}
        </Button>
      </div>

      <AuditFilterBar
        filters={{ ...filters, search: search.draft }}
        onChange={({ search: nextSearch, ...rest }) => {
          if (nextSearch !== undefined) search.setDraft(nextSearch);
          if (nextSearch === "") patchFilters({ ...rest, search: "" });
          else if (Object.keys(rest).length > 0) patchFilters(rest);
        }}
      />

      <div className={cn(isPlaceholderData && "opacity-60 transition-opacity")}>
        <QueryStateBoundary query={logsQuery} rows={5}>
          {(page) =>
            page.logs.length === 0 ? (
              <EmptyState title={t("audit_no_logs_found")} />
            ) : (
              <AuditTable logs={page.logs} />
            )
          }
        </QueryStateBoundary>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground text-sm">
            {t("page")} {data?.page ?? filters.page} / {totalPages}
            {data?.total_count != null && ` · ${data.total_count}`}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={(data?.page ?? 1) <= 1}
              aria-busy={(isPlaceholderData && paging === "previous") || undefined}
              onClick={() => turnPage("previous")}
            >
              {t("previous")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={(data?.page ?? 1) >= totalPages}
              aria-busy={(isPlaceholderData && paging === "next") || undefined}
              onClick={() => turnPage("next")}
            >
              {t("next")}
            </Button>
          </div>
        </div>
      )}

      <ExportDialog open={showExport} onOpenChange={setShowExport} filters={filters} />
    </div>
  );
}

export function AuditPage() {
  const t = useTranslations();
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <PageHeader title={t("audit_logs")} />
      <Tabs defaultValue="logs">
        <TabsList>
          <TabsTrigger value="logs">{t("audit_logs")}</TabsTrigger>
          <TabsTrigger value="categories">{t("audit_categories")}</TabsTrigger>
        </TabsList>
        <TabsContent value="logs" className="pt-4">
          <LogsTab />
        </TabsContent>
        <TabsContent value="categories" className="pt-4">
          <AuditConfig />
        </TabsContent>
      </Tabs>
    </div>
  );
}
