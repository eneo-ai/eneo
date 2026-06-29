"use client";

import { ChevronDown, ChevronRight, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";
import { actionLabel, type AuditLog } from "./audit";

export function AuditTable({ logs }: { logs: AuditLog[] }) {
  const t = useTranslations();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-8" />
            <TableHead className="whitespace-nowrap">{t("audit_timestamp")}</TableHead>
            <TableHead>{t("action")}</TableHead>
            <TableHead>{t("audit_actor")}</TableHead>
            <TableHead>{t("description")}</TableHead>
            <TableHead>{t("audit_outcome")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {logs.map((log) => {
            const isOpen = expanded.has(log.id);
            return (
              <Fragment key={log.id}>
                <TableRow
                  className="cursor-pointer"
                  onClick={() => toggle(log.id)}
                  aria-expanded={isOpen}
                >
                  <TableCell className="w-8">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-6"
                      aria-label={t("audit_full_details")}
                      onClick={(event) => {
                        event.stopPropagation();
                        toggle(log.id);
                      }}
                    >
                      {isOpen ? (
                        <ChevronDown className="size-4" />
                      ) : (
                        <ChevronRight className="size-4" />
                      )}
                    </Button>
                  </TableCell>
                  <TableCell className="text-muted-foreground font-mono text-xs whitespace-nowrap">
                    {formatDateTime(log.timestamp)}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{actionLabel(t, log.action)}</Badge>
                  </TableCell>
                  <TableCell className="text-sm">
                    <span className="text-muted-foreground">
                      {t(`audit_actor_${log.actor_type}`)}
                    </span>
                    {log.actor_id && (
                      <span className="ml-1 font-mono text-xs">{log.actor_id.slice(0, 8)}</span>
                    )}
                  </TableCell>
                  <TableCell className="max-w-md truncate text-sm" title={log.description}>
                    {log.description}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className={
                        log.outcome === "success"
                          ? "border-green-200 text-green-700 dark:border-green-900 dark:text-green-400"
                          : "border-red-200 text-red-700 dark:border-red-900 dark:text-red-400"
                      }
                    >
                      {log.outcome === "success"
                        ? t("audit_outcome_success")
                        : t("audit_outcome_failure")}
                    </Badge>
                  </TableCell>
                </TableRow>
                {isOpen && <AuditDetailRow log={log} t={t} />}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function AuditDetailRow({ log, t }: { log: AuditLog; t: ReturnType<typeof useTranslations> }) {
  const hasMetadata = log.metadata && Object.keys(log.metadata).length > 0;

  const copyMetadata = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(log.metadata, null, 2));
      toast.success(t("audit_json_copied"));
    } catch {
      toast.error(t("audit_export_failed"));
    }
  };

  return (
    <TableRow className="bg-muted/30 hover:bg-muted/30">
      <TableCell />
      <TableCell colSpan={5} className="py-3">
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <Field label={t("audit_actor")} value={log.actor_id} mono />
          <Field label={t("audit_entity")} value={`${log.entity_type} · ${log.entity_id}`} mono />
          <Field
            label={t("audit_ip_address")}
            value={log.ip_address}
            mono
            fallback={t("audit_not_recorded")}
          />
          <Field
            label={t("audit_request_id")}
            value={log.request_id}
            mono
            fallback={t("audit_not_recorded")}
          />
          <Field
            label={t("audit_user_agent")}
            value={log.user_agent}
            fallback={t("audit_not_recorded")}
            className="sm:col-span-2"
          />
          {log.error_message && (
            <Field
              label={t("audit_error_message")}
              value={log.error_message}
              className="text-red-700 sm:col-span-2 dark:text-red-400"
            />
          )}
        </dl>

        {hasMetadata && (
          <div className="mt-3">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-muted-foreground text-xs font-medium">
                {t("audit_metadata_json")}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1 text-xs"
                onClick={copyMetadata}
              >
                <Copy className="size-3" />
                {t("audit_copy_json")}
              </Button>
            </div>
            <pre className="bg-background max-h-64 overflow-auto rounded-md border p-3 font-mono text-xs">
              {JSON.stringify(log.metadata, null, 2)}
            </pre>
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}

function Field({
  label,
  value,
  mono,
  fallback,
  className
}: {
  label: string;
  value?: string | null;
  mono?: boolean;
  fallback?: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd
        className={`break-all ${mono ? "font-mono text-xs" : ""} ${value ? "" : "text-muted-foreground"}`}
      >
        {value || fallback || "—"}
      </dd>
    </div>
  );
}
