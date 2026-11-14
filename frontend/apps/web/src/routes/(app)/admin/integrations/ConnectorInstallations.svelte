<script lang="ts">
  import { onMount } from "svelte";
  import Check from "@lucide/svelte/icons/check";
  import Copy from "@lucide/svelte/icons/copy";
  import KeyRound from "@lucide/svelte/icons/key-round";
  import type { Eneo, components } from "@eneo/eneo-js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { toastError } from "$lib/core/errors";
  import { createCopyState } from "$lib/core/helpers/clipboard.svelte";
  import { formatDateTime } from "$lib/features/integrations/sharepoint/format";
  import { m } from "$lib/paraglide/messages";

  type Installation = components["schemas"]["ConnectorInstallationPublic"];
  type Created = components["schemas"]["ConnectorInstallationCreated"];

  interface Props {
    eneo: Eneo;
  }

  const { eneo }: Props = $props();
  const uid = $props.id();

  const ENDPOINT = "/api/v1/admin/connector-installations/";
  // What the administrator of the other system registers as Eneo's address.
  const connectorAddress = $derived(new URL("/api/v1/connector", eneo.client.baseUrl).toString());

  let installations = $state<Installation[]>([]);
  let name = $state("");
  let baseUrl = $state("");
  let adding = $state(false);
  // The answer to the latest add: the only time the key exists in the clear.
  let created = $state<Created | null>(null);
  let removing = $state<Installation | null>(null);
  let removeOpen = $state(false);
  const copiedAddress = createCopyState();
  const copiedKey = createCopyState();

  async function load() {
    try {
      const page = await eneo.client.fetch(ENDPOINT, { method: "get" });
      installations = page.items;
    } catch (error) {
      toastError(error, m.connector_installations_load_error());
    }
  }

  onMount(() => {
    void load();
  });

  async function add(event: SubmitEvent) {
    event.preventDefault();
    adding = true;
    try {
      created = await eneo.client.fetch(ENDPOINT, {
        method: "post",
        requestBody: { "application/json": { name, base_url: baseUrl } }
      });
      name = "";
      baseUrl = "";
      await load();
    } catch (error) {
      toastError(error, m.connector_installation_add_error());
    } finally {
      adding = false;
    }
  }

  async function remove() {
    if (!removing) return;
    await eneo.client.fetch("/api/v1/admin/connector-installations/{id}/", {
      method: "delete",
      params: { path: { id: removing.id } }
    });
    if (created?.id === removing.id) created = null;
    removing = null;
    await load();
  }
</script>

<div class="flex flex-col gap-6">
  {#if created}
    <Alert.Root>
      <KeyRound aria-hidden="true" />
      <Alert.Title>{m.connector_installation_added_title({ name: created.name })}</Alert.Title>
      <Alert.Description>
        <p>{m.connector_installation_added_description()}</p>
        <dl class="mt-3 grid w-full gap-3">
          <div class="flex flex-col gap-1">
            <dt class="text-sm font-medium">{m.connector_installation_eneo_address()}</dt>
            <dd class="flex items-center gap-2">
              <code class="bg-secondary rounded px-2 py-1 text-sm break-all">
                {connectorAddress}
              </code>
              <Button
                variant="outline"
                size="sm"
                onclick={() => copiedAddress.copy(connectorAddress)}
              >
                {#if copiedAddress.copied}
                  <Check aria-hidden="true" />{m.copied()}
                {:else}
                  <Copy aria-hidden="true" />{m.copy()}
                {/if}
              </Button>
            </dd>
          </div>
          <div class="flex flex-col gap-1">
            <dt class="text-sm font-medium">{m.connector_installation_key()}</dt>
            <dd class="flex items-center gap-2">
              <code class="bg-secondary rounded px-2 py-1 text-sm break-all">{created.key}</code>
              <Button
                variant="outline"
                size="sm"
                onclick={() => created && copiedKey.copy(created.key)}
              >
                {#if copiedKey.copied}
                  <Check aria-hidden="true" />{m.copied()}
                {:else}
                  <Copy aria-hidden="true" />{m.copy()}
                {/if}
              </Button>
            </dd>
          </div>
        </dl>
        <Button class="mt-3" variant="outline" size="sm" onclick={() => (created = null)}>
          {m.connector_installation_key_saved()}
        </Button>
      </Alert.Description>
    </Alert.Root>
  {/if}

  {#if installations.length > 0}
    <div class="border-default overflow-x-auto rounded-lg border">
      <Table.Root>
        <Table.Header>
          <Table.Row>
            <Table.Head>{m.name()}</Table.Head>
            <Table.Head>{m.connector_installation_address()}</Table.Head>
            <Table.Head>{m.created()}</Table.Head>
            <Table.Head><span class="sr-only">{m.actions()}</span></Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each installations as installation (installation.id)}
            <Table.Row>
              <Table.Cell class="font-medium">{installation.name}</Table.Cell>
              <Table.Cell class="break-all">{installation.base_url}</Table.Cell>
              <Table.Cell class="text-muted-foreground text-xs whitespace-nowrap">
                {formatDateTime(installation.created_at)}
              </Table.Cell>
              <Table.Cell class="text-right">
                <Button
                  variant="outline"
                  size="sm"
                  onclick={() => {
                    removing = installation;
                    removeOpen = true;
                  }}
                >
                  {m.remove()}
                </Button>
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </div>
  {:else}
    <p class="text-muted-foreground text-sm">{m.connector_installations_empty()}</p>
  {/if}

  <form class="flex flex-col gap-4" onsubmit={add}>
    <Field.Group>
      <Field.Field>
        <Field.Label for="{uid}-name">{m.name()}</Field.Label>
        <Input id="{uid}-name" bind:value={name} required maxlength={120} autocomplete="off" />
      </Field.Field>
      <Field.Field>
        <Field.Label for="{uid}-address">{m.connector_installation_address()}</Field.Label>
        <Input
          id="{uid}-address"
          type="url"
          bind:value={baseUrl}
          required
          autocomplete="off"
          aria-describedby="{uid}-address-help"
        />
        <Field.Description id="{uid}-address-help">
          {m.connector_installation_address_help()}
        </Field.Description>
      </Field.Field>
    </Field.Group>
    <div>
      <Button type="submit" disabled={adding}>{m.connector_installation_add()}</Button>
    </div>
  </form>
</div>

<ConfirmDialog
  bind:open={removeOpen}
  title={m.connector_installation_remove_title({ name: removing?.name ?? "" })}
  description={m.connector_installation_remove_description()}
  confirmLabel={m.remove()}
  errorContext={m.connector_installation_remove_error()}
  onConfirm={remove}
/>
