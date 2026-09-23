<!--
  Shown where an assistant's tools and functions are configured while an
  active widget publishes it: visitors get the assistant as configured, so
  what is changed here reaches anonymous website visitors at once.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  type Props = {
    /** The widget settings, or the organisation's widget overview. */
    href: string;
  };

  let { href }: Props = $props();
</script>

<div
  role="note"
  aria-labelledby="assistant-widget-notice-title"
  class="label-warning border-label-default bg-label-dimmer text-label-stronger flex flex-col gap-1 rounded-md border px-3 py-2 text-sm"
>
  <p id="assistant-widget-notice-title" class="font-bold">
    {m.widget_admin_assistant_notice_title()}
  </p>
  <p>{m.widget_admin_assistant_notice_body()}</p>
  <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- localized href passed in by the page -->
  <a class="w-fit font-medium underline underline-offset-2" {href}>{m.widget_admin_open()}</a>
</div>
