<script lang="ts">
  import AuthPageShell from "$lib/features/auth/components/AuthPageShell.svelte";
  import AuthAlert from "$lib/features/auth/components/AuthAlert.svelte";
  import PasswordChangeForm from "$lib/features/auth/components/PasswordChangeForm.svelte";
  import { Button } from "$lib/components/ui/button";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  let { data } = $props();

  const description = $derived(
    data.reason === "expired"
      ? m.password_change_required_expired()
      : data.reason === "admin_set"
        ? m.password_change_required_admin_set()
        : m.password_change_not_available()
  );
  // "The password you just signed in with" only fits a one-time password: an
  // expired one may belong to a session that started days ago.
  const currentPasswordHint = $derived(
    data.reason === "expired"
      ? m.password_change_required_expired_current_hint()
      : m.password_change_required_current_hint()
  );
  // A relative action replaces the page's query string, so `next` has to ride along.
  const action = $derived(
    data.next ? `?/changePassword&next=${encodeURIComponent(data.next)}` : "?/changePassword"
  );
</script>

<svelte:head>
  <title>Eneo.ai – {m.password_change_required_title()}</title>
</svelte:head>

<AuthPageShell title={m.password_change_required_title()} {description} tone="warning" size="md">
  {#if data.capability.source === "eneo"}
    <PasswordChangeForm
      capability={data.capability}
      username={data.username}
      {action}
      {currentPasswordHint}
    />
  {:else if data.reason !== null}
    <AuthAlert tone="error">
      <p>{m.password_change_not_available()}</p>
    </AuthAlert>
  {/if}
  <form method="POST" action={localizeHref("/logout?/logout")} class="self-center">
    <Button type="submit" variant="link">{m.logout()}</Button>
  </form>
</AuthPageShell>
