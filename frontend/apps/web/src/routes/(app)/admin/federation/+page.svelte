<script lang="ts">
  import { invalidate } from "$app/navigation";
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import { Page, Settings } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { docsUrl } from "$lib/core/docs";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import FederationForm from "./FederationForm.svelte";

  let { data } = $props();

  // When a save finds the settings gone, the panel that replaces the form takes focus, so a
  // keyboard user is not left on the page body. On a first visit focus stays where it is.
  let formShown = false;
  const markFormShown = () => {
    formShown = true;
  };
  const focusIfReplacingForm = (panel: HTMLElement) => {
    if (formShown) panel.focus();
  };
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.federation_admin_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.federation_admin_title()} tour="admin-federation" />
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <p class="text-muted mb-8 max-w-2xl text-sm">{m.federation_admin_description()}</p>

      {#await data.federation}
        <!-- The operator's settings, then the form. -->
        <div class="flex flex-col gap-8" role="status" aria-label={m.federation_admin_loading()}>
          <Skeleton class="h-32 w-full max-w-3xl" />
          <Skeleton class="h-80 w-full max-w-2xl" />
        </div>
      {:then state}
        {#if state.kind === "ready"}
          <div {@attach markFormShown}>
            <FederationForm view={state.view} />
          </div>
        {:else if state.kind === "error"}
          <Alert.Root variant="destructive">
            <CircleAlert />
            <Alert.Title>{m.federation_admin_load_error()}</Alert.Title>
            <Alert.Description>
              <Button
                size="sm"
                variant="outline"
                class="mt-2"
                onclick={() => invalidate("admin:federation")}
              >
                {m.retry()}
              </Button>
            </Alert.Description>
          </Alert.Root>
        {:else}
          <div
            class="border-default max-w-2xl rounded-lg border border-dashed px-6 py-10 outline-none"
            tabindex="-1"
            {@attach focusIfReplacingForm}
          >
            {#if state.kind === "disabled"}
              <p class="font-medium">{m.federation_admin_disabled_title()}</p>
              <p class="text-muted mt-1 text-sm">{m.federation_admin_disabled_description()}</p>
              <Button
                href={docsUrl(
                  "guides/oidc-federation/single-tenant",
                  getLocale(),
                  "move-the-settings-into-eneo"
                )}
                target="_blank"
                rel="noreferrer"
                variant="link"
                size="sm"
                class="mt-3 h-auto w-fit px-0"
              >
                {m.federation_admin_guide_link()}
                <ExternalLink data-icon="inline-end" aria-hidden="true" />
              </Button>
            {:else}
              <p class="font-medium">{m.federation_admin_not_configured_title()}</p>
              <p class="text-muted mt-1 text-sm">
                {m.federation_admin_not_configured_description()}
              </p>
              <Button
                href={docsUrl(
                  "guides/oidc-federation/single-tenant",
                  getLocale(),
                  "configure-via-api"
                )}
                target="_blank"
                rel="noreferrer"
                variant="link"
                size="sm"
                class="mt-3 h-auto w-fit px-0"
              >
                {m.federation_admin_register_guide_link()}
                <ExternalLink data-icon="inline-end" aria-hidden="true" />
              </Button>
            {/if}
          </div>
        {/if}
      {/await}
    </Settings.Page>
  </Page.Main>
</Page.Root>
