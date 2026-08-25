<script lang="ts">
  import { untrack } from "svelte";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { IconChevronRight } from "@eneo/icons/chevron-right";
  import { IconXMark } from "@eneo/icons/x-mark";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import type { CustomHeader } from "./httpConfigTypes";
  import { isSecretSentinel } from "./httpConfigTypes";

  let {
    headers,
    isPublished,
    onHeadersChange
  }: {
    headers: CustomHeader[];
    isPublished: boolean;
    onHeadersChange?: (detail: { headers: CustomHeader[] }) => void;
  } = $props();

  const uid = $props.id();

  let expanded = $state(untrack(() => headers.length > 0));

  function addHeader() {
    onHeadersChange?.({
      headers: [...headers, { name: "", value: "", secret: false }]
    });
  }

  function removeHeader(index: number) {
    onHeadersChange?.({
      headers: headers.filter((_, i) => i !== index)
    });
  }

  function updateHeader(index: number, patch: Partial<CustomHeader>) {
    const next = headers.map((h, i) => (i === index ? { ...h, ...patch } : h));
    onHeadersChange?.({ headers: next });
  }

  let pendingFocusId = $state<string | null>(null);

  function replaceHeaderSecret(index: number) {
    pendingFocusId = `${uid}-value-${index}`;
    updateHeader(index, { value: "" });
  }

  $effect(() => {
    void headers;
    if (pendingFocusId === null) return;
    const el = document.getElementById(pendingFocusId);
    if (el instanceof HTMLElement) {
      el.focus();
      pendingFocusId = null;
    }
  });

  function rowLabel(header: CustomHeader, index: number): string {
    return header.name.trim().length > 0 ? header.name : String(index + 1);
  }
</script>

<Settings.Row
  title={m.http_headers_title()}
  description={m.http_headers_desc()}
  fullWidth={true}
  density="compact"
>
  <div class="border-default/70 bg-secondary/10 overflow-hidden rounded-lg border">
    <Collapsible.Root bind:open={expanded}>
      <Collapsible.Trigger
        class="hover:bg-secondary/20 flex w-full items-center gap-2 px-3 py-3 text-left text-sm font-medium transition-colors"
      >
        <IconChevronRight
          class="size-3.5 shrink-0 transition-transform duration-200 {expanded ? 'rotate-90' : ''}"
        />
        {m.http_headers_title()}
        {#if headers.length > 0}
          <span class="text-muted text-xs">({headers.length})</span>
        {/if}
      </Collapsible.Trigger>
      <Collapsible.Content class="collapsible-animate">
        <div class="border-default/70 flex flex-col gap-2 border-t px-3 pt-3 pb-3">
          {#each headers as header, i (i)}
            <div class="flex items-start gap-2">
              <Input
                class="w-1/3"
                type="text"
                placeholder={m.http_header_name_placeholder()}
                aria-label="{m.http_header_name_placeholder()} {i + 1}"
                value={header.name}
                disabled={isPublished}
                oninput={(e) => updateHeader(i, { name: e.currentTarget.value })}
              />
              {#if isSecretSentinel(header.value)}
                <div class="flex flex-1 items-center gap-2">
                  <Badge variant="outline">
                    {m.http_secret_stored()}
                  </Badge>
                  <Button
                    variant="link"
                    size="sm"
                    class="h-auto p-0 text-xs"
                    disabled={isPublished}
                    onclick={() => replaceHeaderSecret(i)}
                  >
                    {m.http_secret_replace()}
                  </Button>
                </div>
              {:else}
                <Input
                  id="{uid}-value-{i}"
                  class="flex-1"
                  type={header.secret ? "password" : "text"}
                  placeholder={m.http_header_value_placeholder()}
                  aria-label="{m.http_header_value_placeholder()} {i + 1}"
                  value={typeof header.value === "string" ? header.value : ""}
                  disabled={isPublished}
                  oninput={(e) => updateHeader(i, { value: e.currentTarget.value })}
                />
              {/if}
              <div class="flex items-center gap-1 pt-2.5" title={m.http_header_secret_help()}>
                <Checkbox
                  id="{uid}-secret-{i}"
                  checked={header.secret}
                  disabled={isPublished}
                  onCheckedChange={(checked) => updateHeader(i, { secret: checked === true })}
                />
                <Label for="{uid}-secret-{i}" class="text-xs font-normal">
                  {m.http_header_secret()}
                </Label>
              </div>
              <Button
                variant="ghost"
                size="icon"
                class="text-muted hover:text-negative-stronger mt-1 size-7"
                disabled={isPublished}
                aria-label="{m.http_header_remove()}: {rowLabel(header, i)}"
                onclick={() => removeHeader(i)}
              >
                <IconXMark class="size-3.5" />
              </Button>
            </div>
          {/each}
          <div>
            <Button
              variant="link"
              size="sm"
              class="h-auto p-0 text-xs font-medium"
              disabled={isPublished}
              onclick={addHeader}
            >
              + {m.http_header_add()}
            </Button>
          </div>
        </div>
      </Collapsible.Content>
    </Collapsible.Root>
  </div>
</Settings.Row>
