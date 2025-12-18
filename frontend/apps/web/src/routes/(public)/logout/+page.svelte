<script lang="ts">
  import { Button } from "@intric/ui";
  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let data;

  const messages: Record<string, { label: string; colour: string }> = {
    logout: { label: m.successfully_logged_out(), colour: "green" },
    expired: { label: m.session_expired(), colour: "amber" }
  };

  let message = messages.logout;
  if (data.message && data.message in messages) {
    message = messages[data.message];
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.logout()}</title>
</svelte:head>

<div class="relative flex h-[100vh] w-[100vw] items-center justify-center">
  <div class="box w-[400px] justify-center">
    <h1 class="flex justify-center">
      <EneoWordMark class="text-brand-intric h-16 w-20"></EneoWordMark>
      <span class="hidden">{m.intric()}</span>
    </h1>

    <div aria-live="polite">
      <div class="mb-2 flex flex-col gap-3 p-4 shadow-lg {message.colour}">{message.label}</div>
    </div>

    <div class="shadowed border-default bg-primary flex flex-col gap-3 p-4">
      <Button href={localizeHref("/login")} variant="primary">{m.login_again()}</Button>
    </div>
  </div>
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  .shadowed {
    box-shadow: 0px 8px 20px 4px rgba(0, 0, 0, 0.1);
    border: 0.5px solid rgba(54, 54, 54, 0.3);
  }

  .green {
    @apply bg-positive-dimmer text-positive-default;
  }

  .amber {
    @apply bg-warning-dimmer text-warning-default;
  }
</style>
