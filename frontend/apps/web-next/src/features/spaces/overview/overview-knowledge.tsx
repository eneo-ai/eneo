"use client";

import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { useCollator } from "@astryxdesign/core/i18n";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { BookOpen, FolderClosed, Globe, Plug, Upload, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { StatusLabel } from "@/components/composites/status-label";
import { CollectionActions, CreateCollectionButton } from "@/features/knowledge/collections";
import { IntegrationActions, WrapperActions } from "@/features/knowledge/integrations/actions";
import type { Collection } from "@/features/knowledge/knowledge";
import { KnowledgeNameCell } from "@/features/knowledge/table-controls-ui";
import { UploadBlobsDialog } from "@/features/knowledge/upload-dialog";
import { WebsiteActions } from "@/features/knowledge/websites";
import { SpaceTableFrame } from "../table-frame";
import { useSpace } from "../use-space";
import {
  overviewKnowledgeRows,
  uploadTargets,
  type KnowledgeKind,
  type KnowledgeRow
} from "./overview-data";
import { OverviewLink, OverviewSection } from "./overview-section";

const VISIBLE_ROWS = 5;
/** The section heading's id; it also names the table. */
const HEADING_ID = "overview-knowledge";

const TYPE_KEYS: Record<KnowledgeKind, string> = {
  collection: "space_knowledge_type_collection",
  website: "space_knowledge_type_website",
  integration: "space_knowledge_type_integration"
};

const TYPE_ICONS: Record<KnowledgeKind, LucideIcon> = {
  collection: FolderClosed,
  website: Globe,
  integration: Plug
};

/**
 * "Ladda upp": pick one of the space's collections, then the same upload
 * dialog as on the collection's page (formats, limits, duplicate check).
 */
function UploadMenu() {
  const t = useTranslations();
  const { space } = useSpace();
  const collator = useCollator();
  const [target, setTarget] = useState<Collection | null>(null);
  const targets = uploadTargets(space, collator.compare);
  if (targets.length === 0) return null;

  return (
    <>
      <DropdownMenu
        button={{
          label: t("upload"),
          size: "sm",
          icon: <Upload aria-hidden="true" />
        }}
        alignment="end"
        items={[
          {
            type: "section",
            title: t("space_upload_choose_collection"),
            items: targets.map((collection) => ({
              id: collection.id,
              label: collection.name,
              icon: <FolderClosed aria-hidden="true" />,
              onClick: () => setTarget(collection)
            }))
          }
        ]}
      />
      {target ? (
        <UploadBlobsDialog
          key={target.id}
          collectionId={target.id}
          collectionName={target.name}
          open
          onOpenChange={(open) => {
            if (!open) setTarget(null);
          }}
        />
      ) : null}
    </>
  );
}

function RowActions({ row }: { row: KnowledgeRow }) {
  const { source } = row;
  switch (source.kind) {
    case "collection":
      return <CollectionActions collection={source.collection} />;
    case "website":
      return <WebsiteActions website={source.website} />;
    case "integration":
      return <IntegrationActions item={source.item} />;
    case "wrapper": {
      const permissions = source.items[0]?.permissions ?? [];
      return (
        <WrapperActions
          wrapperId={source.wrapperId}
          wrapperName={source.wrapperName}
          itemCount={source.items.length}
          canEdit={permissions.includes("edit")}
          canDelete={permissions.includes("delete")}
        />
      );
    }
  }
}

function KnowledgeTable({ rows }: { rows: KnowledgeRow[] }) {
  const t = useTranslations();
  const columns: TableColumn<KnowledgeRow>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(3),
      renderCell: (row) => (
        <KnowledgeNameCell icon={TYPE_ICONS[row.kind]} href={row.href}>
          {row.name}
        </KnowledgeNameCell>
      )
    },
    {
      key: "type",
      header: t("type"),
      width: proportional(1),
      renderCell: (row) => t(TYPE_KEYS[row.kind])
    },
    {
      key: "content",
      header: t("content"),
      width: proportional(1),
      renderCell: (row) => (row.content ? t(row.content.key, row.content.values) : "—")
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(1),
      renderCell: (row) => (
        <span className="inline-flex flex-wrap items-center gap-x-2">
          <StatusLabel
            status={row.status.tone}
            label={t(row.status.labelKey)}
            isPulsing={row.status.isPulsing}
            className={row.status.tone === "error" ? "text-ax-error" : undefined}
          />
          {row.status.fixHref ? (
            <Link
              href={row.status.fixHref}
              aria-label={t("space_fix_named", { name: row.name })}
              className="text-ax-text-accent focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 items-center text-sm font-semibold underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
            >
              {t("space_fix")}
            </Link>
          ) : null}
        </span>
      )
    },
    {
      key: "updated",
      header: t("space_updated_column"),
      width: proportional(1),
      renderCell: (row) =>
        row.updatedAt ? <ClientTime value={row.updatedAt} format="date" /> : "—"
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(64),
      align: "end",
      renderCell: (row) => <RowActions row={row} />
    }
  ];

  return (
    <SpaceTableFrame>
      <Table data={rows} columns={columns} idKey="key" aria-labelledby={HEADING_ID} />
    </SpaceTableFrame>
  );
}

/**
 * The space's collections, websites and integrations in one table, most
 * recently updated first, with their sync status and a fix link on errors.
 */
export function OverviewKnowledge() {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const collator = useCollator();
  const rows = overviewKnowledgeRows(space, routeId, collator.compare);

  return (
    <OverviewSection
      id={HEADING_ID}
      title={t("knowledge")}
      end={
        <>
          <UploadMenu />
          {rows.length > 0 ? (
            <OverviewLink
              href={`/spaces/${routeId}/knowledge`}
              label={t("space_view_all_knowledge")}
            >
              {t("space_view_all")}
            </OverviewLink>
          ) : null}
        </>
      }
    >
      {rows.length === 0 ? (
        <EmptyState
          icon={<BookOpen />}
          title={t("space_knowledge_empty_title")}
          description={t("space_knowledge_empty_description")}
          headingLevel={3}
          isCompact
          actions={can("create", "collection") ? <CreateCollectionButton /> : undefined}
        />
      ) : (
        <KnowledgeTable rows={rows.slice(0, VISIBLE_ROWS)} />
      )}
    </OverviewSection>
  );
}
