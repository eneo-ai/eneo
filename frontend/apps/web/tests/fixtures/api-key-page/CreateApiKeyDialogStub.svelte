<script lang="ts">
  let { onCreated } = $props<{
    onCreated?: () => void;
  }>();
</script>

<button type="button" onclick={() => onCreated?.()}>Create API key</button>
