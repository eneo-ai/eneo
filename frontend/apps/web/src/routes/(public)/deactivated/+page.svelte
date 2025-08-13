<script lang="ts">
  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";
  import { Button } from "@intric/ui";

  const { data } = $props();
</script>

<svelte:head>
  <title>Eneo.ai – Deactivated</title>
</svelte:head>

<div class="absolute inset-0 flex flex-col items-center justify-center gap-4">
  <div class="border-default bg-primary flex flex-col items-start rounded-sm border p-8 shadow">
    <EneoWordMark class="text-brand-intric h-8 w-16" />
    <div class="h-14"></div>
    <h2 class="mb-2 text-2xl font-bold">Organisation deactivated</h2>
    <p class="text-secondary max-w-[60ch]">
      Your access to Eneo has been temporarily disabled, most likely because your trial period has
      ended. Please contact
      <a
        href="mailto:{data.salesEmail}"
        class=" text-brand-intric hover:bg-hover-default underline"
      >
        {data.salesEmail}
      </a>
      to regain access for your organisation.
    </p>
    <div class="h-16"></div>

    <div class="flex w-full justify-between">
      <Button href="/logout" variant="outlined">Logout</Button>
      <Button href="/" variant="primary">Retry</Button>
    </div>
  </div>
</div>
