<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import type { StorageSpaceList, StorageUsageSummary } from "@intric/intric-js";
  import StorageOverviewBar from "./StorageOverviewBar.svelte";
  import StorageTable from "./StorageTable.svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    spaces: StorageSpaceList[];
    storageStats: StorageUsageSummary;
  };

  const { spaces, storageStats }: Props = $props();
</script>

<Settings.Page>
  <Settings.Group title={m.overview()}>
    <StorageOverviewBar {storageStats}></StorageOverviewBar>
  </Settings.Group>
  <Settings.Group title={m.details()}>
    <Settings.Row
      title={m.public_spaces()}
      description={m.public_spaces_storage_description()}
      fullWidth
    >
      <StorageTable {spaces} />
    </Settings.Row>
  </Settings.Group>
</Settings.Page>
