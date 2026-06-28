<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@eneo/eneo-js";
  import ApiKeyActionMenu from "$lib/features/api-keys/ApiKeyActionMenu.svelte";
  import ApiKeyDialog from "$lib/features/api-keys/ApiKeyDialog.svelte";

  let {
    apiKey,
    onChanged,
    onSecret,
    isFollowed = false,
    isFollowedViaScope = false,
    onFollowChanged,
    currentUserId = undefined
  } = $props<{
    apiKey: ApiKeyV2;
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
    isFollowed?: boolean;
    isFollowedViaScope?: boolean;
    onFollowChanged?: () => void | Promise<void>;
    currentUserId?: string;
  }>();

  let showViewDialog = $state(false);
  let showEditDialog = $state(false);
</script>

<ApiKeyActionMenu
  {apiKey}
  mode="user"
  {onChanged}
  {onSecret}
  {isFollowed}
  {isFollowedViaScope}
  {onFollowChanged}
  {currentUserId}
  onEditRequested={() => {
    showEditDialog = true;
  }}
  onViewRequested={() => {
    showViewDialog = true;
  }}
/>

<ApiKeyDialog mode="edit" {apiKey} bind:open={showEditDialog} {onChanged} />
<ApiKeyDialog mode="view" {apiKey} bind:open={showViewDialog} />
