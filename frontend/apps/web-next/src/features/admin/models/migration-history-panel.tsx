"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Selector } from "@astryxdesign/core/Selector";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow
} from "@astryxdesign/core/Table";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Token } from "@astryxdesign/core/Token";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment, useId, useMemo, useState } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { browserApi } from "@/lib/api/browser";
import { useModelTypeLabel } from "./model-type-label";
import { type ModelMigrationHistory, migrationHistoryQueryOptions } from "./models";

type TypeFilter = "all" | "completion" | "transcription";
type StatusFilter = "all" | "completed" | "failed" | "in_progress";
type HistoryFilters = { search: string; type: TypeFilter; status: StatusFilter };

// Not Astryx's filtering plugin: it filters one column from its header,
// while this toolbar searches three columns at once next to two selects.
function filterHistory(
  rows: ModelMigrationHistory[],
  { search, type, status }: HistoryFilters
): ModelMigrationHistory[] {
  const term = search.trim().toLowerCase();
  return rows.filter((row) => {
    if (type !== "all" && row.model_type !== type) return false;
    if (status !== "all" && row.status !== status) return false;
    return (
      !term ||
      [row.from_model_name, row.to_model_name, row.initiated_by_name]
        .join(" ")
        .toLowerCase()
        .includes(term)
    );
  });
}

const DETAIL_LABELS: Record<string, string> = {
  assistants: "migration_detail_assistants",
  apps: "migration_detail_apps",
  services: "migration_detail_services",
  questions: "migration_detail_questions",
  spaces: "migration_detail_spaces",
  assistant_templates: "migration_detail_assistant_templates",
  app_templates: "migration_detail_app_templates"
};

const STATUS_TONE: Record<string, StatusTone> = {
  completed: "success",
  failed: "error",
  in_progress: "accent"
};

/**
 * Merged completion + transcription migration history (newest first): search,
 * type and status filters, and a disclosure per migration with its duration,
 * per-entity counts, warnings and error.
 */
export function MigrationHistoryPanel() {
  const t = useTranslations();
  const typeLabel = useModelTypeLabel();
  const { data, isPending, isError, refetch } = useQuery(migrationHistoryQueryOptions(browserApi));
  const [search, setSearch] = useState("");
  const [type, setType] = useState<TypeFilter>("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const baseId = useId();
  const announce = useAnnounce();

  const rows = useMemo(
    () => filterHistory(data ?? [], { search, type, status }),
    [data, search, type, status]
  );

  // The number of migrations a filter change leaves is announced politely,
  // without moving focus (WCAG 4.1.3).
  function announceResults(next: Partial<HistoryFilters>) {
    const filters = { search, type, status, ...next };
    const isFiltering =
      filters.search.trim() !== "" || filters.type !== "all" || filters.status !== "all";
    const count = filterHistory(data ?? [], filters).length;
    announce(isFiltering ? t("admin_models_history_results", { count }) : "");
  }

  // Not useTableRowExpansion: its chevron is named "Expandera rad" on every
  // row, while these disclosures name the migration they open and point at
  // their detail row (aria-controls).
  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (isPending) return <LoadingState rows={4} />;
  if (isError) {
    return (
      <EmptyState
        title={t("migration_history_load_failed")}
        actions={<Button label={t("retry")} onClick={() => void refetch()} />}
      />
    );
  }
  if (!data || data.length === 0) return <EmptyState title={t("migration_history_empty")} />;

  const filterValue = (label: string) => (option: { label?: string }) =>
    t("admin_models_filter_value", { label, value: option.label ?? "" });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <TextInput
          label={t("admin_models_history_search")}
          isLabelHidden
          placeholder={t("search")}
          startIcon={Search}
          value={search}
          onChange={(value) => {
            setSearch(value);
            announceResults({ search: value });
          }}
          hasClear
          className="w-full sm:w-72"
        />
        <Selector
          label={t("model_type")}
          isLabelHidden
          options={[
            { value: "all", label: t("filter_all") },
            { value: "completion", label: typeLabel("completion") },
            { value: "transcription", label: typeLabel("transcription") }
          ]}
          value={type}
          onChange={(value) => {
            setType(value as TypeFilter);
            announceResults({ type: value as TypeFilter });
          }}
          renderValue={filterValue(t("model_type"))}
          width="14rem"
        />
        <Selector
          label={t("migration_history_status")}
          isLabelHidden
          options={[
            { value: "all", label: t("filter_all") },
            { value: "completed", label: t("migration_status_completed") },
            { value: "failed", label: t("migration_status_failed") },
            { value: "in_progress", label: t("migration_status_in_progress") }
          ]}
          value={status}
          onChange={(value) => {
            setStatus(value as StatusFilter);
            announceResults({ status: value as StatusFilter });
          }}
          renderValue={filterValue(t("migration_history_status"))}
          width="12rem"
        />
      </div>

      <div className="bg-ax-card border-ax-border rounded-ax-container overflow-hidden border">
        {/* Below its min width the table scrolls inside its own region. */}
        <Table aria-label={t("migration_history_title")} className="min-w-200">
          <TableHeader>
            <TableRow className="bg-ax-sunken [&>th]:text-xs">
              {/* Fits the 44 px touch-size button (AGENTS.md → Tables). */}
              <TableHeaderCell scope="col" className="w-14 min-w-14">
                <span className="sr-only">{t("details")}</span>
              </TableHeaderCell>
              <TableHeaderCell scope="col">{t("migration_history_date")}</TableHeaderCell>
              <TableHeaderCell scope="col">{t("migration_history_from")}</TableHeaderCell>
              <TableHeaderCell scope="col">{t("migration_history_to")}</TableHeaderCell>
              <TableHeaderCell scope="col" className="text-end">
                {t("migration_history_count")}
              </TableHeaderCell>
              <TableHeaderCell scope="col">{t("migration_history_by")}</TableHeaderCell>
              <TableHeaderCell scope="col">{t("migration_history_status")}</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const open = expanded.has(row.id);
              const detailId = `${baseId}-${row.id}`;
              const at = row.completed_at ?? row.started_at;
              return (
                <Fragment key={row.id}>
                  <TableRow>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        isIconOnly
                        label={t("admin_models_history_details", {
                          from: row.from_model_name,
                          to: row.to_model_name
                        })}
                        icon={
                          open ? (
                            <ChevronDown className="size-4" aria-hidden="true" />
                          ) : (
                            <ChevronRight className="size-4" aria-hidden="true" />
                          )
                        }
                        aria-expanded={open}
                        aria-controls={open ? detailId : undefined}
                        onClick={() => toggle(row.id)}
                      />
                    </TableCell>
                    <TableCell className="text-ax-text-secondary whitespace-nowrap">
                      {at ? <ClientTime value={at} format="date_time" /> : "—"}
                    </TableCell>
                    <TableCell>{row.from_model_name}</TableCell>
                    <TableCell>{row.to_model_name}</TableCell>
                    <TableCell className="text-end tabular-nums">{row.migrated_count}</TableCell>
                    <TableCell className="text-ax-text-secondary">
                      {row.initiated_by_name}
                    </TableCell>
                    <TableCell>
                      <StatusLabel
                        status={STATUS_TONE[row.status] ?? "neutral"}
                        label={
                          DETAIL_STATUS_KEYS.has(row.status)
                            ? t(`migration_status_${row.status}` as "migration_status_completed")
                            : row.status
                        }
                        isPulsing={row.status === "in_progress"}
                      />
                    </TableCell>
                  </TableRow>
                  {open && <DetailRow id={detailId} row={row} t={t} typeLabel={typeLabel} />}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

const DETAIL_STATUS_KEYS = new Set(["completed", "failed", "in_progress"]);

function DetailRow({
  id,
  row,
  t,
  typeLabel
}: {
  id: string;
  row: ModelMigrationHistory;
  t: ReturnType<typeof useTranslations>;
  typeLabel: ReturnType<typeof useModelTypeLabel>;
}) {
  const details = Object.entries(row.migration_details ?? {}).filter(
    ([key, value]) => key !== "total" && value > 0 && key in DETAIL_LABELS
  );

  return (
    <TableRow id={id} className="bg-ax-sunken">
      <TableCell />
      <TableCell colSpan={6}>
        <div className="flex flex-col gap-2 py-1 text-sm">
          <div className="flex flex-wrap gap-x-6 gap-y-1">
            <span>
              <span className="text-ax-text-secondary">{t("migration_history_type")}: </span>
              {typeLabel(row.model_type)}
            </span>
            {row.duration != null && (
              <span>
                <span className="text-ax-text-secondary">{t("migration_history_duration")}: </span>
                {(row.duration / 1000).toFixed(1)}s
              </span>
            )}
          </div>
          {details.length > 0 && (
            <ul className="flex flex-wrap gap-1">
              {details.map(([key, value]) => (
                <li key={key} className="flex">
                  <Token
                    size="sm"
                    label={`${t(DETAIL_LABELS[key] as "migration_detail_assistants")}: ${value}`}
                  />
                </li>
              ))}
            </ul>
          )}
          {row.warnings && row.warnings.length > 0 && (
            <div className="text-ax-text-secondary flex flex-col gap-0.5 text-xs">
              <span className="font-medium">{t("migration_history_warnings")}</span>
              <ul className="flex flex-col gap-0.5">
                {row.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
          {row.error_message && <p className="text-ax-error">{row.error_message}</p>}
        </div>
      </TableCell>
    </TableRow>
  );
}
