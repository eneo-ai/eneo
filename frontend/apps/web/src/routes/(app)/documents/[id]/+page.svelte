<script lang="ts">
  import { page } from "$app/state";
  import { Markdown } from "@eneo/ui";
  import { Check, Copy, Download, ExternalLink, FileText } from "lucide-svelte";
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card/index.js";
  import { toast } from "$lib/components/toast";
  import { getEneo } from "$lib/core/Eneo";
  import { sourceReferenceText } from "$lib/features/widget/widgetMessageContext";
  import { m } from "$lib/paraglide/messages";

  let { data } = $props();

  const eneo = getEneo();
  const title = $derived(data.blob?.metadata.title ?? data.blob?.metadata.url ?? data.id);
  // The text a widget visitor copies, from the request's origin: a pasted
  // link is a full page load, so this renders on the server first.
  const reference = $derived(sourceReferenceText({ id: data.id, title }, page.url.origin));

  let copied = $state(false);
  let downloading = $state(false);

  async function copyReference() {
    try {
      await navigator.clipboard.writeText(reference);
      copied = true;
      setTimeout(() => (copied = false), 2000);
    } catch {
      toast.error(m.widget_document_reference_copy_failed());
    }
  }

  async function downloadOriginal() {
    if (downloading) return;
    downloading = true;
    try {
      const response = await eneo.infoBlobs.generateOriginalSignedUrl({
        infoBlobId: data.id,
        contentDisposition: "attachment"
      });
      window.location.assign(response.url);
    } catch {
      toast.error(m.error_downloading_original());
    } finally {
      downloading = false;
    }
  }
</script>

<svelte:head>
  <title>{title} – {m.document_lookup_title()}</title>
</svelte:head>

{#snippet referenceDetails()}
  <dl class="grid gap-1 text-sm sm:grid-cols-[auto_1fr] sm:gap-x-6">
    <dt class="text-secondary">{m.document_lookup_reference()}</dt>
    <dd class="break-all select-all">{reference}</dd>
  </dl>
{/snippet}

{#snippet copyButton()}
  <Button variant="outline" onclick={copyReference}>
    {#if copied}
      <Check aria-hidden="true" />
      {m.copied_to_clipboard()}
    {:else}
      <Copy aria-hidden="true" />
      {m.copy_to_clipboard()}
    {/if}
  </Button>
{/snippet}

<Page.Root>
  <Page.Header>
    <Page.Title title={m.document_lookup_title()} truncate />
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex w-full max-w-3xl flex-col gap-6 py-6">
      {#if data.blob}
        <Card.Root>
          <Card.Header>
            <Card.Title class="flex items-center gap-2">
              <FileText class="text-secondary size-5 shrink-0" aria-hidden="true" />
              <span class="break-words">{title}</span>
            </Card.Title>
            {#if data.space}
              <Card.Description>
                {#if data.group}
                  {m.document_lookup_collection()}: {data.group.name}
                {:else if data.website}
                  {m.document_lookup_website()}: {data.website.name ?? data.website.url}
                {/if}
              </Card.Description>
            {/if}
          </Card.Header>
          <Card.Content class="flex flex-col gap-4">
            {@render referenceDetails()}
            <div class="flex flex-wrap gap-2">
              {@render copyButton()}
              {#if data.blob.original_available}
                <Button variant="outline" onclick={downloadOriginal} disabled={downloading}>
                  <Download aria-hidden="true" />
                  {m.document_lookup_download_original()}
                </Button>
              {/if}
              {#if data.blob.metadata.url}
                <Button
                  variant="outline"
                  href={data.blob.metadata.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <ExternalLink aria-hidden="true" />
                  {data.blob.metadata.url}
                </Button>
              {/if}
              {#if data.space}
                <Button variant="ghost" href="/spaces/{data.space.id}/knowledge">
                  {m.document_lookup_open_space({ space: data.space.name ?? "" })}
                </Button>
              {/if}
            </div>
            {#if !data.blob.original_available}
              <p class="text-secondary text-sm">{m.document_lookup_original_unavailable()}</p>
            {/if}
          </Card.Content>
        </Card.Root>

        <Card.Root>
          <Card.Header>
            <Card.Title>{m.document_lookup_contents()}</Card.Title>
          </Card.Header>
          <Card.Content>
            <Markdown class="max-w-none text-sm" source={data.blob.text ?? ""} />
          </Card.Content>
        </Card.Root>
      {:else}
        <Card.Root>
          <Card.Header>
            <Card.Title>{m.document_lookup_not_found_title()}</Card.Title>
            <Card.Description>{m.document_lookup_not_found_body()}</Card.Description>
          </Card.Header>
          <Card.Content class="flex flex-col gap-4">
            {@render referenceDetails()}
            <div>
              {@render copyButton()}
            </div>
          </Card.Content>
        </Card.Root>
      {/if}
    </div>
  </Page.Main>
</Page.Root>
