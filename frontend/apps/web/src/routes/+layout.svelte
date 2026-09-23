<script>
  import "../app.css";
  import { initThemeStore } from "$lib/core/theme";
  import { initLanguageStore } from "$lib/core/language";
  import { Toaster } from "$lib/components/ui/sonner/index.js";

  initThemeStore();
  initLanguageStore();
</script>

<slot />
<Toaster richColors closeButton />
