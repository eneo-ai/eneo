"use client";

import { Link as AstryxLink } from "@astryxdesign/core/Link";
import {
  pixel,
  proportional,
  useTableSortable,
  useTableSortableState,
  type TableColumn,
  type TableSortComparator,
  type TableSortState
} from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { Folder } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { SpaceTableFrame } from "@/features/spaces/table-frame";
import { useSpace } from "@/features/spaces/use-space";
import type { IntegrationKnowledge } from "../knowledge";
import { KnowledgeNameCell } from "../table-controls-ui";
import { IntegrationActions, WrapperActions } from "./actions";
import type { IntegrationRow, SharePointItemTypeCounts } from "./grouping";
import { IntegrationStatus } from "./status";
import { SyncHistoryDialog } from "./sync-history";
import { VENDOR, VendorIcon } from "./vendor";

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

/** One table row: a SharePoint folder (wrapper) or a single item. */
type IntegrationTableRow = {
  id: string;
  /** Sorted with the locale's collator (Astryx's default for `name`). */
  name: string;
  /** Latest sync: the item's, or the most recent of a folder's items. */
  syncedAt: number;
  row: IntegrationRow;
};

type IntegrationSortKey = "name" | "status";

const DEFAULT_SORT: TableSortState<IntegrationSortKey> = [
  { sortKey: "name", direction: "ascending" }
];

const COMPARATORS: Partial<Record<IntegrationSortKey, TableSortComparator<IntegrationTableRow>>> = {
  status: (a, b) => a.syncedAt - b.syncedAt
};

function syncedAt(item: IntegrationKnowledge): number {
  const value = item.metadata.last_synced_at;
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

function toTableRow(row: IntegrationRow): IntegrationTableRow {
  return row.kind === "wrapper"
    ? {
        id: `wrapper-${row.wrapperId}`,
        name: row.wrapperName,
        syncedAt: Math.max(0, ...row.items.map(syncedAt)),
        row
      }
    : { id: row.item.id, name: row.item.name, syncedAt: syncedAt(row.item), row };
}

function NameCell({ row }: { row: IntegrationRow }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  if (row.kind === "wrapper") {
    return (
      <span className="flex min-w-0 flex-col gap-0.5">
        <KnowledgeNameCell
          icon={Folder}
          href={`/spaces/${routeId}/knowledge/integrations/wrapper/${row.wrapperId}`}
        >
          {row.wrapperName}
        </KnowledgeNameCell>
        <span className="text-ax-text-secondary ps-9.5 text-xs">
          {wrapperCountsSubtitle(row.counts, t)}
        </span>
      </span>
    );
  }
  const { item } = row;
  return (
    <span className="flex min-w-0 items-center gap-2.5 font-semibold">
      <span className="flex size-7 shrink-0 items-center justify-center">
        <VendorIcon type={item.integration_type} />
      </span>
      <span className="break-words">
        {item.name}
        {item.original_name && item.original_name !== item.name ? (
          <span className="text-ax-text-secondary font-normal"> ({item.original_name})</span>
        ) : null}
      </span>
    </span>
  );
}

/**
 * The integrations of a space (or of one SharePoint folder): a bordered
 * Astryx table that sorts by name or last sync, with the sync history one
 * click away and a named row menu per item or folder. `labelledBy` names the
 * table: the tab or its embedding model's heading, or the folder's title.
 */
export function IntegrationItemsTable({
  rows,
  labelledBy
}: {
  rows: IntegrationRow[];
  labelledBy: string;
}) {
  const t = useTranslations();
  const [syncHistoryItem, setSyncHistoryItem] = useState<IntegrationKnowledge | null>(null);
  const { sortedData, sortConfig } = useTableSortableState<IntegrationTableRow, IntegrationSortKey>(
    {
      data: rows.map(toTableRow),
      defaultSort: DEFAULT_SORT,
      comparators: COMPARATORS
    }
  );
  const sortPlugin = useTableSortable<IntegrationTableRow, IntegrationSortKey>(sortConfig);

  const columns: TableColumn<IntegrationTableRow>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(3),
      sortable: true,
      renderCell: ({ row }) => <NameCell row={row} />
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(2),
      sortable: true,
      renderCell: ({ row }) =>
        row.kind === "wrapper" ? (
          <span className="text-ax-text-secondary text-xs">
            {itemCountLabel(row.items.length, t)}
          </span>
        ) : (
          <IntegrationStatus
            item={row.item}
            onShowSyncHistory={() => setSyncHistoryItem(row.item)}
          />
        )
    },
    {
      key: "link",
      header: t("link"),
      width: proportional(1),
      renderCell: ({ row }) =>
        row.kind === "item" ? (
          <AstryxLink href={row.item.url} isExternalLink color="secondary">
            {t(VENDOR[row.item.integration_type].linkLabel)}
          </AstryxLink>
        ) : null
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(64),
      align: "end",
      renderCell: ({ row }) =>
        row.kind === "wrapper" ? (
          <WrapperActions
            wrapperId={row.wrapperId}
            wrapperName={row.wrapperName}
            itemCount={row.items.length}
            {...wrapperPermissions(row.items)}
          />
        ) : (
          <IntegrationActions item={row.item} />
        )
    }
  ];

  return (
    <>
      <SpaceTableFrame>
        <Table
          data={sortedData}
          columns={columns}
          idKey="id"
          aria-labelledby={labelledBy}
          plugins={{ sort: sortPlugin }}
        />
      </SpaceTableFrame>
      <SyncHistoryDialog
        item={syncHistoryItem}
        onOpenChange={(open) => {
          if (!open) setSyncHistoryItem(null);
        }}
      />
    </>
  );
}
