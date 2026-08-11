<script lang="ts">
  import type {
    ContentOwner,
    ContentState,
    DeploymentPolicy,
    ObjectContentInventory,
    ObjectContentMoves,
    StorageKind
  } from "@eneo/eneo-js";
  import { AlertCircle, ChevronDown, Database, HardDrive, Info, Loader2 } from "lucide-svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { m } from "$lib/paraglide/messages";

  type Capability = DeploymentPolicy["capabilities"][number];
  type LoadStatus = "idle" | "loading" | "error";

  type Props = {
    inventory: ObjectContentInventory | null;
    inventoryStatus: LoadStatus;
    contentMoves: ObjectContentMoves | null;
    moveStatus: LoadStatus;
    activeTarget: StorageKind;
    objectStoreCapability: Capability | undefined;
    onInventoryRetry: () => void | Promise<void>;
    storageTargetLabel: (target: StorageKind) => string;
    contentOwnerLabel: (owner: ContentOwner) => string;
    contentStateLabel: (state: ContentState) => string;
    storageDate: (value: string | null) => string;
    storageCount: (value: number) => string;
    storageBytes: (value: number, maximumFractionDigits?: number) => string;
    readinessLabel: (code: Capability["readiness_code"]) => string;
  };

  let {
    inventory,
    inventoryStatus,
    contentMoves,
    moveStatus,
    activeTarget,
    objectStoreCapability,
    onInventoryRetry,
    storageTargetLabel,
    contentOwnerLabel,
    contentStateLabel,
    storageDate,
    storageCount,
    storageBytes,
    readinessLabel
  }: Props = $props();

  let detailsOpen = $state(false);
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
  let postgresqlShare = $derived(
    managedTotalBytes === 0 ? 0 : (managedPostgresqlBytes / managedTotalBytes) * 100
  );
  let objectStoreShare = $derived(
    managedTotalBytes === 0 ? 0 : (managedObjectStoreBytes / managedTotalBytes) * 100
  );
  let objectStoreReady = $derived(objectStoreCapability?.readiness_code === "ready");
  let objectStoreNotConfigured = $derived(
    objectStoreCapability === undefined ||
      objectStoreCapability.readiness_code === "object_store_not_configured"
  );
  let pendingMoveCount = $derived(
    contentMoves?.moves
      .filter((item) => item.state === "pending" || item.state === "target_verified")
      .reduce((total, item) => total + item.count, 0) ?? 0
  );
  let failedMoveCount = $derived(
    contentMoves?.moves
      .filter((item) => item.state === "failed")
      .reduce((total, item) => total + item.count, 0) ?? 0
  );
  let moveSummary = $derived.by(() => {
    if (moveStatus === "loading") {
      return { label: m.loading(), detail: m.storage_moves_loading(), variant: "outline" as const };
    }
    if (moveStatus === "error" || contentMoves === null) {
      return {
        label: m.storage_inventory_not_available(),
        detail: m.storage_moves_load_error_title(),
        variant: "destructive" as const
      };
    }
    if (failedMoveCount > 0) {
      return {
        label: m.storage_overview_move_attention(),
        detail: m.storage_overview_move_failed({ count: storageCount(failedMoveCount) }),
        variant: "destructive" as const
      };
    }
    if (pendingMoveCount > 0 && contentMoves.paused) {
      return {
        label: m.storage_moves_status_paused(),
        detail: m.storage_overview_move_waiting({ count: storageCount(pendingMoveCount) }),
        variant: "outline" as const
      };
    }
    if (pendingMoveCount > 0) {
      return {
        label: m.storage_moves_status_running(),
        detail: m.storage_overview_move_waiting({ count: storageCount(pendingMoveCount) }),
        variant: "default" as const
      };
    }
    return {
      label: m.storage_overview_move_idle(),
      detail: contentMoves.paused
        ? m.storage_overview_move_idle_paused()
        : m.storage_overview_move_empty(),
      variant: "outline" as const
    };
  });

  $effect(() => alertRef?.focus());
</script>

<section aria-labelledby="storage-overview-title" class="flex flex-col gap-4">
  <div>
    <h2 id="storage-overview-title" class="text-primary text-base font-semibold">
      {m.storage_overview_title()}
    </h2>
    <p class="text-secondary mt-1 max-w-[72ch] text-sm leading-5">
      {m.storage_overview_description()}
    </p>
  </div>

  <div
    class="grid gap-3 sm:grid-cols-2 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(18rem,1.35fr)_minmax(0,1fr)]"
  >
    <Card.Root size="sm">
      <Card.Header>
        <Card.Title class="text-secondary">{m.storage_overview_active_target()}</Card.Title>
        <Card.Action>
          <Badge variant="outline">{m.storage_overview_active()}</Badge>
        </Card.Action>
      </Card.Header>
      <Card.Content class="flex flex-col gap-2">
        <div class="flex items-center gap-2">
          {#if activeTarget === "postgres_inline"}
            <Database class="text-muted size-5" aria-hidden="true" />
          {:else}
            <HardDrive class="text-muted size-5" aria-hidden="true" />
          {/if}
          <p class="text-lg font-semibold">{storageTargetLabel(activeTarget)}</p>
        </div>
        <p class="text-muted text-sm leading-5">{m.storage_overview_active_target_help()}</p>
      </Card.Content>
    </Card.Root>

    <Card.Root size="sm">
      <Card.Header>
        <Card.Title class="text-secondary">{m.storage_target_object_store()}</Card.Title>
        <Card.Action>
          <Badge
            variant={objectStoreReady || objectStoreNotConfigured ? "outline" : "destructive"}
            class={objectStoreReady
              ? "border-positive-default/40 bg-positive-dimmer text-positive-stronger"
              : undefined}
          >
            {objectStoreReady
              ? m.storage_connection_summary_configured()
              : objectStoreNotConfigured
                ? m.storage_connection_summary_unconfigured()
                : m.storage_overview_attention()}
          </Badge>
        </Card.Action>
      </Card.Header>
      <Card.Content class="flex flex-col gap-2">
        <p class="text-lg font-semibold">
          {objectStoreReady
            ? m.storage_target_ready()
            : objectStoreNotConfigured
              ? m.storage_connection_empty_title()
              : readinessLabel(objectStoreCapability!.readiness_code)}
        </p>
        <p class="text-muted text-sm leading-5">
          {objectStoreReady
            ? m.storage_overview_object_store_ready()
            : m.storage_overview_object_store_help()}
        </p>
      </Card.Content>
    </Card.Root>

    <Card.Root size="sm">
      <Card.Header>
        <Card.Title class="text-secondary">{m.storage_inventory_managed_total()}</Card.Title>
      </Card.Header>
      <Card.Content class="flex flex-col gap-3">
        {#if inventory}
          <p class="text-lg font-semibold tabular-nums">{storageBytes(managedTotalBytes, 2)}</p>
          {#if managedTotalBytes > 0}
            <div
              class="bg-secondary flex h-1.5 overflow-hidden rounded-full"
              role="img"
              aria-label={m.storage_overview_distribution_label({
                postgresql: storageBytes(managedPostgresqlBytes, 2),
                objectStore: storageBytes(managedObjectStoreBytes, 2)
              })}
            >
              <div class="bg-accent-default h-full" style={`flex-basis: ${postgresqlShare}%`}></div>
              <div
                class="bg-positive-default h-full"
                style={`flex-basis: ${objectStoreShare}%`}
              ></div>
            </div>
          {/if}
          <dl class="text-muted grid gap-1 text-xs">
            <div class="flex justify-between gap-3">
              <dt>{m.storage_target_postgres_inline()}</dt>
              <dd class="tabular-nums">{storageBytes(managedPostgresqlBytes, 2)}</dd>
            </div>
            <div class="flex justify-between gap-3">
              <dt>{m.storage_target_object_store()}</dt>
              <dd class="tabular-nums">{storageBytes(managedObjectStoreBytes, 2)}</dd>
            </div>
          </dl>
        {:else if inventoryStatus === "loading"}
          <p class="text-secondary flex items-center gap-2 text-sm" aria-live="polite">
            <Loader2 class="size-4 animate-spin" />
            {m.storage_inventory_loading()}
          </p>
        {:else}
          <p class="text-lg font-semibold">{m.storage_inventory_not_available()}</p>
        {/if}
      </Card.Content>
    </Card.Root>

    <Card.Root size="sm">
      <Card.Header>
        <Card.Title class="text-secondary">{m.storage_overview_moves()}</Card.Title>
        <Card.Action><Badge variant={moveSummary.variant}>{moveSummary.label}</Badge></Card.Action>
      </Card.Header>
      <Card.Content class="flex flex-col gap-2">
        <p class="text-lg font-semibold tabular-nums">
          {storageCount(pendingMoveCount + failedMoveCount)}
          <span class="text-secondary text-sm font-normal">{m.storage_overview_items()}</span>
        </p>
        <p class="text-muted text-sm leading-5">{moveSummary.detail}</p>
      </Card.Content>
    </Card.Root>
  </div>

  {#if inventoryStatus === "error"}
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
        <Button class="mt-3" variant="outline" onclick={() => void onInventoryRetry()}>
          {m.retry()}
        </Button>
      </Alert.Description>
    </Alert.Root>
  {/if}

  {#if inventory}
    <Collapsible.Root bind:open={detailsOpen}>
      <Collapsible.Trigger
        class="hover:bg-hover-dimmer focus-visible:ring-ring flex w-full items-center gap-2 rounded-md px-3 py-2 text-left focus-visible:ring-2 focus-visible:outline-none [&[data-state=open]>svg]:rotate-180"
        aria-controls="storage-inventory-details"
      >
        <span class="min-w-0 flex-1 text-sm font-medium">
          {detailsOpen ? m.storage_inventory_hide_details() : m.storage_inventory_caption()}
        </span>
        <ChevronDown
          aria-hidden="true"
          class="size-4 shrink-0 transition-transform motion-reduce:transition-none"
        />
      </Collapsible.Trigger>
      <Collapsible.Content id="storage-inventory-details" class="pt-3">
        <Card.Root>
          <Card.Content class="flex flex-col gap-6">
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
                <p class="text-muted py-2 text-sm">{m.storage_inventory_empty()}</p>
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
                        <Table.Cell class="font-medium">{contentOwnerLabel(item.owner)}</Table.Cell>
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
                      <Table.Cell
                        >{m.storage_inventory_allocation_searchable_knowledge()}</Table.Cell
                      >
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
            {:else}
              <Alert.Root aria-live="polite">
                <Info />
                <Alert.Title>{m.storage_inventory_allocation_unavailable_title()}</Alert.Title>
                <Alert.Description>
                  {m.storage_inventory_allocation_unavailable_description()}
                </Alert.Description>
              </Alert.Root>
            {/if}
          </Card.Content>
        </Card.Root>
      </Collapsible.Content>
    </Collapsible.Root>
  {/if}
</section>
