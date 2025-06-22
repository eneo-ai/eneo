<script>
  import "../app.css";
  import { initThemeStore } from "$lib/core/theme";
  import { initLanguageStore } from "$lib/core/language";
  initThemeStore();
  initLanguageStore();
</script>

<slot />
