<script lang="ts">
  import type {
    ContentOwner,
    ContentState,
    ObjectContentInventory,
    StorageKind
  } from "@eneo/eneo-js";
  import { AlertCircle, Boxes, ChevronDown, Info, Loader2, RefreshCw } from "lucide-svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import PolicySection from "$lib/features/admin/PolicySection.svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    inventory: ObjectContentInventory | null;
    status: "idle" | "loading" | "error";
    lastRefreshed: string | null;
    onRetry: () => void | Promise<void>;
    onRefresh: () => void | Promise<void>;
    storageTargetLabel: (target: StorageKind) => string;
    contentOwnerLabel: (owner: ContentOwner) => string;
    contentStateLabel: (state: ContentState) => string;
    storageDate: (value: string | null) => string;
    storageCount: (value: number) => string;
    storageBytes: (value: number, maximumFractionDigits?: number) => string;
  };

  let {
    inventory,
    status,
    lastRefreshed,
    onRetry,
    onRefresh,
    storageTargetLabel,
    contentOwnerLabel,
    contentStateLabel,
    storageDate,
    storageCount,
    storageBytes
  }: Props = $props();
  let open = $state(false);
  let alertRef = $state<HTMLElement | null>(null);
  let activeInventory = $derived(
    inventory?.inventory.filter((item) => item.state !== "tombstoned") ?? []
  );
  let managedTotalBytes = $derived(activeInventory.reduce((total, item) => total + item.bytes, 0));
  let managedPostgresqlBytes = $derived(
    activeInventory
      .filter((item) => item.target === "postgres_inline")
      .reduce((total, item) => total + item.bytes, 0)
  );
  let managedObjectStoreBytes = $derived(
    activeInventory
      .filter((item) => item.target === "object_store")
      .reduce((total, item) => total + item.bytes, 0)
  );

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

  <div class="flex flex-col gap-5">
    <div class="flex flex-wrap items-center justify-end gap-3">
      {#if lastRefreshed !== null}
        <span class="text-muted text-sm">
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
      <dl class="border-default grid gap-x-8 gap-y-5 border-y py-5 sm:grid-cols-2 xl:grid-cols-4">
        <div class="flex min-w-0 flex-col gap-1">
          <dt class="text-secondary text-sm">{m.storage_inventory_managed_total()}</dt>
          <dd class="text-primary text-xl font-semibold tabular-nums">
            {storageBytes(managedTotalBytes, 2)}
          </dd>
          <p class="text-muted max-w-[38ch] text-sm leading-5">
            {m.storage_inventory_managed_total_description()}
          </p>
        </div>
        <div class="flex min-w-0 flex-col gap-1">
          <dt class="text-secondary text-sm">{m.storage_inventory_managed_postgresql()}</dt>
          <dd class="text-primary text-xl font-semibold tabular-nums">
            {storageBytes(managedPostgresqlBytes, 2)}
          </dd>
          <p class="text-muted max-w-[38ch] text-sm leading-5">
            {m.storage_inventory_managed_postgresql_description()}
          </p>
        </div>
        <div class="flex min-w-0 flex-col gap-1">
          <dt class="text-secondary text-sm">{m.storage_inventory_managed_object_store()}</dt>
          <dd class="text-primary text-xl font-semibold tabular-nums">
            {storageBytes(managedObjectStoreBytes, 2)}
          </dd>
          <p class="text-muted max-w-[38ch] text-sm leading-5">
            {m.storage_inventory_managed_object_store_description()}
          </p>
        </div>
        <div class="flex min-w-0 flex-col gap-1">
          <dt class="text-secondary text-sm">{m.storage_inventory_postgresql_total()}</dt>
          <dd class="text-primary text-xl font-semibold tabular-nums">
            {inventory.postgresql_allocation === null
              ? m.storage_inventory_not_available()
              : storageBytes(inventory.postgresql_allocation.total_bytes, 2)}
          </dd>
          <p class="text-muted max-w-[38ch] text-sm leading-5">
            {m.storage_inventory_postgresql_total_description()}
          </p>
        </div>
      </dl>

      {#if inventory.postgresql_allocation === null}
        <Alert.Root aria-live="polite">
          <Info />
          <Alert.Title>{m.storage_inventory_allocation_unavailable_title()}</Alert.Title>
          <Alert.Description>
            {m.storage_inventory_allocation_unavailable_description()}
          </Alert.Description>
        </Alert.Root>
      {/if}

      <Collapsible.Root bind:open>
        <Collapsible.Trigger
          class="hover:bg-hover-dimmer focus-visible:ring-ring flex w-full items-center gap-2 rounded-md px-3 py-2 text-left focus-visible:ring-2 focus-visible:outline-none [&[data-state=open]>svg]:rotate-180"
          aria-controls="storage-inventory-details"
        >
          <span class="min-w-0 flex-1 text-sm font-medium">
            {open ? m.storage_inventory_hide_details() : m.storage_inventory_caption()}
          </span>
          <ChevronDown
            aria-hidden="true"
            class="size-4 shrink-0 transition-transform motion-reduce:transition-none"
          />
        </Collapsible.Trigger>
        <Collapsible.Content id="storage-inventory-details" class="pt-4">
          <div class="flex flex-col gap-6">
            <div class="flex flex-col gap-3">
              <div class="flex max-w-[72ch] flex-col gap-1">
                <h3 class="text-primary text-sm font-semibold">
                  {m.storage_inventory_managed_caption()}
                </h3>
                <p class="text-muted text-sm leading-5">
                  {m.storage_inventory_managed_note()}
                </p>
              </div>
              {#if inventory.inventory.length === 0}
                <p class="text-muted py-2 text-sm">
                  {m.storage_inventory_empty()}
                </p>
              {:else}
                <Table.Root class="min-w-[780px]">
                  <Table.Caption class="sr-only">
                    {m.storage_inventory_managed_caption()}
                  </Table.Caption>
                  <Table.Header>
                    <Table.Row>
                      <Table.Head>{m.storage_inventory_owner()}</Table.Head>
                      <Table.Head>{m.storage_inventory_target()}</Table.Head>
                      <Table.Head>{m.storage_inventory_state()}</Table.Head>
                      <Table.Head>{m.storage_inventory_count()}</Table.Head>
                      <Table.Head>{m.storage_inventory_bytes()}</Table.Head>
                      <Table.Head>{m.storage_inventory_oldest()}</Table.Head>
                    </Table.Row>
                  </Table.Header>
                  <Table.Body>
                    {#each inventory.inventory as item (`${item.owner}-${item.target}-${item.state}`)}
                      <Table.Row>
                        <Table.Cell class="font-medium">
                          {contentOwnerLabel(item.owner)}
                        </Table.Cell>
                        <Table.Cell>{storageTargetLabel(item.target)}</Table.Cell>
                        <Table.Cell>{contentStateLabel(item.state)}</Table.Cell>
                        <Table.Cell class="tabular-nums">{storageCount(item.count)}</Table.Cell>
                        <Table.Cell class="tabular-nums">{storageBytes(item.bytes)}</Table.Cell>
                        <Table.Cell>{storageDate(item.oldest_created_at)}</Table.Cell>
                      </Table.Row>
                    {/each}
                  </Table.Body>
                </Table.Root>
              {/if}
            </div>

            {#if inventory.postgresql_allocation !== null}
              <Separator />
              <div class="flex flex-col gap-3">
                <div class="flex max-w-[72ch] flex-col gap-1">
                  <h3 class="text-primary text-sm font-semibold">
                    {m.storage_inventory_allocation_caption()}
                  </h3>
                  <p class="text-muted text-sm leading-5">
                    {m.storage_inventory_allocation_note()}
                  </p>
                </div>
                <Table.Root class="min-w-[480px]">
                  <Table.Caption class="sr-only">
                    {m.storage_inventory_allocation_caption()}
                  </Table.Caption>
                  <Table.Header>
                    <Table.Row>
                      <Table.Head>{m.storage_inventory_allocation_group()}</Table.Head>
                      <Table.Head class="text-right">
                        {m.storage_inventory_allocation_bytes()}
                      </Table.Head>
                    </Table.Row>
                  </Table.Header>
                  <Table.Body>
                    <Table.Row>
                      <Table.Cell>{m.storage_inventory_allocation_inline()}</Table.Cell>
                      <Table.Cell class="text-right tabular-nums">
                        {storageBytes(inventory.postgresql_allocation.inline_content_bytes, 1)}
                      </Table.Cell>
                    </Table.Row>
                    <Table.Row>
                      <Table.Cell>
                        {m.storage_inventory_allocation_searchable_knowledge()}
                      </Table.Cell>
                      <Table.Cell class="text-right tabular-nums">
                        {storageBytes(
                          inventory.postgresql_allocation.searchable_knowledge_bytes,
                          1
                        )}
                      </Table.Cell>
                    </Table.Row>
                    <Table.Row>
                      <Table.Cell>{m.storage_inventory_allocation_other()}</Table.Cell>
                      <Table.Cell class="text-right tabular-nums">
                        {storageBytes(inventory.postgresql_allocation.other_bytes, 1)}
                      </Table.Cell>
                    </Table.Row>
                    <Table.Row>
                      <Table.Cell class="font-semibold">
                        {m.storage_inventory_allocation_total()}
                      </Table.Cell>
                      <Table.Cell class="text-right font-semibold tabular-nums">
                        {storageBytes(inventory.postgresql_allocation.total_bytes, 1)}
                      </Table.Cell>
                    </Table.Row>
                  </Table.Body>
                </Table.Root>
              </div>
            {/if}
          </div>
        </Collapsible.Content>
      </Collapsible.Root>
    {:else if status === "loading"}
      <p class="text-secondary flex items-center gap-2 text-sm" aria-live="polite">
        <Loader2 class="size-4 animate-spin" />
        {m.storage_inventory_loading()}
      </p>
    {/if}
  </div>
</PolicySection>
