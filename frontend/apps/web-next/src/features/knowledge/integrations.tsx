"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Folder, MoreHorizontal, Pencil, RefreshCw, Trash2 } from "lucide-react";
import Image, { type StaticImageData } from "next/image";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { formatRelativeTime, hoursUntil } from "@/lib/format";
import { useJobs } from "@/features/jobs/use-jobs";
import { useSpace } from "@/features/spaces/use-space";
import confluenceLogo from "./confluence.png";
import { embeddingModelsInUse, type IntegrationKnowledge } from "./knowledge";
import sharepointLogo from "./sharepoint.png";

// --- Wrapper grouping (pure, unit-tested) ---

export type SharePointItemTypeCounts = {
  files: number;
  folders: number;
  sites: number;
  unknown: number;
  total: number;
};

export function countSharePointItemTypes(items: IntegrationKnowledge[]): SharePointItemTypeCounts {
  const counts = { files: 0, folders: 0, sites: 0, unknown: 0, total: items.length };
  for (const item of items) {
    const itemType = (item.selected_item_type ?? "").toLowerCase();
    if (itemType === "file") counts.files += 1;
    else if (itemType === "folder") counts.folders += 1;
    else if (itemType === "site_root" || itemType === "site") counts.sites += 1;
    else counts.unknown += 1;
  }
  return counts;
}

export type IntegrationRow =
  | {
      kind: "wrapper";
      wrapperId: string;
      wrapperName: string;
      items: IntegrationKnowledge[];
      counts: SharePointItemTypeCounts;
      embeddingModelId: string;
    }
  | { kind: "item"; item: IntegrationKnowledge; embeddingModelId: string };

export function wrapperDisplayName(item: IntegrationKnowledge): string {
  return typeof item.wrapper_name === "string" && item.wrapper_name.trim().length > 0
    ? item.wrapper_name
    : item.name;
}

/**
 * SharePoint items sharing a wrapper_id collapse into one folder row once the
 * wrapper holds at least two items; everything else stays a plain row. Rows
 * come back sorted alphabetically. Ported from IntegrationsTable.svelte.
 */
export function groupIntegrationRows(items: IntegrationKnowledge[]): IntegrationRow[] {
  const wrappers = new Map<string, IntegrationKnowledge[]>();
  const standalone: IntegrationKnowledge[] = [];

  for (const item of items) {
    if (item.wrapper_id && item.integration_type === "sharepoint") {
      const group = wrappers.get(item.wrapper_id) ?? [];
      group.push(item);
      wrappers.set(item.wrapper_id, group);
    } else {
      standalone.push(item);
    }
  }

  const rows: { sortKey: string; row: IntegrationRow }[] = [];

  for (const [wrapperId, wrapperItems] of wrappers) {
    const first = wrapperItems[0];
    if (first && wrapperItems.length >= 2) {
      const wrapperName = wrapperDisplayName(first);
      rows.push({
        sortKey: wrapperName.toLowerCase(),
        row: {
          kind: "wrapper",
          wrapperId,
          wrapperName,
          items: wrapperItems,
          counts: countSharePointItemTypes(wrapperItems),
          embeddingModelId: first.embedding_model.id
        }
      });
    } else {
      for (const item of wrapperItems) standalone.push(item);
    }
  }

  for (const item of standalone) {
    rows.push({
      sortKey: item.name.toLowerCase(),
      row: { kind: "item", item, embeddingModelId: item.embedding_model.id }
    });
  }

  rows.sort((a, b) => a.sortKey.localeCompare(b.sortKey));
  return rows.map((entry) => entry.row);
}

// --- Display helpers ---

const VENDOR: Record<
  IntegrationKnowledge["integration_type"],
  { logo: StaticImageData; linkLabel: string }
> = {
  sharepoint: { logo: sharepointLogo, linkLabel: "open_in_sharepoint" },
  confluence: { logo: confluenceLogo, linkLabel: "open_in_confluence" }
};

function VendorIcon({ type }: { type: IntegrationKnowledge["integration_type"] }) {
  return <Image src={VENDOR[type].logo} alt={type} width={16} height={16} className="shrink-0" />;
}

type Translate = (key: string, params?: Record<string, string>) => string;

function wrapperCountsSubtitle(counts: SharePointItemTypeCounts, t: Translate): string {
  const parts: string[] = [];
  if (counts.files > 0) {
    parts.push(
      t(counts.files === 1 ? "sharepoint_wrapper_files_one" : "sharepoint_wrapper_files_other", {
        count: String(counts.files)
      })
    );
  }
  if (counts.folders > 0) {
    parts.push(
      t(
        counts.folders === 1
          ? "sharepoint_wrapper_folders_one"
          : "sharepoint_wrapper_folders_other",
        { count: String(counts.folders) }
      )
    );
  }
  if (counts.sites > 0) {
    parts.push(
      t(counts.sites === 1 ? "sharepoint_wrapper_sites_one" : "sharepoint_wrapper_sites_other", {
        count: String(counts.sites)
      })
    );
  }
  if (parts.length === 0) {
    parts.push(
      t(counts.total === 1 ? "wrapper_items_count_one" : "wrapper_items_count_other", {
        count: String(counts.total)
      })
    );
  }
  return parts.join(", ");
}

function itemCountLabel(count: number, t: Translate): string {
  return t(count === 1 ? "wrapper_items_count_one" : "wrapper_items_count_other", {
    count: String(count)
  });
}

/** Last-sync line plus, for SharePoint, the webhook subscription state. */
function IntegrationStatus({ item }: { item: IntegrationKnowledge }) {
  const t = useTranslations();
  const locale = useLocale();
  const syncedAt = item.metadata.last_synced_at ?? null;

  let webhook: { label: string; tooltip: string; className: string } | null = null;
  if (item.integration_type === "sharepoint") {
    const expiresAt = item.metadata.sharepoint_subscription_expires_at ?? null;
    if (!expiresAt) {
      webhook = {
        label: t("sharepoint_webhook_none"),
        tooltip: t("sharepoint_webhook_none_tooltip"),
        className: "text-muted-foreground"
      };
    } else {
      const hours = hoursUntil(expiresAt);
      webhook =
        hours <= 0
          ? {
              label: t("sharepoint_webhook_expired"),
              tooltip: t("sharepoint_webhook_expired_tooltip"),
              className: "text-red-600 dark:text-red-400"
            }
          : hours <= 48
            ? {
                label: t("sharepoint_webhook_expiring_soon"),
                tooltip: t("sharepoint_webhook_auto_renewal"),
                className: "text-amber-600 dark:text-amber-400"
              }
            : {
                label: t("sharepoint_webhook_active"),
                tooltip: t("sharepoint_webhook_auto_renewal"),
                className: "text-green-700 dark:text-green-400"
              };
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-0.5 text-xs">
      {syncedAt ? (
        <span className="text-muted-foreground truncate">
          {t("integration_last_synced")} {formatRelativeTime(syncedAt, locale)}
        </span>
      ) : (
        <span className="text-muted-foreground truncate opacity-70">
          {t("integration_sync_summary_none")}
        </span>
      )}
      {webhook && (
        <span className={`truncate ${webhook.className}`} title={webhook.tooltip}>
          {webhook.label}
        </span>
      )}
    </div>
  );
}

// --- Row actions ---

function useSpaceInvalidation() {
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
}

function IntegrationActions({ item }: { item: IntegrationKnowledge }) {
  const t = useTranslations();
  const { space } = useSpace();
  const { trackJob } = useJobs();
  const invalidate = useSpaceInvalidation();
  const [showRename, setShowRename] = useState(false);
  const [showSync, setShowSync] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [newName, setNewName] = useState(item.name);

  const canEdit = item.permissions?.includes("edit") ?? false;
  const canDelete = item.permissions?.includes("delete") ?? false;

  const rename = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.PATCH("/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/", {
          params: { path: { id: space.id, integration_knowledge_id: item.id } },
          body: { name: newName }
        })
      ),
    onSuccess: () => {
      invalidate();
      setShowRename(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const fullSync = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST(
          "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/sync/",
          { params: { path: { id: space.id, integration_knowledge_id: item.id } } }
        )
      ),
    onSuccess: () => {
      trackJob();
      invalidate();
      setShowSync(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteKnowledge = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE(
          "/api/v1/spaces/{id}/knowledge/integrations/remove/{integration_knowledge_id}/",
          { params: { path: { id: space.id, integration_knowledge_id: item.id } } }
        )
      ),
    onSuccess: () => {
      invalidate();
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  if (!canEdit && !canDelete) return null;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={t("actions")}>
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {canEdit && (
            <DropdownMenuItem
              onSelect={() => {
                setNewName(item.name);
                setShowRename(true);
              }}
            >
              <Pencil className="size-4" /> {t("rename")}
            </DropdownMenuItem>
          )}
          {canEdit && item.integration_type === "sharepoint" && (
            <DropdownMenuItem onSelect={() => setShowSync(true)}>
              <RefreshCw className="size-4" /> {t("trigger_full_sync")}
            </DropdownMenuItem>
          )}
          {canDelete && (
            <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
              <Trash2 className="size-4" /> {t("delete")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <RenameDialog
        open={showRename}
        onOpenChange={setShowRename}
        title={t("integration_rename_title")}
        name={newName}
        onNameChange={setNewName}
        pending={rename.isPending}
        onSave={() => rename.mutate()}
      />
      <AlertDialog open={showSync} onOpenChange={setShowSync}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("trigger_full_sync")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("confirm_full_sync", { knowledgeName: item.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={fullSync.isPending}>{t("cancel")}</AlertDialogCancel>
            <Button disabled={fullSync.isPending} onClick={() => fullSync.mutate()}>
              {fullSync.isPending ? t("syncing") : t("start_full_sync")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_integration_knowledge")}
        description={t("confirm_delete_integration_knowledge", { knowledgeName: item.name })}
        confirmLabel={deleteKnowledge.isPending ? t("deleting") : t("delete")}
        pending={deleteKnowledge.isPending}
        onConfirm={() => deleteKnowledge.mutate()}
      />
    </>
  );
}

function RenameDialog({
  open,
  onOpenChange,
  title,
  name,
  onNameChange,
  pending,
  onSave
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  name: string;
  onNameChange: (name: string) => void;
  pending: boolean;
  onSave: () => void;
}) {
  const t = useTranslations();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="integration-name">{t("name")}</Label>
          <Input
            id="integration-name"
            value={name}
            onChange={(event) => onNameChange(event.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={pending || !name.trim()} onClick={onSave}>
            {pending ? t("saving") : t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function WrapperActions({
  wrapperId,
  wrapperName,
  itemCount,
  canEdit,
  canDelete,
  onDeleted
}: {
  wrapperId: string;
  wrapperName: string;
  itemCount: number;
  canEdit: boolean;
  canDelete: boolean;
  onDeleted?: () => void;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const invalidate = useSpaceInvalidation();
  const [showRename, setShowRename] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [newName, setNewName] = useState(wrapperName);

  const rename = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.PATCH("/api/v1/spaces/{id}/knowledge/integrations/wrappers/{wrapper_id}/", {
          params: { path: { id: space.id, wrapper_id: wrapperId } },
          body: { name: newName }
        })
      ),
    onSuccess: () => {
      invalidate();
      setShowRename(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteWrapper = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/spaces/{id}/knowledge/integrations/wrappers/{wrapper_id}/", {
          params: { path: { id: space.id, wrapper_id: wrapperId } }
        })
      ),
    onSuccess: () => {
      invalidate();
      setShowDelete(false);
      onDeleted?.();
    },
    onError: (error) => toastApiError(error, t)
  });

  if (!canEdit && !canDelete) return null;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={t("actions")}>
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {canEdit && (
            <DropdownMenuItem
              onSelect={() => {
                setNewName(wrapperName);
                setShowRename(true);
              }}
            >
              <Pencil className="size-4" /> {t("rename_wrapper")}
            </DropdownMenuItem>
          )}
          {canDelete && (
            <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
              <Trash2 className="size-4" /> {t("delete_wrapper")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <RenameDialog
        open={showRename}
        onOpenChange={setShowRename}
        title={t("rename_wrapper")}
        name={newName}
        onNameChange={setNewName}
        pending={rename.isPending}
        onSave={() => rename.mutate()}
      />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_wrapper")}
        description={t("confirm_delete_sharepoint_wrapper", {
          wrapperName,
          count: String(itemCount)
        })}
        confirmLabel={deleteWrapper.isPending ? t("deleting") : t("delete")}
        pending={deleteWrapper.isPending}
        onConfirm={() => deleteWrapper.mutate()}
      />
    </>
  );
}

// --- Tables ---

function wrapperPermissions(items: IntegrationKnowledge[]): {
  canEdit: boolean;
  canDelete: boolean;
} {
  const permissions = items[0]?.permissions ?? [];
  return {
    canEdit: permissions.includes("edit"),
    canDelete: permissions.includes("delete")
  };
}

export function IntegrationItemsTable({ rows }: { rows: IntegrationRow[] }) {
  const t = useTranslations();
  const { routeId } = useSpace();

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("name")}</TableHead>
          <TableHead>{t("status")}</TableHead>
          <TableHead>{t("link")}</TableHead>
          <TableHead className="w-16" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) =>
          row.kind === "wrapper" ? (
            <TableRow key={`wrapper-${row.wrapperId}`}>
              <TableCell>
                <Link
                  href={`/spaces/${routeId}/knowledge/integrations/wrapper/${row.wrapperId}`}
                  className="flex max-w-72 flex-col gap-0.5 hover:underline"
                >
                  <span className="flex items-center gap-2 font-medium">
                    <Folder className="text-muted-foreground size-4 shrink-0" />
                    <span className="truncate">{row.wrapperName}</span>
                  </span>
                  <span className="text-muted-foreground pl-6 text-xs">
                    {wrapperCountsSubtitle(row.counts, t)}
                  </span>
                </Link>
              </TableCell>
              <TableCell>
                <span className="text-muted-foreground text-xs">
                  {itemCountLabel(row.items.length, t)}
                </span>
              </TableCell>
              <TableCell />
              <TableCell className="text-right">
                <WrapperActions
                  wrapperId={row.wrapperId}
                  wrapperName={row.wrapperName}
                  itemCount={row.items.length}
                  {...wrapperPermissions(row.items)}
                />
              </TableCell>
            </TableRow>
          ) : (
            <TableRow key={row.item.id}>
              <TableCell>
                <span className="flex max-w-72 items-center gap-2 font-medium">
                  <VendorIcon type={row.item.integration_type} />
                  <span className="truncate" title={row.item.name}>
                    {row.item.name}
                    {row.item.original_name && row.item.original_name !== row.item.name && (
                      <span className="text-muted-foreground"> ({row.item.original_name})</span>
                    )}
                  </span>
                </span>
              </TableCell>
              <TableCell>
                <IntegrationStatus item={row.item} />
              </TableCell>
              <TableCell>
                <a
                  href={row.item.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
                >
                  {t(VENDOR[row.item.integration_type].linkLabel)}
                  <ExternalLink className="size-3.5" />
                </a>
              </TableCell>
              <TableCell className="text-right">
                <IntegrationActions item={row.item} />
              </TableCell>
            </TableRow>
          )
        )}
      </TableBody>
    </Table>
  );
}

export function IntegrationsTab() {
  const t = useTranslations();
  const { space } = useSpace();

  const items = space.knowledge.integration_knowledge_list.items.filter(
    (item) => item.space_id === space.id
  );
  const rows = groupIntegrationRows(items);
  const models = embeddingModelsInUse(items, space.embedding_models);
  const grouped =
    models.length > 1 ||
    space.embedding_models.length > 1 ||
    models.some((model) => !model.inSpace);

  if (items.length === 0) {
    return <EmptyState title={t("no_results")} />;
  }

  return (
    <div className="flex flex-col gap-4">
      {(grouped ? models : [null]).map((model) => {
        const modelRows = model ? rows.filter((row) => row.embeddingModelId === model.id) : rows;
        if (modelRows.length === 0) return null;
        return (
          <div key={model?.id ?? "all"} className="flex flex-col gap-1">
            {model && (
              <h3 className="text-muted-foreground text-sm font-medium">
                {model.name}
                {model.inSpace ? "" : ` (${t("disabled")})`}
              </h3>
            )}
            <IntegrationItemsTable rows={modelRows} />
          </div>
        );
      })}
    </div>
  );
}
