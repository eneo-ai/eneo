<script lang="ts">
  import CodeBlock from "$lib/components/CodeBlock.svelte";
  import type { Tokens } from "marked";
  import { getDefaultCodeLanguage } from "../CodeLanguageContext.js";

  export let token: Tokens.Code;

  const defaultLanguage = getDefaultCodeLanguage();
</script>

<CodeBlock source={token.text} lang={token.lang || defaultLanguage()}></CodeBlock>
