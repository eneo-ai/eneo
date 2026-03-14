<script lang="ts">
  import { Button, Dialog } from "@intric/ui";
  import type { PublishableResource, PublishableResourceEndpoints } from "../Publisher";
  import { writable } from "svelte/store";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getExpiringKeysStore } from "$lib/features/api-keys/expiringKeysStore";
  import { m } from "$lib/paraglide/messages";

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
      alert(m.could_not_change_status({ name: resource.name }));
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

<Dialog.Root {openController}>
  {#if includeTrigger}
    <Dialog.Trigger let:trigger asFragment>
      <Button
        variant={resource.published ? "destructive" : "positive"}
        is={trigger}
        class="w-24 transition-colors duration-300"
        disabled={isDisabled}>{strings.action}</Button
      >
    </Dialog.Trigger>
  {/if}

  <Dialog.Content>
    <Dialog.Title>{strings.action} {resource.name}</Dialog.Title>

    <Dialog.Description>{strings.description}</Dialog.Description>
    {#if autoFollowHint}
      <p class="mt-2 text-xs text-muted">{autoFollowHint}</p>
    {/if}

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant={resource.published ? "destructive" : "primary"} on:click={toggleState}
        >{isLoading ? m.loading() : strings.action}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
