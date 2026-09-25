<!--
  Admin → Webbwidgetar → Granska: everything an organisation administrator
  decides on before a widget answers the public, readable without being a
  member of the widget's space.
-->
<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { hasPermission } from "$lib/core/hasPermission.js";
  import SecurityClassificationBadge from "$lib/features/security-classifications/components/SecurityClassificationBadge.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import ReviewPreview from "./ReviewPreview.svelte";
  import ReviewSections from "./ReviewSections.svelte";
  import ReviewStatus from "./ReviewStatus.svelte";

  let { data } = $props();

  const review = $derived(data.review);
  // The editor is the space's own page, so it needs a role there as well as the widgets permission.
  const canOpenEditor = $derived(
    (review?.viewer_role === "admin" || review?.viewer_role === "editor") &&
      hasPermission(data.user)("widgets")
  );
</script>

<svelte:head>
  <title
    >Eneo.ai – {m.admin()} – {m.widget_admin_nav()} – {review?.widget.name ??
      m.widget_review_not_found_title()}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      wrap
      parent={{ title: m.widget_admin_nav(), href: localizeHref("/admin/widgets") }}
      title={review?.widget.name ?? m.widget_review_not_found_title()}
    ></Page.Title>
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex w-full max-w-[1400px] flex-col gap-6 p-4">
      {#if !review}
        <div class="flex max-w-[60ch] flex-col items-start gap-3">
          <p>{m.widget_review_not_found_body()}</p>
          <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href to a fixed route -->
          <a
            class="text-accent-stronger underline underline-offset-2"
            href={localizeHref("/admin/widgets")}>{m.widget_review_back()}</a
          >
          <!-- eslint-enable svelte/no-navigation-without-resolve -->
        </div>
      {:else}
        <div class="flex flex-col gap-3">
          <dl class="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <div class="flex min-w-0 items-baseline gap-1.5">
              <dt class="text-secondary">{m.widget_review_space()}</dt>
              <dd class="min-w-0 break-words">
                {#if review.space_kind === "shared"}
                  <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed id -->
                  <a
                    class="text-accent-stronger underline underline-offset-2"
                    href={localizeHref(`/admin/spaces/${review.space.id}`)}>{review.space.name}</a
                  >
                  <!-- eslint-enable svelte/no-navigation-without-resolve -->
                {:else}
                  {review.space.name}
                {/if}
              </dd>
            </div>
            {#if review.target}
              <div class="flex min-w-0 items-baseline gap-1.5">
                <dt class="text-secondary">{m.assistant()}</dt>
                <dd class="min-w-0 break-words">{review.target.assistant.name}</dd>
              </div>
            {/if}
            {#if review.space_security_classification}
              <div class="flex min-w-0 items-center">
                <dt class="sr-only">{m.security_classification()}</dt>
                <dd>
                  <SecurityClassificationBadge
                    classification={review.space_security_classification}
                  />
                </dd>
              </div>
            {/if}
          </dl>
          <p class="text-secondary max-w-[75ch] text-sm">{m.widget_review_intro()}</p>
        </div>

        <ReviewStatus {review} {canOpenEditor} />

        <div class="grid items-start gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div class="flex min-w-0 flex-col gap-6">
            <ReviewSections {review} policy={data.policy} />
          </div>
          <ReviewPreview {review} eneo={data.eneo} />
        </div>
      {/if}
    </div>
  </Page.Main>
</Page.Root>
