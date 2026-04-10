<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import ApiKeyActionMenu from "$lib/features/api-keys/ApiKeyActionMenu.svelte";
  import ApiKeyDialog from "$lib/features/api-keys/ApiKeyDialog.svelte";

  let {
    apiKey,
    onChanged,
    onSecret,
    isFollowed = false,
    isFollowedViaScope = false,
    onFollowChanged
  } = $props<{
    apiKey: ApiKeyV2;
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
    isFollowed?: boolean;
    isFollowedViaScope?: boolean;
    onFollowChanged?: () => void | Promise<void>;
  }>();

  let showViewDialog = $state(false);
</script>

<ApiKeyActionMenu
  {apiKey}
  mode="user"
  {onChanged}
  {onSecret}
  {isFollowed}
  {isFollowedViaScope}
  {onFollowChanged}
  onViewRequested={() => {
    showViewDialog = true;
  }}
/>

<ApiKeyDialog mode="view" {apiKey} bind:open={showViewDialog} />
