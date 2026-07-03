<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import type { HttpAuth, HttpAuthMode } from "./httpConfigTypes";
  import { isSecretSentinel } from "./httpConfigTypes";

  let {
    auth,
    isPublished,
    onAuthChange
  }: {
    auth: HttpAuth;
    isPublished: boolean;
    onAuthChange?: (detail: { auth: HttpAuth }) => void;
  } = $props();

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
    onAuthChange?.({ auth: next });
  }

  function updateAuth(patch: Partial<HttpAuth>) {
    onAuthChange?.({ auth: { ...auth, ...patch } as HttpAuth });
  }

  const storedToken = $derived(auth.mode === "bearer_token" && isSecretSentinel(auth.token));
  const storedKey = $derived(auth.mode === "api_key" && isSecretSentinel(auth.key));
  const storedPassword = $derived(auth.mode === "basic_auth" && isSecretSentinel(auth.password));

  const authModeLabel = $derived(
    AUTH_MODES.find((mode) => mode.value === auth.mode)?.label ?? auth.mode
  );
</script>

<Settings.Row title={m.http_auth_title()} description="">
  <div class="flex flex-col gap-3">
    <Select.Root
      type="single"
      value={auth.mode}
      disabled={isPublished}
      onValueChange={(value) => handleModeChange(value as HttpAuthMode)}
    >
      <Select.Trigger class="w-full" aria-label={m.http_auth_title()}>
        {authModeLabel}
      </Select.Trigger>
      <Select.Content>
        <Select.Group>
          {#each AUTH_MODES as mode (mode.value)}
            <Select.Item value={mode.value} label={mode.label}>{mode.label}</Select.Item>
          {/each}
        </Select.Group>
      </Select.Content>
    </Select.Root>

    {#if auth.mode === "bearer_token"}
      <div class="flex flex-col gap-1">
        {#if storedToken}
          <div class="flex items-center gap-2">
            <Badge variant="outline">
              {m.http_secret_stored()}
            </Badge>
            <button
              type="button"
              class="text-accent-default text-xs hover:underline"
              disabled={isPublished}
              onclick={() => updateAuth({ token: "" })}
            >
              {m.http_secret_replace()}
            </button>
          </div>
        {:else}
          <input
            class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
            type="password"
            placeholder="Token"
            value={typeof auth.token === "string" ? auth.token : ""}
            disabled={isPublished}
            oninput={(e) => updateAuth({ token: e.currentTarget.value })}
          />
        {/if}
      </div>
    {/if}

    {#if auth.mode === "api_key"}
      <div class="grid gap-2 sm:grid-cols-2">
        <input
          class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
          type="text"
          placeholder={m.http_auth_header_name()}
          value={auth.header_name}
          disabled={isPublished}
          oninput={(e) => updateAuth({ header_name: e.currentTarget.value })}
        />
        {#if storedKey}
          <div class="flex items-center gap-2">
            <Badge variant="outline">
              {m.http_secret_stored()}
            </Badge>
            <button
              type="button"
              class="text-accent-default text-xs hover:underline"
              disabled={isPublished}
              onclick={() => updateAuth({ key: "" })}
            >
              {m.http_secret_replace()}
            </button>
          </div>
        {:else}
          <input
            class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
            type="password"
            placeholder={m.http_auth_api_key_value()}
            value={typeof auth.key === "string" ? auth.key : ""}
            disabled={isPublished}
            oninput={(e) => updateAuth({ key: e.currentTarget.value })}
          />
        {/if}
      </div>
    {/if}

    {#if auth.mode === "basic_auth"}
      <div class="grid gap-2 sm:grid-cols-2">
        <input
          class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
          type="text"
          placeholder={m.http_auth_username()}
          value={auth.username}
          disabled={isPublished}
          oninput={(e) => updateAuth({ username: e.currentTarget.value })}
        />
        {#if storedPassword}
          <div class="flex items-center gap-2">
            <Badge variant="outline">
              {m.http_secret_stored()}
            </Badge>
            <button
              type="button"
              class="text-accent-default text-xs hover:underline"
              disabled={isPublished}
              onclick={() => updateAuth({ password: "" })}
            >
              {m.http_secret_replace()}
            </button>
          </div>
        {:else}
          <input
            class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
            type="password"
            placeholder={m.http_auth_password()}
            value={typeof auth.password === "string" ? auth.password : ""}
            disabled={isPublished}
            oninput={(e) => updateAuth({ password: e.currentTarget.value })}
          />
        {/if}
      </div>
    {/if}
  </div>
</Settings.Row>
