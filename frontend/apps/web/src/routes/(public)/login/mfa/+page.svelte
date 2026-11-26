<script lang="ts">
  import { Button } from "$lib/components/ui/button";
  import AuthAlert from "$lib/features/auth/components/AuthAlert.svelte";
  import AuthPageShell from "$lib/features/auth/components/AuthPageShell.svelte";
  import CorrelationReference from "$lib/features/auth/components/CorrelationReference.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import type { ActionData, PageData } from "./$types";

  let { data, form }: { data: PageData; form: ActionData } = $props();

  let starting = $state(false);
  const notConfigured = $derived(data.end === "mfa_not_configured");
</script>

<svelte:head>
  <title>Eneo.ai – {m.mfa_sign_in_title()}</title>
</svelte:head>

<AuthPageShell
  title={m.mfa_sign_in_title()}
  description={data.end ? undefined : m.mfa_sign_in_start_description()}
>
  {#if data.end}
    <AuthAlert
      tone="warning"
      title={notConfigured ? m.mfa_sign_in_not_configured_title() : m.mfa_sign_in_not_met_title()}
    >
      <p>
        {notConfigured
          ? m.mfa_sign_in_not_configured_description()
          : m.mfa_sign_in_not_met_description()}
      </p>
      {#if data.correlation}
        <CorrelationReference correlationId={data.correlation} />
      {/if}
    </AuthAlert>
  {/if}

  {#if form?.failed}
    <AuthAlert tone="error" title={m.authentication_failed()}>
      <p>
        {form.unavailable ? m.oidc_error_login_unavailable() : m.failed_to_start_authentication()}
      </p>
    </AuthAlert>
  {/if}

  <div class="flex flex-col gap-2">
    {#if !notConfigured}
      <!-- A form, not a link: only a press starts a sign-in. The browser submits it
           itself, since the answer is a redirect to the identity provider's site. -->
      <form method="POST" onsubmit={() => (starting = true)}>
        <input type="hidden" name="next" value={data.next} />
        <Button type="submit" size="lg" class="w-full" aria-busy={starting}>
          {#if starting}
            {m.redirecting_to_authentication()}
          {:else if data.end}
            {m.mfa_sign_in_retry()}
          {:else}
            {m.federation_admin_mfa_sign_in()}
          {/if}
        </Button>
      </form>
    {/if}
    <Button
      href={localizeHref(data.next)}
      variant={notConfigured ? "default" : "outline"}
      size="lg"
      class="w-full"
    >
      {m.mfa_sign_in_back()}
    </Button>
  </div>
</AuthPageShell>
