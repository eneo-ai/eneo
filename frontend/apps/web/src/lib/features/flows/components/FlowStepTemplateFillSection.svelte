<svelte:options runes={false} />

<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { Settings } from "$lib/components/layout";
  import { Button } from "@intric/ui";
  import { IconLockClosed } from "@intric/icons/lock-closed";
  import { IconDownload } from "@intric/icons/download";
  import { m } from "$lib/paraglide/messages";
  import { createEventDispatcher } from "svelte";
  import {
    getTemplateAssetStatusLabel,
    getTemplateAssetStatusClass,
    getTemplateRowStatusText,
    getTemplateRowStatusClass,
    getTemplateReadinessPillClass
  } from "./flowStepEditHelpers";

  const dispatch = createEventDispatcher<{
    outputModeChange: { value: string };
    templateFileSelect: { assetId: string };
    templateUpload: { event: Event };
    templateDownload: void;
    templateRefresh: void;
    bindingChange: { placeholder: string; value: string };
    applyAllSuggestions: void;
  }>();

  export let step: FlowStep;
  export let isPublished: boolean;
  export let isAdvancedMode: boolean;
  export let templateFillConfig: any;
  export let templateInspection: any | null;
  export let templateInspecting: boolean;
  export let templateConfigError: string | null;
  export let templateFilesLoading: boolean;
  export let templatePlaceholders: Array<{ name: string }>;
  export let templateBindingRows: Array<{
    key: string;
    placeholderName: string;
    status: "matched" | "missing" | "invalid" | "orphaned";
    binding: string | null;
    preview?: string;
    autoSuggested?: boolean;
    sourceOutputType?: string;
  }>;
  export let templateBindingSuggestionGroups: Array<{
    key: string;
    label: string;
    options: Array<{ value: string; label: string }>;
  }>;
  export let templateAutoBindings: Record<string, string>;
  export let templateReadiness: { total: number; matched: number; incomplete: boolean };
  export let templateOrphanedRows: Array<any>;
  export let templateHasSelection: boolean;
  export let resolvedTemplateAssetId: string | null;
  export let selectedTemplateAsset: any | null;
  export let templateUnnamedStepWarning: boolean;
  export let templateAutoMatchableCount: number;
  export let availableTemplateFiles: Array<{ id: string; name: string; status?: string }>;

  // Local state
  let expandedTemplateExpressions = new Set<string>();
  let templateUploadInput: HTMLInputElement | null = null;

  function toggleTemplateExpressionEditor(key: string) {
    const next = new Set(expandedTemplateExpressions);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    expandedTemplateExpressions = next;
  }

  function readinessPillClass(): string {
    return getTemplateReadinessPillClass(templateReadiness);
  }
</script>

{#if isAdvancedMode}
  <Settings.Group title={m.flow_template_fill_template_section()}>
    <div class="border-accent-default/15 bg-accent-default/5 rounded-[1rem] border px-5 py-4">
      <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div class="space-y-1.5">
          <p class="text-accent-stronger text-sm font-semibold tracking-tight">
            {m.flow_template_fill_title()}
          </p>
          <p class="text-accent-stronger/90 text-[0.8125rem] leading-relaxed">
            {m.flow_template_fill_desc()}
          </p>
        </div>
        <Button
          variant="outlined"
          size="small"
          disabled={isPublished}
          on:click={() => dispatch("outputModeChange", { value: "pass_through" })}
        >
          {m.flow_template_fill_switch_back()}
        </Button>
      </div>
    </div>
    <div
      class="grid gap-4 px-4 pt-4 lg:grid-cols-[minmax(0,260px)_minmax(0,1fr)] lg:px-0.5"
    >
      <div class="space-y-2 pr-4">
        <h3 class="text-lg font-medium">{m.flow_template_fill_template_label()}</h3>
        <p class="text-secondary whitespace-pre-wrap">
          {m.flow_template_fill_template_help()}
        </p>
      </div>
      <div class="flex flex-col gap-3">
        {#if templateHasSelection || templateReadiness.total > 0}
          <div
            class="border-default bg-secondary/10 flex items-center justify-between gap-3 rounded-xl border px-3 py-3"
          >
            <div class="min-w-0">
              <p class="text-primary truncate text-sm font-medium">
                {templateFillConfig.template_name ??
                  m.flow_template_fill_select_placeholder()}
              </p>
              <p class="text-muted mt-1 text-xs leading-relaxed">
                <span
                  class={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${readinessPillClass()}`}
                >
                  {templateReadiness.matched}/{templateReadiness.total || 0}
                </span>
              </p>
              {#if selectedTemplateAsset}
                <div class="mt-2 flex flex-wrap items-center gap-2 text-xs">
                  <span
                    class={`rounded-full border px-2 py-0.5 font-medium ${getTemplateAssetStatusClass(selectedTemplateAsset.status)}`}
                  >
                    {getTemplateAssetStatusLabel(selectedTemplateAsset.status)}
                  </span>
                  {#if selectedTemplateAsset.last_updated_by_name}
                    <span class="text-muted">
                      Senast uppdaterad av {selectedTemplateAsset.last_updated_by_name}
                    </span>
                  {/if}
                </div>
              {/if}
              {#if templateFillConfig.template_checksum}
                <p class="text-muted mt-2 text-[11px] leading-relaxed">
                  {templateFillConfig.template_checksum}
                </p>
              {/if}
            </div>
          </div>
        {/if}
        <select
          class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
          value={resolvedTemplateAssetId ?? ""}
          disabled={isPublished ||
            templateInspecting ||
            selectedTemplateAsset?.can_edit === false}
          on:change={(e) => dispatch("templateFileSelect", { assetId: e.currentTarget.value })}
        >
          <option value="">{m.flow_template_fill_select_placeholder()}</option>
          {#each availableTemplateFiles as file (file.id)}
            <option value={file.id}>
              {file.name}
              {file.status ? ` (${getTemplateAssetStatusLabel(file.status)})` : ""}
            </option>
          {/each}
        </select>
        <input
          bind:this={templateUploadInput}
          type="file"
          accept=".docx"
          class="hidden"
          disabled={isPublished ||
            templateInspecting ||
            selectedTemplateAsset?.can_edit === false}
          on:change={(e) => dispatch("templateUpload", { event: e })}
        />
        <div class="flex flex-wrap items-center gap-3">
          <Button
            variant="outlined"
            size="small"
            disabled={isPublished ||
              templateInspecting ||
              selectedTemplateAsset?.can_edit === false}
            on:click={() => templateUploadInput?.click()}
          >
            {m.flow_template_fill_upload_action()}
          </Button>
          <Button
            variant="outlined"
            size="small"
            disabled={isPublished ||
              templateInspecting ||
              !resolvedTemplateAssetId ||
              selectedTemplateAsset?.can_download === false}
            on:click={() => dispatch("templateDownload")}
          >
            <IconDownload class="size-3.5" />
            {m.flow_template_fill_download_action()}
          </Button>
          <Button
            variant="outlined"
            size="small"
            disabled={isPublished || templateInspecting || !resolvedTemplateAssetId}
            on:click={() => dispatch("templateRefresh")}
          >
            {m.flow_template_fill_refresh_action()}
          </Button>
          {#if templateFilesLoading}
            <span class="text-muted text-xs"
              >{m.flow_template_fill_loading_templates()}</span
            >
          {/if}
        </div>
        {#if templateUnnamedStepWarning}
          <p class="text-warning-stronger text-xs leading-relaxed">
            {m.flow_template_fill_naming_hint()}
          </p>
        {/if}
        {#if templateOrphanedRows.length > 0}
          <p class="text-warning-stronger text-xs leading-relaxed">
            {m.flow_template_fill_orphaned_warning({
              count: String(templateOrphanedRows.length)
            })}
          </p>
        {/if}
        {#if templateConfigError}
          <p class="text-warning-stronger text-xs" role="alert">{templateConfigError}</p>
        {/if}
      </div>
    </div>
  </Settings.Group>

  <Settings.Group title={m.flow_template_fill_placeholders_title()}>
    <div
      class="grid gap-4 px-4 pt-4 lg:grid-cols-[minmax(0,260px)_minmax(0,1fr)] lg:px-0.5"
    >
      <div class="space-y-2 pr-4">
        <p class="text-secondary whitespace-pre-wrap">
          {m.flow_template_fill_mapping_description()}
        </p>
      </div>
      <div class="flex flex-col gap-3">
        {#if templateHasSelection && templateReadiness.total > 0}
          <div
            class="border-default bg-secondary/10 flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3"
          >
            <div class="flex items-center gap-3">
              <span
                class={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${readinessPillClass()}`}
              >
                {templateReadiness.matched}/{templateReadiness.total}
              </span>
              <div
                class="bg-hover-dimmer h-2 w-full max-w-48 overflow-hidden rounded-full"
              >
                <div
                  class={`h-full transition-all ${templateReadiness.incomplete ? "bg-warning-default" : "bg-positive-default"}`}
                  style={`width: ${(templateReadiness.matched / templateReadiness.total) * 100}%`}
                ></div>
              </div>
            </div>
            {#if templateAutoMatchableCount > 0}
              <Button
                variant="outlined"
                size="small"
                disabled={isPublished}
                on:click={() => dispatch("applyAllSuggestions")}
              >
                {m.flow_template_fill_apply_all({
                  count: String(templateAutoMatchableCount)
                })}
              </Button>
            {/if}
          </div>
        {/if}

        {#if !templateHasSelection}
          <div class="bg-secondary/10 rounded-xl px-4 py-3">
            <p class="text-primary text-sm font-medium">
              {m.flow_template_fill_select_template_first_title()}
            </p>
            <p class="text-muted mt-1 text-xs leading-relaxed">
              {m.flow_template_fill_select_template_first_body()}
            </p>
          </div>
        {:else if templatePlaceholders.length === 0}
          <div class="bg-secondary/10 rounded-xl px-4 py-3">
            <p class="text-primary text-sm font-medium">
              {m.flow_template_fill_no_placeholders()}
            </p>
            <p class="text-muted mt-1 text-xs leading-relaxed">
              {m.flow_template_fill_placeholder_guidance_prefix()}
              <span class="font-mono">{"{{nuläge}}"}</span>,
              <span class="font-mono">{"{{mål}}"}</span> eller
              <span class="font-mono">{"{{bedömning}}"}</span>
              {m.flow_template_fill_placeholder_guidance_suffix()}
            </p>
            <p class="text-muted mt-2 text-xs leading-relaxed">
              {m.flow_template_fill_placeholder_formatting_warning()}
            </p>
            {#if templateInspection?.extracted_text_preview}
              <div class="border-default bg-primary mt-3 rounded-lg border px-3 py-3">
                <p class="text-primary text-xs font-medium">
                  {m.flow_template_fill_extracted_preview_title()}
                </p>
                <pre
                  class="text-muted mt-2 overflow-auto text-xs leading-relaxed break-words whitespace-pre-wrap">{templateInspection.extracted_text_preview}</pre>
              </div>
            {/if}
          </div>
        {:else}
          <div class="flex flex-col gap-2">
            {#each templateBindingRows as row (row.key)}
              <div
                class="rounded-xl border px-3 py-3 transition-colors {row.status ===
                'matched'
                  ? 'border-positive-default/30 bg-positive-dimmer/20 border-l-positive-default/40 border-l-[3px]'
                  : row.status === 'missing'
                    ? 'border-default bg-primary border-l-warning-default/60 border-l-[3px]'
                    : row.status === 'orphaned'
                      ? 'border-negative-default/30 bg-negative-dimmer/10 border-l-negative-default/40 border-l-[3px]'
                      : 'border-default bg-primary'}"
              >
                <div class="flex flex-col gap-2">
                  <div class="flex items-center justify-between gap-2">
                    <div class="flex min-w-0 flex-wrap items-center gap-2">
                      <span class="text-primary text-sm font-medium">
                        {`{{${row.placeholderName}}}`}
                      </span>
                      <span
                        class={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${getTemplateRowStatusClass(row.status)}`}
                      >
                        {getTemplateRowStatusText(row.status)}
                      </span>
                      {#if row.autoSuggested}
                        <span
                          class="bg-accent-dimmer text-accent-stronger inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
                        >
                          {m.flow_template_fill_auto_badge()}
                        </span>
                      {/if}
                    </div>
                    <button
                      type="button"
                      class="text-secondary hover:bg-hover-dimmer inline-flex size-7 shrink-0 items-center justify-center rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-40"
                      disabled={isPublished}
                      aria-label={expandedTemplateExpressions.has(row.key)
                        ? m.flow_template_fill_hide_expression()
                        : m.flow_template_fill_show_expression()}
                      title={expandedTemplateExpressions.has(row.key)
                        ? m.flow_template_fill_hide_expression()
                        : m.flow_template_fill_show_expression()}
                      on:click={() => toggleTemplateExpressionEditor(row.key)}
                    >
                      <svg
                        class="size-3.5 transition-transform {expandedTemplateExpressions.has(
                          row.key
                        )
                          ? 'rotate-180'
                          : ''}"
                        viewBox="0 0 16 16"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      >
                        <polyline points="4 6 8 10 12 6" />
                      </svg>
                    </button>
                  </div>

                  {#if row.preview}
                    <p class="text-muted -mt-1 text-xs leading-relaxed">
                      {row.preview}
                    </p>
                  {/if}

                  {#if row.status === "orphaned"}
                    <p class="text-negative-stronger text-xs leading-relaxed">
                      {m.flow_template_fill_orphaned_row_warning()}
                    </p>
                  {/if}

                  <div class="flex flex-col gap-2 md:flex-row md:items-start">
                    <div class="min-w-0 flex-1">
                      <select
                        class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 text-sm focus-within:ring-2 hover:ring-1 focus-visible:ring-2"
                        value={row.binding ?? "__unset__"}
                        disabled={isPublished}
                        on:change={(e) =>
                          dispatch("bindingChange", {
                            placeholder: row.placeholderName,
                            value: e.currentTarget.value
                          })}
                      >
                        <option value="__unset__"
                          >{m.flow_template_fill_select_source()}</option
                        >
                        <option value="">{m.flow_template_fill_leave_empty()}</option>
                        {#each templateBindingSuggestionGroups as group (group.key)}
                          <optgroup label={group.label}>
                            {#each group.options as suggestion (suggestion.value)}
                              <option value={suggestion.value}>{suggestion.label}</option>
                            {/each}
                          </optgroup>
                        {/each}
                      </select>
                      {#if row.sourceOutputType === "json"}
                        <p class="text-warning-stronger mt-1 text-xs leading-relaxed">
                          {m.flow_template_fill_json_warning()}
                        </p>
                      {/if}
                    </div>
                    {#if row.status === "missing" && templateAutoBindings[row.placeholderName]}
                      <Button
                        variant="outlined"
                        size="small"
                        disabled={isPublished}
                        on:click={() =>
                          dispatch("bindingChange", {
                            placeholder: row.placeholderName,
                            value: templateAutoBindings[row.placeholderName]
                          })}
                      >
                        {m.flow_template_fill_apply_suggestion()}
                      </Button>
                    {/if}
                  </div>

                  {#if expandedTemplateExpressions.has(row.key)}
                    <input
                      class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 font-mono text-sm focus-within:ring-2 hover:ring-1 focus-visible:ring-2"
                      value={row.binding ?? ""}
                      disabled={isPublished}
                      placeholder={m.flow_template_fill_expression_placeholder()}
                      on:input={(e) =>
                        dispatch("bindingChange", {
                          placeholder: row.placeholderName,
                          value: e.currentTarget.value
                        })}
                    />
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </div>
  </Settings.Group>
{:else}
  <Settings.Group title={m.flow_template_fill_template_section()}>
    <div class="border-accent-default/15 bg-accent-default/5 rounded-[1rem] border px-5 py-4">
      <p class="text-accent-stronger text-sm font-semibold tracking-tight">
        {m.flow_template_fill_title()}
      </p>
      <p class="text-accent-stronger/90 mt-1.5 text-[0.8125rem] leading-relaxed">
        {m.flow_template_fill_desc()}
      </p>
    </div>
    <div
      class="grid gap-4 px-4 pt-4 lg:grid-cols-[minmax(0,260px)_minmax(0,1fr)] lg:px-0.5"
    >
      <div class="space-y-2 pr-4">
        <h3 class="text-lg font-medium">{m.flow_template_fill_template_label()}</h3>
        <p class="text-secondary whitespace-pre-wrap">{m.flow_template_fill_summary()}</p>
      </div>
      <div class="flex flex-col gap-3">
        {#if templateHasSelection || templateReadiness.total > 0}
          <div
            class="border-default bg-secondary/10 flex items-center justify-between gap-3 rounded-xl border px-3 py-3"
          >
            <div class="min-w-0">
              <p class="text-primary truncate text-sm font-medium">
                {templateFillConfig.template_name ??
                  m.flow_template_fill_select_placeholder()}
              </p>
              <p class="text-muted mt-1 text-xs leading-relaxed">
                {m.flow_template_fill_readiness_summary({
                  matched: String(templateReadiness.matched),
                  total: String(templateReadiness.total || 0)
                })}
              </p>
            </div>
            <span
              class={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${readinessPillClass()}`}
            >
              {templateReadiness.matched}/{templateReadiness.total || 0}
            </span>
          </div>
        {/if}
        {#if templateOrphanedRows.length > 0}
          <p class="text-warning-stronger text-xs leading-relaxed">
            {m.flow_template_fill_orphaned_warning({
              count: String(templateOrphanedRows.length)
            })}
          </p>
        {/if}
        {#if templateConfigError}
          <p class="text-warning-stronger text-xs" role="alert">{templateConfigError}</p>
        {/if}
      </div>
    </div>
  </Settings.Group>
{/if}

<Settings.Group title={m.flow_step_output_section()}>
  <Settings.Row
    title={m.flow_step_output_type()}
    description={m.flow_template_fill_locked_output_help()}
  >
    <div class="flex items-center gap-2 text-sm">
      <IconLockClosed class="text-muted size-4 shrink-0" />
      <span class="text-primary">{m.flow_output_type_docx()}</span>
    </div>
  </Settings.Row>
  <Settings.Row title={m.flow_step_output_mode()} description="">
    <div class="flex items-center gap-2 text-sm">
      <IconLockClosed class="text-muted size-4 shrink-0" />
      <span class="text-primary">{m.flow_output_mode_template_fill()}</span>
    </div>
  </Settings.Row>
</Settings.Group>
