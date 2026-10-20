<script lang="ts">
  import type { Snippet } from "svelte";
  import AccountLayout from "$lib/features/account/AccountLayout.svelte";

  let { children }: { children: Snippet } = $props();
</script>

<AccountLayout {children} />
