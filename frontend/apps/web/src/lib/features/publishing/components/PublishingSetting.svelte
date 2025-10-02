<script lang="ts">
  import { Tooltip } from "@intric/ui";
  import type { PublishableResource, PublishableResourceEndpoints } from "../Publisher";
  import PublishingDialog from "./PublishingDialog.svelte";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import PublishingStatusChip from "./PublishingStatusChip.svelte";
  import { m } from "$lib/paraglide/messages";

  export let resource: PublishableResource;
  export let endpoints: PublishableResourceEndpoints;
  export let hasUnsavedChanges: boolean;

  let isLoading = false;

  const wrappedPublisher = {
    publish: async () => {
      isLoading = true;
      try {
        resource = await endpoints.publish(resource);
      } catch (e) {
        alert(m.could_not_publish({ name: resource.name }));
      }
      isLoading = false;
      return resource;
    },
    unpublish: async () => {
      isLoading = true;
      try {
        resource = await endpoints.unpublish(resource);
      } catch (e) {
        alert(m.could_not_unpublish({ name: resource.name }));
      }
      isLoading = false;
      return resource;
    }
  };
</script>

<div class="border-default flex h-14 items-center justify-between gap-4 border-b p-2">
  <div class="text-muted flex flex-grow items-center justify-center gap-2">
    {#if isLoading}
      <IconLoadingSpinner class="ml-2 animate-spin"></IconLoadingSpinner>
      <span>{m.updating()}</span>
    {:else}
      <PublishingStatusChip {resource}></PublishingStatusChip>
    {/if}
  </div>
  <Tooltip
    text={hasUnsavedChanges
      ? m.save_or_discard_changes_before_updating()
      : undefined}
  >
    <PublishingDialog
      {resource}
      endpoints={wrappedPublisher}
      includeTrigger
      isDisabled={hasUnsavedChanges}
    ></PublishingDialog>
  </Tooltip>
</div>
