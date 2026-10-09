<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  The organisation's speaker identification services, as the second section of
  the transcription tab. This list owns every change: each is saved as it is
  made and applied from the response, one at a time per service, so a late
  answer never undoes a later change or brings back a removed service. The
  latest check is stored with the service, so every administrator sees it.
-->

<script lang="ts">
  import type {
    SecurityClassification,
    TranscriptionService,
    TranscriptionServiceCreate,
    TranscriptionServiceUpdate
  } from "@eneo/eneo-js";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";
  import { invalidate } from "$app/navigation";
  import AudioLines from "@lucide/svelte/icons/audio-lines";
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Plug from "@lucide/svelte/icons/plug";
  import Plus from "@lucide/svelte/icons/plus";
  import Trash2 from "@lucide/svelte/icons/trash-2";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Empty from "$lib/components/ui/empty/index.js";
  import { Spinner } from "$lib/components/ui/spinner/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { toastError } from "$lib/core/errors";
  import { getEneo } from "$lib/core/Eneo";
  import { formatDateTime, formatRelativeTime } from "$lib/core/formatting/dateTime";
  import { m } from "$lib/paraglide/messages";
  import TranscriptionServiceCheckStatus from "./TranscriptionServiceCheckStatus.svelte";
  import TranscriptionServiceDialog from "./TranscriptionServiceDialog.svelte";

  type Props = {
    /** Null when the list could not be read. */
    services: TranscriptionService[] | null;
    classifications: SecurityClassification[];
  };

  let { services: loaded, classifications }: Props = $props();

  const eneo = getEneo();
  const uid = $props.id();

  // The loaded list, then every change this page saves to it.
  let services = $derived(loaded ?? []);
  const loadFailed = $derived(loaded === null);
  const checking = new SvelteSet<string>();
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
  let disableOpen = $state(false);
  let disabling = $state<TranscriptionService | null>(null);

  function host(url: string): string {
    try {
      return new URL(url).host;
    } catch {
      return url;
    }
  }

  // Lets "Testad för 2 minuter sedan" age while the page stays open.
  let now = $state(Date.now());
  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), 60_000);
    return () => clearInterval(timer);
  });

  // A server clock slightly ahead of this one must not read "om 2 sekunder".
  function checkedAgo(checkedAt: string): string {
    return formatRelativeTime(Math.min(Date.parse(checkedAt), now), now);
  }

  function spaceUsage(count: number): string {
    if (count === 0) return m.speaker_service_used_in_none();
    return count === 1
      ? m.speaker_service_used_in_one({ count })
      : m.speaker_service_used_in({ count });
  }

  // Changes a service still in the list; one that has left it stays gone.
  function patch(id: string, fields: Partial<TranscriptionService>): boolean {
    if (!services.some((service) => service.id === id)) return false;
    services = services.map((service) => (service.id === id ? { ...service, ...fields } : service));
    return true;
  }

  // Applies a saved service as the server returned it, its check included:
  // the server clears a check whose address or key changed, by anyone. A
  // check still running tested settings this answer may have replaced, so its
  // result is dropped; a new address or key starts a fresh one.
  function replace(next: TranscriptionService): boolean {
    if (!patch(next.id, next)) return false;
    checkRuns.set(next.id, (checkRuns.get(next.id) ?? 0) + 1);
    checking.delete(next.id);
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
    checking.add(id);
    try {
      const result = await eneo.transcriptionServices.check({ id });
      if (checkRuns.get(id) === run) {
        now = Date.now();
        patch(id, { last_check: result });
      }
    } catch (error) {
      if (checkRuns.get(id) === run) toastError(error);
    } finally {
      if (checkRuns.get(id) === run) checking.delete(id);
    }
  }

  async function saveEnabled(id: string, enabled: boolean) {
    replace(
      await mutate(id, () => eneo.transcriptionServices.update({ id }, { is_enabled: enabled }))
    );
  }

  // Switching on, or off for a service no space uses, happens at once and is
  // undone if the save fails. Switching off a service in use asks first.
  async function setEnabled(service: TranscriptionService, enabled: boolean) {
    if (busy.has(service.id)) return;
    if (!enabled && service.space_count > 0) {
      disabling = service;
      disableOpen = true;
      return;
    }
    patch(service.id, { is_enabled: enabled });
    try {
      await saveEnabled(service.id, enabled);
    } catch (error) {
      patch(service.id, { is_enabled: !enabled });
      toastError(error);
    }
  }

  // A new service is tested at once; the dialog stays open to show the result.
  async function create(body: TranscriptionServiceCreate): Promise<TranscriptionService> {
    const created = await eneo.transcriptionServices.create(body);
    services = [...services, created];
    editing = created;
    void runCheck(created.id);
    return created;
  }

  // Only a new address or key changes what a check would find.
  async function update(
    id: string,
    body: TranscriptionServiceUpdate
  ): Promise<TranscriptionService> {
    const retest = "endpoint_url" in body || "api_key" in body;
    const updated = await mutate(id, () => eneo.transcriptionServices.update({ id }, body));
    if (replace(updated) && retest) void runCheck(id);
    return updated;
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
    checking.delete(id);
    checkRuns.delete(id);
  }

  async function disable() {
    if (disabling) await saveEnabled(disabling.id, false);
  }

  const editingNow = $derived(
    editing ? services.find((service) => service.id === editing?.id) : undefined
  );
</script>

<section
  aria-labelledby="{uid}-heading"
  class="flex flex-col gap-4 border-t py-4"
  data-tour="admin-speaker-identification"
>
  <header class="flex flex-wrap items-start justify-between gap-3">
    <div>
      <h2 id="{uid}-heading" class="text-primary text-sm font-semibold tracking-tight">
        {m.speaker_identification()}
      </h2>
      <p class="text-secondary mt-1 max-w-3xl text-[0.8125rem] leading-relaxed">
        {m.speaker_service_intro()}
      </p>
    </div>
    {#if !loadFailed}
      <Button onclick={() => openDialog(null)}>
        <Plus data-icon="inline-start" />
        {m.speaker_service_connect()}
      </Button>
    {/if}
  </header>

  {#if loadFailed}
    <Alert.Root variant="destructive">
      <CircleAlert />
      <Alert.Title>{m.speaker_service_list_failed()}</Alert.Title>
      <Alert.Description>
        <Button variant="outline" size="sm" onclick={() => invalidate("admin:models:load")}>
          {m.retry()}
        </Button>
      </Alert.Description>
    </Alert.Root>
  {:else if services.length === 0}
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
            <Table.Row>
              <Table.Cell>
                <div class="flex min-w-0 flex-col">
                  <span class="font-medium">{service.name}</span>
                  <span class="text-muted-foreground truncate text-sm">
                    {host(service.endpoint_url)} · {spaceUsage(service.space_count)}
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
                {#if checking.has(service.id)}
                  <span class="text-muted-foreground inline-flex items-center gap-1.5 text-sm">
                    <Spinner aria-hidden="true" />
                    {m.speaker_service_testing()}
                  </span>
                {:else if service.last_check}
                  <div class="flex flex-col items-start">
                    <TranscriptionServiceCheckStatus check={service.last_check} />
                    <time
                      class="text-muted-foreground text-xs"
                      datetime={service.last_check.checked_at}
                      title={formatDateTime(service.last_check.checked_at)}
                    >
                      {m.speaker_service_checked({
                        when: checkedAgo(service.last_check.checked_at)
                      })}
                    </time>
                  </div>
                {:else}
                  <span class="text-muted-foreground text-sm">
                    {m.speaker_service_not_tested()}
                  </span>
                {/if}
              </Table.Cell>
              <Table.Cell>
                <Switch
                  bind:checked={() => service.is_enabled, (enabled) => setEnabled(service, enabled)}
                  disabled={busy.has(service.id)}
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
    check={editingNow?.last_check ?? undefined}
    checking={editingNow ? checking.has(editingNow.id) : false}
    onCreate={create}
    onUpdate={update}
    onTest={() => editing && runCheck(editing.id)}
  />
{/key}

<ConfirmDialog
  bind:open={disableOpen}
  title={m.speaker_service_disable_title({ name: disabling?.name ?? "" })}
  description={disabling?.space_count === 1
    ? m.speaker_service_disable_description_one({ count: 1 })
    : m.speaker_service_disable_description({ count: disabling?.space_count ?? 0 })}
  confirmLabel={m.speaker_service_disable_confirm()}
  pendingLabel={m.speaker_service_disabling()}
  errorDisplay="inline"
  onConfirm={disable}
/>

<ConfirmDialog
  bind:open={removeOpen}
  title={m.speaker_service_delete_title({ name: removing?.name ?? "" })}
  description={removing && removing.space_count > 0
    ? `${spaceUsage(removing.space_count)}. ${m.speaker_service_delete_description()}`
    : m.speaker_service_delete_description()}
  confirmLabel={m.remove()}
  pendingLabel={m.removing()}
  errorDisplay="inline"
  onConfirm={remove}
/>
