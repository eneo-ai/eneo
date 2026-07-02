<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import { SvelteSet } from "svelte/reactivity";
  import { Settings } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { IconInfo } from "@eneo/icons/info";
  import { IconLockClosed } from "@eneo/icons/lock-closed";
  import { IconDownload } from "@eneo/icons/download";
  import { m } from "$lib/paraglide/messages";
  import { shouldShowTemplateAccessibilityHint } from "$lib/features/flows/templateFillAuthoringHints";
  import type {
    FlowTemplateAssetOption,
    FlowTemplateInspection,
    TemplateBindingRow,
    TemplateBindingSuggestionGroup,
    TemplateFillOutputConfig,
    TemplateFillReadiness
  } from "$lib/features/flows/templateFillConfig";
  import {
    getTemplateAssetStatusLabel,
    getTemplateAssetStatusClass,
    getTemplateRowStatusText,
    getTemplateRowStatusClass,
    getTemplateReadinessPillClass
  } from "./flowStepEditHelpers";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Card from "$lib/components/ui/card/index.js";

  let {
    isPublished,
    isAdvancedMode,
    templateFillConfig,
    templateInspection,
    templateInspecting,
    templateConfigError,
    templateFilesLoading,
    templatePlaceholders,
    templateBindingRows,
    templateBindingSuggestionGroups,
    templateAutoBindings,
    templateReadiness,
    templateOrphanedRows,
    templateHasSelection,
    resolvedTemplateAssetId,
    selectedTemplateAsset,
    templateUnnamedStepWarning,
    templateAutoMatchableCount,
    availableTemplateFiles,
    onOutputModeChange,
    onTemplateFileSelect,
    onTemplateUpload,
    onTemplateDownload,
    onTemplateRefresh,
    onBindingChange,
    onApplyAllSuggestions
  }: {
    isPublished: boolean;
    isAdvancedMode: boolean;
    templateFillConfig: TemplateFillOutputConfig;
    templateInspection: FlowTemplateInspection | null;
    templateInspecting: boolean;
    templateConfigError: string | null;
    templateFilesLoading: boolean;
    templatePlaceholders: Array<{ name: string }>;
    templateBindingRows: TemplateBindingRow[];
    templateBindingSuggestionGroups: TemplateBindingSuggestionGroup[];
    templateAutoBindings: Record<string, string>;
    templateReadiness: TemplateFillReadiness;
    templateOrphanedRows: TemplateBindingRow[];
    templateHasSelection: boolean;
    resolvedTemplateAssetId: string | null;
    selectedTemplateAsset: FlowTemplateAssetOption | null;
    templateUnnamedStepWarning: boolean;
    templateAutoMatchableCount: number;
    availableTemplateFiles: FlowTemplateAssetOption[];
    onOutputModeChange?: (detail: { value: FlowStep["output_mode"] }) => void;
    onTemplateFileSelect?: (detail: { assetId: string }) => void;
    onTemplateUpload?: (detail: { event: Event }) => void;
    onTemplateDownload?: () => void;
    onTemplateRefresh?: () => void;
    onBindingChange?: (detail: { placeholder: string; value: string }) => void;
    onApplyAllSuggestions?: () => void;
  } = $props();

  const expandedTemplateExpressions = new SvelteSet<string>();
  let templateUploadInput: HTMLInputElement | null = $state(null);

  function toggleTemplateExpressionEditor(key: string) {
    if (expandedTemplateExpressions.has(key)) {
      expandedTemplateExpressions.delete(key);
    } else {
      expandedTemplateExpressions.add(key);
    }
  }

  function readinessPillClass(): string {
    return getTemplateReadinessPillClass(templateReadiness);
  }
</script>

{#if isAdvancedMode}
  <Settings.Group title={m.flow_template_fill_template_section()}>
    <Alert.Root
      class="border-accent-default/15 bg-accent-default/5 rounded-[1rem] px-5 py-4"
      role="status"
    >
      <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div class="flex flex-col gap-1.5">
          <Alert.Title class="text-accent-stronger text-sm font-semibold tracking-tight">
            {m.flow_template_fill_title()}
          </Alert.Title>
          <Alert.Description class="text-accent-stronger/90 text-[0.8125rem] leading-relaxed">
            {m.flow_template_fill_desc()}
          </Alert.Description>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={isPublished}
          onclick={() => onOutputModeChange?.({ value: "pass_through" })}
        >
          {m.flow_template_fill_switch_back()}
        </Button>
      </div>
    </Alert.Root>
    <div class="grid gap-4 px-4 pt-4 lg:grid-cols-[minmax(0,260px)_minmax(0,1fr)] lg:px-0.5">
      <div class="space-y-2 pr-4">
        <h3 class="text-lg font-medium">{m.flow_template_fill_template_label()}</h3>
        <p class="text-secondary whitespace-pre-wrap">
          {m.flow_template_fill_template_help()}
        </p>
      </div>
      <div class="flex flex-col gap-3">
        {#if shouldShowTemplateAccessibilityHint({ isAdvancedMode, isTemplateFill: true })}
          <Alert.Root class="border-accent-default/15 bg-accent-default/5">
            <IconInfo />
            <Alert.Title>{m.flow_template_fill_accessibility_title()}</Alert.Title>
            <Alert.Description>{m.flow_template_fill_accessibility_body()}</Alert.Description>
          </Alert.Root>
        {/if}
        {#if templateHasSelection || templateReadiness.total > 0}
          <Card.Root class="bg-secondary/10">
            <Card.Content class="flex items-center justify-between gap-3 px-3 py-3">
              <div class="min-w-0">
                <p class="text-primary truncate text-sm font-medium">
                  {templateFillConfig.template_name ?? m.flow_template_fill_select_placeholder()}
                </p>
                <div class="mt-1">
                  <Badge class={readinessPillClass()}>
                    {templateReadiness.matched}/{templateReadiness.total || 0}
                  </Badge>
                </div>
                {#if selectedTemplateAsset}
                  <div class="mt-2 flex flex-wrap items-center gap-2 text-xs">
                    <Badge class={getTemplateAssetStatusClass(selectedTemplateAsset.status)}>
                      {getTemplateAssetStatusLabel(selectedTemplateAsset.status)}
                    </Badge>
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
            </Card.Content>
          </Card.Root>
        {/if}
        <select
          class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
          value={resolvedTemplateAssetId ?? ""}
          disabled={isPublished || templateInspecting || selectedTemplateAsset?.can_edit === false}
          onchange={(e) => onTemplateFileSelect?.({ assetId: e.currentTarget.value })}
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
          disabled={isPublished || templateInspecting || selectedTemplateAsset?.can_edit === false}
          onchange={(e) => onTemplateUpload?.({ event: e })}
        />
        <div class="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            disabled={isPublished ||
              templateInspecting ||
              selectedTemplateAsset?.can_edit === false}
            onclick={() => templateUploadInput?.click()}
          >
            {m.flow_template_fill_upload_action()}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={isPublished ||
              templateInspecting ||
              !resolvedTemplateAssetId ||
              selectedTemplateAsset?.can_download === false}
            onclick={() => onTemplateDownload?.()}
          >
            <IconDownload class="size-3.5" />
            {m.flow_template_fill_download_action()}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={isPublished || templateInspecting || !resolvedTemplateAssetId}
            onclick={() => onTemplateRefresh?.()}
          >
            {m.flow_template_fill_refresh_action()}
          </Button>
          {#if templateFilesLoading}
            <span class="text-muted text-xs">{m.flow_template_fill_loading_templates()}</span>
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
    <div class="grid gap-4 px-4 pt-4 lg:grid-cols-[minmax(0,260px)_minmax(0,1fr)] lg:px-0.5">
      <div class="space-y-2 pr-4">
        <p class="text-secondary whitespace-pre-wrap">
          {m.flow_template_fill_mapping_description()}
        </p>
      </div>
      <div class="flex flex-col gap-3">
        {#if templateHasSelection && templateReadiness.total > 0}
          <Card.Root class="bg-secondary/10">
            <Card.Content class="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <div class="flex items-center gap-3">
                <Badge class={readinessPillClass()}>
                  {templateReadiness.matched}/{templateReadiness.total}
                </Badge>
                <div class="bg-hover-dimmer h-2 w-full max-w-48 overflow-hidden rounded-full">
                  <div
                    class={`h-full transition-all ${templateReadiness.incomplete ? "bg-warning-default" : "bg-positive-default"}`}
                    style={`width: ${(templateReadiness.matched / templateReadiness.total) * 100}%`}
                  ></div>
                </div>
              </div>
              {#if templateAutoMatchableCount > 0}
                <Button
                  variant="outline"
                  size="sm"
                  disabled={isPublished}
                  onclick={() => onApplyAllSuggestions?.()}
                >
                  {m.flow_template_fill_apply_all({
                    count: String(templateAutoMatchableCount)
                  })}
                </Button>
              {/if}
            </Card.Content>
          </Card.Root>
        {/if}

        {#if !templateHasSelection}
          <Card.Root class="bg-secondary/10">
            <Card.Content class="px-4 py-3">
              <p class="text-primary text-sm font-medium">
                {m.flow_template_fill_select_template_first_title()}
              </p>
              <p class="text-muted mt-1 text-xs leading-relaxed">
                {m.flow_template_fill_select_template_first_body()}
              </p>
            </Card.Content>
          </Card.Root>
        {:else if templatePlaceholders.length === 0}
          <Card.Root class="bg-secondary/10">
            <Card.Content class="flex flex-col gap-2 px-4 py-3">
              <p class="text-primary text-sm font-medium">
                {m.flow_template_fill_no_placeholders()}
              </p>
              <p class="text-muted text-xs leading-relaxed">
                {m.flow_template_fill_placeholder_guidance_prefix()}
                <span class="font-mono">{"{{nuläge}}"}</span>,
                <span class="font-mono">{"{{mål}}"}</span> eller
                <span class="font-mono">{"{{bedömning}}"}</span>
                {m.flow_template_fill_placeholder_guidance_suffix()}
              </p>
              <p class="text-muted text-xs leading-relaxed">
                {m.flow_template_fill_placeholder_formatting_warning()}
              </p>
              {#if templateInspection?.extracted_text_preview}
                <Card.Root class="mt-1">
                  <Card.Content class="px-3 py-3">
                    <p class="text-primary text-xs font-medium">
                      {m.flow_template_fill_extracted_preview_title()}
                    </p>
                    <pre
                      class="text-muted mt-2 overflow-auto text-xs leading-relaxed break-words whitespace-pre-wrap">{templateInspection.extracted_text_preview}</pre>
                  </Card.Content>
                </Card.Root>
              {/if}
            </Card.Content>
          </Card.Root>
        {:else}
          <div class="flex flex-col gap-2">
            {#each templateBindingRows as row (row.key)}
              <Card.Root
                class="transition-colors {row.status === 'matched'
                  ? 'border-positive-default/30 bg-positive-dimmer/20'
                  : row.status === 'missing'
                    ? 'border-default bg-primary'
                    : row.status === 'orphaned'
                      ? 'border-negative-default/30 bg-negative-dimmer/10'
                      : 'border-default bg-primary'}"
              >
                <Card.Content class="flex flex-col gap-2 px-3 py-3">
                  <div class="flex items-center justify-between gap-2">
                    <div class="flex min-w-0 flex-wrap items-center gap-2">
                      <span class="text-primary text-sm font-medium">
                        {`{{${row.placeholderName}}}`}
                      </span>
                      <Badge class={getTemplateRowStatusClass(row.status)}>
                        {getTemplateRowStatusText(row.status)}
                      </Badge>
                      {#if row.autoSuggested}
                        <Badge class="bg-accent-dimmer text-accent-stronger">
                          {m.flow_template_fill_auto_badge()}
                        </Badge>
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
                      onclick={() => toggleTemplateExpressionEditor(row.key)}
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
                        onchange={(e) =>
                          onBindingChange?.({
                            placeholder: row.placeholderName,
                            value: e.currentTarget.value
                          })}
                      >
                        <option value="__unset__">{m.flow_template_fill_select_source()}</option>
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
                        variant="outline"
                        size="sm"
                        disabled={isPublished}
                        onclick={() =>
                          onBindingChange?.({
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
                      oninput={(e) =>
                        onBindingChange?.({
                          placeholder: row.placeholderName,
                          value: e.currentTarget.value
                        })}
                    />
                  {/if}
                </Card.Content>
              </Card.Root>
            {/each}
          </div>
        {/if}
      </div>
    </div>
  </Settings.Group>
{:else}
  <Settings.Group title={m.flow_template_fill_template_section()}>
    <Alert.Root
      class="border-accent-default/15 bg-accent-default/5 rounded-[1rem] px-5 py-4"
      role="status"
    >
      <Alert.Title class="text-accent-stronger text-sm font-semibold tracking-tight">
        {m.flow_template_fill_title()}
      </Alert.Title>
      <Alert.Description class="text-accent-stronger/90 mt-1.5 text-[0.8125rem] leading-relaxed">
        {m.flow_template_fill_desc()}
      </Alert.Description>
    </Alert.Root>
    <div class="grid gap-4 px-4 pt-4 lg:grid-cols-[minmax(0,260px)_minmax(0,1fr)] lg:px-0.5">
      <div class="space-y-2 pr-4">
        <h3 class="text-lg font-medium">{m.flow_template_fill_template_label()}</h3>
        <p class="text-secondary whitespace-pre-wrap">{m.flow_template_fill_summary()}</p>
      </div>
      <div class="flex flex-col gap-3">
        {#if templateHasSelection || templateReadiness.total > 0}
          <Card.Root class="bg-secondary/10">
            <Card.Content class="flex items-center justify-between gap-3 px-3 py-3">
              <div class="min-w-0">
                <p class="text-primary truncate text-sm font-medium">
                  {templateFillConfig.template_name ?? m.flow_template_fill_select_placeholder()}
                </p>
                <p class="text-muted mt-1 text-xs leading-relaxed">
                  {m.flow_template_fill_readiness_summary({
                    matched: String(templateReadiness.matched),
                    total: String(templateReadiness.total || 0)
                  })}
                </p>
              </div>
              <Badge class={readinessPillClass()}>
                {templateReadiness.matched}/{templateReadiness.total || 0}
              </Badge>
            </Card.Content>
          </Card.Root>
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
