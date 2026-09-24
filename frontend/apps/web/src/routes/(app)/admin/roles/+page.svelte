<!--
  Admin → Roles. Each role is one row: name, badges and a per-area summary
  of its permissions, expandable to the full list. Editing happens in a
  dialog; destructive or tenant-wide actions confirm first.
-->
<script lang="ts">
  import type { Role } from "@eneo/eneo-js";
  import { invalidate } from "$app/navigation";
  import { Search } from "@lucide/svelte";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { Page } from "$lib/components/layout";
  import { toast } from "$lib/components/toast";
  import * as Card from "$lib/components/ui/card/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { getAppContext } from "$lib/core/AppContext";
  import { getEneo } from "$lib/core/Eneo";
  import { groupPermissions, roleMatches, sortRoles } from "$lib/features/roles/permission-groups";
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
  const visible = $derived(
    sortRoles(data.roles, defaultRoleId, getLocale()).filter((role) =>
      roleMatches(role, groups, query)
    )
  );
  const defaultRole = $derived(data.roles.find((role) => role.id === defaultRoleId) ?? null);

  let editorOpen = $state(false);
  let editing = $state<Role | null>(null);

  function edit(role: Role) {
    editing = role;
    editorOpen = true;
  }

  type PendingAction = { kind: "delete" | "reset" | "default"; role: Role };
  // Kept after the dialog closes so its text does not vanish mid-animation.
  let pending = $state<PendingAction | null>(null);
  let confirmOpen = $state(false);

  function requestAction(kind: PendingAction["kind"], role: Role) {
    pending = { kind, role };
    confirmOpen = true;
  }

  async function runPending() {
    if (!pending) return;
    const { kind, role } = pending;
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
    await invalidate("admin:roles:load");
  }

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

<Page.Root>
  <Page.Header>
    <Page.Title title={m.roles()} tour="admin-roles" />
    <RoleEditor mode="create" permissions={data.permissions} templates={data.templates} />
  </Page.Header>

  <Page.Main>
    <div class="mx-auto flex w-full max-w-[1100px] flex-col gap-6 py-6 pr-6">
      <div class="flex flex-wrap items-end justify-between gap-4">
        <div class="text-secondary max-w-[72ch] text-sm">
          <p>{m.roles_page_description()} {m.roles_template_note()}</p>
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

      <Card.Root>
        <Card.Content>
          {#if visible.length === 0}
            <p class="text-secondary text-sm" role="status">{m.roles_no_match({ query })}</p>
          {:else}
            <ul class="divide-default -mx-4 -my-4 divide-y" aria-label={m.roles()}>
              {#each visible as role (role.id)}
                <RoleRow
                  {role}
                  {groups}
                  isDefault={role.id === defaultRoleId}
                  onEdit={edit}
                  onDelete={(target) => requestAction("delete", target)}
                  onReset={(target) => requestAction("reset", target)}
                  onSetDefault={(target) => requestAction("default", target)}
                />
              {/each}
            </ul>
          {/if}
        </Card.Content>
      </Card.Root>
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

{#if confirmCopy}
  <ConfirmDialog
    bind:open={confirmOpen}
    title={confirmCopy.title}
    description={confirmCopy.description}
    confirmLabel={confirmCopy.action}
    variant={confirmCopy.destructive ? "destructive" : "default"}
    onConfirm={runPending}
  />
{/if}
