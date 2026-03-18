<svelte:options runes={false} />

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { createEventDispatcher } from "svelte";
  import type { HttpAuth, HttpAuthMode } from "./httpConfigTypes";
  import { isSecretSentinel } from "./httpConfigTypes";

  export let auth: HttpAuth;
  export let isPublished: boolean;

  const dispatch = createEventDispatcher<{ authChange: { auth: HttpAuth } }>();

  const AUTH_MODES: Array<{ value: HttpAuthMode; label: string }> = [
    { value: "none", label: m.http_auth_none() },
    { value: "bearer_token", label: m.http_auth_bearer() },
    { value: "api_key", label: m.http_auth_api_key() },
    { value: "basic_auth", label: m.http_auth_basic() }
  ];

  function handleModeChange(mode: HttpAuthMode) {
    let next: HttpAuth;
    switch (mode) {
      case "bearer_token":
        next = { mode: "bearer_token", token: "" };
        break;
      case "api_key":
        next = { mode: "api_key", header_name: "X-API-Key", key: "" };
        break;
      case "basic_auth":
        next = { mode: "basic_auth", username: "", password: "" };
        break;
      default:
        next = { mode: "none" };
    }
    dispatch("authChange", { auth: next });
  }

  function updateAuth(patch: Partial<HttpAuth>) {
    dispatch("authChange", { auth: { ...auth, ...patch } as HttpAuth });
  }

  $: storedToken =
    auth.mode === "bearer_token" && isSecretSentinel(auth.token);
  $: storedKey =
    auth.mode === "api_key" && isSecretSentinel(auth.key);
  $: storedPassword =
    auth.mode === "basic_auth" && isSecretSentinel(auth.password);
</script>

<Settings.Row title={m.http_auth_title()} description="">
  <div class="flex flex-col gap-3">
    <select
      class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
      value={auth.mode}
      disabled={isPublished}
      on:change={(e) => handleModeChange(e.currentTarget.value as HttpAuthMode)}
    >
      {#each AUTH_MODES as mode (mode.value)}
        <option value={mode.value}>{mode.label}</option>
      {/each}
    </select>

    {#if auth.mode === "bearer_token"}
      <div class="flex flex-col gap-1">
        {#if storedToken}
          <div class="flex items-center gap-2">
            <span
              class="bg-accent-dimmer/50 text-accent-stronger rounded-md px-2 py-1 text-xs font-medium"
            >
              {m.http_secret_stored()}
            </span>
            <button
              type="button"
              class="text-accent-default text-xs hover:underline"
              disabled={isPublished}
              on:click={() => updateAuth({ token: "" })}
            >
              {m.http_secret_replace()}
            </button>
          </div>
        {:else}
          <input
            class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
            type="password"
            placeholder="Token"
            value={typeof auth.token === "string" ? auth.token : ""}
            disabled={isPublished}
            on:input={(e) => updateAuth({ token: e.currentTarget.value })}
          />
        {/if}
      </div>
    {/if}

    {#if auth.mode === "api_key"}
      <div class="grid gap-2 sm:grid-cols-2">
        <input
          class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
          type="text"
          placeholder={m.http_auth_header_name()}
          value={auth.header_name}
          disabled={isPublished}
          on:input={(e) => updateAuth({ header_name: e.currentTarget.value })}
        />
        {#if storedKey}
          <div class="flex items-center gap-2">
            <span
              class="bg-accent-dimmer/50 text-accent-stronger rounded-md px-2 py-1 text-xs font-medium"
            >
              {m.http_secret_stored()}
            </span>
            <button
              type="button"
              class="text-accent-default text-xs hover:underline"
              disabled={isPublished}
              on:click={() => updateAuth({ key: "" })}
            >
              {m.http_secret_replace()}
            </button>
          </div>
        {:else}
          <input
            class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
            type="password"
            placeholder={m.http_auth_api_key_value()}
            value={typeof auth.key === "string" ? auth.key : ""}
            disabled={isPublished}
            on:input={(e) => updateAuth({ key: e.currentTarget.value })}
          />
        {/if}
      </div>
    {/if}

    {#if auth.mode === "basic_auth"}
      <div class="grid gap-2 sm:grid-cols-2">
        <input
          class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
          type="text"
          placeholder={m.http_auth_username()}
          value={auth.username}
          disabled={isPublished}
          on:input={(e) => updateAuth({ username: e.currentTarget.value })}
        />
        {#if storedPassword}
          <div class="flex items-center gap-2">
            <span
              class="bg-accent-dimmer/50 text-accent-stronger rounded-md px-2 py-1 text-xs font-medium"
            >
              {m.http_secret_stored()}
            </span>
            <button
              type="button"
              class="text-accent-default text-xs hover:underline"
              disabled={isPublished}
              on:click={() => updateAuth({ password: "" })}
            >
              {m.http_secret_replace()}
            </button>
          </div>
        {:else}
          <input
            class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
            type="password"
            placeholder={m.http_auth_password()}
            value={typeof auth.password === "string" ? auth.password : ""}
            disabled={isPublished}
            on:input={(e) => updateAuth({ password: e.currentTarget.value })}
          />
        {/if}
      </div>
    {/if}
  </div>
</Settings.Row>
