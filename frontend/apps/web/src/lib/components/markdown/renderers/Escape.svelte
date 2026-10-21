<script lang="ts">
  import type { Tokens } from "marked";

  // `\$`, `\*`, `\(`: the character the backslash protects, without the backslash.
  const { token }: { token: Tokens.Escape } = $props();
</script>

{token.text}
