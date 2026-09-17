<script lang="ts">
  import type { Role } from "@eneo/eneo-js";
  import { resolve } from "$app/paths";
  import {
    Check,
    ChevronRight,
    LayoutTemplate,
    Minus,
    MoreHorizontal,
    Pencil,
    RotateCcw,
    Star,
    Trash2,
    Users
  } from "lucide-svelte";
  import { Badge, badgeVariants } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { summarizeGroups, type PermissionGroup } from "$lib/features/roles/permission-groups";
  import { m } from "$lib/paraglide/messages";

  let {
    role,
    groups,
    isDefault = false,
    onEdit,
    onDelete,
    onReset,
    onSetDefault
  }: {
    role: Role;
    groups: PermissionGroup[];
    isDefault?: boolean;
    onEdit: (role: Role) => void;
    onDelete: (role: Role) => void;
    onReset: (role: Role) => void;
    onSetDefault: (role: Role) => void;
  } = $props();

  const id = $props.id();
  let expanded = $state(false);

  const summary = $derived(summarizeGroups(groups, role.permissions));
  const granted = $derived(new Set<string>(role.permissions));
  const templateTooltip = $derived(
    role.predefined_source ? m.template_role_tooltip({ name: role.predefined_source }) : null
  );
</script>

<li class="px-4 py-3">
  <div class="flex items-start gap-2">
    <Button
      variant="ghost"
      size="icon-sm"
      class="mt-0.5 shrink-0"
      aria-expanded={expanded}
      aria-controls="{id}-permissions"
      onclick={() => (expanded = !expanded)}
    >
      <ChevronRight
        aria-hidden="true"
        class={expanded ? "rotate-90 transition-transform" : "transition-transform"}
      />
      <span class="sr-only">
        {expanded
          ? m.roles_hide_permissions({ name: role.name })
          : m.roles_show_permissions({ name: role.name })}
      </span>
    </Button>

    <div class="min-w-0 flex-1">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-base font-medium">{role.name}</span>
        <Tooltip.Provider delayDuration={150}>
          {#if isDefault}
            <Tooltip.Root>
              <Tooltip.Trigger class={badgeVariants({ variant: "default" })}>
                <Star aria-hidden="true" data-icon="inline-start" />
                {m.roles_default_badge()}
                <span class="sr-only">. {m.roles_default_badge_tooltip()}</span>
              </Tooltip.Trigger>
              <Tooltip.Content>{m.roles_default_badge_tooltip()}</Tooltip.Content>
            </Tooltip.Root>
          {/if}
          {#if templateTooltip}
            <Tooltip.Root>
              <Tooltip.Trigger class={badgeVariants({ variant: "outline" })}>
                <LayoutTemplate aria-hidden="true" data-icon="inline-start" />
                {m.roles_template_badge()}
                <span class="sr-only">. {templateTooltip}</span>
              </Tooltip.Trigger>
              <Tooltip.Content>{templateTooltip}</Tooltip.Content>
            </Tooltip.Root>
          {/if}
        </Tooltip.Provider>
      </div>

      <ul class="mt-2 flex flex-wrap gap-1.5" aria-label={m.roles_group_summary_label()}>
        {#each summary as area (area.id)}
          {@const coverage =
            area.granted === 0 ? "none" : area.granted === area.total ? "all" : "some"}
          <li>
            <Badge
              variant={coverage === "all" ? "secondary" : "outline"}
              class={[coverage === "none" && "text-muted border-dashed"]}
            >
              {#if coverage === "all"}
                <Check class="text-positive-stronger" aria-hidden="true" />
              {:else if coverage === "none"}
                <Minus aria-hidden="true" />
              {/if}
              {area.shortLabel}
              <span class="tabular-nums" aria-hidden="true">{area.granted}/{area.total}</span>
              <span class="sr-only"
                >{m.roles_group_count({ granted: area.granted, total: area.total })}</span
              >
            </Badge>
          </li>
        {/each}
      </ul>
    </div>

    <div class="flex shrink-0 items-center gap-1">
      <Button variant="outline" size="sm" onclick={() => onEdit(role)}>
        <Pencil aria-hidden="true" data-icon="inline-start" />
        {m.edit()}
      </Button>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger>
          {#snippet child({ props })}
            <Button {...props} variant="ghost" size="icon-sm">
              <MoreHorizontal aria-hidden="true" />
              <span class="sr-only">{m.roles_more_actions({ name: role.name })}</span>
            </Button>
          {/snippet}
        </DropdownMenu.Trigger>
        <DropdownMenu.Content align="end">
          <DropdownMenu.Item>
            {#snippet child({ props })}
              <!-- eslint-disable svelte/no-navigation-without-resolve -- resolved route plus a query string, which resolve() cannot express -->
              <a
                {...props}
                href={resolve("/admin/users") + `?role_id=${encodeURIComponent(role.id)}`}
              >
                <Users aria-hidden="true" />
                {m.roles_view_users()}
              </a>
              <!-- eslint-enable svelte/no-navigation-without-resolve -->
            {/snippet}
          </DropdownMenu.Item>
          {#if !isDefault}
            <DropdownMenu.Item onSelect={() => onSetDefault(role)}>
              <Star aria-hidden="true" />
              {m.set_as_default_role()}
            </DropdownMenu.Item>
          {/if}
          {#if role.predefined_source}
            <DropdownMenu.Item onSelect={() => onReset(role)}>
              <RotateCcw aria-hidden="true" />
              {m.reset_to_template()}
            </DropdownMenu.Item>
          {/if}
          <DropdownMenu.Separator />
          <DropdownMenu.Item
            variant="destructive"
            disabled={isDefault}
            onSelect={() => onDelete(role)}
          >
            <Trash2 aria-hidden="true" />
            {m.delete_role()}
          </DropdownMenu.Item>
          {#if isDefault}
            <p class="text-muted max-w-56 px-1.5 pb-1 text-xs">{m.roles_cannot_delete_default()}</p>
          {/if}
        </DropdownMenu.Content>
      </DropdownMenu.Root>
    </div>
  </div>

  {#if expanded}
    <div
      id="{id}-permissions"
      class="mt-3 grid gap-x-6 gap-y-4 pl-9 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5"
    >
      {#each groups as group (group.id)}
        <section aria-labelledby="{id}-{group.id}">
          <span
            id="{id}-{group.id}"
            class="text-secondary block text-xs font-medium tracking-wide uppercase"
            >{group.label}</span
          >
          <ul class="mt-1.5 space-y-1">
            {#each group.permissions as permission (permission.name)}
              {@const held = granted.has(permission.name)}
              <li class={["flex items-center gap-1.5 text-sm", !held && "text-muted"]}>
                {#if held}
                  <Check class="text-positive-stronger size-3.5 shrink-0" aria-hidden="true" />
                {:else}
                  <Minus class="size-3.5 shrink-0" aria-hidden="true" />
                {/if}
                <span class="sr-only">
                  {held ? m.roles_permission_included() : m.roles_permission_not_included()}
                </span>
                {permission.label}
              </li>
            {/each}
          </ul>
        </section>
      {/each}
    </div>
  {/if}
</li>
