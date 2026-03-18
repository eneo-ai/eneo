<svelte:options runes={false} />

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { createEventDispatcher } from "svelte";
  import { slide } from "svelte/transition";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import type { CustomHeader } from "./httpConfigTypes";
  import { isSecretSentinel } from "./httpConfigTypes";

  export let headers: CustomHeader[];
  export let isPublished: boolean;

  const dispatch = createEventDispatcher<{
    headersChange: { headers: CustomHeader[] };
  }>();

  let expanded = headers.length > 0;

  function addHeader() {
    dispatch("headersChange", {
      headers: [...headers, { name: "", value: "", secret: false }]
    });
  }

  function removeHeader(index: number) {
    dispatch("headersChange", {
      headers: headers.filter((_, i) => i !== index)
    });
  }

  function updateHeader(index: number, patch: Partial<CustomHeader>) {
    const next = headers.map((h, i) => (i === index ? { ...h, ...patch } : h));
    dispatch("headersChange", { headers: next });
  }
</script>

<Settings.Row title={m.http_headers_title()} description="" fullWidth={true}>
  <div class="border-default/70 bg-secondary/10 overflow-hidden rounded-lg border">
    <button
      type="button"
      class="hover:bg-secondary/20 flex w-full items-center gap-2 px-3 py-3 text-left text-sm font-medium transition-colors"
      aria-expanded={expanded}
      on:click={() => (expanded = !expanded)}
    >
      <IconChevronRight
        class="size-3.5 shrink-0 transition-transform duration-200 {expanded
          ? 'rotate-90'
          : ''}"
      />
      {m.http_headers_title()}
      {#if headers.length > 0}
        <span class="text-muted text-xs">({headers.length})</span>
      {/if}
    </button>
    {#if expanded}
      <div
        class="border-default/70 flex flex-col gap-2 border-t px-3 pt-3 pb-3"
        transition:slide={{ duration: 200 }}
      >
        {#each headers as header, i (i)}
          <div class="flex items-start gap-2">
            <input
              class="border-default bg-primary w-1/3 rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 ring-default"
              type="text"
              placeholder={m.http_header_name_placeholder()}
              value={header.name}
              disabled={isPublished}
              on:input={(e) =>
                updateHeader(i, { name: e.currentTarget.value })}
            />
            {#if isSecretSentinel(header.value)}
              <div class="flex flex-1 items-center gap-2">
                <span
                  class="bg-accent-dimmer/50 text-accent-stronger rounded-md px-2 py-1 text-xs font-medium"
                >
                  {m.http_secret_stored()}
                </span>
                <button
                  type="button"
                  class="text-accent-default text-xs hover:underline"
                  disabled={isPublished}
                  on:click={() => updateHeader(i, { value: "" })}
                >
                  {m.http_secret_replace()}
                </button>
              </div>
            {:else}
              <input
                class="border-default bg-primary flex-1 rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 ring-default"
                type={header.secret ? "password" : "text"}
                placeholder={m.http_header_value_placeholder()}
                value={typeof header.value === "string" ? header.value : ""}
                disabled={isPublished}
                on:input={(e) =>
                  updateHeader(i, { value: e.currentTarget.value })}
              />
            {/if}
            <label class="flex items-center gap-1 pt-2.5 text-xs">
              <input
                type="checkbox"
                class="accent-accent-default size-3.5"
                checked={header.secret}
                disabled={isPublished}
                on:change={(e) =>
                  updateHeader(i, { secret: e.currentTarget.checked })}
              />
              {m.http_header_secret()}
            </label>
            <button
              type="button"
              class="text-muted hover:text-danger-default pt-2 text-sm"
              disabled={isPublished}
              on:click={() => removeHeader(i)}
            >
              &times;
            </button>
          </div>
        {/each}
        <button
          type="button"
          class="text-accent-default hover:text-accent-stronger text-xs font-medium"
          disabled={isPublished}
          on:click={addHeader}
        >
          + {m.http_header_add()}
        </button>
      </div>
    {/if}
  </div>
</Settings.Row>
