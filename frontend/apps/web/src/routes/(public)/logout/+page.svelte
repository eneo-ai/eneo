<script lang="ts">
  import { Button } from "$lib/components/ui/button";
  import AuthPageShell from "$lib/features/auth/components/AuthPageShell.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import type { PageData } from "./$types";

  let { data }: { data: PageData } = $props();

  const expired = $derived(data.message === "expired");
</script>

<svelte:head>
  <title>Eneo.ai – {m.logout()}</title>
</svelte:head>

<AuthPageShell
  tone={expired ? "warning" : "success"}
  title={expired ? m.session_expired() : m.logout_success()}
  description={expired ? m.session_expired_description() : m.logout_description()}
>
  <Button href={localizeHref("/login")} size="lg" class="w-full">{m.login_again()}</Button>
</AuthPageShell>
