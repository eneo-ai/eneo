<script>
  import "../app.css";
  import { initThemeStore } from "$lib/core/theme";
  import { initLanguageStore } from "$lib/core/language";
  import { Toaster } from "$lib/components/ui/sonner/index.js";

  const theme = initThemeStore();
  initLanguageStore();
</script>

<slot />
<Toaster theme={$theme} richColors closeButton />
