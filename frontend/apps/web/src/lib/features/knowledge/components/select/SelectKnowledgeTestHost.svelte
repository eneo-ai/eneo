<script lang="ts">
  import { untrack } from "svelte";
  import {
    createEneo,
    type GroupSparse,
    type IntegrationKnowledge,
    type Space,
    type WebsiteSparse
  } from "@eneo/eneo-js";
  import { initEneo } from "$lib/core/Eneo";
  import { initSpacesManager } from "$lib/features/spaces/SpacesManager";
  import SelectKnowledge from "./SelectKnowledge.svelte";

  let {
    space,
    initialCollections = [],
    initialWebsites = [],
    initialIntegrationKnowledge = [],
    showHeadings = true
  }: {
    space: Space;
    initialCollections?: GroupSparse[];
    initialWebsites?: WebsiteSparse[];
    initialIntegrationKnowledge?: IntegrationKnowledge[];
    showHeadings?: boolean;
  } = $props();

  const eneo = createEneo({
    baseUrl: "https://eneo.invalid",
    fetch: async () => {
      throw new Error("Knowledge selection must not request the backend");
    }
  });
  untrack(() => {
    initEneo({ eneo });
    // A regular user has no membership in the organization space.
    initSpacesManager({ currentSpace: space, spaces: [], eneo });
  });

  let selectedCollections = $state(untrack(() => [...initialCollections]));
  let selectedWebsites = $state(untrack(() => [...initialWebsites]));
  let selectedIntegrationKnowledge = $state(untrack(() => [...initialIntegrationKnowledge]));
</script>

<SelectKnowledge
  {showHeadings}
  bind:selectedCollections
  bind:selectedWebsites
  bind:selectedIntegrationKnowledge
/>
<output data-testid="knowledge-selection"
  >{JSON.stringify({
    collections: selectedCollections.map((item) => item.id),
    websites: selectedWebsites.map((item) => item.id),
    integrations: selectedIntegrationKnowledge.map((item) => item.id)
  })}</output
>
