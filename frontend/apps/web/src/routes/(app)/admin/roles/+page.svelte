<!--
  Admin → Roles. Each role is one row: name, badges and a per-area summary
  of its permissions, expandable to the full list. Editing happens in a
  dialog; destructive or tenant-wide actions confirm first.
-->
<script lang="ts">
  import type { Role } from "@eneo/eneo-js";
  import { invalidate } from "$app/navigation";
  import { Search } from "lucide-svelte";
  import { Page } from "$lib/components/layout";
  import { toast } from "$lib/components/toast";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { getAppContext } from "$lib/core/AppContext";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { groupPermissions, roleMatches } from "$lib/features/roles/permission-groups";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import RoleEditor from "./RoleEditor.svelte";
  import RoleRow from "./RoleRow.svelte";

  let { data } = $props();

  const eneo = getEneo();
  const { tenant, updateTenant } = getAppContext();

  let defaultRoleId = $state<string | null>(tenant.default_role_id ?? null);
  let query = $state("");

  const groups = $derived(groupPermissions(data.permissions));
  const templateRank = $derived(
    new Map(data.templates.map((template, index) => [template.name, index] as const))
  );

  function compareRoles(a: Role, b: Role) {
    if (a.id === defaultRoleId) return -1;
    if (b.id === defaultRoleId) return 1;
    const rankA = templateRank.get(a.predefined_source ?? "") ?? Number.MAX_SAFE_INTEGER;
    const rankB = templateRank.get(b.predefined_source ?? "") ?? Number.MAX_SAFE_INTEGER;
    if (rankA !== rankB) return rankA - rankB;
    return a.name.localeCompare(b.name, getLocale());
  }

  const visible = $derived(
    [...data.roles].sort(compareRoles).filter((role) => roleMatches(role, groups, query))
  );
  const builtIn = $derived(visible.filter((role) => role.predefined_source));
  const custom = $derived(visible.filter((role) => !role.predefined_source));
  const defaultRole = $derived(data.roles.find((role) => role.id === defaultRoleId) ?? null);

  let editorOpen = $state(false);
  let editing = $state<Role | null>(null);

  function edit(role: Role) {
    editing = role;
    editorOpen = true;
  }

  type PendingAction = { kind: "delete" | "reset" | "default"; role: Role };
  let pending = $state<PendingAction | null>(null);

  const run = createAsyncState(async () => {
    const action = pending;
    if (!action) return;
    const { kind, role } = action;
    try {
      if (kind === "delete") {
        await eneo.roles.delete(role);
        toast.success(m.roles_deleted_toast({ name: role.name }));
      } else if (kind === "reset") {
        await eneo.roles.resetToDefault(role);
        toast.success(m.roles_reset_toast({ name: role.name }));
      } else {
        await eneo.roles.setAsDefault(role);
        defaultRoleId = role.id;
        updateTenant({ default_role_id: role.id });
        toast.success(m.roles_default_toast({ name: role.name }));
      }
      pending = null;
      await invalidate("admin:roles:load");
    } catch (error) {
      toastError(error);
    }
  });

  const confirmCopy = $derived.by(() => {
    if (!pending) return null;
    const name = pending.role.name;
    switch (pending.kind) {
      case "delete":
        return {
          title: m.delete_role(),
          description: m.roles_delete_description({ name }),
          action: m.delete(),
          destructive: true
        };
      case "reset":
        return {
          title: m.reset_to_template(),
          description: m.reset_to_template_description({ name }),
          action: m.reset(),
          destructive: false
        };
      case "default":
        return {
          title: m.set_as_default_role(),
          description: m.set_as_default_role_description({ name }),
          action: m.confirm(),
          destructive: false
        };
    }
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.roles()}</title>
</svelte:head>

{#snippet roleList(roles: Role[], label: string)}
  <ul class="divide-default -mx-4 -my-4 divide-y" aria-label={label}>
    {#each roles as role (role.id)}
      <RoleRow
        {role}
        {groups}
        isDefault={role.id === defaultRoleId}
        onEdit={edit}
        onDelete={(target) => (pending = { kind: "delete", role: target })}
        onReset={(target) => (pending = { kind: "reset", role: target })}
        onSetDefault={(target) => (pending = { kind: "default", role: target })}
      />
    {/each}
  </ul>
{/snippet}

<Page.Root>
  <Page.Header>
    <Page.Title title={m.roles()} />
    <RoleEditor mode="create" permissions={data.permissions} templates={data.templates} />
  </Page.Header>

  <Page.Main>
    <div class="mx-auto flex w-full max-w-[1100px] flex-col gap-6 py-6 pr-6">
      <div class="flex flex-wrap items-end justify-between gap-4">
        <div class="text-secondary max-w-[72ch] text-sm">
          <p>{m.roles_page_description()}</p>
          <p class="mt-1">
            {#if defaultRole}
              {m.roles_default_role_note({ name: defaultRole.name })}
            {:else}
              {m.roles_no_default_role_note()}
            {/if}
          </p>
        </div>
        <div class="relative w-full sm:w-72">
          <Search
            class="text-muted pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2"
            aria-hidden="true"
          />
          <Input
            type="search"
            class="pl-8"
            placeholder={m.roles_search_placeholder()}
            aria-label={m.roles_search_label()}
            bind:value={query}
          />
        </div>
      </div>

      {#if visible.length === 0}
        <p class="text-secondary text-sm" role="status">{m.roles_no_match({ query })}</p>
      {/if}

      {#if builtIn.length > 0}
        <Card.Root>
          <Card.Header class="border-b">
            <Card.Title>{m.roles_builtin_section()}</Card.Title>
            <Card.Description>{m.roles_builtin_section_description()}</Card.Description>
          </Card.Header>
          <Card.Content>
            {@render roleList(builtIn, m.roles_builtin_section())}
          </Card.Content>
        </Card.Root>
      {/if}

      {#if custom.length > 0 || !query.trim()}
        <Card.Root>
          <Card.Header class="border-b">
            <Card.Title>{m.roles_custom_section()}</Card.Title>
            <Card.Description>{m.roles_custom_section_description()}</Card.Description>
          </Card.Header>
          <Card.Content>
            {#if custom.length === 0}
              <p class="text-secondary text-sm">{m.roles_custom_empty()}</p>
            {:else}
              {@render roleList(custom, m.roles_custom_section())}
            {/if}
          </Card.Content>
        </Card.Root>
      {/if}
    </div>
  </Page.Main>
</Page.Root>

<RoleEditor
  mode="update"
  role={editing}
  permissions={data.permissions}
  bind:open={editorOpen}
  hideTrigger
/>

<AlertDialog.Root
  open={pending !== null}
  onOpenChange={(open) => {
    if (!open && !run.isLoading) pending = null;
  }}
>
  {#if confirmCopy}
    <AlertDialog.Content>
      <AlertDialog.Header>
        <AlertDialog.Title>{confirmCopy.title}</AlertDialog.Title>
        <AlertDialog.Description>{confirmCopy.description}</AlertDialog.Description>
      </AlertDialog.Header>
      <AlertDialog.Footer>
        <AlertDialog.Cancel disabled={run.isLoading}>{m.cancel()}</AlertDialog.Cancel>
        <AlertDialog.Action
          class={[confirmCopy.destructive && "bg-negative-default text-on-fill"]}
          disabled={run.isLoading}
          onclick={(event) => {
            event.preventDefault();
            void run();
          }}>{confirmCopy.action}</AlertDialog.Action
        >
      </AlertDialog.Footer>
    </AlertDialog.Content>
  {/if}
</AlertDialog.Root>
