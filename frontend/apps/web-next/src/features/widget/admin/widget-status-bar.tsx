"use client";

import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toastApiError } from "@/lib/api/toast";
import type { AutosaveSnapshot, Widget, WidgetAutosave } from "./autosave";
import { blockerLabel } from "./blockers";
import { toastWidgetError, widgetErrorMessage } from "./errors";

/**
 * Lifecycle of one widget: status, save state, why it cannot be activated
 * yet (or, once active, what keeps it from serving properly), and the
 * activate / pause / archive actions. Activation and archiving are for tenant
 * admins; pausing is the kill switch every editor has.
 */
export function WidgetStatusBar({
  autosave,
  state,
  isAdmin,
  onActivate,
  onPause,
  onArchive,
  onReload
}: {
  autosave: WidgetAutosave;
  state: AutosaveSnapshot<Widget>;
  isAdmin: boolean;
  onActivate: () => Promise<void>;
  onPause: () => Promise<void>;
  onArchive: () => Promise<void>;
  onReload: () => Promise<void>;
}) {
  const t = useTranslations();
  const widget = state.widget;
  const blockers = widget.activation_blockers ?? [];
  const refusals = [...new Set(Object.values(state.refusals))];
  const canActivate = isAdmin && blockers.length === 0 && !state.hasPending;
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiving, setArchiving] = useState(false);
  // Busy buttons stay enabled so they keep focus; a second press is ignored.
  const [busy, setBusy] = useState<"activate" | "pause" | null>(null);

  async function activate() {
    if (busy) return;
    setBusy("activate");
    try {
      await autosave.flush();
      if (autosave.hasPending) return;
      await onActivate();
    } catch (error) {
      toastWidgetError(error, t);
    } finally {
      setBusy(null);
    }
  }
  async function pause() {
    if (busy) return;
    setBusy("pause");
    try {
      await onPause();
    } catch (error) {
      toastApiError(error, t);
    } finally {
      setBusy(null);
    }
  }
  async function archive() {
    setArchiving(true);
    try {
      await onArchive();
      setArchiveOpen(false);
    } catch (error) {
      toastApiError(error, t);
    } finally {
      setArchiving(false);
    }
  }

  const statusLabel =
    widget.status === "active"
      ? t("widget_admin_status_active")
      : widget.status === "paused"
        ? t("widget_admin_status_paused")
        : widget.status === "archived"
          ? t("widget_admin_status_archived")
          : t("widget_admin_status_draft");

  const saveLabel =
    state.status === "saving"
      ? t("widget_admin_saving")
      : state.status === "saved"
        ? t("widget_admin_saved")
        : state.status === "error"
          ? t("widget_admin_save_failed")
          : state.status === "refused"
            ? t("widget_admin_save_refused")
            : state.status === "conflict"
              ? // A lock published underneath the editor reads differently from
                // another person's edit; both end in a reload.
                (widgetErrorMessage(state.error, t) ?? t("widget_admin_save_conflict"))
              : "";

  const activateTooltip = !isAdmin
    ? t("widget_admin_activate_admin_only")
    : blockers.length > 0
      ? t("widget_admin_activate_blocked")
      : null;
  // The tooltip never opens on touch, so the reason is also written out below.
  const adminOnlyNote =
    isAdmin || blockers.length > 0
      ? null
      : widget.status === "draft"
        ? t("widget_admin_ready_for_admin")
        : widget.status === "paused"
          ? t("widget_admin_resume_admin_only")
          : null;
  const activateLabel =
    widget.status === "paused" ? t("widget_admin_resume") : t("widget_admin_activate");

  return (
    <section
      aria-labelledby="widget-status-title"
      className="bg-ax-card border-ax-border flex flex-col gap-3 rounded-xl border p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 id="widget-status-title" className="text-base font-semibold">
            {t("widget_admin_status")}
          </h2>
          <Badge
            variant={
              widget.status === "active"
                ? "success"
                : widget.status === "paused"
                  ? "warning"
                  : "neutral"
            }
            label={statusLabel}
          />
          {/* The header's save chip announces saved and failed; this is the
              editor's own, fuller wording next to the actions it affects. */}
          <span className="text-ax-text-secondary flex flex-wrap items-center gap-2 text-sm">
            {saveLabel}
            {state.status === "error" && (
              <Button
                variant="ghost"
                size="sm"
                label={t("widget_admin_retry_save")}
                onClick={() => void autosave.retry()}
              />
            )}
            {state.status === "conflict" && (
              <Button
                variant="ghost"
                size="sm"
                label={t("widget_admin_reload_discard")}
                isInterruptible
                clickAction={async () => {
                  try {
                    await onReload();
                  } catch (error) {
                    toastApiError(error, t);
                  }
                }}
              />
            )}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {widget.status === "active" ? (
            <Button
              label={t("widget_admin_pause")}
              isLoading={busy === "pause"}
              isInterruptible
              clickAction={pause}
            />
          ) : widget.status !== "archived" ? (
            <Button
              variant="primary"
              label={activateLabel}
              isDisabled={!canActivate}
              isLoading={busy === "activate"}
              isInterruptible
              tooltip={activateTooltip ?? undefined}
              clickAction={activate}
            />
          ) : null}
          {isAdmin && widget.status !== "archived" && (
            <Button
              variant="destructive"
              label={t("widget_admin_archive")}
              onClick={() => setArchiveOpen(true)}
            />
          )}
        </div>
      </div>

      {refusals.length > 0 && (
        <div className="bg-ax-error-muted text-ax-red rounded-lg px-3 py-2 text-sm">
          <p className="font-medium">{t("widget_admin_refusals_title")}</p>
          <ul className="mt-1 list-disc pl-5">
            {refusals.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      )}
      {blockers.length > 0 ? (
        // An active widget with blockers is live but not serving as configured
        // (an unpublished assistant, no allowed website, no AI disclosure).
        <div
          id="widget-status-blockers"
          className="bg-ax-warning-muted text-ax-text rounded-lg px-3 py-2 text-sm"
        >
          <p className="font-medium">
            {widget.status === "active"
              ? t("widget_admin_active_issues_title")
              : t("widget_admin_blockers_title")}
          </p>
          <ul className="mt-1 list-disc pl-5">
            {blockers.map((blocker) => (
              <li key={blocker}>{blockerLabel(blocker, t)}</li>
            ))}
          </ul>
        </div>
      ) : adminOnlyNote ? (
        <p id="widget-status-admin-only" className="text-ax-text-secondary text-sm">
          {adminOnlyNote}
        </p>
      ) : null}

      <AlertDialog
        isOpen={archiveOpen}
        onOpenChange={(open) => {
          if (!archiving) setArchiveOpen(open);
        }}
        title={t("widget_admin_archive_title")}
        description={t("widget_admin_archive_description")}
        actionLabel={t("widget_admin_archive")}
        cancelLabel={t("cancel")}
        isActionLoading={archiving}
        onAction={() => void archive()}
      />
    </section>
  );
}
