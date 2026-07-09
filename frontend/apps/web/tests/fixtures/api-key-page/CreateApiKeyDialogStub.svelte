<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  let { onCreated } = $props<{
    onCreated?: () => void;
  }>();
</script>

<button type="button" onclick={() => onCreated?.()}>{m.api_keys_create()}</button>
