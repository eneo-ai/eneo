<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { Button, Dropdown } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { invalidate } from "$app/navigation";
  import { writable, type Writable } from "svelte/store";
  import { Pencil, Trash2, RefreshCw } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import MCPServerDialog from "./MCPServerDialog.svelte";
  import DeleteMCPDialog from "./DeleteMCPDialog.svelte";

  type Props = {
    mcpServer: any;
  };

  const { mcpServer }: Props = $props();

  const intric = getIntric();

  const showEditDialog: Writable<boolean> = writable(false);
  const showDeleteDialog: Writable<boolean> = writable(false);

  let syncing = $state(false);

  async function handleSave(data: any, id?: string) {
    if (id) {
      await intric.mcpServers.update({ id, ...data });
    }
    await Promise.all([invalidate("admin:layout"), invalidate("spaces:data")]);
  }

  async function handleDelete(id: string) {
    await intric.mcpServers.delete({ id });
    await Promise.all([invalidate("admin:layout"), invalidate("spaces:data")]);
  }

  async function syncTools() {
    syncing = true;
    try {
      await intric.mcpServers.syncTools({ mcp_server_id: mcpServer.mcp_server_id });
      await invalidate("spaces:data");
    } catch (error) {
      console.error("Failed to sync tools:", error);
    } finally {
      syncing = false;
    }
  }
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <Button variant="on-fill" is={trigger} disabled={false} padding="icon">
      <IconEllipsis />
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    <Button
      is={item}
      padding="icon-leading"
      onclick={() => {
        $showEditDialog = true;
      }}
    >
      <Pencil class="h-4 w-4" />{m.edit()}
    </Button>
    <Button is={item} padding="icon-leading" onclick={syncTools} disabled={syncing}>
      <RefreshCw class="h-4 w-4 {syncing ? 'animate-spin' : ''}" />
      {syncing ? "Syncing..." : "Sync Tools"}
    </Button>
    <Button
      is={item}
      padding="icon-leading"
      variant="destructive"
      onclick={() => {
        $showDeleteDialog = true;
      }}
    >
      <Trash2 class="h-4 w-4" />{m.delete()}
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

<MCPServerDialog openController={showEditDialog} {mcpServer} onSubmit={handleSave} />
<DeleteMCPDialog openController={showDeleteDialog} {mcpServer} onDelete={handleDelete} />
