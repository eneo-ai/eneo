<script lang="ts">
  import type { Tokens } from "marked";

  export let token: Tokens.HTML | Tokens.Tag;
</script>

<code class="bg-secondary rounded-lg px-1.5 py-0.5 whitespace-pre-wrap before:hidden after:hidden"
  >{token.text}</code
>

<style>
  code {
    font-weight: inherit !important;
  }
</style>
