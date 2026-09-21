<script lang="ts">
  import CodeBlock from "$lib/CodeBlock/CodeBlock.svelte";
  import type { Tokens } from "marked";

  export let token: Tokens.Code;
</script>

<CodeBlock source={token.text} lang={token.lang}></CodeBlock>
