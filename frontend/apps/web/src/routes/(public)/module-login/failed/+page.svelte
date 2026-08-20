<script lang="ts">
  import { DEFAULT_LANDING_PAGE } from "$lib/core/constants";
  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { Button } from "@eneo/ui";

  const { data } = $props();

  const description = $derived(
    data.reason === "service_unavailable"
      ? m.module_login_service_unavailable()
      : data.reason === "module_unavailable"
        ? m.module_login_unavailable()
        : m.module_login_invalid_request()
  );
</script>

<svelte:head>
  <title>Eneo.ai – {m.module_login_failed()}</title>
</svelte:head>

<main class="relative flex min-h-screen items-center justify-center px-4">
  <section class="box w-full max-w-md justify-center" aria-labelledby="module-login-error-title">
    <h1 class="flex justify-center">
      <EneoWordMark class="text-brand-eneo h-16 w-20" />
      <span class="sr-only">{m.app_name()}</span>
    </h1>

    <div class="bg-negative-dimmer text-negative-default flex flex-col gap-3 p-4 shadow-lg">
      <strong id="module-login-error-title">{m.module_login_failed()}</strong>
      <p>{description}</p>
    </div>

    <div class="border-default bg-primary flex flex-col gap-3 p-4">
      <Button href={localizeHref(DEFAULT_LANDING_PAGE)} variant="primary">
        {m.module_login_back_to_eneo()}
      </Button>
    </div>
  </section>
</main>
