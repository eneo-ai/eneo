<script lang="ts">
  let { keys = [], loading = false } = $props<{
    keys?: unknown[];
    loading?: boolean;
  }>();
</script>

<div data-testid="api-key-table">{loading ? "loading" : `${keys.length} keys`}</div>
