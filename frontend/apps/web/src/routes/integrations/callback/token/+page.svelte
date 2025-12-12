<script lang="ts">
  import { onMount } from "svelte";

  const MESSAGE_TYPE = "intric/integration-callback";

  onMount(() => {
    const url = new URL(window.location.href);
    const code = url.searchParams.get("code");
    const state = url.searchParams.get("state");
    const params = url.search;

    const opener = window.opener;
    if (opener) {
      opener.postMessage({ type: MESSAGE_TYPE, code, state, params }, "*");
      window.close();
    }
  });
</script>

<svelte:head>
  <title>Processing integration authentication…</title>
</svelte:head>

<main class="callback">
  <h1>Finishing sign-in…</h1>
  <p>You can close this window.</p>
</main>

<style>
  .callback {
    margin: 0;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 1rem;
    background: var(--color-primary-bg, #fff);
    color: var(--color-primary-text, #111);
  }
</style>
