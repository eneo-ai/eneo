<script lang="ts">
  let { items = [] } = $props<{ items?: unknown[] }>();
</script>

<div data-testid="expiring-keys-banner">{items.length}</div>
