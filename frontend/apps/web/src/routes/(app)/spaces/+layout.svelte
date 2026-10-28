<!--
    Copyright (c) 2024 Sundsvalls Kommun
-->

<script lang="ts">
  import { initSpacesManager } from "$lib/features/spaces/SpacesManager.js";
  import ImportCompletionToasts from "$lib/features/integrations/components/ImportCompletionToasts.svelte";
  import QueuedSyncWatcher from "$lib/features/integrations/components/QueuedSyncWatcher.svelte";

  export let data;

  initSpacesManager(data);
</script>

<ImportCompletionToasts />
<QueuedSyncWatcher />
<slot />
