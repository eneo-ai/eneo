"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { AuditFilters } from "./audit";

const POLL_MS = 2000;
const RUNNING = new Set(["pending", "processing"]);

/**
 * Async CSV export: start a job, poll its progress, then download through the
 * proxy (which streams the file with its content-disposition). The four
 * SvelteKit BFF endpoints are unnecessary here — the generic /api/eneo proxy
 * already attaches the bearer.
 */
export function ExportDialog({
  open,
  onOpenChange,
  filters
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  filters: AuditFilters;
}) {
  const t = useTranslations();
  const [jobId, setJobId] = useState<string | null>(null);
  const [format, setFormat] = useState<"csv" | "json" | "jsonl">("csv");

  const start = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/audit/logs/export/async", {
          body: {
            from_date: filters.from_date || undefined,
            to_date: filters.to_date || undefined,
            action: filters.actions[0] ?? undefined,
            format
          }
        })
      ),
    onSuccess: (job) => setJobId(job.job_id),
    onError: (error) => toastApiError(error, t)
  });

  const { data: status } = useQuery({
    queryKey: ["audit-export", jobId],
    enabled: jobId !== null,
    refetchInterval: (query) => (RUNNING.has(query.state.data?.status ?? "") ? POLL_MS : false),
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/audit/logs/export/{job_id}/status", {
          params: { path: { job_id: jobId as string } }
        })
      )
  });

  const cancel = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/audit/logs/export/{job_id}/cancel", {
          params: { path: { job_id: jobId as string } }
        })
      ),
    onError: (error) => toastApiError(error, t)
  });

  const running = status ? RUNNING.has(status.status) : start.isPending;
  const complete = status?.status === "completed";

  function reset() {
    setJobId(null);
    onOpenChange(false);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setJobId(null);
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("export")}</DialogTitle>
          <DialogDescription>{t("audit_logs_description")}</DialogDescription>
        </DialogHeader>

        {jobId && status ? (
          <div className="flex flex-col gap-3">
            <Progress value={status.progress} />
            <p className="text-muted-foreground text-sm">
              {complete
                ? t("audit_export_completed")
                : status.status === "failed"
                  ? (status.error_message ?? t("audit_export_failed"))
                  : t("audit_exporting")}
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-muted-foreground text-sm">{t("audit_export_hint")}</p>
            <div className="flex flex-col gap-2">
              <Label htmlFor="audit-export-format">{t("audit_export_format")}</Label>
              <Select
                value={format}
                onValueChange={(value) => setFormat(value as "csv" | "json" | "jsonl")}
              >
                <SelectTrigger id="audit-export-format" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="csv">CSV</SelectItem>
                  <SelectItem value="json">JSON</SelectItem>
                  <SelectItem value="jsonl">JSONL</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        )}

        <DialogFooter>
          {complete ? (
            <>
              <Button variant="outline" onClick={reset}>
                {t("close")}
              </Button>
              <Button asChild>
                <a href={`/api/eneo/api/v1/audit/logs/export/${jobId}/download`}>
                  <Download className="size-4" /> {t("download")}
                </a>
              </Button>
            </>
          ) : running ? (
            <Button
              variant="destructive"
              disabled={cancel.isPending || !jobId}
              onClick={() => cancel.mutate()}
            >
              {t("cancel")}
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={reset}>
                {t("cancel")}
              </Button>
              <Button disabled={start.isPending} onClick={() => start.mutate()}>
                {t("export")}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
