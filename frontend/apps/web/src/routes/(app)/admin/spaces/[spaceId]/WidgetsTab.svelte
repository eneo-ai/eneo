<!--
  The space's web widgets and whether anyone asked to activate them. Each
  links to its review, where an administrator activates it.
-->
<script lang="ts">
  import type { AdminSpaceWidgetRef } from "@eneo/eneo-js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { formatDateMedium } from "$lib/core/formatting/dateTime";
  import { activationRequestState, widgetStatusLabel } from "$lib/features/widget/admin/status";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  type Props = { widgets: readonly AdminSpaceWidgetRef[] };

  let { widgets }: Props = $props();
</script>

<!-- Only a draft or paused widget can be requested; for the others there is nothing to say. -->
{#snippet activation(widget: AdminSpaceWidgetRef)}
  {@const request = activationRequestState(widget)}
  {#if request.kind === "requested"}
    {m.admin_spaces_widget_requested({ date: formatDateMedium(request.at) })}
  {:else if request.kind === "not_applicable"}
    <span aria-hidden="true">–</span>
    <span class="sr-only">{m.admin_spaces_activation_not_applicable()}</span>
  {:else}
    {m.admin_spaces_widget_not_requested()}
  {/if}
{/snippet}

<section aria-labelledby="space-widgets-title" class="flex flex-col gap-4">
  <h2 id="space-widgets-title" class="text-lg font-semibold">{m.widget_admin_nav()}</h2>
  {#if widgets.length > 0}
    <div class="border-default bg-primary overflow-hidden rounded-lg border">
      <Table.Root
        class="[&_td]:px-3 [&_td]:py-3 [&_td]:align-top [&_td]:whitespace-normal [&_th]:px-3 [&_th]:whitespace-normal @3xl:[&_td]:px-4 @3xl:[&_th]:px-4"
      >
        <Table.Caption class="sr-only">{m.admin_spaces_widgets_caption()}</Table.Caption>
        <Table.Header>
          <Table.Row>
            <Table.Head scope="col">{m.admin_spaces_col_widget()}</Table.Head>
            <Table.Head scope="col" class="hidden @2xl:table-cell">
              {m.admin_spaces_col_assistant()}
            </Table.Head>
            <Table.Head scope="col">{m.status()}</Table.Head>
            <Table.Head scope="col" class="hidden @2xl:table-cell">
              {m.admin_spaces_col_activation()}
            </Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each widgets as widget (widget.id)}
            <Table.Row>
              <th scope="row" class="py-3 text-left align-top font-normal">
                <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed id -->
                <a
                  class="text-accent-stronger font-medium wrap-anywhere underline underline-offset-2"
                  href={localizeHref(`/admin/widgets/${widget.id}`)}>{widget.name}</a
                >
                <!-- eslint-enable svelte/no-navigation-without-resolve -->
                <span class="text-secondary block text-xs wrap-anywhere @2xl:hidden">
                  {widget.assistant?.name ?? m.admin_spaces_assistant_missing()}
                  {#if activationRequestState(widget).kind !== "not_applicable"}
                    · {@render activation(widget)}
                  {/if}
                </span>
              </th>
              <Table.Cell class="hidden wrap-anywhere @2xl:table-cell">
                {widget.assistant?.name ?? m.admin_spaces_assistant_missing()}
              </Table.Cell>
              <Table.Cell>{widgetStatusLabel(widget.status)}</Table.Cell>
              <Table.Cell class="hidden @2xl:table-cell">{@render activation(widget)}</Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </div>
  {:else}
    <div class="flex flex-col gap-1">
      <p>{m.admin_spaces_no_widgets()}</p>
      <p class="text-secondary max-w-[75ch] text-sm">{m.admin_spaces_no_widgets_help()}</p>
    </div>
  {/if}
</section>
