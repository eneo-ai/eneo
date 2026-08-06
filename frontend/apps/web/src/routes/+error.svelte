<script lang="ts">
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getErrorCodeMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import Check from "@lucide/svelte/icons/check";
  import Copy from "@lucide/svelte/icons/copy";

  /** Codes and statuses that are a state to recover from, not a page to read. */
  function recoveryRoute(error: App.Error): string | undefined {
    if (error.code === 9006) return "/activate";
    if (error.code === 9025) return "/deactivated";
    if (error.status === 401) return "/logout?message=expired";
    return undefined;
  }

  const appError = $derived<App.Error>(
    $page.error ?? { code: 0, message: m.unexpected_error(), status: 500 }
  );
  // The backend message is English; the code has a localized message when we
  // know it. Same resolution the toasts use.
  const message = $derived(getErrorCodeMessage(appError.code) ?? appError.message);
  const heading = $derived(m.error_status_message({ status: appError.status, message }));
  const redirectTo = $derived(recoveryRoute(appError));

  let copyState = $state<"idle" | "copied" | "failed">("idle");
  let resetCopyState: ReturnType<typeof setTimeout> | undefined;

  async function copyReferenceId(referenceId: string) {
    try {
      await navigator.clipboard.writeText(referenceId);
      copyState = "copied";
    } catch {
      // No Clipboard API, an insecure context, or a denied write. The id is
      // selectable either way, so say that rather than fail silently — and
      // never let this escape as a second error on the error page.
      copyState = "failed";
    }
    clearTimeout(resetCopyState);
    resetCopyState = setTimeout(() => (copyState = "idle"), 4000);
  }

  // Effects never run on the server, so the redirect stays a client concern
  // while the markup below still renders without JavaScript.
  $effect(() => {
    if (redirectTo) {
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- server endpoints, not typed routes
      goto(redirectTo);
    }
  });

  $effect(() => () => clearTimeout(resetCopyState));
</script>

<svelte:head>
  <title>{heading}</title>
</svelte:head>

{#if redirectTo === undefined}
  <div
    class="bg-secondary absolute inset-0 flex flex-col items-center justify-center overflow-y-auto px-6 py-8"
  >
    <div class="flex w-full max-w-md flex-col items-center gap-4 text-center">
      <!-- The alert role is what tells a screen reader something went wrong
           when this page replaces the one being loaded. -->
      <div role="alert">
        <h1 class="text-xl break-words sm:text-2xl">{heading}</h1>
        <p class="pt-2 text-lg">{m.were_experiencing_difficulties()}</p>
      </div>

      <!-- A link to the same URL, not a reload button: it retries with or
           without JavaScript, and `data-sveltekit-reload` forces a fresh server
           render instead of a client navigation the router may treat as a
           no-op. -->
      <Button
        href={$page.url.pathname + $page.url.search}
        data-sveltekit-reload
        size="lg"
        class="min-h-12 px-6">{m.error_try_again()}</Button
      >

      <!-- One sentence, so it wraps as prose instead of breaking at the link. -->
      <p class="text-lg">
        {m.if_error_persists()}
        <Button
          href={localizeHref("/login?clear_cookies=true")}
          variant="link"
          class="h-auto p-0 align-baseline text-lg underline">{m.delete_cookies()}</Button
        >
      </p>

      {#if appError.code}
        <p class="text-muted text-sm">{m.error_code({ code: appError.code })}</p>
      {/if}

      <!-- The trace id ties this failure to the backend logs; support cannot
           look anything up without it, so it has to be readable and copyable. -->
      {#if appError.traceId}
        {@const referenceId = appError.traceId}
        <div class="flex w-full flex-col items-center gap-1">
          <span class="text-muted text-sm">{m.error_reference_id()}</span>
          <div class="flex w-full flex-wrap items-center justify-center gap-1">
            <code class="max-w-full text-sm break-all select-all">{referenceId}</code>
            <Button
              variant="ghost"
              size="lg"
              class="min-h-12 gap-1.5 px-3"
              aria-label={copyState === "copied"
                ? m.copied_to_clipboard()
                : m.copy_error_reference_id()}
              onclick={() => copyReferenceId(referenceId)}
            >
              {#if copyState === "copied"}
                <Check aria-hidden="true" />
              {:else}
                <Copy aria-hidden="true" />
              {/if}
              {copyState === "copied" ? m.copied() : m.copy()}
            </Button>
          </div>
          <!-- One status region for both outcomes. Success is already visible
               on the button, so only the failure needs to be seen as well. -->
          <p role="status" class={copyState === "failed" ? "text-muted text-sm" : "sr-only"}>
            {#if copyState === "copied"}
              {m.copied_to_clipboard()}
            {:else if copyState === "failed"}
              {m.copy_failed_select_manually()}
            {/if}
          </p>
        </div>
      {/if}
    </div>
  </div>
{/if}
