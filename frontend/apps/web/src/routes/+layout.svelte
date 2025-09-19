<script>
  import "../app.css";
  import { initThemeStore } from "$lib/core/theme";
  import { initLanguageStore } from "$lib/core/language";
  import { setContext } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { MESSAGES_CONTEXT_KEY } from "@intric/ui";

  initThemeStore();
  initLanguageStore();

  // Provide paraglide messages to all UI components
  setContext(MESSAGES_CONTEXT_KEY, m);
</script>

<slot />
