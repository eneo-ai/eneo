<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
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

  const uid = $props.id();

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

  let pendingFocusId = $state<string | null>(null);

  function replaceSecret(patch: Partial<HttpAuth>, focusId: string) {
    pendingFocusId = focusId;
    updateAuth(patch);
  }

  $effect(() => {
    void auth;
    if (pendingFocusId === null) return;
    const el = document.getElementById(pendingFocusId);
    if (el instanceof HTMLElement) {
      el.focus();
      pendingFocusId = null;
    }
  });

  const storedToken = $derived(auth.mode === "bearer_token" && isSecretSentinel(auth.token));
  const storedKey = $derived(auth.mode === "api_key" && isSecretSentinel(auth.key));
  const storedPassword = $derived(auth.mode === "basic_auth" && isSecretSentinel(auth.password));

  const authModeLabel = $derived(
    AUTH_MODES.find((mode) => mode.value === auth.mode)?.label ?? auth.mode
  );
</script>

{#snippet storedSecret(patch: Partial<HttpAuth>, focusId: string)}
  <div class="flex flex-col gap-1">
    <div class="flex items-center gap-2">
      <Badge variant="outline">
        {m.http_secret_stored()}
      </Badge>
      <Button
        variant="link"
        size="sm"
        class="h-auto p-0 text-xs"
        disabled={isPublished}
        onclick={() => replaceSecret(patch, focusId)}
      >
        {m.http_secret_replace()}
      </Button>
    </div>
    <p class="text-muted text-xs leading-relaxed">{m.http_secret_stored_help()}</p>
  </div>
{/snippet}

<Settings.Row title={m.http_auth_title()} description={m.http_auth_desc()} density="compact">
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
      <div class="flex flex-col gap-1.5">
        <Label for="{uid}-token" class="text-xs">{m.http_auth_bearer()}</Label>
        {#if storedToken}
          {@render storedSecret({ token: "" }, `${uid}-token`)}
        {:else}
          <Input
            id="{uid}-token"
            type="password"
            placeholder={m.http_auth_token_placeholder()}
            value={typeof auth.token === "string" ? auth.token : ""}
            disabled={isPublished}
            oninput={(e) => updateAuth({ token: e.currentTarget.value })}
          />
        {/if}
      </div>
    {/if}

    {#if auth.mode === "api_key"}
      <div class="grid gap-2 sm:grid-cols-2">
        <div class="flex flex-col gap-1.5">
          <Label for="{uid}-header-name" class="text-xs">{m.http_auth_header_name()}</Label>
          <Input
            id="{uid}-header-name"
            type="text"
            placeholder={m.http_auth_header_name()}
            value={auth.header_name}
            disabled={isPublished}
            oninput={(e) => updateAuth({ header_name: e.currentTarget.value })}
          />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="{uid}-api-key" class="text-xs">{m.http_auth_api_key_value()}</Label>
          {#if storedKey}
            {@render storedSecret({ key: "" }, `${uid}-api-key`)}
          {:else}
            <Input
              id="{uid}-api-key"
              type="password"
              placeholder={m.http_auth_api_key_value()}
              value={typeof auth.key === "string" ? auth.key : ""}
              disabled={isPublished}
              oninput={(e) => updateAuth({ key: e.currentTarget.value })}
            />
          {/if}
        </div>
      </div>
    {/if}

    {#if auth.mode === "basic_auth"}
      <div class="grid gap-2 sm:grid-cols-2">
        <div class="flex flex-col gap-1.5">
          <Label for="{uid}-username" class="text-xs">{m.http_auth_username()}</Label>
          <Input
            id="{uid}-username"
            type="text"
            placeholder={m.http_auth_username()}
            value={auth.username}
            disabled={isPublished}
            oninput={(e) => updateAuth({ username: e.currentTarget.value })}
          />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="{uid}-password" class="text-xs">{m.http_auth_password()}</Label>
          {#if storedPassword}
            {@render storedSecret({ password: "" }, `${uid}-password`)}
          {:else}
            <Input
              id="{uid}-password"
              type="password"
              placeholder={m.http_auth_password()}
              value={typeof auth.password === "string" ? auth.password : ""}
              disabled={isPublished}
              oninput={(e) => updateAuth({ password: e.currentTarget.value })}
            />
          {/if}
        </div>
      </div>
    {/if}
  </div>
</Settings.Row>
