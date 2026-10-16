<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { initSpacesManager } from "$lib/features/spaces/SpacesManager.js";
  import ImportCompletionToasts from "$lib/features/integrations/components/ImportCompletionToasts.svelte";

  export let data;

  initSpacesManager(data);
</script>

<ImportCompletionToasts />
<slot />
