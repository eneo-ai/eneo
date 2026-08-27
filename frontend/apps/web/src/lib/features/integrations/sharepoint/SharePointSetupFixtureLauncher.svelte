<script lang="ts">
  import { writable } from "svelte/store";
  import { FlaskConical } from "lucide-svelte";
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";
  import SharePointAppConfigDialog from "./SharePointAppConfigDialog.svelte";
  import SharePointAppDeleteDialog from "./SharePointAppDeleteDialog.svelte";

  const showConfigDialog = writable(false);
  const showDeleteDialog = writable(false);
</script>

<Tooltip.Provider>
  <Tooltip.Root>
    <Tooltip.Trigger
      class={buttonVariants({ variant: "outline", size: "icon" })}
      aria-label={m.sharepoint_setup_fixture_open()}
      onclick={() => ($showConfigDialog = true)}
    >
      <FlaskConical aria-hidden="true" />
    </Tooltip.Trigger>
    <Tooltip.Content>{m.sharepoint_setup_fixture_open()}</Tooltip.Content>
  </Tooltip.Root>
</Tooltip.Provider>

<SharePointAppConfigDialog
  openController={showConfigDialog}
  fixtureScenario="fresh"
  onDeleteRequested={() => ($showDeleteDialog = true)}
/>
<SharePointAppDeleteDialog openController={showDeleteDialog} simulate />
