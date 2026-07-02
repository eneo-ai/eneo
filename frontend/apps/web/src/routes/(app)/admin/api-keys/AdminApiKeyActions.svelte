<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@eneo/eneo-js";
  import ApiKeyActionMenu from "$lib/features/api-keys/ApiKeyActionMenu.svelte";
  import ApiKeyDialog from "$lib/features/api-keys/ApiKeyDialog.svelte";

  let { apiKey, onChanged, onSecret } = $props<{
    apiKey: ApiKeyV2;
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
  }>();

  let showEditDialog = $state(false);
  let showViewDialog = $state(false);
</script>

<ApiKeyActionMenu
  {apiKey}
  mode="admin"
  {onChanged}
  {onSecret}
  onEditRequested={() => {
    showEditDialog = true;
  }}
  onViewRequested={() => {
    showViewDialog = true;
  }}
/>

<ApiKeyDialog mode="edit" scope="admin" {apiKey} bind:open={showEditDialog} {onChanged} />
<ApiKeyDialog mode="view" {apiKey} bind:open={showViewDialog} />
