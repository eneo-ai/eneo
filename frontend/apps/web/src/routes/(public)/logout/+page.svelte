<script lang="ts">
  import { Button } from "$lib/components/ui/button";
  import AuthPageShell from "$lib/features/auth/components/AuthPageShell.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import type { ActionData, PageData } from "./$types";

  let { data, form }: { data: PageData; form?: ActionData } = $props();

  const expired = $derived(data.message === "expired");
</script>

<svelte:head>
  <title>Eneo.ai – {m.logout()}</title>
</svelte:head>

{#if form?.signOutFailed}
  <!-- The server did not confirm the session ended, so the cookies stay and
       the same action can be tried again. -->
  <AuthPageShell
    tone="error"
    title={m.logout_unavailable()}
    description={m.logout_unavailable_description()}
  >
    <form method="POST" action={localizeHref(`/logout?/${form.signOutFailed}`)}>
      <input type="hidden" name="message" value={form.message} />
      <Button type="submit" size="lg" class="w-full">{m.retry()}</Button>
    </form>
  </AuthPageShell>
{:else}
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
{/if}
