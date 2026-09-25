<!--
  The space at a glance. Each usage count shows only when enough different
  people are behind it; otherwise the page says why that number is missing.
-->
<script lang="ts">
  import type { AdminSpaceDetail } from "@eneo/eneo-js";
  import { TriangleAlert } from "@lucide/svelte";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatDateMedium, intlLocale } from "$lib/core/formatting/dateTime";
  import SecurityClassificationBadge from "$lib/features/security-classifications/components/SecurityClassificationBadge.svelte";
  import { activityLabel } from "$lib/features/spaces/oversight/activity";
  import { m } from "$lib/paraglide/messages";
  import { adminNames, groupCount, peopleCount } from "../labels";

  type Props = {
    space: AdminSpaceDetail;
    securityEnabled: boolean;
  };

  let { space, securityEnabled }: Props = $props();

  const number = new Intl.NumberFormat(intlLocale());
  const format = (value: number) => number.format(value);

  const usage = $derived(space.usage);
  const days = $derived(usage.window_days ?? 30);
  const admins = $derived(adminNames(space.members.admins, 3));
  const threshold = $derived(format(usage.threshold ?? 5));
</script>

<!-- A missing count says why it is missing: too few people, or no widget has been public. -->
{#snippet count(value: number | null | undefined, hidden: string)}
  {#if value == null}
    <span class="text-secondary text-sm font-normal">{hidden}</span>
  {:else}
    <span class="tabular-nums">{format(value)}</span>
  {/if}
{/snippet}

<section aria-labelledby="space-summary-title" class="flex flex-col gap-2">
  <h2 id="space-summary-title" class="sr-only">{m.admin_spaces_summary_title()}</h2>
  <dl
    class="border-default bg-primary grid grid-cols-1 gap-x-6 gap-y-4 rounded-lg border p-4 @xl:grid-cols-2 @4xl:grid-cols-4"
  >
    {#if securityEnabled}
      <div class="flex min-w-0 flex-col gap-1">
        <dt class="text-secondary text-xs">{m.admin_spaces_col_classification()}</dt>
        <dd>
          {#if space.security_classification}
            <SecurityClassificationBadge classification={space.security_classification} />
          {:else}
            {m.no_classification()}
          {/if}
        </dd>
      </div>
    {/if}
    <div class="flex min-w-0 flex-col gap-1">
      <dt class="text-secondary text-xs">{m.admin_spaces_col_admins()}</dt>
      <dd class="font-medium wrap-anywhere">
        {#if admins}
          {admins}
        {:else}
          <span class="text-warning-stronger inline-flex items-center gap-1">
            <TriangleAlert class="size-4 shrink-0" aria-hidden="true" />
            {m.admin_spaces_admins_missing()}
          </span>
        {/if}
      </dd>
    </div>
    <div class="flex min-w-0 flex-col gap-1">
      <dt class="text-secondary text-xs">{m.members()}</dt>
      <dd class="font-medium">
        {peopleCount(space.members.member_count, format)} · {groupCount(
          space.members.group_count,
          format
        )}
      </dd>
    </div>
    <div class="flex min-w-0 flex-col gap-1">
      <dt class="text-secondary text-xs">{m.admin_spaces_col_last_active()}</dt>
      <dd class="font-medium">
        {activityLabel(usage.last_activity)}
        {#if usage.last_activity === "none"}
          <span class="text-secondary block text-sm font-normal">
            {m.admin_spaces_activity_none_help()}
          </span>
        {/if}
      </dd>
    </div>
    <div class="flex min-w-0 flex-col gap-1">
      <dt class="text-secondary text-xs">{m.admin_spaces_fact_questions({ days })}</dt>
      <dd class="font-medium">
        {@render count(usage.questions, m.admin_spaces_suppressed_questions({ threshold }))}
      </dd>
    </div>
    <div class="flex min-w-0 flex-col gap-1">
      <dt class="text-secondary text-xs">{m.admin_spaces_fact_active_users({ days })}</dt>
      <dd class="font-medium">
        {@render count(usage.active_users, m.admin_spaces_suppressed({ threshold }))}
      </dd>
    </div>
    {#if space.apps.length > 0}
      <div class="flex min-w-0 flex-col gap-1">
        <dt class="text-secondary text-xs">{m.admin_spaces_fact_app_runs({ days })}</dt>
        <dd class="font-medium">
          {@render count(usage.app_runs, m.admin_spaces_suppressed_app_runs({ threshold }))}
        </dd>
      </div>
    {/if}
    {#if space.widgets.length > 0}
      <!-- Test questions from editors and administrators count too, so none are shown
           until a widget has been public. -->
      <div class="flex min-w-0 flex-col gap-1">
        <dt class="text-secondary text-xs">{m.admin_spaces_fact_widget_questions({ days })}</dt>
        <dd class="font-medium">
          {@render count(usage.widget_questions, m.admin_spaces_widget_questions_hidden())}
        </dd>
      </div>
    {/if}
    <div class="flex min-w-0 flex-col gap-1">
      <dt class="text-secondary text-xs">{m.admin_spaces_fact_knowledge_size()}</dt>
      <dd class="font-medium tabular-nums">{formatBytes(usage.knowledge_bytes)}</dd>
    </div>
    <div class="flex min-w-0 flex-col gap-1">
      <dt class="text-secondary text-xs">{m.created()}</dt>
      <dd class="font-medium">
        <time datetime={space.created_at}>{formatDateMedium(space.created_at)}</time>
      </dd>
    </div>
  </dl>
  {#if usage.suppressed}
    <p class="text-secondary text-sm">{m.admin_spaces_suppressed_help({ threshold })}</p>
  {/if}
</section>
