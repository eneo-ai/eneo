"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
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

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="whitespace-nowrap">{t("audit_timestamp")}</TableHead>
            <TableHead>{t("action")}</TableHead>
            <TableHead>{t("audit_actor")}</TableHead>
            <TableHead>{t("description")}</TableHead>
            <TableHead>{t("audit_outcome")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {logs.map((log) => (
            <TableRow key={log.id}>
              <TableCell className="text-muted-foreground font-mono text-xs whitespace-nowrap">
                {formatDateTime(log.timestamp)}
              </TableCell>
              <TableCell>
                <Badge variant="secondary">{actionLabel(t, log.action)}</Badge>
              </TableCell>
              <TableCell className="text-sm">
                <span className="text-muted-foreground">{t(`audit_actor_${log.actor_type}`)}</span>
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
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
