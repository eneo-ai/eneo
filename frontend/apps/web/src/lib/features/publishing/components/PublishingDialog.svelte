<script lang="ts">
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import type { PublishableResource, PublishableResourceEndpoints } from "../Publisher";
  import { writable } from "svelte/store";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getExpiringKeysStore } from "$lib/features/api-keys/expiringKeysStore";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  const { refreshCurrentSpace } = getSpacesManager();
  const { forceRefresh: refreshExpiringKeys } = getExpiringKeysStore();

  /** Pass in a publishable resource. Its state should be maintained from the outside */
  export let resource: PublishableResource;
  export let endpoints: PublishableResourceEndpoints;
  /** A store to control the dialogs visibility*/
  export let openController = writable(false);
  /** Should the dialog await the resource update before colsing? */
  export let awaitUpdate = false;
  /** Will render a dialog trigger buttone */
  export let includeTrigger = false;
  /** Should the included trigger be disabled? */
  export let isDisabled = false;
  /** Optional resource kind to provide contextual publish UX hints */
  export let resourceKind: "assistant" | "app" | "resource" = "resource";

  let isLoading = false;
  async function toggleState() {
    try {
      const fn = resource.published ? endpoints.unpublish : endpoints.publish;
      if (awaitUpdate) {
        isLoading = true;
        await fn(resource);
        refreshCurrentSpace();
        await refreshExpiringKeys();
        isLoading = false;
      } else {
        fn(resource).then(() => {
          refreshCurrentSpace();
          void refreshExpiringKeys();
        });
      }
      $openController = false;
    } catch (e) {
      toastError(e, m.could_not_change_status({ name: resource.name }));
      console.error(e);
    }
  }

  function updateStrings(resource: PublishableResource) {
    if (resource.published) {
      return {
        action: m.unpublish(),
        description: m.do_you_really_want_to_unpublish({ name: resource.name })
      };
    } else {
      return {
        action: m.publish(),
        description: m.do_you_want_to_publish({ name: resource.name })
      };
    }
  }

  $: strings = updateStrings(resource);
  $: autoFollowHint =
    !resource.published && resourceKind === "assistant"
      ? m.api_keys_notifications_publish_assistant_hint()
      : !resource.published && resourceKind === "app"
        ? m.api_keys_notifications_publish_app_hint()
        : null;
</script>

<Dialog.Root bind:open={$openController}>
  {#if includeTrigger}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button
          {...props}
          variant={resource.published ? "destructive" : "default"}
          class={[
            "w-24 transition-colors duration-300",
            !resource.published && "bg-positive-default hover:bg-positive-stronger"
          ]}
          disabled={isDisabled}>{strings.action}</Button
        >
      {/snippet}
    </Dialog.Trigger>
  {/if}

  <Dialog.Content class={dialogLayout.content()} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{strings.action} {resource.name}</Dialog.Title>
      <Dialog.Description>{strings.description}</Dialog.Description>
    </Dialog.Header>

    {#if autoFollowHint}
      <div class={dialogLayout.body}>
        <p class="text-muted text-xs">{autoFollowHint}</p>
      </div>
    {/if}

    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
      <Button variant={resource.published ? "destructive" : "default"} onclick={toggleState}
        >{isLoading ? m.loading() : strings.action}</Button
      >
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
