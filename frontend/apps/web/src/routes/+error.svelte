<script lang="ts">
  import { Button } from "@eneo/ui";
  import { browser } from "$app/environment";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import type { EneoErrorCode } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  type Error = {
    message: string;
    status: number;
    code: EneoErrorCode;
  };

  let appError: Error | undefined = undefined;

  async function handleServerError(error: Error) {
    if (error.code === 9006) {
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- server endpoint, not a typed route
      goto("/activate");
      return;
    }
    if (error.code === 9025) {
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- server endpoint, not a typed route
      goto("/deactivated");
      return;
    }
    if (error.status === 401) {
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- server endpoint, not a typed route
      goto("/logout?message=expired");
      return;
    }
    appError = error;
  }

  function init() {
    if (!browser) return;

    if ($page.error) {
      handleServerError($page.error);
    } else {
      appError = {
        code: 0,
        message: m.unexpected_error(),
        status: 500
      };
    }
  }

  init();
</script>

{#if appError !== undefined}
  <div class="bg-secondary absolute inset-0 flex flex-col items-center justify-center">
    <div class="flex flex-col justify-center pb-12 text-center">
      <div class="pb-4 text-2xl">
        {m.error_status_message({ status: appError.status, message: appError.message })}
      </div>
      <p class="text-lg">{m.were_experiencing_difficulties()}</p>
      <div class="flex items-center justify-center gap-2 text-lg">
        <p>{m.if_error_persists()}</p>
        <Button
          href={localizeHref("/login?clear_cookies=true")}
          unstyled
          class="hover:text-hover-on-fill hover:bg-accent-stronger underline"
          >{m.delete_cookies()}</Button
        >
      </div>
      <p class="pt-4">{m.error_code({ code: appError.code })}</p>
    </div>
  </div>
{/if}
