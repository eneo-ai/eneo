<script lang="ts">
  import type { GroupSparse, IntegrationKnowledge, WebsiteSparse } from "@eneo/eneo-js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import { partitionByOrigin, type KnowledgeOrigin } from "./knowledgeOrigin";
  import { getSelectedIntegrationDisplay, type IntegrationEntry } from "./knowledgeIntegration";
  import SelectedKnowledgeItem from "./SelectedKnowledgeItem.svelte";
  import SelectedIntegrationItem from "./SelectedIntegrationItem.svelte";
  import KnowledgeCombobox from "./KnowledgeCombobox.svelte";

  type Props = {
    /** Bind to enable selecting websites. */
    selectedWebsites?: WebsiteSparse[];
    /** Bind to enable selecting collections (aka groups). */
    selectedCollections?: GroupSparse[];
    /** Bind to enable selecting integration knowledge. */
    selectedIntegrationKnowledge?: IntegrationKnowledge[];
    /** Portal the dropdown to the body and lift its z-index when rendered inside a dialog. */
    inDialog?: boolean;
    /** The template wizard supplies its own heading; the assistant editor shows origin headings. */
    showHeadings?: boolean;
  };

  let {
    selectedWebsites = $bindable(),
    selectedCollections = $bindable(),
    selectedIntegrationKnowledge = $bindable(),
    inDialog = false,
    showHeadings = false
  }: Props = $props();

  const {
    state: { currentSpace, organizationSpaceId }
  } = getSpacesManager();

  const currentSpaceId = $derived($currentSpace?.id);
  const orgSpaceId = $derived($organizationSpaceId ?? undefined);
  const enabledModels = $derived($currentSpace.embedding_models.map((model) => model.id));
  const allIntegration = $derived($currentSpace?.knowledge?.integrationKnowledge ?? []);
  const integrationList = $derived(selectedIntegrationKnowledge ?? []);

  const allOrigins: KnowledgeOrigin[] = ["space", "organization"];
  const originLabels = $derived({
    space: m.knowledge(),
    organization: m.organization_knowledge()
  });
  const collectionsByOrigin = $derived(
    partitionByOrigin(selectedCollections ?? [], currentSpaceId, orgSpaceId)
  );
  const websitesByOrigin = $derived(
    partitionByOrigin(selectedWebsites ?? [], currentSpaceId, orgSpaceId)
  );
  const integrationByOrigin = $derived(
    partitionByOrigin(integrationList, currentSpaceId, orgSpaceId)
  );
  const availableIntegrationByOrigin = $derived(
    partitionByOrigin(allIntegration, currentSpaceId, orgSpaceId)
  );

  function addCollection(collection: GroupSparse) {
    if (!(selectedCollections ?? []).some((c) => c.id === collection.id)) {
      selectedCollections = [...(selectedCollections ?? []), collection];
    }
  }
  function addWebsite(website: WebsiteSparse) {
    if (!(selectedWebsites ?? []).some((w) => w.id === website.id)) {
      selectedWebsites = [...(selectedWebsites ?? []), website];
    }
  }
  function addIntegration(entry: IntegrationEntry) {
    const items = entry.type === "wrapper" ? entry.wrapper.items : [entry.knowledge];
    const have = new Set(integrationList.map((k) => k.id));
    const toAdd = items.filter((k) => !have.has(k.id));
    if (toAdd.length > 0) {
      selectedIntegrationKnowledge = [...integrationList, ...toAdd];
    }
  }
  function removeCollection(id: string) {
    selectedCollections = (selectedCollections ?? []).filter((c) => c.id !== id);
  }
  function removeWebsite(id: string) {
    selectedWebsites = (selectedWebsites ?? []).filter((w) => w.id !== id);
  }
  function removeIntegration(ids: string[]) {
    selectedIntegrationKnowledge = integrationList.filter((k) => !ids.includes(k.id));
  }
</script>

{#snippet selectedSection(
  collections: GroupSparse[],
  websites: WebsiteSparse[],
  integration: IntegrationEntry[]
)}
  <section class="mt-6 space-y-2">
    {#each collections as collection (`group:${collection.id}`)}
      <SelectedKnowledgeItem
        kind="collection"
        item={collection}
        modelEnabled={enabledModels.includes(collection.embedding_model.id)}
        onRemove={() => removeCollection(collection.id)}
      />
    {/each}
    {#each websites as website (`website:${website.id}`)}
      <SelectedKnowledgeItem
        kind="website"
        item={website}
        modelEnabled={enabledModels.includes(website.embedding_model.id)}
        onRemove={() => removeWebsite(website.id)}
      />
    {/each}
    {#each integration as entry (entry.key)}
      <SelectedIntegrationItem {entry} {enabledModels} onRemove={removeIntegration} />
    {/each}
  </section>
{/snippet}

{#snippet comboboxSection(origin: KnowledgeOrigin)}
  <section class="mt-4">
    <KnowledgeCombobox
      {origin}
      space={$currentSpace}
      {currentSpaceId}
      organizationSpaceId={orgSpaceId}
      {selectedCollections}
      {selectedWebsites}
      selectedIntegrationKnowledge={integrationList}
      {inDialog}
      onAddCollection={addCollection}
      onAddWebsite={addWebsite}
      onAddIntegration={addIntegration}
    />
  </section>
{/snippet}

{#each allOrigins as sectionOrigin (sectionOrigin)}
  {@const collections = collectionsByOrigin[sectionOrigin]}
  {@const websites = websitesByOrigin[sectionOrigin]}
  {@const integration = getSelectedIntegrationDisplay(
    integrationByOrigin[sectionOrigin],
    availableIntegrationByOrigin[sectionOrigin]
  )}
  <section aria-label={originLabels[sectionOrigin]} class="space-y-2">
    {#if showHeadings}
      <h4 class="font-medium">{originLabels[sectionOrigin]}</h4>
    {/if}
    {#if collections.length + websites.length + integration.length > 0}
      {@render selectedSection(collections, websites, integration)}
    {/if}
    {@render comboboxSection(sectionOrigin)}
  </section>
{/each}
