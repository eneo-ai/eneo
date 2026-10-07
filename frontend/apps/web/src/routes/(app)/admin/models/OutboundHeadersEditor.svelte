<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Outbound headers for one model provider: a repeatable name/value table.

  The dynamic values offered, and which provider types support headers at all,
  come from the server (`getOutboundHeaderOptions`); nothing about tokens is
  hard-coded here. Secret values follow the api_key pattern: never seeded into
  an input, kept by omission, replaced only after an explicit "Change" that
  can be cancelled.
-->

<script lang="ts">
  import type { OutboundHeaderOptions } from "@eneo/eneo-js";
  import { tick } from "svelte";
  import { Braces, CircleAlert, Info, Plus, Trash2, TriangleAlert } from "@lucide/svelte";

  import { m } from "$lib/paraglide/messages";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";

  import {
    canKeepStored,
    changeStored,
    headerClassification,
    insertToken,
    isRowComplete,
    isUnencryptedRemote,
    keepStored,
    newHeaderRow,
    setSecret,
    supportsOutboundHeaders,
    tokenProblems,
    type HeaderEncoding,
    type HeaderOnMissing,
    type HeaderRow,
    type StoredPart
  } from "./outboundHeaders";

  let {
    providerType,
    options,
    rows = $bindable(),
    idPrefix,
    endpoint = "",
    optionsError = false,
    onRetry,
    editing = false
  }: {
    providerType: string;
    options: OutboundHeaderOptions | null;
    rows: HeaderRow[];
    idPrefix: string;
    /** The endpoint being configured, for the plain-http warning. */
    endpoint?: string;
    /** The options request failed; offer a retry instead of the editor. */
    optionsError?: boolean;
    onRetry?: () => void;
    /** Editing a saved provider, whose headers stay as they are without options. */
    editing?: boolean;
  } = $props();

  const MASK = "••••••••";

  const supported = $derived(supportsOutboundHeaders(options, providerType));
  const classification = $derived(headerClassification(rows, options));
  const maxHeaders = $derived(options?.max_headers ?? 10);
  const atMax = $derived(rows.length >= maxHeaders);
  const incomplete = $derived(rows.some((row) => !isRowComplete(row, options)));
  const plainHttp = $derived(rows.some((row) => row.secret) && isUnencryptedRemote(endpoint));
  const noticeId = $derived(`${idPrefix}-notice`);
  const addId = $derived(`${idPrefix}-add`);

  // Examples come from the registry, preferring a value that describes a group.
  const exampleToken = $derived(
    options?.dynamic_values.find((value) => value.classification === "organisational")?.token ??
      options?.dynamic_values[0]?.token
  );
  const valuePlaceholder = $derived(exampleToken ? `{{${exampleToken}}}` : "");

  const encodingOptions: { value: HeaderEncoding; label: () => string }[] = [
    { value: "percent", label: m.outbound_headers_encoding_percent },
    { value: "none", label: m.outbound_headers_encoding_none }
  ];
  const onMissingOptions: { value: HeaderOnMissing; label: () => string }[] = [
    { value: "omit", label: m.outbound_headers_on_missing_omit },
    { value: "fallback", label: m.outbound_headers_on_missing_fallback },
    { value: "fail", label: m.outbound_headers_on_missing_fail }
  ];

  function tokenDescription(value: OutboundHeaderOptions["dynamic_values"][number]): string {
    return value.source === "external_id"
      ? m.outbound_headers_token_source_external_id()
      : m.outbound_headers_token_source_scim({ attribute: value.attribute });
  }

  function rowId(row: HeaderRow): string {
    return `${idPrefix}-${row.key}`;
  }

  function rowLabel(row: HeaderRow, index: number): string {
    return row.name.trim() || m.outbound_headers_unnamed({ position: index + 1 });
  }

  function focusElement(id: string) {
    void tick().then(() => document.getElementById(id)?.focus());
  }

  function addRow() {
    const row = newHeaderRow();
    rows = [...rows, row];
    focusElement(`${rowId(row)}-name`);
  }

  function removeRow(index: number) {
    const next = rows[index + 1] ?? rows[index - 1];
    rows = rows.filter((_, i) => i !== index);
    focusElement(next ? `${rowId(next)}-name` : addId);
  }

  function change(index: number, part: StoredPart) {
    rows[index] = changeStored(rows[index], part);
    focusElement(`${rowId(rows[index])}-${part}`);
  }

  function keep(index: number, part: StoredPart) {
    rows[index] = keepStored(rows[index], part);
    focusElement(`${rowId(rows[index])}-${part}-change`);
  }

  function describedBy(...ids: (string | false | null | undefined)[]): string | undefined {
    const present = ids.filter(Boolean);
    return present.length > 0 ? present.join(" ") : undefined;
  }
</script>

{#snippet stored(row: HeaderRow, index: number, part: StoredPart, label: string)}
  <div
    class="border-border bg-muted/40 flex items-center justify-between rounded-lg border px-4 py-2"
  >
    <span class="text-muted-foreground font-mono text-sm" aria-hidden="true">{MASK}</span>
    <Button
      id="{rowId(row)}-{part}-change"
      type="button"
      variant="outline"
      size="sm"
      aria-label={part === "value"
        ? m.outbound_headers_change_value({ name: label })
        : m.outbound_headers_change_fallback({ name: label })}
      onclick={() => change(index, part)}
    >
      {m.change()}
    </Button>
  </div>
{/snippet}

{#snippet keepLink(index: number, part: StoredPart)}
  <button
    type="button"
    class="text-muted-foreground hover:text-primary text-left text-xs underline transition-colors"
    onclick={() => keep(index, part)}
  >
    {part === "value" ? m.outbound_headers_keep_value() : m.outbound_headers_keep_fallback()}
  </button>
{/snippet}

{#if options || optionsError}
  <Field.Set class="border-border mt-2 border-t pt-4">
    <Field.Legend>{m.outbound_headers_title()}</Field.Legend>

    {#if !options}
      <Alert.Root variant="destructive">
        <CircleAlert aria-hidden="true" />
        <Alert.Title>{m.outbound_headers_options_failed()}</Alert.Title>
        <Alert.Description>
          {editing
            ? m.outbound_headers_options_failed_kept()
            : m.outbound_headers_options_failed_create()}
        </Alert.Description>
        {#if onRetry}
          <Alert.Action>
            <Button type="button" variant="outline" size="sm" onclick={onRetry}>
              {m.retry()}
            </Button>
          </Alert.Action>
        {/if}
      </Alert.Root>
    {:else if !supported}
      <p class="text-muted-foreground text-sm">{m.outbound_headers_unsupported()}</p>
    {:else}
      <Field.Description>{m.outbound_headers_description()}</Field.Description>

      {#each rows as row, index (row.key)}
        {@const id = rowId(row)}
        {@const label = rowLabel(row, index)}
        {@const problems = row.keepsStoredValue ? null : tokenProblems(row.value, options)}
        <Field.Set class="border-border gap-3 border-t pt-4">
          <Field.Legend class="sr-only">{label}</Field.Legend>

          <div class="flex items-end gap-2">
            <Field.Field class="flex-1">
              <Field.Label for="{id}-name">{m.outbound_headers_name()}</Field.Label>
              <Input
                id="{id}-name"
                bind:value={row.name}
                placeholder={m.outbound_headers_name_placeholder()}
                autocomplete="off"
                required
              />
            </Field.Field>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={m.outbound_headers_remove_named({ name: label })}
              onclick={() => removeRow(index)}
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </div>

          <Field.Field>
            {#if row.keepsStoredValue}
              <Field.Label>{m.outbound_headers_value()}</Field.Label>
              {@render stored(row, index, "value", label)}
            {:else}
              <Field.Label for="{id}-value">{m.outbound_headers_value()}</Field.Label>
              <InputGroup.Root>
                <InputGroup.Input
                  id="{id}-value"
                  class="font-mono"
                  type={row.secret ? "password" : "text"}
                  bind:value={row.value}
                  placeholder={valuePlaceholder}
                  autocomplete="off"
                  required
                  aria-invalid={problems ? true : undefined}
                  aria-describedby={describedBy(
                    problems && `${id}-value-error`,
                    `${id}-value-hint`,
                    classification && noticeId
                  )}
                />
                <InputGroup.Addon align="inline-end">
                  <DropdownMenu.Root>
                    <DropdownMenu.Trigger>
                      {#snippet child({ props })}
                        <InputGroup.Button
                          {...props}
                          size="icon-xs"
                          aria-label={m.outbound_headers_insert_dynamic_value()}
                        >
                          <Braces aria-hidden="true" />
                        </InputGroup.Button>
                      {/snippet}
                    </DropdownMenu.Trigger>
                    <DropdownMenu.Content align="end" class="max-w-sm">
                      {#each options.dynamic_values as value (value.token)}
                        <DropdownMenu.Item
                          onSelect={() => (row.value = insertToken(row.value, value.token))}
                        >
                          <div class="flex flex-col">
                            <span class="font-mono text-sm">{`{{${value.token}}}`}</span>
                            <span class="text-muted-foreground text-xs">
                              {tokenDescription(value)}
                              {#if value.classification === "identifying"}
                                · {m.outbound_headers_token_identifying()}
                              {/if}
                            </span>
                          </div>
                        </DropdownMenu.Item>
                      {/each}
                    </DropdownMenu.Content>
                  </DropdownMenu.Root>
                </InputGroup.Addon>
              </InputGroup.Root>
              {#if problems}
                <Field.Error id="{id}-value-error">
                  {#if problems.unknown.length > 0}
                    {m.outbound_headers_unknown_token({
                      tokens: problems.unknown.map((token) => `{{${token}}}`).join(", ")
                    })}
                  {:else}
                    {m.outbound_headers_malformed_token({ example: valuePlaceholder })}
                  {/if}
                </Field.Error>
              {/if}
              <Field.Description id="{id}-value-hint">
                {m.outbound_headers_value_hint()}
                {#if exampleToken}
                  {m.outbound_headers_value_examples({
                    fixed: "eu-north",
                    dynamic: `{{${exampleToken}}}`,
                    mixed: `tier-{{${exampleToken}}}`
                  })}
                {/if}
              </Field.Description>
              {#if canKeepStored(row, "value")}
                {@render keepLink(index, "value")}
              {/if}
              {#if row.wasSecret && !row.secret}
                <Field.Description>{m.outbound_headers_secret_reenter()}</Field.Description>
              {/if}
            {/if}
          </Field.Field>

          <div class="grid gap-3 sm:grid-cols-2">
            <Field.Field>
              <Field.Label for="{id}-encoding">{m.outbound_headers_encoding()}</Field.Label>
              <Select.Root
                type="single"
                value={row.encoding}
                onValueChange={(v) =>
                  (row.encoding =
                    encodingOptions.find((option) => option.value === v)?.value ?? row.encoding)}
              >
                <Select.Trigger id="{id}-encoding" class="w-full">
                  {encodingOptions.find((option) => option.value === row.encoding)?.label()}
                </Select.Trigger>
                <Select.Content>
                  {#each encodingOptions as option (option.value)}
                    <Select.Item value={option.value} label={option.label()}>
                      {option.label()}
                    </Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>
              <Field.Description>
                {row.encoding === "none"
                  ? m.outbound_headers_encoding_none_hint()
                  : m.outbound_headers_encoding_percent_hint()}
              </Field.Description>
            </Field.Field>

            <Field.Field>
              <Field.Label for="{id}-on-missing">{m.outbound_headers_on_missing()}</Field.Label>
              <Select.Root
                type="single"
                value={row.onMissing}
                onValueChange={(v) =>
                  (row.onMissing =
                    onMissingOptions.find((option) => option.value === v)?.value ?? row.onMissing)}
              >
                <Select.Trigger id="{id}-on-missing" class="w-full">
                  {onMissingOptions.find((option) => option.value === row.onMissing)?.label()}
                </Select.Trigger>
                <Select.Content>
                  {#each onMissingOptions as option (option.value)}
                    <Select.Item value={option.value} label={option.label()}>
                      {option.label()}
                    </Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>
            </Field.Field>
          </div>

          {#if row.onMissing === "fallback"}
            <Field.Field>
              {#if row.keepsStoredFallback}
                <Field.Label>{m.outbound_headers_fallback()}</Field.Label>
                {@render stored(row, index, "fallback", label)}
              {:else}
                <Field.Label for="{id}-fallback">{m.outbound_headers_fallback()}</Field.Label>
                <Input
                  id="{id}-fallback"
                  class="font-mono"
                  type={row.secret ? "password" : "text"}
                  bind:value={row.fallback}
                  autocomplete="off"
                  required
                  aria-describedby="{id}-fallback-hint"
                />
                <Field.Description id="{id}-fallback-hint">
                  {m.outbound_headers_fallback_hint()}
                </Field.Description>
                {#if canKeepStored(row, "fallback")}
                  {@render keepLink(index, "fallback")}
                {/if}
                {#if row.wasSecret && !row.secret && row.hasStoredFallback}
                  <Field.Description>
                    {m.outbound_headers_secret_reenter_fallback()}
                  </Field.Description>
                {/if}
              {/if}
            </Field.Field>
          {:else if row.onMissing === "fail"}
            <Alert.Root role="status">
              <TriangleAlert aria-hidden="true" />
              <Alert.Description>{m.outbound_headers_fail_warning()}</Alert.Description>
            </Alert.Root>
          {/if}

          <div class="flex items-start gap-2">
            <Checkbox
              id="{id}-secret"
              class="mt-0.5"
              checked={row.secret}
              aria-describedby="{id}-secret-hint"
              onCheckedChange={(v) => (rows[index] = setSecret(row, v === true))}
            />
            <div class="flex flex-col">
              <label for="{id}-secret" class="text-sm font-medium">
                {m.outbound_headers_secret()}
              </label>
              <span id="{id}-secret-hint" class="text-muted-foreground text-xs">
                {m.outbound_headers_secret_hint()}
              </span>
            </div>
          </div>
        </Field.Set>
      {/each}

      <div class="flex flex-col gap-1">
        <div>
          <Button
            id={addId}
            type="button"
            variant="outline"
            size="sm"
            disabled={atMax}
            onclick={addRow}
          >
            <Plus aria-hidden="true" />
            {m.outbound_headers_add()}
          </Button>
        </div>
        {#if atMax}
          <p class="text-muted-foreground text-xs">
            {m.outbound_headers_max_reached({ max: maxHeaders })}
          </p>
        {/if}
        {#if incomplete}
          <p class="text-muted-foreground text-xs">{m.outbound_headers_incomplete_hint()}</p>
        {/if}
      </div>

      {#if plainHttp}
        <Alert.Root role="status">
          <TriangleAlert aria-hidden="true" />
          <Alert.Description>{m.outbound_headers_plain_http_warning()}</Alert.Description>
        </Alert.Root>
      {/if}

      {#if classification}
        <Alert.Root id={noticeId} role="status">
          <Info aria-hidden="true" />
          <Alert.Description>
            {classification === "identifying"
              ? m.outbound_headers_notice_identifying()
              : m.outbound_headers_notice_organisational()}
          </Alert.Description>
        </Alert.Root>
      {/if}

      {#if rows.length > 0}
        <p class="text-muted-foreground text-xs">{m.outbound_headers_blocked_operations_note()}</p>
      {/if}
    {/if}
  </Field.Set>
{/if}
