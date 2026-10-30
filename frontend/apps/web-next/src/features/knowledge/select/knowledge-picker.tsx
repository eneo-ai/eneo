"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { IconButton } from "@astryxdesign/core/IconButton";
import { List, ListItem } from "@astryxdesign/core/List";
import {
  Selector,
  type SelectorOptionData,
  type SelectorOptionType
} from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { Database, FileText, Globe, Plus, X } from "lucide-react";
import { useLocale, useTranslations } from "use-intl";
import { useState, type ReactNode } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { BlobPreviewDialog } from "@/features/knowledge/blobs";
import { browserApi } from "@/lib/api/browser";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { spacesListQueryOptions } from "@/features/spaces/space";
import { useSpace } from "@/features/spaces/use-space";
import { VendorIcon } from "../integrations/vendor";
import {
  collectionBlobsQueryOptions,
  formatWebsiteName,
  websiteBlobsQueryOptions,
  type Collection,
  type InfoBlob,
  type IntegrationKnowledge,
  type Website
} from "../knowledge";
import {
  availableKnowledge,
  byOrigin,
  collectionInfoBlobCount,
  integrationOptions,
  selectedIntegrationDisplay,
  websiteFailedPageCount,
  websiteIndexedResultCount,
  type IntegrationEntry,
  type KnowledgeOrigin,
  type KnowledgeSelections
} from "./logic";

/** The organization space id, used to bucket shared knowledge by origin. */
function useOrgSpaceId(): string | undefined {
  const { data: spaces } = useQuery(spacesListQueryOptions(browserApi));
  return spaces?.find((space) => space.organization)?.id;
}

/** The bordered box of one selected source; a failed crawl marks its start edge. */
function rowFrameClass(failed: boolean) {
  return cn(
    "border-ax-border rounded-ax-element flex w-full border",
    failed && "border-s-ax-error border-s-4"
  );
}

/** Icon, name (with the disabled-model note) and what it holds, on one line. */
function RowSummary({
  icon,
  name,
  modelEnabled,
  meta
}: {
  icon: ReactNode;
  name: string;
  modelEnabled: boolean;
  meta?: ReactNode;
}) {
  const t = useTranslations();
  return (
    <span className="flex min-h-12 min-w-0 flex-1 items-center gap-2 text-sm">
      {icon}
      <span className="min-w-0 flex-1 truncate font-medium" title={name}>
        {name}
        {!modelEnabled && <span className="text-ax-error"> ({t("model_disabled")})</span>}
      </span>
      {meta}
    </span>
  );
}

function RemoveButton({ disabled, onRemove }: { disabled?: boolean; onRemove: () => void }) {
  const t = useTranslations();
  return (
    <IconButton
      variant="ghost"
      size="sm"
      label={t("delete")}
      icon={<X aria-hidden="true" />}
      isDisabled={disabled}
      onClick={onRemove}
    />
  );
}

function SupportingText({ children }: { children: ReactNode }) {
  return (
    <Text type="supporting" size="sm" className="shrink-0">
      {children}
    </Text>
  );
}

function SelectedRow({
  icon,
  name,
  modelEnabled,
  meta,
  onRemove,
  disabled
}: {
  icon: ReactNode;
  name: string;
  modelEnabled: boolean;
  meta?: ReactNode;
  onRemove: () => void;
  disabled?: boolean;
}) {
  return (
    <div className={cn(rowFrameClass(false), "items-center gap-2 px-3")}>
      <RowSummary icon={icon} name={name} modelEnabled={modelEnabled} meta={meta} />
      <RemoveButton disabled={disabled} onRemove={onRemove} />
    </div>
  );
}

function integrationMeta(entry: IntegrationEntry): ReactNode {
  if (entry.type === "single") return null;
  return <SupportingText>{entry.wrapper.items.length}</SupportingText>;
}

const BLOBS_PAGE_SIZE = 10;

function blobTitle(blob: InfoBlob): string {
  return blob.metadata.title ?? blob.metadata.url ?? blob.id;
}

function SelectedKnowledgeBlobList({
  blobs,
  loading,
  error,
  emptyMessage
}: {
  blobs: InfoBlob[] | undefined;
  loading: boolean;
  error: boolean;
  emptyMessage: string;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const [page, setPage] = useState(0);
  const [preview, setPreview] = useState<InfoBlob | null>(null);

  if (loading) {
    return <LoadingState variant="text" rows={2} />;
  }
  if (error) {
    return (
      <p className="text-ax-error m-0 px-3 py-3 text-sm">{t("attachment_error_loading_content")}</p>
    );
  }
  if (!blobs || blobs.length === 0) {
    return (
      <Text type="supporting" as="p" display="block" className="m-0 px-3 py-3">
        {emptyMessage}
      </Text>
    );
  }

  const pageCount = Math.max(1, Math.ceil(blobs.length / BLOBS_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = blobs.slice(currentPage * BLOBS_PAGE_SIZE, (currentPage + 1) * BLOBS_PAGE_SIZE);

  return (
    <div className="border-ax-border border-t px-1 py-1">
      <List density="compact">
        {visible.map((blob) => (
          <ListItem
            key={blob.id}
            label={blobTitle(blob)}
            startContent={<FileText aria-hidden="true" className="text-ax-text-secondary size-4" />}
            endContent={
              blob.metadata.size ? (
                <SupportingText>{formatBytes(blob.metadata.size, locale)}</SupportingText>
              ) : undefined
            }
            onClick={() => setPreview(blob)}
          />
        ))}
      </List>
      {pageCount > 1 ? (
        <div className="border-ax-border mt-1 flex items-center justify-end gap-2 border-t px-2 pt-2 pb-1">
          <SupportingText>
            {currentPage + 1} / {pageCount}
          </SupportingText>
          <Button
            size="sm"
            label={t("previous")}
            isDisabled={currentPage === 0}
            onClick={() => setPage(currentPage - 1)}
          />
          <Button
            size="sm"
            label={t("next")}
            isDisabled={currentPage >= pageCount - 1}
            onClick={() => setPage(currentPage + 1)}
          />
        </div>
      ) : null}
      {preview ? (
        <BlobPreviewDialog
          blob={preview}
          open
          onOpenChange={(open) => {
            if (!open) setPreview(null);
          }}
        />
      ) : null}
    </div>
  );
}

function SelectedKnowledgeRow({
  kind,
  item,
  modelEnabled,
  onRemove,
  disabled
}:
  | {
      kind: "collection";
      item: Collection;
      modelEnabled: boolean;
      onRemove: () => void;
      disabled?: boolean;
    }
  | {
      kind: "website";
      item: Website;
      modelEnabled: boolean;
      onRemove: () => void;
      disabled?: boolean;
    }) {
  const t = useTranslations();
  const [expanded, setExpanded] = useState(false);
  const isCollection = kind === "collection";
  const title = isCollection ? item.name : formatWebsiteName(item);
  const pagesCrawled = isCollection ? 0 : (item.latest_crawl?.pages_crawled ?? 0);
  const indexedCount = isCollection
    ? collectionInfoBlobCount(item)
    : websiteIndexedResultCount(item);
  const pagesFailed = isCollection ? 0 : websiteFailedPageCount(item);
  const expandable = indexedCount > 0;
  const blobsQuery = useQuery({
    ...(isCollection
      ? collectionBlobsQueryOptions(browserApi, item.id)
      : websiteBlobsQueryOptions(browserApi, item.id)),
    enabled: expanded && expandable
  });

  const summary = (
    <RowSummary
      icon={
        isCollection ? (
          <Database aria-hidden="true" className="text-ax-text-secondary size-4 shrink-0" />
        ) : (
          <Globe aria-hidden="true" className="text-ax-text-secondary size-4 shrink-0" />
        )
      }
      name={title}
      modelEnabled={modelEnabled}
      meta={
        <>
          {pagesFailed > 0 ? (
            <Badge
              variant="error"
              label={t("space_crawl_failed", {
                items: t("space_pages_count", { count: pagesFailed })
              })}
            />
          ) : null}
          {!isCollection && pagesCrawled > 0 ? (
            <SupportingText>{t("space_pages_count", { count: pagesCrawled })}</SupportingText>
          ) : null}
          {isCollection ? (
            <SupportingText>
              {indexedCount > 0 ? t("space_files_count", { count: indexedCount }) : t("empty")}
            </SupportingText>
          ) : null}
        </>
      }
    />
  );

  return (
    <div className={cn(rowFrameClass(pagesFailed > 0), "items-start gap-2 pe-3")}>
      {expandable ? (
        // The whole summary is the disclosure button; Remove follows it, beside
        // the summary line, so the row reads summary, files, then Remove.
        <Collapsible
          isOpen={expanded}
          onOpenChange={setExpanded}
          className="min-w-0 flex-1 [&>.astryx-collapsible-trigger]:ps-3 [&>.astryx-collapsible-trigger]:text-sm [&>.astryx-collapsible-trigger]:font-normal"
          trigger={summary}
        >
          {expanded ? (
            <SelectedKnowledgeBlobList
              blobs={blobsQuery.data}
              loading={blobsQuery.isPending}
              error={blobsQuery.isError}
              emptyMessage={isCollection ? t("knowledge_no_files_found") : t("noPagesFound")}
            />
          ) : null}
        </Collapsible>
      ) : (
        <div className="flex min-w-0 flex-1 ps-3">{summary}</div>
      )}
      <div className="flex min-h-12 items-center">
        <RemoveButton disabled={disabled} onRemove={onRemove} />
      </div>
    </div>
  );
}

/**
 * Selected knowledge for the current space or organization plus a searchable
 * add-selector sectioned per embedding model (an Astryx Selector that holds no
 * value: picking an option adds it). Ported from SelectKnowledge +
 * KnowledgeCombobox.
 */
export function KnowledgePicker({
  origin,
  selections,
  onChange,
  disabled,
  resourceKinds
}: {
  origin: KnowledgeOrigin;
  selections: KnowledgeSelections;
  onChange: (next: KnowledgeSelections) => void;
  disabled?: boolean;
  resourceKinds?: Partial<Record<keyof KnowledgeSelections, boolean>>;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const orgSpaceId = useOrgSpaceId();
  const addLabel =
    origin === "organization"
      ? t("add_knowledge_organization")
      : space.personal
        ? t("add_knowledge_personal")
        : t("add_knowledge_this_space");
  const emptyLabel =
    origin === "organization"
      ? t("no_organization_sources")
      : space.personal
        ? t("no_personal_sources")
        : t("no_space_sources");
  const allowedKinds = {
    collections: resourceKinds?.collections ?? true,
    websites: resourceKinds?.websites ?? true,
    integrationKnowledge: resourceKinds?.integrationKnowledge ?? true
  };

  const currentSpaceId = space.id;
  const inOrigin = <T extends { space_id?: string | null }>(items: T[]) =>
    byOrigin(items, origin, currentSpaceId, orgSpaceId);

  const spaceKnowledge = {
    collections: allowedKinds.collections ? space.knowledge.groups.items : [],
    websites: allowedKinds.websites ? space.knowledge.websites.items : [],
    integrationKnowledge: allowedKinds.integrationKnowledge
      ? space.knowledge.integration_knowledge_list.items
      : []
  };
  const enabledModels = new Set(space.embedding_models.map((model) => model.id));

  const selectedCollections = allowedKinds.collections ? inOrigin(selections.collections) : [];
  const selectedWebsites = allowedKinds.websites ? inOrigin(selections.websites) : [];
  const selectedIntegration = allowedKinds.integrationKnowledge
    ? selectedIntegrationDisplay(
        inOrigin(selections.integrationKnowledge),
        inOrigin(spaceKnowledge.integrationKnowledge)
      )
    : [];

  // The Selector's search filters the options by name.
  const available = availableKnowledge(
    { knowledge: spaceKnowledge, embeddingModelIds: [...enabledModels] },
    selections
  );
  // Incompatible sections come back empty and drop out here; disabled-model
  // sections keep their items and show the "not enabled" note instead.
  const sections = available.sections
    .map((section) => ({
      ...section,
      collections: inOrigin(section.collections),
      websites: inOrigin(section.websites),
      integration: integrationOptions(
        inOrigin(section.integrationKnowledge),
        selections.integrationKnowledge
      )
    }))
    .filter(
      (section) =>
        section.collections.length + section.websites.length + section.integration.length > 0
    );

  function update(partial: Partial<KnowledgeSelections>) {
    onChange({ ...selections, ...partial });
  }

  function addIntegration(entry: IntegrationEntry) {
    const items = entry.type === "wrapper" ? entry.wrapper.items : [entry.knowledge];
    const have = new Set(selections.integrationKnowledge.map((item) => item.id));
    const toAdd = items.filter((item) => !have.has(item.id));
    if (toAdd.length > 0) {
      update({ integrationKnowledge: [...selections.integrationKnowledge, ...toAdd] });
    }
  }

  function removeIntegration(entry: IntegrationEntry) {
    const ids = new Set(
      (entry.type === "wrapper" ? entry.wrapper.items : [entry.knowledge]).map((item) => item.id)
    );
    update({
      integrationKnowledge: selections.integrationKnowledge.filter((item) => !ids.has(item.id))
    });
  }

  // Each option's value maps to what picking it adds.
  const additions = new Map<string, () => void>();
  const sectionOptions = sections.flatMap((section): SelectorOptionType[] => {
    let items: SelectorOptionData[];
    if (!section.isEnabled || !section.isCompatible) {
      // A note in the list, read out with the section; it cannot be picked.
      items = [
        {
          value: `note:${section.modelId}`,
          label: section.isEnabled
            ? t("sources_not_compatible")
            : t("section_not_enabled", { section: section.name }),
          disabled: true
        }
      ];
    } else {
      items = [
        ...section.collections.map((collection) => {
          const value = `group:${collection.id}`;
          additions.set(value, () =>
            update({ collections: [...selections.collections, collection] })
          );
          return {
            value,
            label: collection.name,
            icon: <Database aria-hidden="true" />,
            description:
              collection.metadata.num_info_blobs > 0
                ? t("space_files_count", { count: collection.metadata.num_info_blobs })
                : t("empty")
          };
        }),
        ...section.websites.map((website) => {
          const value = `website:${website.id}`;
          const pagesFailed = website.latest_crawl?.pages_failed ?? 0;
          additions.set(value, () => update({ websites: [...selections.websites, website] }));
          return {
            value,
            label: formatWebsiteName(website),
            icon: <Globe aria-hidden="true" />,
            description:
              pagesFailed > 0
                ? t("space_crawl_failed", {
                    items: t("space_pages_count", { count: pagesFailed })
                  })
                : undefined
          };
        }),
        ...section.integration.map((entry) => {
          additions.set(entry.key, () => addIntegration(entry));
          return {
            value: entry.key,
            label: entry.type === "wrapper" ? entry.wrapper.name : entry.knowledge.name,
            icon: (
              <VendorIcon
                type={
                  entry.type === "wrapper"
                    ? entry.wrapper.integration_type
                    : entry.knowledge.integration_type
                }
              />
            ),
            description: entry.type === "wrapper" ? String(entry.wrapper.items.length) : undefined
          };
        })
      ];
    }
    return available.showHeaders
      ? [{ type: "section" as const, title: section.name, options: items }]
      : items;
  });
  // Nothing to add says so as a note in the list: an empty listbox has no
  // options, which assistive tech cannot make sense of.
  const options: SelectorOptionType[] =
    sectionOptions.length > 0
      ? sectionOptions
      : [{ value: "note:empty", label: emptyLabel, disabled: true }];

  const hasSelection =
    selectedCollections.length + selectedWebsites.length + selectedIntegration.length > 0;

  return (
    <div className="flex flex-col gap-2">
      {hasSelection && (
        <div className="flex flex-col gap-2">
          {selectedCollections.map((collection) => (
            <SelectedKnowledgeRow
              key={`group:${collection.id}`}
              kind="collection"
              item={collection}
              modelEnabled={enabledModels.has(collection.embedding_model.id)}
              disabled={disabled}
              onRemove={() =>
                update({
                  collections: selections.collections.filter((item) => item.id !== collection.id)
                })
              }
            />
          ))}
          {selectedWebsites.map((website) => (
            <SelectedKnowledgeRow
              key={`website:${website.id}`}
              kind="website"
              item={website}
              modelEnabled={enabledModels.has(website.embedding_model.id)}
              disabled={disabled}
              onRemove={() =>
                update({ websites: selections.websites.filter((item) => item.id !== website.id) })
              }
            />
          ))}
          {selectedIntegration.map((entry) => (
            <SelectedRow
              key={entry.key}
              icon={
                <VendorIcon
                  type={
                    entry.type === "wrapper"
                      ? entry.wrapper.integration_type
                      : entry.knowledge.integration_type
                  }
                />
              }
              name={entry.type === "wrapper" ? entry.wrapper.name : entry.knowledge.name}
              modelEnabled={
                entry.type === "wrapper"
                  ? entry.wrapper.items.every((item) => enabledModels.has(item.embedding_model.id))
                  : enabledModels.has(entry.knowledge.embedding_model.id)
              }
              meta={integrationMeta(entry)}
              disabled={disabled}
              onRemove={() => removeIntegration(entry)}
            />
          ))}
        </div>
      )}

      <Selector
        label={addLabel}
        isLabelHidden
        placeholder={addLabel}
        startIcon={<Plus aria-hidden="true" />}
        options={options}
        // Holds no value: a pick adds that source and the trigger reads "add" again.
        value={undefined}
        onChange={(value) => additions.get(value)?.()}
        hasSearch
        searchPlaceholder={t("knowledge_filter_label")}
        isDisabled={disabled}
        width="100%"
      />
    </div>
  );
}

export type { IntegrationKnowledge };
