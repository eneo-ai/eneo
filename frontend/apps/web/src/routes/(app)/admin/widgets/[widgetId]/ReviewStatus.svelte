<!--
  Where the reviewed widget stands and what the administrator can do next:
  who asked for activation, a request that was sent back, what blocks
  activation, and the lifecycle actions. An archived widget is read only.
-->
<script lang="ts">
  import type { AdminWidgetReview } from "@eneo/eneo-js";
  import { Archive, Clock, Pause, Undo2 } from "@lucide/svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { intlLocale } from "$lib/core/formatting/dateTime";
  import { blockerLabel } from "$lib/features/widget/admin/blockers";
  import { activationRequestState, widgetStatusLabel } from "$lib/features/widget/admin/status";
  import TimedText from "$lib/features/widget/admin/TimedText.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import DeclineRequestDialog from "./DeclineRequestDialog.svelte";
  import LifecycleDialog from "./LifecycleDialog.svelte";

  type Props = {
    review: AdminWidgetReview;
    /** Whether the administrator may also open the widget in the space's editor. */
    canOpenEditor: boolean;
  };

  let { review, canOpenEditor }: Props = $props();

  let heading = $state<HTMLElement | null>(null);

  const widget = $derived(review.widget);
  const inactive = $derived(widget.status === "draft" || widget.status === "paused");
  const request = $derived(activationRequestState(widget));
  const requestedAt = $derived(request.kind === "requested" ? request.at : null);
  const returnedAt = $derived(request.kind === "returned" ? request.at : null);
  // The API's blockers already include the tenant policy's violations.
  const problems = $derived(widget.activation_blockers ?? []);
  const blocked = $derived(problems.length > 0);

  let lifecycle = $state<"activate" | "pause" | "archive">("activate");
  let lifecycleOpen = $state(false);
  let declineOpen = $state(false);

  function openLifecycle(action: "activate" | "pause" | "archive") {
    lifecycle = action;
    lifecycleOpen = true;
  }

  const dateTime = new Intl.DateTimeFormat(intlLocale(), {
    dateStyle: "medium",
    timeStyle: "short"
  });
  const formatDateTime = (value: string) => dateTime.format(new Date(value));
</script>

<section
  aria-labelledby="review-status-title"
  class="border-default bg-primary flex flex-col gap-4 rounded-xl border p-4"
>
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div class="flex flex-wrap items-center gap-3">
      <h2
        id="review-status-title"
        bind:this={heading}
        tabindex="-1"
        class="text-base font-semibold"
      >
        {m.widget_admin_status()}
      </h2>
      <Badge
        variant={widget.status === "active"
          ? "default"
          : widget.status === "paused"
            ? "destructive"
            : "outline"}>{widgetStatusLabel(widget.status)}</Badge
      >
      {#if requestedAt}
        <Badge variant="outline">
          <Clock aria-hidden="true" />
          {m.widget_request_badge()}
        </Badge>
      {/if}
    </div>

    {#if widget.status !== "archived"}
      <div class="flex flex-wrap items-center gap-2">
        {#if inactive}
          <!-- aria-disabled rather than disabled: it stays focusable and is described by what blocks it. -->
          <Button
            class={["max-md:min-h-11", blocked && "opacity-50"]}
            aria-disabled={blocked}
            aria-describedby={blocked ? "review-blockers" : undefined}
            onclick={() => {
              if (!blocked) openLifecycle("activate");
            }}
          >
            {widget.status === "paused" ? m.widget_review_resume() : m.widget_review_activate()}
          </Button>
        {/if}
        {#if requestedAt}
          <Button variant="outline" class="max-md:min-h-11" onclick={() => (declineOpen = true)}>
            <Undo2 aria-hidden="true" data-icon="inline-start" />
            {m.widget_review_send_back()}
          </Button>
        {/if}
        {#if widget.status === "active"}
          <Button variant="outline" class="max-md:min-h-11" onclick={() => openLifecycle("pause")}>
            <Pause aria-hidden="true" data-icon="inline-start" />
            {m.widget_review_pause()}
          </Button>
        {/if}
        <Button variant="outline" class="max-md:min-h-11" onclick={() => openLifecycle("archive")}>
          <Archive aria-hidden="true" data-icon="inline-start" />
          {m.widget_review_archive()}
        </Button>
      </div>
    {/if}
  </div>

  <div class="flex flex-col gap-3 text-sm">
    {#if requestedAt}
      <p class="flex items-start gap-2">
        <Clock class="text-secondary mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <span>
          <TimedText
            message={(date) =>
              review.activation_requested_by
                ? m.widget_review_requested({ name: review.activation_requested_by.name, date })
                : m.widget_review_requested_unknown({ date })}
            value={requestedAt}
            format={formatDateTime}
          />
        </span>
      </p>
    {:else if request.kind === "none"}
      <p class="text-secondary">{m.widget_review_not_requested()}</p>
    {:else if widget.activated_at}
      <p class="text-secondary">
        <TimedText
          message={(date) =>
            review.activated_by
              ? m.widget_review_activated_line({ name: review.activated_by.name, date })
              : m.widget_review_activated_line_unknown({ date })}
          value={widget.activated_at}
          format={formatDateTime}
        />
      </p>
    {/if}

    {#if returnedAt}
      <div class="bg-secondary flex items-start gap-2 rounded-lg px-3 py-3">
        <Undo2 class="text-secondary mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <div class="flex min-w-0 flex-col gap-2">
          <p>
            <TimedText
              message={(date) =>
                review.activation_declined_by
                  ? m.widget_review_returned({ date, name: review.activation_declined_by.name })
                  : m.widget_review_returned_unknown({ date })}
              value={returnedAt}
              format={formatDateTime}
            />
          </p>
          {#if widget.activation_decline_reason}
            <blockquote class="border-strongest border-l-2 pl-3 break-words whitespace-pre-wrap">
              {widget.activation_decline_reason}
            </blockquote>
          {/if}
        </div>
      </div>
    {/if}

    {#if blocked && widget.status !== "archived"}
      <!-- An active widget with blockers is live but not serving as configured. -->
      <div
        id="review-blockers"
        class="bg-warning-dimmer text-warning-stronger rounded-lg px-3 py-2"
      >
        <p class="font-medium">
          {widget.status === "active"
            ? m.widget_admin_active_issues_title()
            : m.widget_admin_blockers_title()}
        </p>
        <ul class="mt-1 list-disc pl-5">
          {#each problems as problem (problem)}
            <li>{blockerLabel(problem)}</li>
          {/each}
        </ul>
      </div>
    {/if}

    {#if widget.status === "archived"}
      <p class="text-secondary">{m.widget_review_archived_note()}</p>
    {/if}

    {#if canOpenEditor && review.target && widget.status !== "archived"}
      <p>
        <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from typed ids -->
        <a
          class="text-accent-stronger underline underline-offset-2"
          href={localizeHref(`/spaces/${widget.space_id}/assistants/${widget.target_id}/widget`)}
          >{m.widget_review_open_editor()}</a
        >
        <!-- eslint-enable svelte/no-navigation-without-resolve -->
      </p>
    {/if}
  </div>
</section>

<LifecycleDialog
  bind:open={lifecycleOpen}
  action={lifecycle}
  {widget}
  requested={requestedAt !== null}
  focusAfter={() => heading}
/>
<DeclineRequestDialog bind:open={declineOpen} {widget} focusAfter={() => heading} />
