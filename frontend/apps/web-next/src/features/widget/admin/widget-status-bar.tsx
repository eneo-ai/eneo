"use client";

import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { revealProblems } from "@/components/composites/field-problem";
import { useFocusRescue } from "@/lib/focus-rescue";
import { toastApiError } from "@/lib/api/toast";
import type { AutosaveSnapshot, Widget, WidgetAutosave } from "./autosave";
import { blockerLabel } from "./blockers";
import { currentExternalTools, toastWidgetError, widgetErrorMessage } from "./errors";

type ExternalTools = Widget["external_tools"];

/**
 * What the acknowledgement dialog lists, which is exactly what gets
 * acknowledged: the API refuses any other list, so one that changed meanwhile
 * is shown again in its place.
 */
type Review = {
  servers: ExternalTools;
  /** Shown again because the list changed under the admin. */
  changed: boolean;
  /** The dialog was opened by activating, which follows the acknowledgement. */
  activatesAfter: boolean;
};

/**
 * Lifecycle of one widget: status, save state, why it cannot be activated
 * yet (or, once active, what keeps it from serving properly), and the
 * activate / pause / archive actions. Activation, archiving and acknowledging
 * tools outside Eneo are for tenant admins; pausing is the kill switch every
 * editor has.
 */
export function WidgetStatusBar({
  autosave,
  state,
  isAdmin,
  onActivate,
  onAcknowledgeExternalTools,
  onPause,
  onArchive,
  onReload
}: {
  autosave: WidgetAutosave;
  state: AutosaveSnapshot<Widget>;
  isAdmin: boolean;
  onActivate: () => Promise<void>;
  /** Acknowledges exactly the servers and tools the admin was shown. */
  onAcknowledgeExternalTools: (servers: ExternalTools) => Promise<void>;
  onPause: () => Promise<void>;
  onArchive: () => Promise<void>;
  onReload: () => Promise<void>;
}) {
  const t = useTranslations();
  const ids = useId();
  const widget = state.widget;
  const blockers = widget.activation_blockers ?? [];
  const refusals = [...new Set(Object.values(state.refusals))];
  const canActivate = isAdmin && blockers.length === 0 && !state.hasPending;
  // The assistant's tools at MCP servers outside Eneo, as the backend lists
  // them, and whether an admin's acknowledgement covers them all. Visitors
  // reach only acknowledged tools, so activation stops at a dialog until the
  // admin has read the list and said yes, and a live widget with newer tools
  // offers the same dialog without pausing.
  const externalTools = widget.external_tools ?? [];
  const needsAcknowledgement =
    externalTools.length > 0 && !(widget.external_tools_acknowledged ?? true);
  const canAcknowledgeLive = isAdmin && widget.status === "active" && needsAcknowledgement;
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiving, setArchiving] = useState(false);
  // Busy buttons stay enabled so they keep focus; their handlers ignore a
  // second press. They run from onClick, not clickAction: state set inside
  // clickAction's transition is held until the action ends, so these flags
  // would not stop a second press, nor Cancel during an acknowledgement.
  const [busy, setBusy] = useState<"activate" | "pause" | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [confirmTried, setConfirmTried] = useState(false);
  const [acknowledging, setAcknowledging] = useState(false);
  // Each refusal mounts the alert anew, so a second one is announced too.
  const [changes, setChanges] = useState(0);
  const checkbox = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const rescueFocus = useFocusRescue();

  function showReview(next: Review) {
    setReview(next);
    if (next.changed) setChanges((count) => count + 1);
    setAcknowledged(false);
    setConfirmTried(false);
  }

  // The dialog hands focus back to what opened it; an acknowledgement on a
  // live widget removes that button with the blocker it answered, and focus
  // then goes to the status heading instead of the page.
  function endReview() {
    setReview(null);
    rescueFocus(heading.current);
  }

  function closeReview(open: boolean) {
    if (!open && !acknowledging) endReview();
  }

  // Activates, or shows the current list (again) when it changed under the
  // admin; true when the widget was activated.
  async function activateOrReview(): Promise<boolean> {
    try {
      await onActivate();
      return true;
    } catch (error) {
      const servers = currentExternalTools(error);
      if (!servers) throw error;
      showReview({ servers, changed: true, activatesAfter: true });
      return false;
    }
  }

  async function activate() {
    if (busy) return;
    setBusy("activate");
    try {
      await autosave.flush();
      if (autosave.hasPending) return;
      // The saved widget, not this render's: the flush may have answered with newer tools.
      const saved = autosave.widget;
      const tools = saved.external_tools ?? [];
      if (tools.length > 0 && !(saved.external_tools_acknowledged ?? true)) {
        showReview({ servers: tools, changed: false, activatesAfter: true });
        return;
      }
      // Activate gives way to Pause, which is a new button: focus would fall to the page.
      if (await activateOrReview()) rescueFocus(heading.current);
    } catch (error) {
      toastWidgetError(error, t);
    } finally {
      setBusy(null);
    }
  }

  // The confirming button stays enabled; pressed before the box is ticked,
  // it says so at the box, which takes focus.
  async function acknowledge() {
    if (!review || acknowledging) return;
    if (review.servers.length > 0 && !acknowledged) {
      revealProblems(() => setConfirmTried(true), checkbox.current);
      return;
    }
    setAcknowledging(true);
    try {
      try {
        await onAcknowledgeExternalTools(review.servers);
      } catch (error) {
        const servers = currentExternalTools(error);
        if (servers) showReview({ ...review, servers, changed: true });
        else toastWidgetError(error, t);
        return;
      }
      if (!review.activatesAfter) {
        endReview();
        return;
      }
      try {
        if (await activateOrReview()) endReview();
      } catch (error) {
        // The acknowledgement holds; activation failed for another reason.
        endReview();
        toastWidgetError(error, t);
      }
    } finally {
      setAcknowledging(false);
    }
  }

  async function pause() {
    if (busy) return;
    setBusy("pause");
    try {
      await onPause();
      rescueFocus(heading.current);
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
  // An admin about to activate is told up front that a dialog follows.
  const externalToolsNote =
    isAdmin && blockers.length === 0 && widget.status !== "active" && needsAcknowledgement
      ? t("widget_admin_external_tools_note")
      : null;
  const externalToolsNoteId = `${ids}-external-tools-note`;
  const activateLabel =
    widget.status === "paused" ? t("widget_admin_resume") : t("widget_admin_activate");

  return (
    <section
      aria-labelledby="widget-status-title"
      className="bg-ax-card border-ax-border flex flex-col gap-3 rounded-xl border p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2
            id="widget-status-title"
            ref={heading}
            tabIndex={-1}
            className="text-base font-semibold"
          >
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
          {/* Keyed apart: a pressed Activate must not become the Pause button
              under the user's focus, nor Pause the Activate button. */}
          {widget.status === "active" ? (
            <Button
              key="pause"
              label={t("widget_admin_pause")}
              isLoading={busy === "pause"}
              isInterruptible
              onClick={() => void pause()}
            />
          ) : widget.status !== "archived" ? (
            <Button
              key="activate"
              variant="primary"
              label={activateLabel}
              isDisabled={!canActivate}
              isLoading={busy === "activate"}
              isInterruptible
              tooltip={activateTooltip ?? undefined}
              aria-describedby={externalToolsNote ? externalToolsNoteId : undefined}
              onClick={() => void activate()}
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
        // (an unpublished assistant, no allowed website, no AI disclosure,
        // tools no admin has acknowledged).
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
          {canAcknowledgeLive && (
            <div className="mt-2">
              <Button
                size="sm"
                label={t("widget_admin_external_tools_review")}
                onClick={() =>
                  showReview({ servers: externalTools, changed: false, activatesAfter: false })
                }
              />
            </div>
          )}
        </div>
      ) : adminOnlyNote ? (
        <p id="widget-status-admin-only" className="text-ax-text-secondary text-sm">
          {adminOnlyNote}
        </p>
      ) : externalToolsNote ? (
        <p id={externalToolsNoteId} className="text-ax-text-secondary text-sm">
          {externalToolsNote}
        </p>
      ) : null}

      {/* Only the header stays mounted while closed: Astryx names the dialog
          from the title present when the <dialog> mounts. */}
      <Dialog
        isOpen={review !== null}
        onOpenChange={closeReview}
        purpose="form"
        width={520}
        aria-describedby={`${ids}-external-tools-description`}
      >
        <Layout
          height="auto"
          header={
            <DialogHeader
              title={t("widget_admin_external_tools_title")}
              onOpenChange={closeReview}
            />
          }
          content={
            review ? (
              <LayoutContent>
                <div className="flex flex-col gap-4">
                  <p
                    id={`${ids}-external-tools-description`}
                    className="text-ax-text-secondary text-sm"
                  >
                    {t("widget_admin_external_tools_description")}
                  </p>
                  {review.changed && (
                    <p
                      key={changes}
                      role="alert"
                      className="bg-ax-warning-muted text-ax-text rounded-lg px-3 py-2 text-sm"
                    >
                      {t("widget_admin_external_tools_changed")}
                    </p>
                  )}
                  {review.servers.length > 0 ? (
                    <>
                      <ul
                        className="flex flex-col gap-2 text-sm"
                        aria-label={t("widget_admin_external_tools_servers")}
                      >
                        {review.servers.map((server) => (
                          <li
                            key={server.id}
                            className="border-ax-border rounded-md border px-3 py-2"
                          >
                            <p className="font-medium">{server.name}</p>
                            <p className="text-ax-text-secondary">
                              {t("widget_admin_external_tools_tools", {
                                tools: server.tools.map((tool) => tool.name).join(", ")
                              })}
                            </p>
                          </li>
                        ))}
                      </ul>
                      <CheckboxInput
                        ref={checkbox}
                        label={t("widget_admin_external_tools_acknowledge")}
                        description={t("widget_admin_external_tools_acknowledge_help")}
                        value={acknowledged}
                        onChange={setAcknowledged}
                        status={
                          confirmTried && !acknowledged
                            ? {
                                type: "error",
                                message: t("form_problem_acknowledge_external_tools")
                              }
                            : undefined
                        }
                      />
                    </>
                  ) : (
                    // Every tool was switched off meanwhile: nothing is left to accept.
                    <p className="text-ax-text-secondary text-sm">
                      {t("widget_admin_external_tools_none_left")}
                    </p>
                  )}
                </div>
              </LayoutContent>
            ) : null
          }
          footer={
            review ? (
              <LayoutFooter>
                <div className="flex flex-wrap justify-end gap-2">
                  <Button
                    label={t("cancel")}
                    isDisabled={acknowledging}
                    onClick={() => closeReview(false)}
                  />
                  <Button
                    variant="primary"
                    label={
                      !review.activatesAfter
                        ? t("widget_admin_external_tools_confirm")
                        : activateLabel
                    }
                    isLoading={acknowledging}
                    isInterruptible
                    onClick={() => void acknowledge()}
                  />
                </div>
              </LayoutFooter>
            ) : null
          }
        />
      </Dialog>

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
