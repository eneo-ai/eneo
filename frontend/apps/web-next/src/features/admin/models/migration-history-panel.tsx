"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment, useMemo, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { browserApi } from "@/lib/api/browser";
import { formatDateTime } from "@/lib/format";
import { type ModelMigrationHistory, migrationHistoryQueryOptions } from "./models";

const DETAIL_LABELS: Record<string, string> = {
  assistants: "migration_detail_assistants",
  apps: "migration_detail_apps",
  services: "migration_detail_services",
  questions: "migration_detail_questions",
  spaces: "migration_detail_spaces",
  assistant_templates: "migration_detail_assistant_templates",
  app_templates: "migration_detail_app_templates"
};

function statusVariant(status: string): "default" | "destructive" | "secondary" {
  if (status === "completed") return "default";
  if (status === "failed") return "destructive";
  return "secondary";
}

export function MigrationHistoryPanel() {
  const t = useTranslations();
  const { data, isPending, isError } = useQuery(migrationHistoryQueryOptions(browserApi));
  const [search, setSearch] = useState("");
  const [type, setType] = useState<"all" | "completion" | "transcription">("all");
  const [status, setStatus] = useState<"all" | "completed" | "failed" | "in_progress">("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (data ?? []).filter((row) => {
      if (type !== "all" && row.model_type !== type) return false;
      if (status !== "all" && row.status !== status) return false;
      if (
        term &&
        ![row.from_model_name, row.to_model_name, row.initiated_by_name]
          .join(" ")
          .toLowerCase()
          .includes(term)
      )
        return false;
      return true;
    });
  }, [data, search, type, status]);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (isPending) return <Skeleton className="h-48 w-full" />;
  if (isError) return <EmptyState title={t("migration_history_load_failed")} />;
  if (!data || data.length === 0) return <EmptyState title={t("migration_history_empty")} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        <Input
          className="max-w-xs"
          placeholder={t("search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Select value={type} onValueChange={(value) => setType(value as typeof type)}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("filter_all")}</SelectItem>
            <SelectItem value="completion">{t("completion_models")}</SelectItem>
            <SelectItem value="transcription">{t("transcription_models")}</SelectItem>
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={(value) => setStatus(value as typeof status)}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("filter_all")}</SelectItem>
            <SelectItem value="completed">{t("migration_status_completed")}</SelectItem>
            <SelectItem value="failed">{t("migration_status_failed")}</SelectItem>
            <SelectItem value="in_progress">{t("migration_status_in_progress")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead className="whitespace-nowrap">{t("migration_history_date")}</TableHead>
              <TableHead>{t("migration_history_from")}</TableHead>
              <TableHead>{t("migration_history_to")}</TableHead>
              <TableHead className="text-right">{t("migration_history_count")}</TableHead>
              <TableHead>{t("migration_history_by")}</TableHead>
              <TableHead>{t("migration_history_status")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const open = expanded.has(row.id);
              return (
                <Fragment key={row.id}>
                  <TableRow
                    className="cursor-pointer"
                    onRowAction={() => toggle(row.id)}
                    aria-expanded={open}
                    aria-label={
                      open ? t("migration_history_collapse") : t("migration_history_expand")
                    }
                  >
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-6"
                        aria-label={
                          open ? t("migration_history_collapse") : t("migration_history_expand")
                        }
                        onClick={(event) => {
                          event.stopPropagation();
                          toggle(row.id);
                        }}
                      >
                        {open ? (
                          <ChevronDown className="size-4" />
                        ) : (
                          <ChevronRight className="size-4" />
                        )}
                      </Button>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                      {formatDateTime(row.completed_at ?? row.started_at ?? "")}
                    </TableCell>
                    <TableCell className="text-sm">{row.from_model_name}</TableCell>
                    <TableCell className="text-sm">{row.to_model_name}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.migrated_count}</TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {row.initiated_by_name}
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(row.status)}>
                        {t(`migration_status_${row.status}` as "migration_status_completed")}
                      </Badge>
                    </TableCell>
                  </TableRow>
                  {open && <DetailRow row={row} t={t} />}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function DetailRow({
  row,
  t
}: {
  row: ModelMigrationHistory;
  t: ReturnType<typeof useTranslations>;
}) {
  const details = Object.entries(row.migration_details ?? {}).filter(
    ([key, value]) => key !== "total" && value > 0 && key in DETAIL_LABELS
  );

  return (
    <TableRow className="bg-muted/30 hover:bg-muted/30">
      <TableCell />
      <TableCell colSpan={6} className="py-3">
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex flex-wrap gap-x-6 gap-y-1">
            <span>
              <span className="text-muted-foreground">{t("migration_history_type")}: </span>
              {t(row.model_type === "completion" ? "completion_models" : "transcription_models")}
            </span>
            {row.duration != null && (
              <span>
                <span className="text-muted-foreground">{t("migration_history_duration")}: </span>
                {(row.duration / 1000).toFixed(1)}s
              </span>
            )}
          </div>
          {details.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {details.map(([key, value]) => (
                <Badge key={key} variant="outline">
                  {t(DETAIL_LABELS[key] as "migration_detail_assistants")}: {value}
                </Badge>
              ))}
            </div>
          )}
          {row.warnings && row.warnings.length > 0 && (
            <div className="text-muted-foreground flex flex-col gap-0.5 text-xs">
              <span className="font-medium">{t("migration_history_warnings")}</span>
              {row.warnings.map((warning, index) => (
                <span key={index}>{warning}</span>
              ))}
            </div>
          )}
          {row.error_message && <p className="text-destructive">{row.error_message}</p>}
        </div>
      </TableCell>
    </TableRow>
  );
}
