<script lang="ts">
  import { createWidgetClient, EneoError, type WidgetPublicConfig } from "@eneo/eneo-js";
  import { onMount } from "svelte";
  import EmbedApp from "$lib/features/widget/components/EmbedApp.svelte";
  import { readPreviewToken } from "$lib/features/widget/preview";
  import { m } from "$lib/paraglide/messages";

  let { data } = $props();

  // Preview mode (admin page): the token lives in the fragment, so the
  // configuration can only be fetched here in the browser.
  let previewToken = $state<string | null>(null);
  let previewConfig = $state<WidgetPublicConfig | null>(null);
  let previewFailed = $state(false);

  const config = $derived(data.config ?? previewConfig);
  const title = $derived(config ? config.texts.title || config.name : m.widget_preview_title());

  onMount(() => {
    if (data.config || data.unavailable) return;
    const token = readPreviewToken(location.hash);
    if (!token) {
      previewFailed = true;
      return;
    }
    previewToken = token;
    // The public config is cacheable for a minute; a preview must always
    // show what was just saved.
    const client = createWidgetClient({
      baseUrl: data.baseUrl,
      publicId: data.publicId,
      getToken: () => token,
      fetch: (input, init) => fetch(input, { ...init, cache: "no-store" })
    });
    client
      .config()
      .then((loaded) => (previewConfig = loaded))
      .catch((error: unknown) => {
        previewFailed = true;
        if (!(error instanceof EneoError)) console.error(error);
      });
  });
</script>

<svelte:head>
  <title>{title}</title>
  <meta name="robots" content="noindex" />
</svelte:head>

{#if config}
  <EmbedApp
    {config}
    publicId={data.publicId}
    baseUrl={data.baseUrl}
    hostOrigin={data.hostOrigin}
    hostScheme={data.hostScheme}
    {previewToken}
  />
{:else if data.unavailable}
  <!-- Every state of the page is its main landmark, like the chat itself. -->
  <main
    class="bg-primary text-primary fixed inset-0 flex flex-col items-center justify-center gap-2 p-6"
  >
    <h1 class="text-base font-semibold">{m.widget_not_available_title()}</h1>
    <p class="text-secondary text-center text-sm">{m.widget_not_available_body()}</p>
  </main>
{:else if previewFailed}
  <main class="bg-primary text-secondary fixed inset-0 flex items-center justify-center p-6">
    <p class="text-center text-sm" role="alert">{m.widget_preview_unavailable()}</p>
  </main>
{:else}
  <main class="bg-primary text-secondary fixed inset-0 flex items-center justify-center p-6">
    <p class="text-sm" aria-live="polite">{m.widget_preview_loading()}</p>
  </main>
{/if}
