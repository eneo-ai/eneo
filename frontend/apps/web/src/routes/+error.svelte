<script lang="ts">
  import { Button } from "@intric/ui";
  import { browser } from "$app/environment";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import type { IntricErrorCode } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";

  type Error = {
    message: string;
    status: number;
    code: IntricErrorCode;
  };

  let appError: Error | undefined = undefined;

  async function handleServerError(error: Error) {
    if (error.code === 9006) {
      goto("/activate");
      return;
    }
    if (error.code === 9025) {
      goto("/deactivated");
      return;
    }
    if (error.status === 401) {
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
      <div class="pb-4 text-2xl">Error {appError.status}: {appError.message}</div>
      <p class="text-lg">{m.were_experiencing_difficulties()}</p>
      <div class="flex items-center justify-center gap-2 text-lg">
        <p>{m.if_error_persists()}</p>
        <Button
          href="/login?clear_cookies=true"
          unstyled
          class="hover:text-hover-on-fill hover:bg-accent-stronger underline"
          >{m.delete_cookies()}</Button
        >
      </div>
      <p class="pt-4">(Code: {appError.code})</p>
    </div>
  </div>
{/if}
