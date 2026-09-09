<script>
  import "../app.css";
  import { initThemeStore } from "$lib/core/theme";
  import { initLanguageStore } from "$lib/core/language";
  import { setContext } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { LOCALE_CONTEXT_KEY, MESSAGES_CONTEXT_KEY } from "@eneo/ui";
  import { Toaster } from "$lib/components/ui/sonner/index.js";

  initThemeStore();
  initLanguageStore();

  // Provide paraglide messages and the active locale to all UI components
  setContext(MESSAGES_CONTEXT_KEY, m);
  setContext(LOCALE_CONTEXT_KEY, getLocale() === "sv" ? "sv-SE" : "en-US");
</script>

<slot />
<Toaster richColors closeButton />
