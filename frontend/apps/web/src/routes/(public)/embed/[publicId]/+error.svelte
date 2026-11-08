<script lang="ts">
  import { m } from "$lib/paraglide/messages";
</script>

<svelte:head>
  <title>{m.widget_not_available_title()}</title>
  <meta name="robots" content="noindex" />
</svelte:head>

<main
  class="bg-primary text-primary fixed inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center"
>
  <h1 class="text-base font-semibold">{m.widget_not_available_title()}</h1>
  <p class="text-secondary max-w-[40ch] text-sm">{m.widget_not_available_body()}</p>
</main>
