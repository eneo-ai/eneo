"use client";

import { useQuery } from "@tanstack/react-query";
import { Database, Globe, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { browserApi } from "@/lib/api/browser";
import { spacesListQueryOptions } from "@/features/spaces/space";
import { useSpace } from "@/features/spaces/use-space";
import { VendorIcon } from "../integrations/vendor";
import { formatWebsiteName, type IntegrationKnowledge } from "../knowledge";
import {
  availableKnowledge,
  byOrigin,
  integrationOptions,
  selectedIntegrationDisplay,
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
        {!modelEnabled && (
          <span className="text-red-600 dark:text-red-400"> ({t("model_disabled")})</span>
        )}
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

/**
 * Selected knowledge for one origin (personal or organization) plus an
 * add-combobox sectioned per embedding model. Ported from SelectKnowledge +
 * KnowledgeCombobox; the expandable per-item blob list is deferred.
 */
export function KnowledgePicker({
  origin,
  selections,
  onChange,
  disabled
}: {
  origin: KnowledgeOrigin;
  selections: KnowledgeSelections;
  onChange: (next: KnowledgeSelections) => void;
  disabled?: boolean;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const orgSpaceId = useOrgSpaceId();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");

  const currentSpaceId = space.id;
  const inOrigin = <T extends { space_id?: string | null }>(items: T[]) =>
    byOrigin(items, origin, currentSpaceId, orgSpaceId);

  const spaceKnowledge = {
    collections: space.knowledge.groups.items,
    websites: space.knowledge.websites.items,
    integrationKnowledge: space.knowledge.integration_knowledge_list.items
  };
  const enabledModels = new Set(space.embedding_models.map((model) => model.id));

  const selectedCollections = inOrigin(selections.collections);
  const selectedWebsites = inOrigin(selections.websites);
  const selectedIntegration = selectedIntegrationDisplay(
    inOrigin(selections.integrationKnowledge),
    inOrigin(spaceKnowledge.integrationKnowledge)
  );

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
            <SelectedRow
              key={`group:${collection.id}`}
              icon={<Database className="text-muted-foreground size-4 shrink-0" />}
              name={collection.name}
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
            <SelectedRow
              key={`website:${website.id}`}
              icon={<Globe className="text-muted-foreground size-4 shrink-0" />}
              name={formatWebsiteName(website)}
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
                                <Badge
                                  variant="outline"
                                  className="font-normal text-red-600 dark:text-red-400"
                                >
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
