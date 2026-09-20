<script lang="ts">
  import { Button } from "$lib/components/ui/button";
  import AuthPageShell from "$lib/features/auth/components/AuthPageShell.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import type { PageData } from "./$types";

  let { data }: { data: PageData } = $props();
</script>

<svelte:head>
  <title>Eneo.ai – {m.login_failed()}</title>
</svelte:head>

<AuthPageShell
  tone="error"
  title={m.login_failed()}
  description={data.message || m.authentication_error_occurred()}
>
  {#if data.details}
    <div class="bg-secondary rounded-lg p-3 text-xs">
      <p class="text-muted mb-1">{m.details()}</p>
      <code class="font-mono break-all select-all">{data.details}</code>
    </div>
  {/if}

  <Button href={localizeHref(data.retryUrl)} size="lg" class="w-full">
    {m.try_logging_in_again()}
  </Button>
</AuthPageShell>
