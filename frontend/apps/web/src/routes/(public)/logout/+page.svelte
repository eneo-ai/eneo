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
  tone={expired ? "warning" : data.signedIn ? undefined : "success"}
  title={expired ? m.session_expired() : data.signedIn ? m.logout() : m.logout_success()}
  description={expired
    ? m.session_expired_description()
    : data.signedIn
      ? m.logout_confirmation_description()
      : m.logout_description()}
>
  {#if data.signedIn}
    <form method="POST" action={localizeHref("/logout?/logout")}>
      <input type="hidden" name="message" value={expired ? "expired" : "logout"} />
      <Button type="submit" size="lg" class="w-full">
        {expired ? m.login_again() : m.logout()}
      </Button>
    </form>
  {:else}
    <Button href={localizeHref("/login")} size="lg" class="w-full">{m.login_again()}</Button>
  {/if}
</AuthPageShell>
