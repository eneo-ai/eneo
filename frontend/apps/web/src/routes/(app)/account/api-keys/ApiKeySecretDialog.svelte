<script lang="ts">
  import { Button, CodeBlock, Dialog } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { AlertCircle, Check, Copy, Key } from "lucide-svelte";
  import { fade, fly } from "svelte/transition";
  import type { Writable } from "svelte/store";

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

  async function copyToClipboard() {
    if (!secret) return;
    await navigator.clipboard.writeText(secret);
    copied = true;
    setTimeout(() => {
      copied = false;
    }, 2000);
  }
</script>

<Dialog.Root {openController} alert>
  <Dialog.Content width="medium">
    <Dialog.Title class="flex items-center gap-3">
      <div
        class="flex h-10 w-10 items-center justify-center rounded-xl bg-positive/10 dark:bg-positive/15"
      >
        <Key class="h-5 w-5 text-positive" />
      </div>
      <span class="text-default">
        {source === "rotated" ? m.api_keys_rotated_title() : m.api_keys_created_title()}
      </span>
    </Dialog.Title>

    <Dialog.Description>
      <div
        class="mt-3 flex items-start gap-3 rounded-lg border border-caution/35 bg-caution/8 px-4 py-3 dark:bg-caution/12"
      >
        <AlertCircle class="mt-0.5 h-5 w-5 flex-shrink-0 text-caution" />
        <p class="text-sm text-secondary">
          <strong class="text-caution">{m.api_keys_important()}</strong> {m.api_keys_copy_warning()}
        </p>
      </div>
    </Dialog.Description>

    {#if secret}
      <div class="mt-5">
        <span class="mb-2 block text-sm font-medium text-secondary">{m.api_keys_your_new_key()}</span>
        <CodeBlock source={secret} />

        <div class="mt-4 flex items-center gap-3">
          <Button
            variant={copied ? "positive-outlined" : "primary"}
            on:click={copyToClipboard}
            class="gap-2 transition-all duration-200"
          >
            {#if copied}
              <span in:fly={{ y: -8, duration: 150 }}>
                <Check class="h-4 w-4" />
              </span>
              <span in:fly={{ y: 8, duration: 150 }}>{m.api_keys_copied()}</span>
            {:else}
              <Copy class="h-4 w-4" />
              {m.api_keys_copy_to_clipboard()}
            {/if}
          </Button>

          {#if copied}
            <span
              class="text-sm text-positive"
              role="status"
              aria-live="polite"
              in:fade={{ duration: 150 }}
              out:fade={{ duration: 150 }}
            >
              {m.api_keys_copied_message()}
            </span>
          {/if}
        </div>
      </div>
    {/if}

    <Dialog.Controls let:close>
      <Button is={close} variant="outlined">{m.close()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
