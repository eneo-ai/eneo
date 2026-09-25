<!--
  How the widget looks to visitors, always as a static picture. Its answers
  come from the space's knowledge, which is content: only members test them,
  and only against a published assistant. The live preview is not mounted
  for anyone else, so no preview token is ever minted for them.
-->
<script lang="ts">
  import type { AdminWidgetReview, Eneo } from "@eneo/eneo-js";
  import { MessagesSquare } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import JoinSpaceDialog from "$lib/features/spaces/oversight/JoinSpaceDialog.svelte";
  import WidgetMockPreview from "$lib/features/widget/admin/WidgetMockPreview.svelte";
  import WidgetPreview from "$lib/features/widget/admin/WidgetPreview.svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    review: AdminWidgetReview;
    eneo: Eneo;
  };

  let { review, eneo }: Props = $props();

  const widget = $derived(review.widget);
  const member = $derived(review.viewer_role != null);
  const published = $derived(review.target?.assistant.published === true);
  const canTest = $derived(member && published && widget.status !== "archived");
  const panelId = $props.id();

  let heading = $state<HTMLElement | null>(null);
  let testing = $state(false);
  let column = $state<HTMLElement | null>(null);
  let body = $state<HTMLElement | null>(null);
  let scrollable = $state(false);

  // From xl the column is sticky with its own scroll. Only while its content
  // overflows is it a Tab stop, so a keyboard can scroll it.
  $effect(() => {
    if (!column || !body) return;
    const measured = column;
    const observer = new ResizeObserver(() => {
      scrollable = measured.scrollHeight > measured.clientHeight;
    });
    observer.observe(measured);
    observer.observe(body);
    return () => observer.disconnect();
  });
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex (sticky overflow region must be keyboard-scrollable) -->
<section
  bind:this={column}
  aria-labelledby="review-preview-title"
  tabindex={scrollable ? 0 : undefined}
  class="border-default bg-primary min-w-0 self-start rounded-xl border p-4 xl:sticky xl:top-4 xl:max-h-[calc(100dvh-8rem)] xl:overflow-auto"
>
  <div bind:this={body} class="flex flex-col gap-4">
    <div class="flex flex-col gap-1">
      <h2
        id="review-preview-title"
        bind:this={heading}
        tabindex="-1"
        class="text-base font-semibold"
      >
        {m.widget_admin_preview()}
      </h2>
      <p class="text-secondary text-sm">{m.widget_review_preview_note()}</p>
    </div>

    <WidgetMockPreview
      framed={false}
      name={widget.name}
      texts={widget.texts}
      theme={widget.theme}
      alt={m.widget_review_preview_alt({ name: widget.name })}
    />

    {#if review.target && widget.status !== "archived"}
      <div class="border-default flex flex-col items-start gap-3 border-t pt-4 text-sm">
        {#if !member}
          <p>{m.widget_review_preview_members_only()}</p>
          {#if review.space_kind === "shared" && review.viewer_membership}
            <JoinSpaceDialog
              space={{
                ...review.space,
                security_classification: review.space_security_classification
              }}
              membership={review.viewer_membership}
              triggerVariant="outline"
              focusAfterJoin={() => heading}
            />
          {/if}
        {:else if !published}
          <p>{m.widget_review_preview_unpublished()}</p>
        {:else if canTest}
          <p>{m.widget_review_preview_live_note()}</p>
          <Button
            variant="outline"
            class="max-md:min-h-11"
            aria-expanded={testing}
            aria-controls={panelId}
            onclick={() => (testing = !testing)}
          >
            <MessagesSquare aria-hidden="true" data-icon="inline-start" />
            {m.widget_review_preview_test()}
          </Button>
        {/if}
      </div>
    {/if}

    <div id={panelId} class="empty:hidden">
      {#if canTest && testing}
        <WidgetPreview {widget} {eneo} headingLevel={3} title={m.widget_review_live_title()} />
      {/if}
    </div>
  </div>
</section>
