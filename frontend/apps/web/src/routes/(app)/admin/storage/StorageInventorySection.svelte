<script lang="ts">
  import type { ContentState, ObjectContentInventory, StorageKind } from "@eneo/eneo-js";
  import { AlertCircle, Boxes, ChevronDown, Loader2, RefreshCw } from "lucide-svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import PolicySection from "$lib/features/admin/PolicySection.svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    inventory: ObjectContentInventory | null;
    status: "idle" | "loading" | "error";
    lastRefreshed: string | null;
    onRetry: () => void | Promise<void>;
    onRefresh: () => void | Promise<void>;
    storageTargetLabel: (target: StorageKind | null) => string;
    contentStateLabel: (state: ContentState) => string;
    storageDate: (value: string | null) => string;
    storageCount: (value: number) => string;
    storageBytes: (value: number) => string;
  };

  let {
    inventory,
    status,
    lastRefreshed,
    onRetry,
    onRefresh,
    storageTargetLabel,
    contentStateLabel,
    storageDate,
    storageCount,
    storageBytes
  }: Props = $props();
  let open = $state(false);
  let alertRef = $state<HTMLElement | null>(null);

  $effect(() => alertRef?.focus());

  function refreshInventory(): void {
    if (status === "loading") return;
    void onRefresh();
  }
</script>

<PolicySection
  id="storage-inventory"
  title={m.storage_inventory_title()}
  description={m.storage_inventory_description()}
  summary={status === "loading"
    ? m.loading()
    : status === "error"
      ? m.storage_target_unavailable()
      : m.available()}
  summaryVariant={status === "error" ? "destructive" : "outline"}
>
  {#snippet icon()}
    <Boxes class="size-5" aria-hidden="true" />
  {/snippet}

  <div class="flex flex-wrap items-center justify-end gap-3">
    {#if lastRefreshed !== null}
      <span class="text-muted text-xs">
        {m.storage_last_refreshed({ time: lastRefreshed })}
      </span>
    {/if}
    <Button
      variant="outline"
      aria-disabled={status === "loading"}
      aria-busy={status === "loading"}
      class={status === "loading" ? "pointer-events-none opacity-50" : undefined}
      onclick={refreshInventory}
    >
      <RefreshCw
        data-icon="inline-start"
        class={status === "loading" ? "animate-spin" : undefined}
        aria-hidden="true"
      />
      {m.storage_inventory_refresh()}
    </Button>
  </div>

  {#if status === "error"}
    <Alert.Root
      bind:ref={alertRef}
      data-testid="inventory-recovery-alert"
      tabindex={-1}
      variant="destructive"
      aria-live="assertive"
    >
      <AlertCircle />
      <Alert.Title>{m.storage_inventory_error_title()}</Alert.Title>
      <Alert.Description>
        <p>{m.storage_inventory_error_description()}</p>
        <Button class="mt-3" variant="outline" onclick={() => void onRetry()}>
          {m.retry()}
        </Button>
      </Alert.Description>
    </Alert.Root>
  {/if}

  {#if inventory}
    <Collapsible.Root bind:open>
      <Collapsible.Trigger
        class="hover:bg-hover-dimmer focus-visible:ring-ring flex w-full items-center gap-2 rounded-md px-3 py-2 text-left focus-visible:ring-2 focus-visible:outline-none [&[data-state=open]>svg]:rotate-180"
        aria-controls="storage-inventory-details"
      >
        <span class="min-w-0 flex-1 text-sm font-medium">
          {m.storage_inventory_caption()}
        </span>
        <ChevronDown
          aria-hidden="true"
          class="size-4 shrink-0 transition-transform motion-reduce:transition-none"
        />
      </Collapsible.Trigger>
      <Collapsible.Content id="storage-inventory-details" class="pt-3">
        {#if inventory.inventory.length === 0}
          <p class="border-default text-muted rounded-lg border px-4 py-3 text-sm">
            {m.storage_inventory_empty()}
          </p>
        {:else}
          <div class="border-default overflow-x-auto rounded-lg border">
            <Table.Root class="min-w-[640px]">
              <Table.Caption class="sr-only">
                {m.storage_inventory_caption()}
              </Table.Caption>
              <Table.Header>
                <Table.Row>
                  <Table.Head>{m.storage_inventory_target()}</Table.Head>
                  <Table.Head>{m.storage_inventory_state()}</Table.Head>
                  <Table.Head>{m.storage_inventory_count()}</Table.Head>
                  <Table.Head>{m.storage_inventory_bytes()}</Table.Head>
                  <Table.Head>{m.storage_inventory_oldest()}</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#each inventory.inventory as item (`${item.target}-${item.state}`)}
                  <Table.Row>
                    <Table.Cell class="font-medium">
                      {storageTargetLabel(item.target)}
                    </Table.Cell>
                    <Table.Cell>{contentStateLabel(item.state)}</Table.Cell>
                    <Table.Cell>{storageCount(item.count)}</Table.Cell>
                    <Table.Cell>{storageBytes(item.bytes)}</Table.Cell>
                    <Table.Cell>{storageDate(item.oldest_created_at)}</Table.Cell>
                  </Table.Row>
                {/each}
              </Table.Body>
            </Table.Root>
          </div>
        {/if}
      </Collapsible.Content>
    </Collapsible.Root>
  {:else if status === "loading"}
    <p class="text-secondary flex items-center gap-2 text-sm" aria-live="polite">
      <Loader2 class="size-4 animate-spin" />
      {m.storage_inventory_loading()}
    </p>
  {/if}
</PolicySection>
