"use client";

import { Button } from "@astryxdesign/core/Button";
import { useCollator } from "@astryxdesign/core/i18n";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { Table } from "@/components/astryx/table";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { cn } from "@/lib/utils";
import type { IntegrationKnowledge } from "../../knowledge";
import { IntegrationActions } from "../actions";
import { safeExternalUrl } from "../external-url";
import { buildIntegrationTree, flattenIntegrationTree } from "../integration-tree";
import { SourceStateLabel, useWatchStates } from "../source-status";
import { itemState, watchStateLabel, type ItemState, type QueuedIds } from "../sources";
import type { ProgressById } from "../sync-progress";
import { VENDOR } from "../vendor";
import type { InPlaceLink } from "./in-place-link";

type FolderRow = { id: string; item: IntegrationKnowledge; depth: number };

const isActive = (state: ItemState) => state === "syncing" || state === "queued";

function LastUpToDate({ item }: { item: IntegrationKnowledge }) {
  const t = useTranslations();
  const attempted = useClientTimeText(item.metadata?.last_sync_attempted_at, "date_time");
  if (item.metadata?.last_synced_at) {
    return (
      <span className="text-ax-text-secondary text-sm">
        <ClientTime value={item.metadata.last_synced_at} format="auto" />
      </span>
    );
  }
  return (
    <span className="text-ax-text-secondary text-sm">
      {attempted ? t("integration_source_last_attempt_at", { time: attempted }) : "–"}
    </span>
  );
}

/** Whether SharePoint tells Eneo about changes to the folder; "–" for other vendors. */
function WatchCell({ item }: { item: IntegrationKnowledge }) {
  const t = useTranslations();
  const [watch] = useWatchStates([item]) ?? [];
  if (item.integration_type !== "sharepoint" || !watch) {
    return <span className="text-ax-text-secondary text-sm">–</span>;
  }
  return (
    <span
      className={cn("text-sm", watch === "expired" ? "text-ax-warning" : "text-ax-text-secondary")}
    >
      {watchStateLabel(watch, t)}
    </span>
  );
}

/** Every folder of a source in tree order, with its state, documents and actions. */
export function FolderOverview({
  items,
  progress,
  queued,
  sourceName,
  linkFor
}: {
  items: IntegrationKnowledge[];
  progress: ProgressById;
  queued: QueuedIds;
  sourceName: string;
  linkFor: (itemId: string) => InPlaceLink;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const collator = useCollator();
  const rows: FolderRow[] = flattenIntegrationTree(
    buildIntegrationTree(items, collator.compare),
    () => true
  ).map((row) => ({ id: row.item.id, item: row.item, depth: row.depth }));

  const columns: TableColumn<FolderRow>[] = [
    {
      key: "folder",
      header: t("integration_source_folder"),
      width: proportional(1, { minWidth: 176 }),
      renderCell: (row) => (
        <span
          className="flex min-w-0 flex-col"
          style={{ paddingInlineStart: `${row.depth * 1.25}rem` }}
        >
          <Link
            {...linkFor(row.item.id)}
            prefetch={false}
            className="text-ax-text focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 w-fit items-center font-semibold break-words hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
          >
            {row.item.name}
            {row.item.original_name && row.item.original_name !== row.item.name ? (
              <span className="text-ax-text-secondary ms-1 font-normal">
                ({row.item.original_name})
              </span>
            ) : null}
          </Link>
          {row.item.folder_path ? (
            <span className="text-ax-text-secondary truncate text-xs">{row.item.folder_path}</span>
          ) : null}
        </span>
      )
    },
    {
      key: "status",
      header: t("status"),
      width: pixel(144),
      renderCell: (row) => <SourceStateLabel state={itemState(row.item, progress, queued)} />
    },
    {
      key: "documents",
      header: t("documents"),
      width: pixel(110),
      align: "end",
      renderCell: (row) => (
        <span className="tabular-nums">
          {progress[row.item.id] ? "–" : format.number(row.item.metadata?.document_count ?? 0)}
        </span>
      )
    },
    {
      key: "updated",
      header: t("integration_source_last_up_to_date"),
      width: pixel(128),
      renderCell: (row) => <LastUpToDate item={row.item} />
    },
    ...(items.some((item) => item.integration_type === "sharepoint")
      ? [
          {
            key: "watch",
            header: t("integration_source_stat_watch"),
            width: pixel(168),
            renderCell: (row: FolderRow) => <WatchCell item={row.item} />
          }
        ]
      : []),
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(120),
      align: "end",
      renderCell: (row) => {
        const url = safeExternalUrl(row.item.url);
        return (
          <span className="flex items-center justify-end gap-1">
            {url ? (
              <Button
                variant="ghost"
                size="sm"
                label={t("integration_source_open_item_link", {
                  label: t(VENDOR[row.item.integration_type].linkLabel),
                  name: row.item.name
                })}
                isIconOnly
                icon={<ExternalLink className="size-4" aria-hidden="true" />}
                href={url}
                target="_blank"
                rel="noopener noreferrer"
              />
            ) : null}
            <IntegrationActions
              item={row.item}
              syncActive={isActive(itemState(row.item, progress, queued))}
            />
          </span>
        );
      }
    }
  ];

  return (
    <Table
      data={rows}
      columns={columns}
      idKey="id"
      aria-label={t("integration_source_folders_table_label", { name: sourceName })}
      pinnedColumn="folder"
      // Not in a frame: the pinned column takes the page's colour.
      className="[--table-sticky-background:var(--color-ax-surface)]"
    />
  );
}
