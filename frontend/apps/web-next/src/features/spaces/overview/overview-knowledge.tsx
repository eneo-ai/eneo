"use client";

import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { useCollator } from "@astryxdesign/core/i18n";
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
import { useSpace } from "../use-space";
import {
  overviewKnowledgeRows,
  uploadTargets,
  type KnowledgeKind,
  type KnowledgeRow
} from "./overview-data";
import { OverviewLink, OverviewSection } from "./overview-section";

const VISIBLE_ROWS = 5;
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

/** A short overview list; the full knowledge page owns the sortable table. */
function KnowledgeList({ rows }: { rows: KnowledgeRow[] }) {
  const t = useTranslations();

  return (
    <ul className="border-ax-border bg-ax-card rounded-ax-container divide-ax-border divide-y overflow-hidden border">
      {rows.map((row) => (
        <li
          key={row.key}
          className="flex min-w-0 flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center"
        >
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <KnowledgeNameCell icon={TYPE_ICONS[row.kind]} href={row.href}>
              {row.name}
            </KnowledgeNameCell>
            <div className="text-ax-text-secondary flex flex-wrap gap-x-3 gap-y-0.5 ps-9 text-xs">
              <span className="font-medium">{t(TYPE_KEYS[row.kind])}</span>
              {row.content ? <span>{t(row.content.key, row.content.values)}</span> : null}
              {row.updatedAt ? (
                <span>
                  {t("space_updated_column")}: <ClientTime value={row.updatedAt} format="date" />
                </span>
              ) : null}
            </div>
          </div>
          <div className="flex min-w-0 items-center justify-between gap-3 ps-9 sm:justify-end sm:ps-0">
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
            <RowActions row={row} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * The space's collections, websites and integrations in one compact list,
 * most recently updated first, with sync status and a fix link on errors.
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
      <p className="text-ax-text-secondary text-sm">{t("space_knowledge_description")}</p>
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
        <KnowledgeList rows={rows.slice(0, VISIBLE_ROWS)} />
      )}
    </OverviewSection>
  );
}
