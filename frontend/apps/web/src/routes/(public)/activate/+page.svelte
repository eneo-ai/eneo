<script lang="ts">
  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";
  import { Button } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
</script>

<svelte:head>
  <title>Eneo.ai – {m.activate()}</title>
</svelte:head>

<div class="absolute inset-0 flex flex-col items-center justify-center gap-4">
  <div class=" border-default bg-primary flex flex-col items-start rounded-sm border p-8 shadow">
    <EneoWordMark class="text-brand-intric h-8 w-16" />
    <div class="h-14"></div>
    <h2 class="mb-2 text-2xl font-bold">{m.almost_there()}</h2>
    <p class="text-secondary max-w-[60ch]">
      {m.account_not_activated()}
    </p>
    <div class="h-16"></div>

    <div class="flex w-full justify-between">
      <Button href={localizeHref("/logout")} variant="outlined">{m.logout()}</Button>
      <Button href={localizeHref("/")} variant="primary">{m.retry()}</Button>
    </div>
  </div>
</div>
