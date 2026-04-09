<script>
  import "../app.css";
  import { initThemeStore } from "$lib/core/theme";
  import { initLanguageStore } from "$lib/core/language";
  import { setContext } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { MESSAGES_CONTEXT_KEY } from "@intric/ui";
  import { Toaster } from "$lib/components/ui/sonner/index.js";

  initThemeStore();
  initLanguageStore();

  // Provide paraglide messages to all UI components
  setContext(MESSAGES_CONTEXT_KEY, m);
</script>

<slot />
<Toaster richColors closeButton />
