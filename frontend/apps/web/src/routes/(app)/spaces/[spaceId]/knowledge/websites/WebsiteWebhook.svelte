<script lang="ts">
  import { onMount } from "svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";

  export let websiteId: string;
  export let nextRetryAt: string | null | undefined = undefined;
  const eneo = getEneo();
  let url = "";
  let token = "";
  let enabled = false;
  let pending = false;
  let busy = false;
  let copied = false;
  $: example = `curl --request POST '${url}' --header 'Authorization: Bearer ${token || "<TOKEN>"}'`;

  onMount(() => {
    let mounted = true;
    eneo.websites
      .webhook({ id: websiteId })
      .then((settings) => {
        if (!mounted) return;
        url = settings.url;
        enabled = settings.enabled;
        pending = settings.pending;
        nextRetryAt = settings.next_retry_at;
      })
      .catch(toastError);
    return () => {
      mounted = false;
      token = "";
    };
  });

  async function rotate() {
    busy = true;
    copied = false;
    try {
      const result = await eneo.websites.rotateWebhookToken({ id: websiteId });
      token = result.token;
      url = result.url;
      enabled = true;
    } catch (error) {
      toastError(error);
    } finally {
      busy = false;
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(example);
      copied = true;
    } catch (error) {
      toastError(error);
    }
  }
</script>

<div class="border-default flex flex-col gap-3 border-b p-4">
  <p>{m.website_webhook_description()}</p>
  {#if url}
    <label class="flex flex-col gap-1">
      {m.website_webhook_url()}
      <input class="border-default rounded border p-2" readonly value={url} />
    </label>
  {/if}
  {#if pending}<p role="status">{m.website_webhook_pending()}</p>{/if}
  {#if nextRetryAt}<p>
      {m.website_webhook_backoff({ date: new Date(nextRetryAt).toLocaleString() })}
    </p>{/if}
  {#if token}
    <p>{m.website_webhook_secret()}</p>
    <pre
      class="overflow-x-auto whitespace-pre-wrap break-all rounded bg-secondary p-3 text-sm">{example}</pre>
    <Button type="button" onclick={copy}
      >{copied ? m.website_webhook_copied() : m.website_webhook_copy()}</Button
    >
  {:else if enabled}
    <p>{m.website_webhook_ready()}</p>
  {/if}
  {#if enabled}<p class="text-sm">{m.website_webhook_rotate_hint()}</p>{/if}
  <Button type="button" disabled={busy} onclick={rotate}>
    {enabled ? m.website_webhook_rotate() : m.website_webhook_generate()}
  </Button>
</div>
