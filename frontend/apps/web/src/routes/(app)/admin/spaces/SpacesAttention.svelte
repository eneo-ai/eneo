<!--
  What needs an organisation administrator across the spaces: spaces nobody
  can manage, and web widgets waiting for activation. Always present, so an
  empty section confirms that nothing is waiting.
-->
<script lang="ts">
  import type { AdminSpaceListItem, AdminWidgetRequestRef } from "@eneo/eneo-js";
  import { ArrowRight, CircleCheck, Inbox, TriangleAlert } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { formatDateMedium, intlLocale } from "$lib/core/formatting/dateTime";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  type Props = {
    items: readonly AdminSpaceListItem[];
    requests: readonly AdminWidgetRequestRef[];
    /** Narrows the list to the spaces without an administrator. */
    onShowNoAdmin: () => void;
  };

  let { items, requests, onShowNoAdmin }: Props = $props();

  const SHOWN_REQUESTS = 3;
  const number = new Intl.NumberFormat(intlLocale());
  const noAdmin = $derived(items.filter((item) => item.attention.includes("no_admin")).length);
</script>

<section aria-labelledby="spaces-attention-title" class="flex flex-col gap-3">
  <h2 id="spaces-attention-title" class="text-lg font-semibold">
    {m.admin_spaces_attention_title()}
  </h2>
  <ul class="border-default bg-primary divide-default divide-y rounded-lg border">
    {#if noAdmin > 0}
      <li class="flex gap-3 p-4">
        <TriangleAlert class="text-warning-stronger mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <div class="flex min-w-0 flex-1 flex-col gap-3 @2xl:flex-row @2xl:items-center">
          <div class="flex min-w-0 flex-1 flex-col gap-1">
            <p class="font-medium">
              {noAdmin === 1
                ? m.admin_spaces_attention_no_admin_one()
                : m.admin_spaces_attention_no_admin({ count: number.format(noAdmin) })}
            </p>
            <p class="text-secondary max-w-[75ch] text-sm">
              {m.admin_spaces_attention_no_admin_help()}
            </p>
          </div>
          <Button variant="outline" class="w-fit shrink-0 max-md:min-h-12" onclick={onShowNoAdmin}>
            {m.admin_spaces_attention_show()}
          </Button>
        </div>
      </li>
    {/if}
    {#if requests.length > 0}
      <li class="flex gap-3 p-4">
        <Inbox class="text-secondary mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <div class="flex min-w-0 flex-1 flex-col gap-2">
          <p class="font-medium">
            {requests.length === 1
              ? m.admin_spaces_attention_widgets_one()
              : m.admin_spaces_attention_widgets({ count: number.format(requests.length) })}
          </p>
          <ul class="flex flex-col gap-2 text-sm">
            {#each requests.slice(0, SHOWN_REQUESTS) as request (request.widget_id)}
              <li class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span class="min-w-0 break-words">
                  {m.admin_spaces_attention_widget_item({
                    widget: request.widget_name,
                    space: request.space.name,
                    date: formatDateMedium(request.requested_at)
                  })}
                </span>
                <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed id -->
                <a
                  class="text-accent-stronger inline-flex min-h-6 items-center font-medium underline underline-offset-2"
                  href={localizeHref(`/admin/widgets/${request.widget_id}`)}
                  aria-label={m.admin_spaces_review_named({ name: request.widget_name })}
                  >{m.admin_spaces_review()}</a
                >
                <!-- eslint-enable svelte/no-navigation-without-resolve -->
              </li>
            {/each}
          </ul>
          {#if requests.length > SHOWN_REQUESTS}
            <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href with a fixed query and anchor -->
            <a
              class="text-accent-stronger inline-flex min-h-6 w-fit items-center gap-1 text-sm font-medium underline underline-offset-2"
              href={`${localizeHref("/admin/widgets")}?tab=widgets#activation-requests`}
            >
              {m.admin_spaces_attention_all_widgets()}
              <ArrowRight class="size-4" aria-hidden="true" />
            </a>
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          {/if}
        </div>
      </li>
    {/if}
    {#if noAdmin === 0 && requests.length === 0}
      <li class="flex items-center gap-3 p-4">
        <CircleCheck class="text-positive-stronger size-5 shrink-0" aria-hidden="true" />
        <p>{m.admin_spaces_attention_none()}</p>
      </li>
    {/if}
  </ul>
</section>
