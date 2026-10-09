<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  The organisation's speaker identification services, as the second section of
  the transcription tab. This list owns every change: each is saved as it is
  made and applied from the response, one at a time per service, so a late
  answer never undoes a later change or brings back a removed service. Check
  results are kept for the session only.
-->

<script lang="ts">
  import type {
    SecurityClassification,
    TranscriptionService,
    TranscriptionServiceCheck,
    TranscriptionServiceCreate,
    TranscriptionServiceUpdate
  } from "@eneo/eneo-js";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";
  import AudioLines from "@lucide/svelte/icons/audio-lines";
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plug from "@lucide/svelte/icons/plug";
  import Plus from "@lucide/svelte/icons/plus";
  import Trash2 from "@lucide/svelte/icons/trash-2";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Empty from "$lib/components/ui/empty/index.js";
  import { Spinner } from "$lib/components/ui/spinner/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { toastError } from "$lib/core/errors";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import TranscriptionServiceCheckStatus from "./TranscriptionServiceCheckStatus.svelte";
  import TranscriptionServiceDialog from "./TranscriptionServiceDialog.svelte";

  type Props = {
    services: TranscriptionService[];
    classifications: SecurityClassification[];
  };

  let { services: loaded, classifications }: Props = $props();

  const eneo = getEneo();
  const uid = $props.id();

  // The loaded list, then every change this page saves to it.
  let services = $derived(loaded);
  const checks = new SvelteMap<string, TranscriptionServiceCheck | "checking">();
  // The latest check started per service; an earlier one's answer is dropped.
  const checkRuns = new SvelteMap<string, number>();
  // Services with a change in flight; their other changes wait for it.
  const busy = new SvelteSet<string>();

  let dialogOpen = $state(false);
  // Each opening mounts a fresh dialog, which reads the service it edits once.
  let dialogKey = $state(0);
  let editing = $state<TranscriptionService | null>(null);
  let removeOpen = $state(false);
  let removing = $state<TranscriptionService | null>(null);

  function host(url: string): string {
    try {
      return new URL(url).host;
    } catch {
      return url;
    }
  }

  // Updates a service still in the list; one that has left it stays gone.
  function replace(next: TranscriptionService): boolean {
    if (!services.some((service) => service.id === next.id)) return false;
    services = services.map((service) => (service.id === next.id ? next : service));
    return true;
  }

  async function mutate<T>(id: string, change: () => Promise<T>): Promise<T> {
    busy.add(id);
    try {
      return await change();
    } finally {
      busy.delete(id);
    }
  }

  // Every check is a new run, so one started before a save never answers for
  // the saved settings.
  async function runCheck(id: string) {
    const run = (checkRuns.get(id) ?? 0) + 1;
    checkRuns.set(id, run);
    checks.set(id, "checking");
    try {
      const result = await eneo.transcriptionServices.check({ id });
      if (checkRuns.get(id) === run) checks.set(id, result);
    } catch (error) {
      if (checkRuns.get(id) !== run) return;
      checks.delete(id);
      toastError(error);
    }
  }

  async function setEnabled(service: TranscriptionService, enabled: boolean) {
    if (busy.has(service.id)) return;
    replace({ ...service, is_enabled: enabled });
    try {
      replace(
        await mutate(service.id, () =>
          eneo.transcriptionServices.update({ id: service.id }, { is_enabled: enabled })
        )
      );
    } catch (error) {
      replace(service);
      toastError(error);
    }
  }

  // A saved service is tested once right away, so the row says whether it works.
  async function create(body: TranscriptionServiceCreate) {
    const created = await eneo.transcriptionServices.create(body);
    services = [...services, created];
    void runCheck(created.id);
  }

  async function update(id: string, body: TranscriptionServiceUpdate) {
    const updated = await mutate(id, () => eneo.transcriptionServices.update({ id }, body));
    if (replace(updated)) void runCheck(id);
  }

  function openDialog(service: TranscriptionService | null) {
    editing = service;
    dialogKey += 1;
    dialogOpen = true;
  }

  function confirmRemove(service: TranscriptionService) {
    removing = service;
    removeOpen = true;
  }

  async function remove() {
    if (!removing) return;
    const { id } = removing;
    await mutate(id, () => eneo.transcriptionServices.delete({ id }));
    services = services.filter((service) => service.id !== id);
    checks.delete(id);
    checkRuns.delete(id);
  }
</script>

<section aria-labelledby="{uid}-heading" class="flex flex-col gap-4 border-t p-4">
  <header class="flex flex-wrap items-start justify-between gap-3">
    <div>
      <h2 id="{uid}-heading" class="text-primary text-sm font-semibold tracking-tight">
        {m.speaker_identification()}
      </h2>
      <p class="text-secondary mt-1 max-w-3xl text-[0.8125rem] leading-relaxed">
        {m.speaker_service_intro()}
      </p>
    </div>
    <Button onclick={() => openDialog(null)}>
      <Plus data-icon="inline-start" />
      {m.speaker_service_connect()}
    </Button>
  </header>

  {#if services.length === 0}
    <Empty.Root>
      <Empty.Header>
        <Empty.Media variant="icon"><AudioLines /></Empty.Media>
        <Empty.Title>{m.speaker_service_empty_title()}</Empty.Title>
        <Empty.Description>{m.speaker_service_empty_description()}</Empty.Description>
      </Empty.Header>
    </Empty.Root>
  {:else}
    <div class="overflow-hidden rounded-lg border">
      <Table.Root>
        <Table.Header>
          <Table.Row>
            <Table.Head>{m.speaker_service_column_service()}</Table.Head>
            <Table.Head>{m.speaker_service_column_classification()}</Table.Head>
            <Table.Head>{m.speaker_service_column_connection()}</Table.Head>
            <Table.Head>{m.speaker_service_column_active()}</Table.Head>
            <Table.Head><span class="sr-only">{m.actions()}</span></Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each services as service (service.id)}
            {@const check = checks.get(service.id)}
            <Table.Row>
              <Table.Cell>
                <div class="flex min-w-0 flex-col">
                  <span class="font-medium">{service.name}</span>
                  <span class="text-muted-foreground truncate text-sm">
                    {host(service.endpoint_url)}
                  </span>
                </div>
              </Table.Cell>
              <Table.Cell>
                {#if service.security_classification}
                  {service.security_classification.name}
                {:else}
                  <span class="text-muted-foreground">
                    {m.speaker_service_classification_none()}
                  </span>
                {/if}
              </Table.Cell>
              <Table.Cell>
                {#if check === "checking"}
                  <span class="text-muted-foreground inline-flex items-center gap-1.5 text-sm">
                    <Spinner aria-hidden="true" />
                    {m.speaker_service_testing()}
                  </span>
                {:else if check}
                  <TranscriptionServiceCheckStatus {check} />
                {:else}
                  <span class="text-muted-foreground text-sm">
                    {m.speaker_service_not_tested()}
                  </span>
                {/if}
              </Table.Cell>
              <Table.Cell>
                <Switch
                  checked={service.is_enabled}
                  disabled={busy.has(service.id)}
                  onCheckedChange={(enabled) => setEnabled(service, enabled)}
                  aria-label={service.name}
                />
              </Table.Cell>
              <Table.Cell class="text-right">
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger>
                    {#snippet child({ props })}
                      <Button
                        {...props}
                        variant="ghost"
                        size="icon-sm"
                        aria-label={m.speaker_service_actions({ name: service.name })}
                      >
                        <Ellipsis />
                      </Button>
                    {/snippet}
                  </DropdownMenu.Trigger>
                  <DropdownMenu.Content align="end">
                    <DropdownMenu.Group>
                      <DropdownMenu.Item
                        disabled={busy.has(service.id)}
                        onclick={() => openDialog(service)}
                      >
                        <Pencil />
                        {m.edit()}
                      </DropdownMenu.Item>
                      <!-- Never disabled while it runs: an item that disables itself on
                           select keeps the menu open. -->
                      <DropdownMenu.Item onclick={() => runCheck(service.id)}>
                        <Plug />
                        {m.speaker_service_test()}
                      </DropdownMenu.Item>
                    </DropdownMenu.Group>
                    <DropdownMenu.Separator />
                    <DropdownMenu.Group>
                      <DropdownMenu.Item
                        variant="destructive"
                        disabled={busy.has(service.id)}
                        onclick={() => confirmRemove(service)}
                      >
                        <Trash2 />
                        {m.remove()}
                      </DropdownMenu.Item>
                    </DropdownMenu.Group>
                  </DropdownMenu.Content>
                </DropdownMenu.Root>
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </div>
  {/if}
</section>

{#key dialogKey}
  <TranscriptionServiceDialog
    bind:open={dialogOpen}
    service={editing}
    {classifications}
    check={editing ? checks.get(editing.id) : undefined}
    onCreate={create}
    onUpdate={update}
    onTest={() => editing && runCheck(editing.id)}
  />
{/key}

<ConfirmDialog
  bind:open={removeOpen}
  title={m.speaker_service_delete_title({ name: removing?.name ?? "" })}
  description={m.speaker_service_delete_description()}
  confirmLabel={m.remove()}
  pendingLabel={m.removing()}
  errorDisplay="inline"
  onConfirm={remove}
/>
