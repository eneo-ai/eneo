"use client";

import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useClipboard } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { Table } from "@/components/astryx/table";
import { ClientTime } from "@/components/composites/client-time";
import { StatusLabel } from "@/components/composites/status-label";
import { TableFrame } from "@/components/composites/table-frame";
import { Button } from "@/components/ui/button";
import { toast } from "@/lib/toast";
import { actionLabel, type AuditLog } from "./audit";

/**
 * The audit log as a table that keeps every column on a phone (decision 9):
 * it scrolls sideways in its own named region with the event pinned, and the
 * pinned cell says what happened, to what, and whether it failed, so no row
 * depends on a scroll. The event opens its full details.
 */
export function AuditTable({ logs }: { logs: AuditLog[] }) {
  const t = useTranslations();
  // The event opened last stays in the dialog while it closes.
  const [shown, setShown] = useState<AuditLog | null>(null);
  const [isOpen, setIsOpen] = useState(false);

  // Kept across renders: new columns would remount the cells, and with them
  // the event that has the focus the dialog returns to.
  const columns = useMemo((): TableColumn<AuditLog>[] => {
    const show = (log: AuditLog) => {
      setShown(log);
      setIsOpen(true);
    };
    const outcome = (log: AuditLog) =>
      log.outcome === "success" ? t("audit_outcome_success") : t("audit_outcome_failure");
    return [
      {
        key: "event",
        header: t("audit_event"),
        width: proportional(1, { minWidth: 240 }),
        renderCell: (log) => (
          <button
            type="button"
            aria-haspopup="dialog"
            onClick={(event) => {
              // Safari does not focus a tapped button; the dialog returns focus
              // to what had it when it opened, so this event takes it first.
              event.currentTarget.focus();
              show(log);
            }}
            className="focus-visible:outline-ring rounded-ax-inner flex min-h-11 w-full min-w-0 flex-col items-start gap-0.5 py-1 text-start focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <span className="line-clamp-2 font-semibold break-words">
              {actionLabel(t, log.action)}
            </span>
            <span className="text-ax-text-secondary line-clamp-2 text-sm break-words">
              {log.description}
            </span>
            {log.outcome === "success" ? null : <StatusLabel status="error" label={outcome(log)} />}
          </button>
        )
      },
      {
        key: "time",
        header: t("audit_timestamp"),
        width: pixel(152),
        renderCell: (log) => (
          <span className="text-sm tabular-nums">
            <ClientTime value={log.timestamp} format="date_time" />
          </span>
        )
      },
      {
        key: "actor",
        header: t("audit_actor"),
        width: pixel(168),
        renderCell: (log) => (
          <span className="text-sm">
            <span className="text-ax-text-secondary">{t(`audit_actor_${log.actor_type}`)}</span>
            {log.actor_id ? (
              <span className="ms-1 font-mono text-xs">{log.actor_id.slice(0, 8)}</span>
            ) : null}
          </span>
        )
      },
      {
        key: "outcome",
        header: t("audit_outcome"),
        width: pixel(136),
        renderCell: (log) => (
          <StatusLabel
            status={log.outcome === "success" ? "success" : "error"}
            label={outcome(log)}
          />
        )
      }
    ];
  }, [t]);

  return (
    <>
      <TableFrame>
        <Table
          data={logs}
          columns={columns}
          idKey="id"
          aria-label={t("audit_logs")}
          // No row hover: only the event opens the details, the row does not.
          pinnedColumn="event"
        />
      </TableFrame>
      {/* Mounted from the start: a dialog that mounts open records where focus
          was only after its contents have taken it, and returns nowhere. */}
      <AuditDetailsDialog log={shown} isOpen={isOpen} onOpenChange={setIsOpen} />
    </>
  );
}

/** One event in full: when, the outcome, who, what, from where, and its metadata. */
function AuditDetailsDialog({
  log,
  isOpen,
  onOpenChange
}: {
  log: AuditLog | null;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  return (
    <Dialog isOpen={isOpen} onOpenChange={onOpenChange} width={640} maxHeight="85dvh">
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={log ? actionLabel(t, log.action) : t("audit_full_details")}
            subtitle={log?.description}
            onOpenChange={onOpenChange}
          />
        }
        content={
          // Keyed: each event starts afresh (a copy confirmation is the one it was for).
          <LayoutContent>{log ? <AuditDetails key={log.id} log={log} /> : null}</LayoutContent>
        }
      />
    </Dialog>
  );
}

function AuditDetails({ log }: { log: AuditLog }) {
  const t = useTranslations();
  const hasMetadata = log.metadata && Object.keys(log.metadata).length > 0;
  const { copy, isCopied } = useClipboard({ announce: t("copied_to_clipboard") });

  const copyMetadata = async () => {
    if (!(await copy(JSON.stringify(log.metadata, null, 2)))) toast.error(t("chat_copy_failed"));
  };

  return (
    <div className="flex flex-col gap-4 pb-2">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground text-xs">{t("audit_timestamp")}</dt>
          <dd>
            <ClientTime value={log.timestamp} format="date_time" />
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">{t("audit_outcome")}</dt>
          <dd>
            <StatusLabel
              status={log.outcome === "success" ? "success" : "error"}
              label={
                log.outcome === "success" ? t("audit_outcome_success") : t("audit_outcome_failure")
              }
            />
          </dd>
        </div>
        {/* What kind of actor, with its id: a system event has none. */}
        <Field
          label={t("audit_actor")}
          value={t(`audit_actor_${log.actor_type}`) + (log.actor_id ? ` · ${log.actor_id}` : "")}
          mono
        />
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
            className="text-destructive sm:col-span-2"
          />
        )}
      </dl>

      {hasMetadata && (
        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="text-muted-foreground text-xs font-medium">
              {t("audit_metadata_json")}
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="gap-1 text-xs"
              onClick={() => void copyMetadata()}
            >
              {isCopied ? <Check className="size-3" /> : <Copy className="size-3" />}
              {isCopied ? t("audit_json_copied") : t("audit_copy_json")}
            </Button>
          </div>
          {/* A scroll area without focusable content: focusable, so it scrolls by keyboard. */}
          <pre
            role="region"
            aria-label={t("audit_metadata_json")}
            tabIndex={0}
            className="bg-background focus-visible:outline-ring max-h-64 overflow-auto rounded-md border p-3 font-mono text-xs focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            {JSON.stringify(log.metadata, null, 2)}
          </pre>
        </div>
      )}
    </div>
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
