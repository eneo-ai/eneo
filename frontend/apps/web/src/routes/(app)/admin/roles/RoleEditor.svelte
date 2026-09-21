<script lang="ts">
  import type { Permission, Role } from "@eneo/eneo-js";
  import { invalidate } from "$app/navigation";
  import { Plus } from "lucide-svelte";
  import { untrack } from "svelte";
  import { toast } from "$lib/components/toast";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import {
    groupPermissions,
    sameSet,
    type PermissionGroup
  } from "$lib/features/roles/permission-groups";
  import { m } from "$lib/paraglide/messages";

  type Template = { name: string; permissions: string[] };

  let {
    mode = "create",
    role = null,
    permissions,
    templates = [],
    open = $bindable(false),
    hideTrigger = false
  }: {
    mode?: "create" | "update";
    role?: Role | null;
    permissions: Array<{ name: Permission; description: string }>;
    templates?: Template[];
    open?: boolean;
    hideTrigger?: boolean;
  } = $props();

  const eneo = getEneo();
  const id = $props.id();
  const groups = $derived(groupPermissions(permissions));

  let name = $state("");
  let selected = $state<Permission[]>([]);
  let pending = $state(false);
  let nameInput = $state<HTMLInputElement | null>(null);

  function resetForm() {
    name = role?.name ?? "";
    selected = [...(role?.permissions ?? [])];
  }
  $effect(() => {
    if (open) untrack(resetForm);
  });

  const nameChanged = $derived(name.trim() !== (role?.name ?? "").trim());
  const permissionsChanged = $derived(!sameSet(selected, role?.permissions ?? []));
  const dirty = $derived(mode === "create" || nameChanged || permissionsChanged);
  const canSubmit = $derived(!pending && name.trim().length > 0 && dirty);

  function setPermission(permission: Permission, on: boolean) {
    if (on) {
      if (!selected.includes(permission)) selected = [...selected, permission];
    } else {
      selected = selected.filter((current) => current !== permission);
    }
  }

  function setGroup(group: PermissionGroup, on: boolean) {
    const names = group.permissions.map((permission) => permission.name);
    selected = on
      ? [...new Set([...selected, ...names])]
      : selected.filter((current) => !names.includes(current));
  }

  function grantedIn(group: PermissionGroup) {
    return group.permissions.filter((permission) => selected.includes(permission.name)).length;
  }

  function applyTemplate(template: Template) {
    selected = [...template.permissions] as Permission[];
  }

  function handleOpenChange(next: boolean) {
    if (!pending) open = next;
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    pending = true;
    const trimmed = name.trim();
    try {
      if (mode === "create") {
        await eneo.roles.create({ name: trimmed, permissions: selected });
        toast.success(m.roles_created_toast({ name: trimmed }));
      } else if (role) {
        await eneo.roles.update({
          role: { id: role.id },
          update: {
            ...(nameChanged ? { name: trimmed } : {}),
            ...(permissionsChanged ? { permissions: selected } : {})
          }
        });
        toast.success(m.roles_saved_toast({ name: trimmed }));
      }
      open = false;
      await invalidate("admin:roles:load");
    } catch (error) {
      toastError(error);
    } finally {
      pending = false;
    }
  }
</script>

<Dialog.Root {open} onOpenChange={handleOpenChange}>
  {#if !hideTrigger}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props}>
          <Plus aria-hidden="true" data-icon="inline-start" />
          {m.create_role()}
        </Button>
      {/snippet}
    </Dialog.Trigger>
  {/if}

  <Dialog.Content
    class="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl"
    closeLabel={m.close()}
    showCloseButton={!pending}
    onOpenAutoFocus={(event) => {
      if (mode === "create") {
        event.preventDefault();
        nameInput?.focus();
      }
    }}
    onEscapeKeydown={(event) => {
      if (pending) event.preventDefault();
    }}
    onInteractOutside={(event) => {
      if (pending) event.preventDefault();
    }}
  >
    <Dialog.Header>
      <Dialog.Title>{mode === "create" ? m.create_a_new_role() : m.edit_role()}</Dialog.Title>
      <Dialog.Description>{m.what_users_of_this_role_can_manage()}</Dialog.Description>
    </Dialog.Header>

    <form onsubmit={submit} aria-busy={pending} class="flex flex-col gap-5">
      <fieldset disabled={pending} class="flex flex-col gap-5">
        <Field.Field>
          <Field.Label for="{id}-name">{m.role_name()}</Field.Label>
          <Input
            id="{id}-name"
            bind:ref={nameInput}
            bind:value={name}
            required
            autocomplete="off"
            aria-describedby="{id}-name-help"
          />
          <Field.Description id="{id}-name-help">
            {m.descriptive_name_for_this_role()}
          </Field.Description>
        </Field.Field>

        {#if mode === "create" && templates.length > 0}
          <div>
            <p id="{id}-templates" class="text-sm font-medium">{m.start_from_template()}</p>
            <p class="text-secondary text-sm">{m.roles_template_hint()}</p>
            <div class="mt-2 flex flex-wrap gap-2" role="group" aria-labelledby="{id}-templates">
              {#each templates as template (template.name)}
                {@const active = sameSet(selected, template.permissions)}
                <Button
                  type="button"
                  size="sm"
                  variant={active ? "secondary" : "outline"}
                  aria-pressed={active}
                  onclick={() => applyTemplate(template)}
                >
                  {template.name}
                </Button>
              {/each}
            </div>
          </div>
        {/if}

        <div class="flex flex-col gap-3">
          <p class="text-sm font-medium">{m.included_permissions()}</p>
          {#each groups as group (group.id)}
            {@const granted = grantedIn(group)}
            {@const all = granted === group.permissions.length}
            <Field.Set class="border-default gap-0 overflow-hidden rounded-lg border">
              <Field.Legend class="sr-only">{group.label}</Field.Legend>
              <div
                class="border-default bg-secondary/60 flex items-center justify-between gap-3 border-b px-3 py-2"
              >
                <span class="text-sm font-medium">
                  {group.label}
                  <span class="text-secondary font-normal tabular-nums"
                    >{granted}/{group.permissions.length}</span
                  >
                </span>
                <div class="flex items-center gap-2">
                  <Label for="{id}-{group.id}-all" class="text-secondary text-xs font-normal">
                    {m.roles_select_all()}
                  </Label>
                  <Checkbox
                    id="{id}-{group.id}-all"
                    checked={all}
                    indeterminate={granted > 0 && !all}
                    aria-label={m.roles_select_all_in_group({ group: group.label })}
                    onCheckedChange={(checked) => setGroup(group, checked === true)}
                  />
                </div>
              </div>
              <div class="divide-default divide-y">
                {#each group.permissions as permission (permission.name)}
                  <Field.Field orientation="horizontal" class="px-3 py-2.5">
                    <Field.Content>
                      <Field.Label for="{id}-{permission.name}">{permission.label}</Field.Label>
                      <Field.Description>{permission.description}</Field.Description>
                    </Field.Content>
                    <Switch
                      id="{id}-{permission.name}"
                      checked={selected.includes(permission.name)}
                      onCheckedChange={(checked) => setPermission(permission.name, checked)}
                    />
                  </Field.Field>
                {/each}
              </div>
            </Field.Set>
          {/each}
        </div>
      </fieldset>

      <Dialog.Footer class="sticky -bottom-4 flex-row items-center justify-between gap-3 py-3">
        <span class="text-secondary text-sm tabular-nums" aria-live="polite" aria-atomic="true">
          {m.permissions_selected_count({ selected: selected.length, total: permissions.length })}
        </span>
        <div class="flex gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={pending}
            onclick={() => handleOpenChange(false)}>{m.cancel()}</Button
          >
          <Button type="submit" disabled={!canSubmit}>
            {pending ? m.saving() : mode === "create" ? m.create_role() : m.save_changes()}
          </Button>
        </div>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
