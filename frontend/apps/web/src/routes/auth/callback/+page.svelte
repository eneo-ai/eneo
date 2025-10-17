<script lang="ts">
  import { goto } from "$app/navigation";
  import { browser } from "$app/environment";
  import { onMount } from "svelte";
  import { m } from "$lib/paraglide/messages";

  const { data } = $props();

  // If there was an error during server-side processing, redirect to login
  onMount(() => {
    if (data.error) {
      console.error("Authentication callback error:", data.error, {
        detailCode: data.detailCode,
        rawDetail: data.rawDetail,
        correlationId: data.correlationId
      });

      // Redirect to login with error message
      const params = new URLSearchParams();
      params.set("message", data.error);

      if (data.detailCode) {
        params.set("detailCode", data.detailCode);
      }

      if (data.correlationId) {
        params.set("correlation", data.correlationId);
      }

      if (data.rawDetail) {
        params.set("rawDetail", data.rawDetail);
      }

      if (browser) {
        const rememberedTenant = sessionStorage.getItem("eneo-last-tenant-slug");
        if (rememberedTenant) {
          params.set("tenant", rememberedTenant);
        }
      }

      setTimeout(() => goto(`/login?${params.toString()}`, { replaceState: true }), 1200);
    }
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.completing_authentication()}</title>
</svelte:head>

<div class="bg-default flex min-h-screen items-center justify-center px-4">
  <div class="max-w-md text-center">
    {#if !data.error}
      <!-- Success: Processing authentication -->
      <div
        class="border-accent-default mx-auto mb-6 h-16 w-16 animate-spin rounded-full border-b-2"
      ></div>
      <h2 class="text-default mb-2 text-xl font-semibold">
        {m.completing_authentication()}
      </h2>
      <p class="text-dimmer">
        {m.redirecting_to_authentication()}
      </p>
    {:else}
      <!-- Error state -->
      <div class="text-negative-default mb-6">
        <svg class="mx-auto h-16 w-16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
      </div>
      <h2 class="text-default mb-2 text-xl font-semibold">
        {m.authentication_failed()}
      </h2>
      {#if data.rawDetail}
        <p class="text-default mb-4">{data.rawDetail}</p>
      {/if}
      <p class="text-dimmer text-sm">
        {m.redirecting_to_authentication()}
      </p>
    {/if}
  </div>
</div>
