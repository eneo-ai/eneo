<script lang="ts">
  import type { GroupSparse, IntegrationKnowledge, WebsiteSparse } from "@intric/intric-js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { isOrgItem, isPersonalItem } from "./knowledgeOrigin";
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
    aria?: Record<string, string>;
    /** Portal the dropdown to the body and lift its z-index when rendered inside a dialog. */
    inDialog?: boolean;
    originMode?: "personal" | "organization" | "both";
  };

  let {
    selectedWebsites = $bindable(),
    selectedCollections = $bindable(),
    selectedIntegrationKnowledge = $bindable(),
    aria = { "aria-label": "Select knowledge" },
    inDialog = false,
    originMode = "both"
  }: Props = $props();

  const {
    state: { currentSpace, organizationSpaceId }
  } = getSpacesManager();

  const currentSpaceId = $derived($currentSpace?.id);
  const orgSpaceId = $derived($organizationSpaceId ?? undefined);
  const enabledModels = $derived($currentSpace.embedding_models.map((model) => model.id));
  const allIntegration = $derived($currentSpace?.knowledge?.integrationKnowledge ?? []);
  const integrationList = $derived(selectedIntegrationKnowledge ?? []);

  const showPersonal = $derived(originMode !== "organization");
  const showOrg = $derived(originMode !== "personal");

  const personalCollections = $derived(
    (selectedCollections ?? []).filter((c) => isPersonalItem(c, currentSpaceId))
  );
  const orgCollections = $derived(
    (selectedCollections ?? []).filter((c) => isOrgItem(c, currentSpaceId, orgSpaceId))
  );
  const personalWebsites = $derived(
    (selectedWebsites ?? []).filter((w) => isPersonalItem(w, currentSpaceId))
  );
  const orgWebsites = $derived(
    (selectedWebsites ?? []).filter((w) => isOrgItem(w, currentSpaceId, orgSpaceId))
  );
  const personalIntegration = $derived(
    getSelectedIntegrationDisplay(
      integrationList.filter((k) => isPersonalItem(k, currentSpaceId)),
      allIntegration.filter((k) => isPersonalItem(k, currentSpaceId))
    )
  );
  const orgIntegration = $derived(
    getSelectedIntegrationDisplay(
      integrationList.filter((k) => isOrgItem(k, currentSpaceId, orgSpaceId)),
      allIntegration.filter((k) => isOrgItem(k, currentSpaceId, orgSpaceId))
    )
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

{#snippet comboboxSection(origin: "personal" | "organization")}
  <section class="mt-4">
    <KnowledgeCombobox
      {origin}
      space={$currentSpace}
      {currentSpaceId}
      {selectedCollections}
      {selectedWebsites}
      selectedIntegrationKnowledge={integrationList}
      {inDialog}
      {aria}
      onAddCollection={addCollection}
      onAddWebsite={addWebsite}
      onAddIntegration={addIntegration}
    />
  </section>
{/snippet}

{#if showPersonal && personalCollections.length + personalWebsites.length + personalIntegration.length > 0}
  {@render selectedSection(personalCollections, personalWebsites, personalIntegration)}
{/if}
{#if showOrg && orgCollections.length + orgWebsites.length + orgIntegration.length > 0}
  {@render selectedSection(orgCollections, orgWebsites, orgIntegration)}
{/if}

{#if showPersonal}
  {@render comboboxSection("personal")}
{/if}
{#if showOrg}
  {@render comboboxSection("organization")}
{/if}
