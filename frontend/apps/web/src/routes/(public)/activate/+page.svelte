<script lang="ts">
  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";
  import { Button } from "@intric/ui";
</script>

<svelte:head>
  <title>Eneo.ai – Activate</title>
</svelte:head>

<div class="absolute inset-0 flex flex-col items-center justify-center gap-4">
  <div class=" border-default bg-primary flex flex-col items-start rounded-sm border p-8 shadow">
    <EneoWordMark class="text-brand-intric h-8 w-16" />
    <div class="h-14"></div>
    <h2 class="mb-2 text-2xl font-bold">Almost there!</h2>
    <p class="text-secondary max-w-[60ch]">
      Your account has not yet been activated in intric. Please ask your administrator to create an
      invitation for your email address and then try again.
    </p>
    <div class="h-16"></div>

    <div class="flex w-full justify-between">
      <Button href="/logout" variant="outlined">Logout</Button>
      <Button href="/" variant="primary">Retry</Button>
    </div>
  </div>
</div>
