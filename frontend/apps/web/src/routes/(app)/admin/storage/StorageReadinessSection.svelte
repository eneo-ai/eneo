<script lang="ts">
  import type { DeploymentPolicy, ObjectContentReadinessCode, StorageKind } from "@eneo/eneo-js";
  import { ChevronDown, ShieldCheck } from "lucide-svelte";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import PolicySection from "$lib/features/admin/PolicySection.svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    capabilities: DeploymentPolicy["capabilities"];
    storageTargetLabel: (target: StorageKind | null) => string;
    readinessLabel: (code: ObjectContentReadinessCode) => string;
  };

  let { capabilities, storageTargetLabel, readinessLabel }: Props = $props();
  let open = $state(false);
  const objectStoreCapability = $derived(
    capabilities.find((capability) => capability.target === "object_store")
  );
</script>

<PolicySection
  id="storage-readiness"
  title={m.storage_capabilities_title()}
  description={m.storage_capabilities_description()}
  summary={objectStoreCapability
    ? readinessLabel(objectStoreCapability.readiness_code)
    : m.storage_target_not_applicable()}
  summaryVariant={objectStoreCapability?.readiness_code === "store_degraded" ||
  objectStoreCapability?.readiness_code === "database_unavailable"
    ? "destructive"
    : "outline"}
>
  {#snippet icon()}
    <ShieldCheck class="size-5" aria-hidden="true" />
  {/snippet}

  <Collapsible.Root bind:open>
    <Collapsible.Trigger
      class="hover:bg-hover-dimmer focus-visible:ring-ring flex w-full items-center gap-2 rounded-md px-3 py-2 text-left focus-visible:ring-2 focus-visible:outline-none [&[data-state=open]>svg]:rotate-180"
      aria-controls="storage-readiness-details"
    >
      <span class="min-w-0 flex-1 text-sm font-medium">
        {m.storage_capabilities_caption()}
      </span>
      <ChevronDown
        aria-hidden="true"
        class="size-4 shrink-0 transition-transform motion-reduce:transition-none"
      />
    </Collapsible.Trigger>
    <Collapsible.Content id="storage-readiness-details" class="pt-3">
      <div class="border-default overflow-x-auto rounded-lg border">
        <Table.Root class="min-w-[560px]">
          <Table.Caption class="sr-only">
            {m.storage_capabilities_caption()}
          </Table.Caption>
          <Table.Header>
            <Table.Row>
              <Table.Head>{m.storage_capabilities_target()}</Table.Head>
              <Table.Head>{m.storage_capabilities_configured()}</Table.Head>
              <Table.Head>{m.storage_capabilities_selectable()}</Table.Head>
              <Table.Head>{m.storage_capabilities_status()}</Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each capabilities as capability (capability.target)}
              <Table.Row>
                <Table.Cell class="font-medium">
                  {storageTargetLabel(capability.target)}
                </Table.Cell>
                <Table.Cell>{capability.configured ? m.yes() : m.no()}</Table.Cell>
                <Table.Cell>{capability.selectable ? m.yes() : m.no()}</Table.Cell>
                <Table.Cell>{readinessLabel(capability.readiness_code)}</Table.Cell>
              </Table.Row>
            {/each}
          </Table.Body>
        </Table.Root>
      </div>
    </Collapsible.Content>
  </Collapsible.Root>
</PolicySection>
