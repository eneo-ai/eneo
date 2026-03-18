<svelte:options runes={false} />

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { createEventDispatcher } from "svelte";
  import type {
    HttpAuthoredConfig,
    HttpDirection,
    HttpMethod,
    HttpAuth,
    HttpBody,
    CustomHeader
  } from "./httpConfigTypes";
  import HttpAuthSection from "./HttpAuthSection.svelte";
  import HttpHeadersEditor from "./HttpHeadersEditor.svelte";
  import HttpBodyEditor from "./HttpBodyEditor.svelte";
  import HttpTestConnection from "./HttpTestConnection.svelte";

  export let config: HttpAuthoredConfig;
  export let direction: HttpDirection;
  export let method: HttpMethod;
  export let isPublished: boolean;
  export let flowId: string;

  const dispatch = createEventDispatcher<{
    configChange: { config: HttpAuthoredConfig };
  }>();

  function update(patch: Partial<HttpAuthoredConfig>) {
    dispatch("configChange", { config: { ...config, ...patch } });
  }

  function handleAuthChange(event: CustomEvent<{ auth: HttpAuth }>) {
    update({ auth: event.detail.auth });
  }

  function handleBodyChange(event: CustomEvent<{ body: HttpBody }>) {
    update({ body: event.detail.body });
  }

  function handleHeadersChange(
    event: CustomEvent<{ headers: CustomHeader[] }>
  ) {
    update({ custom_headers: event.detail.headers });
  }

  $: urlInvalid = (() => {
    const val = config.url.trim();
    if (!val) return false;
    try {
      const parsed = new URL(val);
      return !["http:", "https:"].includes(parsed.protocol);
    } catch {
      return true;
    }
  })();
</script>

<Settings.Group title={m.http_config_title()}>
  <Settings.Row title={m.http_url_title()} description="">
    <div class="flex flex-col gap-1">
      <input
        class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50 {urlInvalid
          ? 'border-danger-default/60'
          : ''}"
        type="url"
        placeholder="https://api.example.com/webhook"
        value={config.url}
        disabled={isPublished}
        on:input={(e) => update({ url: e.currentTarget.value })}
      />
      {#if urlInvalid}
        <p class="text-danger-default text-xs">{m.http_url_invalid()}</p>
      {/if}
    </div>
  </Settings.Row>

  <HttpAuthSection
    auth={config.auth}
    {isPublished}
    on:authChange={handleAuthChange}
  />

  <HttpBodyEditor
    body={config.body}
    {method}
    {isPublished}
    on:bodyChange={handleBodyChange}
  />

  {#if direction === "input"}
    <Settings.Row title={m.http_response_format()} description="">
      <select
        class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
        value={config.response_format ?? "text"}
        disabled={isPublished}
        on:change={(e) =>
          update({
            response_format: e.currentTarget.value as "text" | "json"
          })}
      >
        <option value="text">Text</option>
        <option value="json">JSON</option>
      </select>
    </Settings.Row>
  {/if}

  <HttpHeadersEditor
    headers={config.custom_headers}
    {isPublished}
    on:headersChange={handleHeadersChange}
  />

  <Settings.Row title={m.http_timeout_title()} description="">
    <div class="flex items-center gap-2">
      <input
        class="border-default bg-primary w-24 rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
        type="number"
        min="1"
        max="120"
        value={config.timeout_seconds}
        disabled={isPublished}
        on:input={(e) =>
          update({
            timeout_seconds: Math.max(
              1,
              Math.min(120, Number(e.currentTarget.value) || 30)
            )
          })}
      />
      <span class="text-muted text-sm">{m.http_timeout_unit()}</span>
    </div>
  </Settings.Row>

  <Settings.Row title={m.http_test_title()} description="" fullWidth={true}>
    <HttpTestConnection
      {config}
      {direction}
      {method}
      {flowId}
      {isPublished}
    />
  </Settings.Row>
</Settings.Group>
