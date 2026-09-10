<script lang="ts">
  import { writable } from "svelte/store";
  import { FlaskConical } from "lucide-svelte";
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
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

<Tooltip.Provider>
  <Tooltip.Root>
    <Tooltip.Trigger
      class={buttonVariants({ variant: "outline", size: "icon" })}
      aria-label={m.sharepoint_fixture_open()}
      onclick={() => ($showFixtureDialog = true)}
    >
      <FlaskConical aria-hidden="true" />
    </Tooltip.Trigger>
    <Tooltip.Content>{m.sharepoint_fixture_open()}</Tooltip.Content>
  </Tooltip.Root>
</Tooltip.Provider>

<SharepointImportDialog
  goBack={closeFixtureDialog}
  openController={showFixtureDialog}
  integration={fixtureIntegration}
  fixtureScenario="representative"
></SharepointImportDialog>
