<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { AlertCircle, Check, Copy, Key } from "lucide-svelte";
  import type { Writable } from "svelte/store";
  import { toast } from "svelte-sonner";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  let {
    openController,
    secret,
    source = "created"
  } = $props<{
    openController: Writable<boolean>;
    secret: string | null;
    source?: "created" | "rotated";
  }>();

  let copied = $state(false);
  let copyResetTimer: ReturnType<typeof setTimeout> | null = null;

  async function copyToClipboard() {
    if (!secret) return;
    try {
      await navigator.clipboard.writeText(secret);
      copied = true;
      toast.success(m.api_keys_copied_message());
      if (copyResetTimer) clearTimeout(copyResetTimer);
      copyResetTimer = setTimeout(() => {
        copied = false;
      }, 2000);
    } catch {
      toast.error(m.something_went_wrong());
    }
  }
</script>

<Dialog.Root bind:open={$openController}>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-3">
        <span
          class="bg-positive-default/10 dark:bg-positive-default/15 flex h-10 w-10 items-center justify-center rounded-xl"
          aria-hidden="true"
        >
          <Key class="text-positive-stronger h-5 w-5" />
        </span>
        <span class="text-default text-base font-semibold">
          {source === "rotated" ? m.api_keys_rotated_title() : m.api_keys_created_title()}
        </span>
      </Dialog.Title>
      <Dialog.Description class="sr-only">
        {m.api_keys_copy_warning()}
      </Dialog.Description>
    </Dialog.Header>

    <Alert.Root class="border-caution/35 bg-caution/8 dark:bg-caution/12 mt-1">
      <AlertCircle class="text-caution" />
      <Alert.Title class="text-caution">{m.api_keys_important()}</Alert.Title>
      <Alert.Description class="text-secondary">
        {m.api_keys_copy_warning()}
      </Alert.Description>
    </Alert.Root>

    {#if secret}
      <div class="mt-2">
        <p id="api-key-secret-label" class="text-secondary mb-2 text-sm font-medium">
          {m.api_keys_your_new_key()}
        </p>
        <pre
          aria-labelledby="api-key-secret-label"
          class="border-default bg-subtle text-default max-h-40 overflow-auto rounded-lg border px-3 py-2.5 font-mono text-xs break-all whitespace-pre-wrap select-all">{secret}</pre>

        <div class="mt-4 flex items-center gap-3">
          <Button
            variant={copied ? "outline" : "default"}
            onclick={copyToClipboard}
            aria-label={m.api_keys_copy_to_clipboard()}
          >
            {#if copied}
              <Check class="text-positive-stronger" />
              {m.api_keys_copied()}
            {:else}
              <Copy />
              {m.api_keys_copy_to_clipboard()}
            {/if}
          </Button>
        </div>
      </div>
    {/if}

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.close()}</Button>
        {/snippet}
      </Dialog.Close>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
