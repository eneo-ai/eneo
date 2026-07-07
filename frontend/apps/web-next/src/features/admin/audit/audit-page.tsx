"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import { auditLogsQueryOptions, type AuditFilters } from "./audit";
import { AuditConfig } from "./audit-config";
import { AuditFilterBar } from "./audit-filters";
import { AuditTable } from "./audit-table";
import { auditFiltersSearchParams, parseAuditFilters } from "./audit-url-filters";
import { ExportDialog } from "./export-dialog";
import { JustificationForm } from "./justification-form";
import { RetentionPanel } from "./retention-panel";

const SEARCH_DEBOUNCE_MS = 300;

function LogsTab() {
  const t = useTranslations();
  const searchParams = useSearchParams();
  const [filters, setFilters] = useState<AuditFilters>(() => parseAuditFilters(searchParams));
  const [searchInput, setSearchInput] = useState(() => parseAuditFilters(searchParams).search);
  const [showExport, setShowExport] = useState(false);

  // Debounce the free-text search into the committed filters.
  const debounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      setFilters((current) =>
        current.search === searchInput ? current : { ...current, search: searchInput, page: 1 }
      );
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(debounce.current);
  }, [searchInput]);

  useEffect(() => {
    const query = auditFiltersSearchParams(filters).toString();
    const nextUrl = query ? `${window.location.pathname}?${query}` : window.location.pathname;
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (nextUrl !== currentUrl) window.history.replaceState(null, "", nextUrl);
  }, [filters]);

  const { data, error, isPending, isPlaceholderData } = useQuery({
    ...auditLogsQueryOptions(browserApi, filters),
    placeholderData: keepPreviousData
  });

  // 401 = no active access session; show the justification gate instead.
  if (error instanceof EneoApiError && error.status === 401) {
    return <JustificationForm />;
  }

  function patchFilters(next: Partial<AuditFilters>) {
    setFilters((current) => ({ ...current, ...next, page: next.page ?? 1 }));
  }

  const logs = data?.logs ?? [];
  const totalPages = data?.total_pages ?? 1;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex justify-end">
        <Button variant="outline" onClick={() => setShowExport(true)}>
          <Download className="size-4" /> {t("audit_export_csv")}
        </Button>
      </div>

      <RetentionPanel />

      <AuditFilterBar
        filters={{ ...filters, search: searchInput }}
        onChange={({ search, ...rest }) => {
          if (search !== undefined) {
            setSearchInput(search);
            if (search === "") {
              setFilters((current) =>
                current.search === "" ? current : { ...current, search: "", page: 1 }
              );
            }
          }
          if (Object.keys(rest).length > 0) patchFilters(rest);
        }}
      />

      <div className={cn(isPlaceholderData && "opacity-60 transition-opacity")}>
        {isPending ? (
          <EmptyState title={t("loading")} />
        ) : logs.length === 0 ? (
          <EmptyState title={t("audit_no_logs_found")} />
        ) : (
          <AuditTable logs={logs} />
        )}
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
              disabled={(data?.page ?? 1) <= 1 || isPlaceholderData}
              onClick={() => setFilters((current) => ({ ...current, page: current.page - 1 }))}
            >
              {t("previous")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={(data?.page ?? 1) >= totalPages || isPlaceholderData}
              onClick={() => setFilters((current) => ({ ...current, page: current.page + 1 }))}
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
