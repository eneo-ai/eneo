"use client";

import { ExternalLink, Folder } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { useSpace } from "@/features/spaces/use-space";
import type { IntegrationKnowledge } from "../knowledge";
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

/** Shared rows for the integrations tab and the wrapper detail page. */
export function IntegrationItemsTable({ rows }: { rows: IntegrationRow[] }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const [syncHistoryItem, setSyncHistoryItem] = useState<IntegrationKnowledge | null>(null);

  return (
    <>
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
                  <IntegrationStatus
                    item={row.item}
                    onShowSyncHistory={() => setSyncHistoryItem(row.item)}
                  />
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
      <SyncHistoryDialog
        item={syncHistoryItem}
        onOpenChange={(open) => {
          if (!open) setSyncHistoryItem(null);
        }}
      />
    </>
  );
}
