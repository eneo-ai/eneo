"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Database, FileText, Globe, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { BlobPreviewDialog } from "@/features/knowledge/blobs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { browserApi } from "@/lib/api/browser";
import { formatBytes } from "@/lib/format";
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

function SelectedRow({
  icon,
  name,
  modelEnabled,
  badges,
  onRemove,
  disabled
}: {
  icon: React.ReactNode;
  name: string;
  modelEnabled: boolean;
  badges?: React.ReactNode;
  onRemove: () => void;
  disabled?: boolean;
}) {
  const t = useTranslations();
  return (
    <div className="flex h-12 w-full items-center gap-2 rounded-xl border px-3">
      {icon}
      <span className="min-w-0 flex-1 truncate text-sm" title={name}>
        {name}
        {!modelEnabled && <span className="text-destructive"> ({t("model_disabled")})</span>}
      </span>
      {badges}
      <Button
        variant="ghost"
        size="icon"
        aria-label={t("delete")}
        disabled={disabled}
        onClick={onRemove}
      >
        <X className="size-4" />
      </Button>
    </div>
  );
}

function IntegrationBadges({ entry }: { entry: IntegrationEntry }) {
  if (entry.type === "single") return null;
  return (
    <Badge variant="outline" className="text-muted-foreground shrink-0 font-normal">
      {entry.wrapper.items.length}
    </Badge>
  );
}

const BLOBS_PAGE_SIZE = 10;

function blobTitle(blob: InfoBlob): string {
  return blob.metadata.title ?? blob.metadata.url ?? blob.id;
}

function SelectedKnowledgeBlobRow({ blob }: { blob: InfoBlob }) {
  const [showPreview, setShowPreview] = useState(false);

  return (
    <li>
      <button
        type="button"
        className="hover:bg-muted/60 focus-visible:ring-ring flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none"
        onClick={() => setShowPreview(true)}
      >
        <span className="flex min-w-0 items-center gap-2">
          <FileText className="text-muted-foreground size-4 shrink-0" />
          <span className="truncate">{blobTitle(blob)}</span>
        </span>
        {blob.metadata.size ? (
          <span className="text-muted-foreground shrink-0 text-xs">
            {formatBytes(blob.metadata.size)}
          </span>
        ) : null}
      </button>
      {showPreview ? (
        <BlobPreviewDialog blob={blob} open={showPreview} onOpenChange={setShowPreview} />
      ) : null}
    </li>
  );
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
  const [page, setPage] = useState(0);

  if (loading) {
    return <div className="text-muted-foreground px-3 py-3 text-sm">{t("loading")}</div>;
  }
  if (error) {
    return (
      <div className="text-destructive px-3 py-3 text-sm">
        {t("attachment_error_loading_content")}
      </div>
    );
  }
  if (!blobs || blobs.length === 0) {
    return <div className="text-muted-foreground px-3 py-3 text-sm">{emptyMessage}</div>;
  }

  const pageCount = Math.max(1, Math.ceil(blobs.length / BLOBS_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = blobs.slice(currentPage * BLOBS_PAGE_SIZE, (currentPage + 1) * BLOBS_PAGE_SIZE);

  return (
    <div className="border-t px-2 py-2">
      <ul className="flex flex-col gap-0.5">
        {visible.map((blob) => (
          <SelectedKnowledgeBlobRow key={blob.id} blob={blob} />
        ))}
      </ul>
      {pageCount > 1 ? (
        <div className="mt-2 flex items-center justify-end gap-2 border-t pt-2 text-sm">
          <span className="text-muted-foreground">
            {currentPage + 1} / {pageCount}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={currentPage === 0}
            onClick={() => setPage(currentPage - 1)}
          >
            {t("previous")}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={currentPage >= pageCount - 1}
            onClick={() => setPage(currentPage + 1)}
          >
            {t("next")}
          </Button>
        </div>
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
  const expandable = isCollection
    ? collectionInfoBlobCount(item) > 0
    : websiteIndexedResultCount(item) > 0;
  const blobsQuery = useQuery({
    ...(isCollection
      ? collectionBlobsQueryOptions(browserApi, item.id)
      : websiteBlobsQueryOptions(browserApi, item.id)),
    enabled: expanded && expandable
  });

  return (
    <Collapsible open={expanded} onOpenChange={setExpanded} className="rounded-xl border">
      <div
        className={`flex min-h-12 w-full items-center gap-2 px-3 ${
          pagesFailed > 0 ? "border-destructive bg-destructive/5 border-l-4" : ""
        }`}
      >
        {expandable ? (
          <CollapsibleTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={expanded ? t("aria_collapse") : t("aria_expand")}
              className="size-7 shrink-0"
            >
              {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
            </Button>
          </CollapsibleTrigger>
        ) : (
          <span className="size-7 shrink-0" />
        )}
        {isCollection ? (
          <Database className="text-muted-foreground size-4 shrink-0" />
        ) : (
          <Globe className="text-muted-foreground size-4 shrink-0" />
        )}
        <CollapsibleTrigger
          type="button"
          disabled={!expandable}
          className="min-w-0 flex-1 rounded-md text-left text-sm font-medium hover:underline disabled:hover:no-underline"
        >
          <span className="truncate" title={title}>
            {title}
            {!modelEnabled ? (
              <span className="text-destructive"> ({t("model_disabled")})</span>
            ) : null}
          </span>
        </CollapsibleTrigger>
        {!isCollection && pagesFailed > 0 ? (
          <Badge variant="outline" className="text-destructive shrink-0 font-normal">
            {t("pages_failed", { count: String(pagesFailed) })}
          </Badge>
        ) : null}
        {!isCollection && pagesCrawled > 0 ? (
          <Badge variant="outline" className="text-muted-foreground shrink-0 font-normal">
            {t("pageCount", { count: String(pagesCrawled) })}
          </Badge>
        ) : null}
        {isCollection ? (
          <Badge variant="outline" className="text-muted-foreground shrink-0 font-normal">
            {indexedCount > 0 ? `${indexedCount} ${t("resource_files")}` : t("empty")}
          </Badge>
        ) : null}
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("delete")}
          disabled={disabled}
          onClick={onRemove}
        >
          <X className="size-4" />
        </Button>
      </div>
      <CollapsibleContent>
        <SelectedKnowledgeBlobList
          blobs={blobsQuery.data}
          loading={blobsQuery.isPending && expanded}
          error={blobsQuery.isError}
          emptyMessage={isCollection ? t("knowledge_no_files_found") : t("noPagesFound")}
        />
      </CollapsibleContent>
    </Collapsible>
  );
}

/**
 * Selected knowledge for one origin (personal or organization) plus an
 * add-combobox sectioned per embedding model. Ported from SelectKnowledge +
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
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
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

  const available = availableKnowledge(
    { knowledge: spaceKnowledge, embeddingModelIds: [...enabledModels] },
    selections,
    filter
  );
  // Incompatible sections come back empty and drop out here; disabled-model
  // sections keep their items and render the "not enabled" message instead.
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

  function selectAndClose(action: () => void) {
    action();
    setOpen(false);
    setFilter("");
  }

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
              badges={<IntegrationBadges entry={entry} />}
              disabled={disabled}
              onRemove={() => removeIntegration(entry)}
            />
          ))}
        </div>
      )}

      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            disabled={disabled}
            className="text-muted-foreground hover:text-foreground hover:bg-muted/50 flex h-12 w-full items-center justify-center gap-2 rounded-xl border border-dashed text-sm font-medium transition-colors disabled:opacity-50"
          >
            <Plus className="size-4" />
            {origin === "personal" ? t("add_knowledge_personal") : t("add_knowledge_organization")}
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-(--radix-popover-trigger-width) min-w-80 p-0">
          <Command shouldFilter={false}>
            <CommandInput
              value={filter}
              onValueChange={setFilter}
              placeholder={t("knowledge_filter_label")}
            />
            <CommandList>
              {sections.length === 0 ? (
                <div className="text-muted-foreground flex min-h-16 items-center justify-center px-4 py-6 text-center text-sm">
                  {origin === "personal" ? t("no_personal_sources") : t("no_organization_sources")}
                </div>
              ) : (
                sections.map((section) => (
                  <CommandGroup
                    key={section.modelId}
                    heading={available.showHeaders ? section.name : undefined}
                  >
                    {!section.isEnabled ? (
                      <p className="text-muted-foreground px-4 py-3 text-sm">
                        {t("section_not_enabled", { section: section.name })}
                      </p>
                    ) : !section.isCompatible ? (
                      <p className="text-muted-foreground px-4 py-3 text-sm">
                        {t("sources_not_compatible")}
                      </p>
                    ) : (
                      <>
                        {section.collections.map((collection) => (
                          <CommandItem
                            key={`group:${collection.id}`}
                            value={`group:${collection.id}`}
                            onSelect={() =>
                              selectAndClose(() =>
                                update({ collections: [...selections.collections, collection] })
                              )
                            }
                          >
                            <Database className="size-4 shrink-0" />
                            <span className="flex-1 truncate">{collection.name}</span>
                            <Badge variant="outline" className="text-muted-foreground font-normal">
                              {collection.metadata.num_info_blobs > 0
                                ? `${collection.metadata.num_info_blobs} ${t("resource_files")}`
                                : t("empty")}
                            </Badge>
                          </CommandItem>
                        ))}
                        {section.websites.map((website) => {
                          const pagesFailed = website.latest_crawl?.pages_failed ?? 0;
                          return (
                            <CommandItem
                              key={`website:${website.id}`}
                              value={`website:${website.id}`}
                              onSelect={() =>
                                selectAndClose(() =>
                                  update({ websites: [...selections.websites, website] })
                                )
                              }
                            >
                              <Globe className="size-4 shrink-0" />
                              <span className="flex-1 truncate">{formatWebsiteName(website)}</span>
                              {pagesFailed > 0 && (
                                <Badge variant="outline" className="text-destructive font-normal">
                                  {t("pages_failed", { count: String(pagesFailed) })}
                                </Badge>
                              )}
                            </CommandItem>
                          );
                        })}
                        {section.integration.map((entry) => (
                          <CommandItem
                            key={entry.key}
                            value={entry.key}
                            onSelect={() => selectAndClose(() => addIntegration(entry))}
                          >
                            <VendorIcon
                              type={
                                entry.type === "wrapper"
                                  ? entry.wrapper.integration_type
                                  : entry.knowledge.integration_type
                              }
                            />
                            <span className="flex-1 truncate">
                              {entry.type === "wrapper" ? entry.wrapper.name : entry.knowledge.name}
                            </span>
                            <IntegrationBadges entry={entry} />
                          </CommandItem>
                        ))}
                      </>
                    )}
                  </CommandGroup>
                ))
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}

export type { IntegrationKnowledge };
