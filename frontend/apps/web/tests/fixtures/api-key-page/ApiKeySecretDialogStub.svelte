<script lang="ts">
  let {
    open = false,
    secret = null,
    source = "created"
  } = $props<{
    open?: boolean;
    secret?: string | null;
    source?: "created" | "rotated";
  }>();
</script>

{#if open}
  <div data-testid="api-key-secret-dialog">{source}: {secret}</div>
{/if}
