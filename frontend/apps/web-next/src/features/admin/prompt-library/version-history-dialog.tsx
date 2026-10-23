"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Eye, RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { ClientTime } from "@/components/composites/client-time";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import {
  type Entry,
  type EntryFull,
  PROMPT_LIBRARY_KEY,
  promptLibraryVersionsQueryOptions,
  type Version
} from "./prompt-library";

type Step = { kind: "list" } | { kind: "view"; version: Version };

const LIST: Step = { kind: "list" };

/** Who saved a version: the signed-in admin, or another one (the API gives only an id). */
function useAuthorLabel() {
  const t = useTranslations();
  const { user } = useAppContext();
  return (version: Version) =>
    version.created_by_user_id === user.id
      ? t("prompt_library_version_by_you")
      : t("prompt_library_version_by_other");
}

/** The versions as a table: number (with "Aktuell"), name, length, when, who, view and restore. */
function VersionTable({
  entry,
  versions,
  onView,
  onRestore
}: {
  entry: Entry;
  versions: Version[];
  onView: (version: Version) => void;
  onRestore: (version: Version) => void;
}) {
  const t = useTranslations();
  const author = useAuthorLabel();

  const columns: TableColumn<Version>[] = [
    {
      key: "version",
      header: t("governance_prompts_version"),
      width: pixel(140),
      renderCell: (version) => (
        <span className="inline-flex flex-wrap items-center gap-2 font-medium">
          {t("governance_prompt_version_short", { version: String(version.version) })}
          {version.version === entry.current_version ? (
            <Badge variant="success" label={t("governance_prompt_versions_current")} />
          ) : null}
        </span>
      )
    },
    { key: "name", header: t("name"), width: proportional(2) },
    {
      key: "characters",
      header: t("governance_prompt_versions_characters"),
      width: proportional(1),
      align: "end",
      renderCell: (version) => <span className="tabular-nums">{version.text.length}</span>
    },
    {
      key: "created_at",
      header: t("created"),
      width: proportional(1),
      renderCell: (version) => (
        <span className="whitespace-nowrap">
          <ClientTime value={version.created_at} format="date_time" />
        </span>
      )
    },
    {
      key: "created_by",
      header: t("prompt_library_version_by"),
      width: proportional(1),
      renderCell: (version) => <span className="text-ax-text-secondary">{author(version)}</span>
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      // Room for two 44 px touch targets plus the cell padding.
      width: pixel(116),
      align: "end",
      renderCell: (version) => (
        <span className="inline-flex items-center justify-end gap-1">
          <IconButton
            label={t("governance_prompt_versions_view_label", {
              version: String(version.version)
            })}
            icon={<Eye aria-hidden="true" />}
            variant="ghost"
            size="sm"
            onClick={() => onView(version)}
          />
          {version.version !== entry.current_version ? (
            <IconButton
              label={t("governance_prompt_versions_restore_label", {
                version: String(version.version)
              })}
              icon={<RotateCcw aria-hidden="true" />}
              variant="ghost"
              size="sm"
              onClick={() => onRestore(version)}
            />
          ) : null}
        </span>
      )
    }
  ];

  if (versions.length === 0) {
    return (
      <EmptyState
        title={t("prompt_library_versions_empty")}
        headingLevel={3}
        isCompact
        framed={false}
      />
    );
  }

  return (
    // No overflow clipping here: the Astryx table owns its scroll region, and
    // a clipped wrapper cut the header row and the action column inside the
    // dialog.
    <div className="border-ax-border rounded-ax-container [&_thead_tr]:bg-ax-sunken border">
      <Table
        data={versions}
        columns={columns}
        idKey="id"
        aria-label={t("governance_prompt_versions_title")}
      />
    </div>
  );
}

/** One version, read-only: its facts and its text in a scrollable region. */
function VersionView({ version }: { version: Version }) {
  const t = useTranslations();
  const author = useAuthorLabel();
  return (
    <div className="flex flex-col gap-4">
      <MetadataList columns="multi">
        <MetadataListItem label={t("name")}>{version.name}</MetadataListItem>
        {version.description ? (
          <MetadataListItem label={t("description")}>{version.description}</MetadataListItem>
        ) : null}
        <MetadataListItem label={t("created")}>
          <ClientTime value={version.created_at} format="date_time" />
        </MetadataListItem>
        <MetadataListItem label={t("prompt_library_version_by")}>
          {author(version)}
        </MetadataListItem>
        <MetadataListItem label={t("governance_prompt_versions_characters")}>
          <span className="tabular-nums">{version.text.length}</span>
        </MetadataListItem>
      </MetadataList>
      {/* A named, focusable region, so the keyboard can scroll long prompts. */}
      <div
        role="region"
        tabIndex={0}
        aria-label={t("prompt_library_version_content_region", {
          version: String(version.version)
        })}
        className="bg-ax-sunken border-ax-border rounded-ax-element focus-visible:outline-ring max-h-[40dvh] overflow-y-auto border p-3 text-sm break-words whitespace-pre-wrap focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {version.text}
      </div>
    </div>
  );
}

/**
 * A prompt's version history in a dialog: the list of versions, a read-only
 * view of one (a step inside the same dialog, with a back button) and
 * "Återställ den här versionen", which saves that version's content as a new
 * version after a confirmation and announces the result. `entry` comes from
 * the list query, so "Aktuell" follows a restore.
 */
export function VersionHistoryDialog({
  entry,
  open,
  onOpenChange
}: {
  entry: Entry | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const dialogRef = useRef<HTMLDialogElement>(null);
  // Opened from a row menu, whose item is gone by the time the dialog is up:
  // focus goes back to the menu button.
  const noTrigger = useRef<HTMLElement | null>(null);
  useReturnFocus(open, noTrigger);
  const [step, setStep] = useState<Step>(LIST);
  const [restoreTarget, setRestoreTarget] = useState<Version | null>(null);
  const versions = useQuery({
    ...promptLibraryVersionsQueryOptions(browserApi, entry?.id ?? ""),
    enabled: open && entry !== null
  });

  // Switching steps replaces the dialog's content; focus goes to the new
  // title, as it does when the dialog opens.
  const previousStep = useRef<Step>(step);
  useEffect(() => {
    if (previousStep.current !== step && open) {
      dialogRef.current?.querySelector<HTMLElement>("h2")?.focus();
    }
    previousStep.current = step;
  }, [step, open]);

  const restore = useMutation({
    mutationFn: (version: Version): Promise<EntryFull> =>
      unwrap(
        browserApi.PUT("/api/v1/admin/prompt-library/{id}/", {
          params: { path: { id: version.prompt_library_id } },
          body: { name: version.name, description: version.description, text: version.text }
        })
      ),
    onSuccess: (saved, version) => {
      void queryClient.invalidateQueries({ queryKey: PROMPT_LIBRARY_KEY });
      const message = t("prompt_library_restored", {
        version: String(version.version),
        current: String(saved.current_version)
      });
      announce(message);
      toast.success(message);
      setRestoreTarget(null);
      // Back to the list, where the new version is at the top as "Aktuell".
      setStep(LIST);
    },
    onError: (error) => toastApiError(error, t)
  });

  function requestOpenChange(next: boolean) {
    if (!next && restore.isPending) return;
    if (!next) setStep(LIST);
    onOpenChange(next);
  }

  const title =
    step.kind === "view"
      ? t("governance_prompt_versions_view_title", { version: String(step.version.version) })
      : t("prompt_library_versions_title", { name: entry?.name ?? "" });

  return (
    <>
      <Dialog
        ref={dialogRef}
        isOpen={open}
        onOpenChange={requestOpenChange}
        purpose="form"
        width={840}
        maxHeight="85dvh"
      >
        {/* Header, body and footer as plain children (as explore-conversations-dialog
            does): the Layout primitive sized its content slot from the dialog's
            height at open time, so a list that arrived later was clipped. */}
        <DialogHeader
          title={title}
          subtitle={step.kind === "list" ? t("governance_prompt_versions_intro") : undefined}
          startContent={
            step.kind === "view" ? (
              <IconButton
                label={t("prompt_library_version_view_back")}
                icon={<ArrowLeft aria-hidden="true" />}
                variant="ghost"
                size="sm"
                onClick={() => setStep(LIST)}
              />
            ) : undefined
          }
          onOpenChange={requestOpenChange}
        />
        {open && entry ? (
          <>
            <div className="flex min-h-0 flex-col gap-4 py-4">
              {step.kind === "view" ? (
                <VersionView version={step.version} />
              ) : (
                <QueryStateBoundary query={versions} rows={4}>
                  {(items) => (
                    <VersionTable
                      entry={entry}
                      versions={items}
                      onView={(version) => setStep({ kind: "view", version })}
                      onRestore={setRestoreTarget}
                    />
                  )}
                </QueryStateBoundary>
              )}
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              {step.kind === "view" && step.version.version !== entry.current_version ? (
                <Button
                  label={t("prompt_library_restore_this_version")}
                  icon={<RotateCcw aria-hidden="true" />}
                  onClick={() => setRestoreTarget(step.version)}
                />
              ) : null}
              <Button
                variant="primary"
                label={t("close")}
                onClick={() => requestOpenChange(false)}
              />
            </div>
          </>
        ) : null}
      </Dialog>
      <ConfirmDialogControlled
        open={open && restoreTarget !== null}
        onOpenChange={(next) => {
          if (!next) setRestoreTarget(null);
        }}
        title={t("governance_prompt_versions_restore_title")}
        description={t("governance_prompt_versions_restore_desc", {
          version: String(restoreTarget?.version ?? 0)
        })}
        confirmLabel={restore.isPending ? t("governance_prompt_versions_restoring") : t("restore")}
        variant="default"
        pending={restore.isPending}
        onConfirm={() => {
          if (restoreTarget) restore.mutate(restoreTarget);
        }}
      />
    </>
  );
}
