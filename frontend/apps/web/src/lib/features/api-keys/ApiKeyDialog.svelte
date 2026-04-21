<script lang="ts">
  import type { ApiKeyScopeType, ApiKeyV2 } from "@intric/intric-js";
  import CreateApiKeyDialog from "./CreateApiKeyDialog.svelte";

  type DialogMode = "create" | "edit" | "view";

  let {
    mode = "create",
    apiKey,
    open = $bindable(false),
    onCreated,
    onChanged,
    lockedScopeType,
    lockedScopeId,
    lockedScopeName,
    triggerVariant = "primary"
  } = $props<{
    mode?: DialogMode;
    apiKey?: ApiKeyV2;
    open?: boolean;
    onCreated?: () => void;
    onChanged?: () => void;
    lockedScopeType?: ApiKeyScopeType;
    lockedScopeId?: string;
    lockedScopeName?: string;
    triggerVariant?: "primary" | "outlined";
  }>();
</script>

<CreateApiKeyDialog
  {mode}
  {apiKey}
  bind:open
  {onCreated}
  {onChanged}
  {lockedScopeType}
  {lockedScopeId}
  {lockedScopeName}
  {triggerVariant}
/>
