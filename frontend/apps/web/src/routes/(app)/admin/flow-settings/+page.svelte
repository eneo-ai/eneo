<script lang="ts">
  import FlowRetentionOnlyView from "./FlowRetentionOnlyView.svelte";
  import FlowSettingsAdminView from "./FlowSettingsAdminView.svelte";
  import { adminSettingsData } from "./flowSettingsData";

  let { data } = $props();

  // Admins get every tab; a retention-only role gets the retention tab alone.
  const adminData = $derived(adminSettingsData(data));
</script>

{#if adminData}
  <FlowSettingsAdminView data={adminData} />
{:else}
  <FlowRetentionOnlyView {data} />
{/if}
