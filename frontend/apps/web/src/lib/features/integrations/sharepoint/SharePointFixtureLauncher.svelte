<script lang="ts">
  import { writable } from "svelte/store";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import SharepointImportDialog from "./SharepointImportDialog.svelte";
  import {
    createSharePointFixtureIntegration,
    type SharePointFixtureAuthType
  } from "./fixtureMode";

  type Props = {
    authType: SharePointFixtureAuthType;
  };

  const { authType }: Props = $props();
  const fixtureIntegration = $derived(createSharePointFixtureIntegration(authType));
  const showFixtureDialog = writable(false);

  function closeFixtureDialog() {
    $showFixtureDialog = false;
  }
</script>

<Button variant="outline" onclick={() => ($showFixtureDialog = true)}>
  {m.sharepoint_fixture_open()}
</Button>

<SharepointImportDialog
  goBack={closeFixtureDialog}
  openController={showFixtureDialog}
  integration={fixtureIntegration}
  fixtureScenario="representative"
></SharepointImportDialog>
