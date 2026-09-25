<!--
  What the administrator reviews before a widget faces the public: where it
  can be embedded, what visitors read, what they reach through it, how their
  conversations are kept, and how it has been used. Settings only: never
  questions, answers or documents.
-->
<script lang="ts">
  import type { AdminWidgetReview, WidgetPolicy } from "@eneo/eneo-js";
  import { Info, TriangleAlert } from "@lucide/svelte";
  import * as Card from "$lib/components/ui/card/index.js";
  import { formatDayMedium, intlLocale } from "$lib/core/formatting/dateTime";
  import { formatList } from "$lib/core/formatting/formatList";
  import AssistantConfigCard from "$lib/features/spaces/oversight/AssistantConfigCard.svelte";
  import { retentionLabel } from "$lib/features/spaces/oversight/labels";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    review: AdminWidgetReview;
    policy: WidgetPolicy | null;
  };

  let { review, policy }: Props = $props();

  const widget = $derived(review.widget);
  const texts = $derived(widget.texts);
  const number = new Intl.NumberFormat(intlLocale());
  // The API always sends every limit; a missing one is shown as missing, never guessed.
  const count = (value: number | undefined) => (value === undefined ? "–" : number.format(value));

  const languageLabel = $derived.by(() => {
    switch (widget.language) {
      case "sv":
        return m.widget_admin_language_sv();
      case "en":
        return m.widget_admin_language_en();
      default:
        return m.widget_admin_language_auto();
    }
  });

  const visitorTools = $derived([
    ...(review.target?.visitor_mcp_servers ?? []).map((server) => server.name),
    ...(review.target?.visitor_capabilities ?? []).map(() => m.widget_review_web_search())
  ]);

  const shown = $derived.by(() => {
    if (widget.show_sources && widget.show_tool_activity) return m.widget_review_shown_both();
    if (widget.show_sources) return m.widget_review_shown_sources();
    if (widget.show_tool_activity) return m.widget_review_shown_tools();
    return m.widget_review_shown_none();
  });

  const retention = $derived(
    widget.privacy.retention_days === 0
      ? m.widget_review_retention_zero()
      : retentionLabel(widget.privacy.retention_days, "–")
  );

  // Usage is only worth showing once the widget has answered visitors.
  const everActive = $derived(widget.activated_at != null);
</script>

{#snippet term(label: string)}
  <dt class="text-secondary text-xs">{label}</dt>
{/snippet}

<section aria-labelledby="review-where-title">
  <Card.Root>
    <Card.Header>
      <Card.Title><h2 id="review-where-title">{m.widget_review_where()}</h2></Card.Title>
      {#if widget.allowed_origins.length > 0}
        <Card.Description>{m.widget_review_origins_help()}</Card.Description>
      {/if}
    </Card.Header>
    <Card.Content>
      {#if widget.allowed_origins.length > 0}
        <ul class="flex flex-col gap-1">
          {#each widget.allowed_origins as origin (origin)}
            <li class="font-mono text-sm break-all">{origin}</li>
          {/each}
        </ul>
      {:else}
        <p class="text-warning-stronger flex items-start gap-2 text-sm">
          <TriangleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {m.widget_review_no_origins()}
        </p>
      {/if}
    </Card.Content>
  </Card.Root>
</section>

<section aria-labelledby="review-visitors-title">
  <Card.Root>
    <Card.Header>
      <Card.Title
        ><h2 id="review-visitors-title">{m.widget_review_what_visitors_see()}</h2></Card.Title
      >
    </Card.Header>
    <Card.Content>
      <dl class="grid grid-cols-1 gap-x-6 gap-y-4 text-sm sm:grid-cols-2">
        <div class="min-w-0">
          {@render term(m.widget_admin_text_title())}
          <dd class="break-words">{texts.title || widget.name}</dd>
        </div>
        <div class="min-w-0">
          {@render term(m.widget_admin_text_subtitle())}
          <dd class="break-words">{texts.subtitle || m.none()}</dd>
        </div>
        <div class="min-w-0 sm:col-span-2">
          {@render term(m.widget_admin_text_welcome())}
          <dd class="break-words whitespace-pre-wrap">{texts.welcome || m.none()}</dd>
        </div>
        <div class="min-w-0 sm:col-span-2">
          {@render term(m.widget_admin_text_suggestions())}
          <dd>
            {#if texts.suggested_questions?.length}
              <ul class="list-disc pl-5">
                {#each texts.suggested_questions as question, index (index)}
                  <li class="break-words">{question}</li>
                {/each}
              </ul>
            {:else}
              {m.admin_spaces_none()}
            {/if}
          </dd>
        </div>
        <div class="min-w-0 sm:col-span-2">
          {@render term(m.widget_admin_text_footer())}
          <dd class="flex flex-col gap-1 break-words">
            <span>{texts.footer_text || m.none()}</span>
            {#if texts.footer_link_url}
              <span class="text-secondary break-all">
                {texts.footer_link_label
                  ? `${texts.footer_link_label} – ${texts.footer_link_url}`
                  : texts.footer_link_url}
              </span>
            {/if}
          </dd>
        </div>
        <div class="min-w-0">
          {@render term(m.widget_admin_language())}
          <dd>{languageLabel}</dd>
        </div>
        <div class="min-w-0">
          {@render term(m.widget_admin_template())}
          <dd class="break-words">
            {widget.template
              ? m.widget_review_template_value({ name: widget.template.name })
              : m.widget_admin_template_none()}
          </dd>
        </div>
      </dl>
    </Card.Content>
  </Card.Root>
</section>

<section aria-labelledby="review-access-title">
  <Card.Root>
    <Card.Header>
      <Card.Title><h2 id="review-access-title">{m.widget_review_access()}</h2></Card.Title>
    </Card.Header>
    <Card.Content class="flex flex-col gap-5">
      {#if review.space_kind === "personal"}
        <p
          class="bg-warning-dimmer text-warning-stronger flex items-start gap-2 rounded-lg p-3 text-sm"
        >
          <TriangleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {m.widget_review_personal_space()}
        </p>
      {:else if !review.target}
        <p
          class="bg-warning-dimmer text-warning-stronger flex items-start gap-2 rounded-lg p-3 text-sm"
        >
          <TriangleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {m.widget_review_target_missing()}
        </p>
      {:else}
        <dl class="grid grid-cols-1 gap-x-6 gap-y-4 text-sm sm:grid-cols-2">
          <div class="min-w-0">
            {@render term(m.widget_review_visitor_tools())}
            <dd class="break-words">
              {visitorTools.length > 0 ? formatList(visitorTools) : m.admin_spaces_none()}
            </dd>
          </div>
          <div class="min-w-0">
            {@render term(m.widget_review_shown())}
            <dd>{shown}</dd>
          </div>
        </dl>
        <div class="text-secondary flex items-start gap-2 text-sm">
          <Info class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div class="flex flex-col gap-1">
            <p>{m.widget_review_visitors_anonymous()}</p>
            <p>{m.widget_admin_visitor_access_never()}</p>
          </div>
        </div>
        <div class="flex flex-col gap-3">
          <h3 class="text-sm font-semibold">{m.assistant()}</h3>
          <AssistantConfigCard
            assistant={review.target.assistant}
            knowledge={review.target.knowledge}
            headingLevel={4}
            showWidget={false}
            retentionTerm={m.widget_review_retention_staff()}
          />
        </div>
      {/if}
    </Card.Content>
  </Card.Root>
</section>

<section aria-labelledby="review-privacy-title">
  <Card.Root>
    <Card.Header>
      <Card.Title><h2 id="review-privacy-title">{m.widget_review_privacy()}</h2></Card.Title>
    </Card.Header>
    <Card.Content>
      <dl class="grid grid-cols-1 gap-x-6 gap-y-4 text-sm sm:grid-cols-2">
        <div class="min-w-0">
          {@render term(m.widget_review_retention_visitors())}
          <dd>
            {retention}
            {#if policy}
              <span class="text-secondary block">
                {m.widget_review_policy_range({
                  min: number.format(policy.min_retention_days),
                  max: number.format(policy.max_retention_days)
                })}
              </span>
            {/if}
          </dd>
        </div>
        <div class="min-w-0">
          {@render term(m.widget_admin_bot_protection())}
          <dd>
            {widget.bot_protection === "none"
              ? m.widget_admin_bot_protection_none()
              : m.widget_admin_bot_protection_altcha()}
          </dd>
        </div>
        <div class="min-w-0">
          {@render term(m.widget_admin_daily_budget())}
          <dd>
            <span class="tabular-nums">{count(widget.limits.daily_token_budget)}</span>
            {#if policy}
              <span class="text-secondary block">
                {m.widget_review_budget_cap({ max: number.format(policy.max_daily_token_budget) })}
              </span>
            {/if}
          </dd>
        </div>
        <div class="min-w-0">
          {@render term(m.widget_admin_limits())}
          <dd>
            {m.widget_review_limits_value({
              visitor: count(widget.limits.messages_per_visitor_10min),
              ip: count(widget.limits.messages_per_ip_hour)
            })}
          </dd>
        </div>
        <div class="min-w-0 sm:col-span-2">
          {@render term(m.widget_review_feedback())}
          <dd>
            {widget.privacy.store_feedback_text
              ? m.widget_review_feedback_text()
              : m.widget_review_feedback_votes()}
          </dd>
        </div>
      </dl>
    </Card.Content>
  </Card.Root>
</section>

{#if everActive}
  <section aria-labelledby="review-usage-title">
    <Card.Root>
      <Card.Header>
        <Card.Title><h2 id="review-usage-title">{m.usage()}</h2></Card.Title>
      </Card.Header>
      <Card.Content>
        <dl class="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
          <div>
            {@render term(m.widget_admin_overview_questions_7d())}
            <dd class="text-lg font-semibold tabular-nums">
              {number.format(review.usage.questions_7d)}
            </dd>
          </div>
          <div>
            {@render term(m.widget_admin_overview_questions_30d())}
            <dd class="text-lg font-semibold tabular-nums">
              {number.format(review.usage.questions_30d)}
            </dd>
          </div>
          <div>
            {@render term(m.widget_admin_overview_blocked_30d())}
            <dd
              class={[
                "text-lg font-semibold tabular-nums",
                review.usage.blocked_30d > 0 && "text-warning-stronger"
              ]}
            >
              {number.format(review.usage.blocked_30d)}
            </dd>
          </div>
          <div>
            {@render term(m.widget_admin_overview_feedback_30d())}
            <dd class="text-lg font-semibold tabular-nums">
              {m.widget_admin_overview_feedback_value({
                helpful: number.format(review.usage.helpful_30d),
                unhelpful: number.format(review.usage.unhelpful_30d)
              })}
            </dd>
          </div>
        </dl>
        <p class="text-secondary mt-3 text-xs">
          {m.widget_admin_overview_last_activity()}:
          {#if review.usage.last_activity}
            <time datetime={review.usage.last_activity}
              >{formatDayMedium(review.usage.last_activity)}</time
            >
          {:else}
            {m.widget_admin_overview_never()}
          {/if}
        </p>
      </Card.Content>
    </Card.Root>
  </section>
{/if}
