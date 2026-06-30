<script lang="ts">
  import type { GroupSparse, WebsiteSparse } from "@eneo/eneo-js";
  import { tick } from "svelte";
  import { IconPlus } from "@eneo/icons/plus";
  import { IconCollections } from "@eneo/icons/collections";
  import { IconWeb } from "@eneo/icons/web";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";
  import { formatWebsiteName } from "$lib/core/formatting/formatWebsiteName";
  import IntegrationVendorIcon from "$lib/features/integrations/components/IntegrationVendorIcon.svelte";
  import { getAvailableKnowledge } from "../../getAvailableKnowledge";
  import { partitionByOrigin } from "./knowledgeOrigin";
  import {
    dedupeById,
    getIntegrationKnowledgeOptions,
    type IntegrationEntry
  } from "./knowledgeIntegration";
  import WrapperBadges from "./WrapperBadges.svelte";

  type Space = Parameters<typeof getAvailableKnowledge>[0];

  type Props = {
    origin: "personal" | "organization";
    space: Space;
    currentSpaceId: string | undefined;
    selectedCollections: GroupSparse[] | undefined;
    selectedWebsites: WebsiteSparse[] | undefined;
    selectedIntegrationKnowledge: Space["knowledge"]["integrationKnowledge"] | undefined;
    inDialog?: boolean;
    aria?: Record<string, string>;
    onAddCollection: (collection: GroupSparse) => void;
    onAddWebsite: (website: WebsiteSparse) => void;
    onAddIntegration: (entry: IntegrationEntry) => void;
  };

  let {
    origin,
    space,
    currentSpaceId,
    selectedCollections,
    selectedWebsites,
    selectedIntegrationKnowledge,
    inDialog = false,
    aria = {},
    onAddCollection,
    onAddWebsite,
    onAddIntegration
  }: Props = $props();

  let open = $state(false);
  let filter = $state("");
  let triggerRef = $state<HTMLButtonElement | null>(null);

  const originBucket = $derived(origin === "personal" ? "personal" : "org");

  // getAvailableKnowledge already applies the text filter and embedding-model compatibility,
  // so the Command component must not filter again (shouldFilter={false} below).
  const available = $derived(
    getAvailableKnowledge(
      space,
      selectedWebsites,
      selectedCollections,
      selectedIntegrationKnowledge,
      filter
    )
  );

  /** The available sections, restricted to this combobox's origin (personal or organization). */
  const sections = $derived.by(() => {
    const out: Array<{
      key: string;
      name: string;
      isEnabled: boolean;
      isCompatible: boolean;
      groups: GroupSparse[];
      websites: WebsiteSparse[];
      integrationOptions: IntegrationEntry[];
    }> = [];

    for (const [modelId, section] of Object.entries(available.sections)) {
      const groups = partitionByOrigin(dedupeById(section.groups), currentSpaceId)[originBucket];
      const websites = partitionByOrigin(dedupeById(section.websites), currentSpaceId)[
        originBucket
      ];
      const integration = partitionByOrigin(
        dedupeById(section.integrationKnowledge),
        currentSpaceId
      )[originBucket];
      const integrationOptions = getIntegrationKnowledgeOptions(
        integration,
        selectedIntegrationKnowledge ?? []
      );

      if (groups.length + websites.length + integrationOptions.length === 0) continue;

      out.push({
        key: modelId,
        name: section.name,
        isEnabled: section.isEnabled,
        isCompatible: section.isCompatible,
        groups,
        websites,
        integrationOptions
      });
    }

    return out;
  });

  const triggerLabel = $derived(
    origin === "personal" ? m.add_knowledge_personal() : m.add_knowledge_organization()
  );
  const emptyLabel = $derived(
    origin === "personal" ? m.no_personal_sources() : m.no_organization_sources()
  );

  function selectAndClose(action: () => void) {
    action();
    open = false;
    filter = "";
    void tick().then(() => triggerRef?.focus());
  }
</script>

<Popover.Root bind:open>
  <Popover.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        {...aria}
        bind:this={triggerRef}
        type="button"
        class="border-default text-secondary hover:border-stronger hover:bg-hover-dimmer hover:text-primary focus-visible:ring-stronger flex h-12 w-full items-center justify-center gap-2 rounded-xl border border-dashed text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none"
      >
        <IconPlus class="size-4" />
        {triggerLabel}
      </button>
    {/snippet}
  </Popover.Trigger>

  <Popover.Content
    align="start"
    class={["w-(--bits-popover-anchor-width) min-w-[320px] p-0", inDialog && "z-[5000]"]}
  >
    <Command.Root shouldFilter={false}>
      <Command.Input bind:value={filter} placeholder={m.knowledge_filter_label()} />
      <Command.List>
        {#if sections.length === 0}
          <div
            class="text-muted flex min-h-16 items-center justify-center px-4 py-6 text-center text-sm"
          >
            {emptyLabel}
          </div>
        {:else}
          {#each sections as section (section.key)}
            <Command.Group heading={available.showHeaders ? section.name : undefined}>
              {#if !section.isEnabled}
                <p class="text-muted px-4 py-3 text-sm">
                  {m.section_not_enabled({ section: section.name })}
                </p>
              {:else if !section.isCompatible}
                <p class="text-muted px-4 py-3 text-sm">{m.sources_not_compatible()}</p>
              {:else}
                {#each section.groups as collection (`group:${collection.id}`)}
                  <Command.Item
                    value={`group:${collection.id}`}
                    onSelect={() => selectAndClose(() => onAddCollection(collection))}
                  >
                    <IconCollections class="shrink-0" />
                    <span class="flex-grow truncate">{collection.name}</span>
                    {#if collection.metadata.num_info_blobs > 0}
                      <Badge variant="outline" class="text-muted font-normal">
                        {collection.metadata.num_info_blobs}
                        {m.resource_files()}
                      </Badge>
                    {:else}
                      <Badge variant="outline" class="text-muted font-normal">{m.empty()}</Badge>
                    {/if}
                  </Command.Item>
                {/each}

                {#each section.websites as website (`website:${website.id}`)}
                  {@const pagesFailed = website.latest_crawl?.pages_failed ?? 0}
                  <Command.Item
                    value={`website:${website.id}`}
                    onSelect={() => selectAndClose(() => onAddWebsite(website))}
                    class={pagesFailed > 0
                      ? "border-negative-default bg-negative-default/10 border-l-4"
                      : undefined}
                  >
                    <IconWeb class="shrink-0" />
                    <span class="flex-grow truncate">{formatWebsiteName(website)}</span>
                    {#if pagesFailed > 0}
                      <Badge
                        variant="outline"
                        class="border-negative-default/30 text-negative-stronger"
                      >
                        {m.pages_failed({ count: pagesFailed })}
                      </Badge>
                    {/if}
                  </Command.Item>
                {/each}

                {#each section.integrationOptions as option (option.key)}
                  <Command.Item
                    value={option.key}
                    onSelect={() => selectAndClose(() => onAddIntegration(option))}
                  >
                    {#if option.type === "wrapper"}
                      <IntegrationVendorIcon size="sm" type={option.wrapper.integration_type} />
                      <span class="flex-grow truncate">{option.wrapper.name}</span>
                      <WrapperBadges items={option.wrapper.items} />
                    {:else}
                      <IntegrationVendorIcon size="sm" type={option.knowledge.integration_type} />
                      <span class="flex-grow truncate">{option.knowledge.name}</span>
                    {/if}
                  </Command.Item>
                {/each}
              {/if}
            </Command.Group>
          {/each}
        {/if}
      </Command.List>
    </Command.Root>
  </Popover.Content>
</Popover.Root>
