<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Settings } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";
  import { IconCPU } from "@intric/icons/CPU";
  import { Plug, Sparkles, AlertCircle, CheckCircle2, Info } from "lucide-svelte";

  let { data } = $props();

  const allModels = $derived(data.models.completionModels);
  const allProviders = $derived((data.modelProviders ?? []).filter((p) => p.is_active));
  const modelsByProvider = $derived.by(() => {
    const map = new SvelteMap<string | null, typeof allModels>();
    for (const m of allModels) {
      const key = m.provider_id ?? null;
      const list = map.get(key);
      if (list) list.push(m);
      else map.set(key, [m]);
    }
    return map;
  });

  function getInitialModelSelections() {
    return data.models.completionModels.map((model) => {
      const existing = data.policy.models_restriction.models.find(
        (entry) => entry.completion_model_id === model.id
      );
      return [
        model.id,
        { selected: !!existing, isDefault: existing?.is_default ?? false }
      ] as const;
    });
  }

  function getInitialProviderSelections() {
    return data.policy.models_restriction.provider_ids ?? [];
  }

  function getInitialModelsEnabled() {
    return data.policy.models_restriction.enabled;
  }

  function getInitialMcpEnabled() {
    return data.policy.mcp_restriction.enabled;
  }

  function getInitialMcpSelections() {
    return data.policy.mcp_restriction.server_ids;
  }

  function getInitialPromptEnabled() {
    return data.policy.prompt_enforcement.enabled;
  }

  function getInitialSelectedPromptId() {
    return data.policy.prompt_enforcement.prompt_library_id ?? null;
  }

  let modelsEnabled = $state(getInitialModelsEnabled());
  const modelSelections = new SvelteMap<string, { selected: boolean; isDefault: boolean }>(
    getInitialModelSelections()
  );
  const providerSelections = new SvelteSet<string>(getInitialProviderSelections());

  const allMcpServers = $derived((data.mcpSettings?.items ?? []).filter((s) => s.is_available));
  let mcpEnabled = $state(getInitialMcpEnabled());
  const mcpSelections = new SvelteSet<string>(getInitialMcpSelections());

  const promptOptions = $derived(data.promptLibrary.items);
  let promptEnabled = $state(getInitialPromptEnabled());
  let selectedPromptId = $state<string | null>(getInitialSelectedPromptId());

  let saving = $state(false);
  let saveError = $state<string | null>(null);
  let saveAnnouncement = $state<string>("");
  let pendingConfirm = $state<{ messages: string[]; submit: () => Promise<void> } | null>(null);

  const selectedModels = $derived(
    Array.from(modelSelections.entries())
      .filter(([, v]) => v.selected)
      .map(([id, v]) => ({ completion_model_id: id, is_default: v.isDefault }))
  );
  // Effective allowed set = explicit models ∪ all models from selected providers.
  // The default model must live in this set; preview it for validation + summary.
  const effectiveModelIds = $derived.by(() => {
    const out = new SvelteSet<string>(selectedModels.map((m) => m.completion_model_id));
    for (const pid of providerSelections) {
      for (const m of modelsByProvider.get(pid) ?? []) out.add(m.id);
    }
    return out;
  });
  const defaultModelId = $derived(
    selectedModels.find((m) => m.is_default)?.completion_model_id ?? null
  );

  $effect(() => {
    modelsEnabled = getInitialModelsEnabled();
    modelSelections.clear();
    for (const [modelId, selection] of getInitialModelSelections()) {
      modelSelections.set(modelId, selection);
    }
    providerSelections.clear();
    for (const pid of getInitialProviderSelections()) providerSelections.add(pid);

    mcpEnabled = getInitialMcpEnabled();
    mcpSelections.clear();
    for (const serverId of getInitialMcpSelections()) {
      mcpSelections.add(serverId);
    }

    promptEnabled = getInitialPromptEnabled();
    selectedPromptId = getInitialSelectedPromptId();
  });

  function setSingleDefault(id: string) {
    // The default flag must travel on a row in `personal_assistant_policy_completion_models`,
    // so if the target is allowed only via a whitelisted provider, also flip its
    // `selected` bit on — that materialises the row at save time. The provider row
    // continues to cover all OTHER models from that provider unchanged.
    for (const [k, v] of modelSelections) {
      modelSelections.set(k, {
        selected: k === id ? true : v.selected,
        isDefault: k === id
      });
    }
  }

  function toggleModelSelected(id: string, on: boolean) {
    const cur = modelSelections.get(id);
    if (!cur) return;
    modelSelections.set(id, { selected: on, isDefault: on && cur.isDefault });
    if (!on && cur.isDefault) {
      modelSelections.set(id, { selected: false, isDefault: false });
    }
  }

  function toggleMcp(id: string, on: boolean) {
    if (on) mcpSelections.add(id);
    else mcpSelections.delete(id);
  }

  const initialModelIds = $derived(
    new SvelteSet(data.policy.models_restriction.models.map((m) => m.completion_model_id))
  );
  const initialDefaultModelId = $derived(
    data.policy.models_restriction.models.find((m) => m.is_default)?.completion_model_id ?? null
  );
  const initialProviderIds = $derived(
    new SvelteSet(data.policy.models_restriction.provider_ids ?? [])
  );
  const initialMcpIds = $derived(new SvelteSet(data.policy.mcp_restriction.server_ids));

  const modelsDirty = $derived(
    modelsEnabled !== data.policy.models_restriction.enabled ||
      selectedModels.length !== initialModelIds.size ||
      selectedModels.some((m) => !initialModelIds.has(m.completion_model_id)) ||
      defaultModelId !== initialDefaultModelId ||
      providerSelections.size !== initialProviderIds.size ||
      Array.from(providerSelections).some((pid) => !initialProviderIds.has(pid))
  );
  const mcpDirty = $derived(
    mcpEnabled !== data.policy.mcp_restriction.enabled ||
      mcpSelections.size !== initialMcpIds.size ||
      Array.from(mcpSelections).some((id) => !initialMcpIds.has(id))
  );
  const promptDirty = $derived(
    promptEnabled !== data.policy.prompt_enforcement.enabled ||
      (promptEnabled
        ? selectedPromptId !== data.policy.prompt_enforcement.prompt_library_id
        : false)
  );
  const dirty = $derived(modelsDirty || mcpDirty || promptDirty);

  function buildConfirmations(): string[] {
    const out: string[] = [];
    const initial = data.policy;
    // "Locked single-model" UX only triggers when effective set is exactly one.
    if (
      modelsEnabled &&
      effectiveModelIds.size === 1 &&
      (!initial.models_restriction.enabled ||
        initial.models_restriction.models.length +
          (initial.models_restriction.provider_ids ?? []).length >
          1)
    ) {
      out.push("Modellväljaren döljs för alla användare i den personliga assistenten.");
    }
    if (
      mcpEnabled &&
      mcpSelections.size === 0 &&
      (!initial.mcp_restriction.enabled || initial.mcp_restriction.server_ids.length !== 0)
    ) {
      out.push("Alla MCP-servrar inaktiveras i den personliga assistenten.");
    }
    if (promptEnabled && !initial.prompt_enforcement.enabled) {
      out.push("Användarnas egna prompts döljs och den valda prompten används istället.");
    }
    return out;
  }

  async function doSave() {
    saving = true;
    saveError = null;
    saveAnnouncement = "";
    try {
      await data.intric.personalAssistantPolicy.update({
        models_restriction: {
          enabled: modelsEnabled,
          models: selectedModels,
          provider_ids: Array.from(providerSelections)
        },
        mcp_restriction: {
          enabled: mcpEnabled,
          server_ids: Array.from(mcpSelections)
        },
        prompt_enforcement: {
          enabled: promptEnabled,
          prompt_library_id: promptEnabled ? selectedPromptId : null
        }
      });
      await invalidate("admin:personal-assistant-policy");
      pendingConfirm = null;
      saveAnnouncement = "Inställningarna har sparats.";
    } catch (e) {
      const err = e as { message?: string };
      saveError = err.message ?? "Kunde inte spara policy.";
      saveAnnouncement = "Det gick inte att spara inställningarna.";
    } finally {
      saving = false;
    }
  }

  function save() {
    const confirmations = buildConfirmations();
    if (confirmations.length > 0) {
      pendingConfirm = { messages: confirmations, submit: doSave };
    } else {
      doSave();
    }
  }

  function discardChanges() {
    modelsEnabled = getInitialModelsEnabled();
    modelSelections.clear();
    for (const [id, sel] of getInitialModelSelections()) modelSelections.set(id, sel);
    providerSelections.clear();
    for (const pid of getInitialProviderSelections()) providerSelections.add(pid);
    mcpEnabled = getInitialMcpEnabled();
    mcpSelections.clear();
    for (const id of getInitialMcpSelections()) mcpSelections.add(id);
    promptEnabled = getInitialPromptEnabled();
    selectedPromptId = getInitialSelectedPromptId();
    saveError = null;
  }

  const defaultValid = $derived(
    !modelsEnabled || defaultModelId === null || effectiveModelIds.has(defaultModelId)
  );
  const canSave = $derived(
    dirty &&
      (!modelsEnabled || effectiveModelIds.size > 0) &&
      defaultValid &&
      (!promptEnabled || selectedPromptId !== null)
  );

  const modelsSummary = $derived.by(() => {
    if (!modelsEnabled) return "Inaktiv – alla modeller tillåtna";
    const total = effectiveModelIds.size;
    if (total === 0) return "Aktiv – inga modeller valda";
    if (total === 1) return "Aktiv – 1 modell (väljare dold)";
    const providerCount = providerSelections.size;
    if (providerCount === 0) return `Aktiv – ${total} modeller`;
    const providerNoun = providerCount === 1 ? "provider" : "providers";
    return `Aktiv – ${total} modeller (${providerCount} ${providerNoun})`;
  });
  const mcpSummary = $derived(
    !mcpEnabled
      ? "Inaktiv – följer användarens vanliga åtkomst"
      : mcpSelections.size === 0
        ? "Aktiv – inga servrar tillåtna"
        : `Aktiv – ${mcpSelections.size} av ${allMcpServers.length} servrar`
  );
  const promptSummary = $derived(
    !promptEnabled
      ? "Inaktiv – användarens egna prompts gäller"
      : !selectedPromptId
        ? "Aktiv – ingen prompt vald"
        : `Aktiv – ${promptOptions.find((p) => p.id === selectedPromptId)?.name ?? "okänd prompt"}`
  );

  function badgeVariant(enabled: boolean, valid: boolean) {
    if (!enabled) return "outline" as const;
    return valid ? "default" : ("destructive" as const);
  }

  function providerName(pid: string | null) {
    if (pid === null) return "Övriga modeller";
    return allProviders.find((p) => p.id === pid)?.name ?? "Okänd provider";
  }

  function toggleProvider(pid: string, on: boolean) {
    if (on) {
      providerSelections.add(pid);
      // When a provider is whitelisted, individual selections under it become
      // redundant — clear them so the UI doesn't show duplicate state.
      for (const m of modelsByProvider.get(pid) ?? []) {
        const cur = modelSelections.get(m.id);
        if (cur) modelSelections.set(m.id, { selected: false, isDefault: cur.isDefault });
      }
    } else {
      providerSelections.delete(pid);
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai – Admin – Personlig assistent</title>
</svelte:head>

<div class="flex-1 overflow-y-auto px-6 pt-6">
  <Settings.Page>
    <div class="space-y-6 pb-32">
      <!-- MODELLER -->
      <section
        aria-labelledby="section-models-title"
        aria-describedby="section-models-summary"
        class="border-default bg-card overflow-hidden rounded-xl border"
      >
        <header class="border-default flex items-start gap-4 border-b p-5">
          <div
            class="bg-secondary text-primary flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
            aria-hidden="true"
          >
            <IconCPU class="h-5 w-5" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h2 id="section-models-title" class="text-primary text-base font-semibold">
                Modeller
              </h2>
              <Badge
                id="section-models-summary"
                variant={badgeVariant(modelsEnabled, effectiveModelIds.size > 0 && defaultValid)}
              >
                {modelsSummary}
              </Badge>
            </div>
            <p class="text-secondary mt-1 text-sm">
              Tillåt antingen hela providers (inklusive framtida modeller) eller enskilda modeller.
              Om bara en modell är tillgänglig döljs väljaren för slutanvändaren.
            </p>
          </div>
        </header>
        <div class="space-y-4 p-5">
          <div class="flex items-center justify-between gap-3">
            <Label for="models-enabled" class="text-sm font-medium">
              Begränsa modellval i personlig assistent
            </Label>
            <Switch
              id="models-enabled"
              bind:checked={modelsEnabled}
              aria-describedby="models-help"
            />
          </div>

          {#if modelsEnabled}
            <p id="models-help" class="text-secondary text-sm">
              Slå på en hel provider för att tillåta alla nuvarande och framtida modeller från den.
              Markera enskilda modeller för fin-granulär kontroll.
            </p>
            <div class="space-y-3">
              {#each Array.from(modelsByProvider.entries()) as [pid, providerModels] (pid ?? "_unprovided")}
                {@const isProviderSelected = pid !== null && providerSelections.has(pid)}
                <fieldset class="border-default overflow-hidden rounded-lg border">
                  <legend class="sr-only">{providerName(pid)}</legend>
                  <div
                    class="bg-secondary border-default flex items-center justify-between gap-3 border-b px-4 py-3"
                  >
                    <div class="flex items-center gap-3">
                      {#if pid !== null}
                        <Checkbox
                          checked={isProviderSelected}
                          onCheckedChange={(v) => toggleProvider(pid, !!v)}
                          aria-label={`Tillåt alla nuvarande och framtida modeller från ${providerName(pid)}`}
                        />
                      {:else}
                        <div class="h-4 w-4" aria-hidden="true"></div>
                      {/if}
                      <div>
                        <div class="text-primary text-sm font-semibold">
                          {providerName(pid)}
                        </div>
                        <div class="text-secondary text-xs">
                          {#if isProviderSelected}
                            Alla nuvarande och framtida modeller tillåts
                          {:else if pid === null}
                            Modeller utan kopplad provider
                          {:else}
                            {providerModels.length} modell{providerModels.length === 1 ? "" : "er"} –
                            välj enskilda eller hela provider
                          {/if}
                        </div>
                      </div>
                    </div>
                  </div>
                  <table class="w-full text-sm" aria-label={`Modeller från ${providerName(pid)}`}>
                    <thead class="sr-only">
                      <tr>
                        <th scope="col">Tillåt</th>
                        <th scope="col">Modell</th>
                        <th scope="col">Förvald</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each providerModels as model (model.id)}
                        {@const sel = modelSelections.get(model.id)}
                        {@const includedViaProvider = isProviderSelected}
                        {@const effectivelySelected =
                          includedViaProvider || (sel?.selected ?? false)}
                        <tr
                          class="border-default border-t {includedViaProvider
                            ? 'bg-secondary/30'
                            : ''}"
                        >
                          <td class="w-12 px-4 py-2.5">
                            <Checkbox
                              checked={effectivelySelected}
                              disabled={includedViaProvider}
                              onCheckedChange={(v) => toggleModelSelected(model.id, !!v)}
                              aria-label={`Tillåt ${model.nickname ?? model.name}`}
                            />
                          </td>
                          <td class="px-4 py-2.5">
                            <span class={includedViaProvider ? "text-secondary" : ""}>
                              {model.nickname ?? model.name}
                            </span>
                            {#if includedViaProvider}
                              <span class="text-tertiary ml-1.5 text-xs">· via provider</span>
                            {/if}
                          </td>
                          <td class="w-20 px-4 py-2.5">
                            <label class="flex items-center gap-2">
                              <input
                                type="radio"
                                name="default-model"
                                disabled={!effectivelySelected}
                                checked={defaultModelId === model.id}
                                onchange={() => setSingleDefault(model.id)}
                                aria-label={`Använd ${model.nickname ?? model.name} som förvald modell`}
                              />
                              <span class="text-secondary text-xs">Förvald</span>
                            </label>
                          </td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </fieldset>
              {/each}
            </div>
            {#if effectiveModelIds.size === 0}
              <p class="text-destructive flex items-center gap-2 text-sm" role="alert">
                <AlertCircle class="h-4 w-4 shrink-0" aria-hidden="true" />
                Välj minst en provider eller modell.
              </p>
            {:else if !defaultValid}
              <p class="text-destructive flex items-center gap-2 text-sm" role="alert">
                <AlertCircle class="h-4 w-4 shrink-0" aria-hidden="true" />
                Förvald modell ingår inte längre i tillåtna modeller – välj en ny förvald.
              </p>
            {/if}
          {:else}
            <p id="models-help" class="text-secondary text-sm">
              Den personliga assistenten kan använda alla completion-modeller som är aktiverade för
              organisationen.
            </p>
          {/if}
        </div>
      </section>

      <!-- MCP-SERVRAR -->
      <section
        aria-labelledby="section-mcp-title"
        aria-describedby="section-mcp-summary"
        class="border-default bg-card overflow-hidden rounded-xl border"
      >
        <header class="border-default flex items-start gap-4 border-b p-5">
          <div
            class="bg-secondary text-primary flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
            aria-hidden="true"
          >
            <Plug class="h-5 w-5" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h2 id="section-mcp-title" class="text-primary text-base font-semibold">
                MCP-servrar
              </h2>
              <Badge id="section-mcp-summary" variant={badgeVariant(mcpEnabled, true)}>
                {mcpSummary}
              </Badge>
            </div>
            <p class="text-secondary mt-1 text-sm">
              Begränsa vilka MCP-servrar som är tillgängliga i den personliga assistenten. Användare
              kan själva slå av och på dem i sin egen chatt.
            </p>
          </div>
        </header>
        <div class="space-y-4 p-5">
          <div class="flex items-center justify-between gap-3">
            <Label for="mcp-enabled" class="text-sm font-medium">
              Begränsa MCP-servrar i personlig assistent
            </Label>
            <Switch id="mcp-enabled" bind:checked={mcpEnabled} aria-describedby="mcp-help" />
          </div>

          {#if mcpEnabled}
            {#if allMcpServers.length === 0}
              <p id="mcp-help" class="text-secondary flex items-center gap-2 text-sm">
                <Info class="h-4 w-4 shrink-0" aria-hidden="true" />
                Inga MCP-servrar är aktiverade för organisationen ännu.
              </p>
            {:else}
              <p id="mcp-help" class="text-secondary text-sm">
                Markera de servrar som ska vara tillgängliga. En tom lista betyder att inga
                MCP-servrar tillåts i personlig assistent.
              </p>
              <fieldset class="border-default rounded-lg border p-4">
                <legend class="sr-only">Tillåtna MCP-servrar</legend>
                <div class="space-y-2.5">
                  {#each allMcpServers as server (server.id)}
                    <label
                      class="hover:bg-hover-default -mx-2 flex items-center gap-3 rounded-md px-2 py-1.5"
                    >
                      <Checkbox
                        checked={mcpSelections.has(server.id)}
                        onCheckedChange={(v) => toggleMcp(server.id, !!v)}
                      />
                      <span class="text-sm">{server.name}</span>
                    </label>
                  {/each}
                </div>
              </fieldset>
            {/if}
          {:else}
            <p id="mcp-help" class="text-secondary text-sm">
              Personlig assistent följer den vanliga MCP-tillgängligheten för användaren och
              organisationen.
            </p>
          {/if}
        </div>
      </section>

      <!-- DEFAULT-PROMPT -->
      <section
        aria-labelledby="section-prompt-title"
        aria-describedby="section-prompt-summary"
        class="border-default bg-card overflow-hidden rounded-xl border"
      >
        <header class="border-default flex items-start gap-4 border-b p-5">
          <div
            class="bg-secondary text-primary flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
            aria-hidden="true"
          >
            <Sparkles class="h-5 w-5" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h2 id="section-prompt-title" class="text-primary text-base font-semibold">
                Gemensam prompt
              </h2>
              <Badge
                id="section-prompt-summary"
                variant={badgeVariant(promptEnabled, selectedPromptId !== null)}
              >
                {promptSummary}
              </Badge>
            </div>
            <p class="text-secondary mt-1 text-sm">
              Tvinga en gemensam system-prompt på alla personliga assistenter. Användarnas egna
              prompts döljs så länge policyn är aktiv.
            </p>
          </div>
        </header>
        <div class="space-y-4 p-5">
          <div class="flex items-center justify-between gap-3">
            <Label for="prompt-enabled" class="text-sm font-medium">Tvinga gemensam prompt</Label>
            <Switch
              id="prompt-enabled"
              bind:checked={promptEnabled}
              aria-describedby="prompt-help"
            />
          </div>

          {#if promptEnabled}
            {#if promptOptions.length === 0}
              <div
                class="border-caution bg-warning-dimmer flex items-start gap-3 rounded-lg border p-4 text-sm"
              >
                <Info class="text-warning-stronger mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <div>
                  <p>Det finns inga prompts i biblioteket.</p>
                  <a
                    class="text-accent-default mt-1 inline-block underline"
                    href={resolve("/admin/personal-assistant/prompts")}
                  >
                    Skapa en prompt i biblioteket →
                  </a>
                </div>
              </div>
            {:else}
              <p id="prompt-help" class="text-secondary text-sm">
                Välj vilken prompt som ska tvingas på alla personliga assistenter.
              </p>
              <RadioGroup.Root
                bind:value={() => selectedPromptId ?? "", (v) => (selectedPromptId = v)}
              >
                <div class="space-y-2">
                  {#each promptOptions as p (p.id)}
                    <Label
                      for={`p-${p.id}`}
                      class="border-default hover:border-stronger aria-checked:border-accent-default flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors"
                    >
                      <RadioGroup.Item value={p.id} id={`p-${p.id}`} class="mt-0.5" />
                      <div class="flex-1">
                        <div class="text-sm font-medium">{p.name}</div>
                        {#if p.description}
                          <div class="text-secondary mt-0.5 text-xs">{p.description}</div>
                        {/if}
                      </div>
                    </Label>
                  {/each}
                </div>
              </RadioGroup.Root>
              {#if !selectedPromptId}
                <p class="text-destructive flex items-center gap-2 text-sm" role="alert">
                  <AlertCircle class="h-4 w-4 shrink-0" aria-hidden="true" />
                  En prompt måste väljas.
                </p>
              {/if}
            {/if}
          {:else}
            <p id="prompt-help" class="text-secondary text-sm">
              Ingen gemensam prompt tvingas. Användarnas egna personliga chatprompts är synliga och
              används som vanligt.
            </p>
          {/if}
        </div>
      </section>
    </div>
  </Settings.Page>
</div>

<!-- Live region for save status (announced by screen readers) -->
<div role="status" aria-live="polite" class="sr-only">{saveAnnouncement}</div>

<!-- Sticky save bar - appears when there are unsaved changes -->
{#if dirty || saveError}
  <div
    class="border-default bg-primary fixed right-0 bottom-0 left-0 z-50 border-t shadow-lg md:left-[17rem]"
    role="region"
    aria-label="Osparade ändringar"
  >
    <div class="mx-auto flex max-w-[1100px] items-center justify-between gap-4 px-6 py-3">
      <div class="flex items-center gap-2 text-sm">
        {#if saveError}
          <AlertCircle class="text-destructive h-4 w-4 shrink-0" aria-hidden="true" />
          <span class="text-destructive" role="alert">{saveError}</span>
        {:else if !canSave}
          <AlertCircle class="text-warning-stronger h-4 w-4 shrink-0" aria-hidden="true" />
          <span class="text-secondary">Åtgärda valideringsfel innan du kan spara.</span>
        {:else}
          <CheckCircle2 class="text-accent-default h-4 w-4 shrink-0" aria-hidden="true" />
          <span class="text-secondary">Du har osparade ändringar.</span>
        {/if}
      </div>
      <div class="flex items-center gap-2">
        <Button variant="ghost" onclick={discardChanges} disabled={saving}>Återställ</Button>
        <Button onclick={save} disabled={!canSave || saving} aria-busy={saving}>
          {saving ? "Sparar…" : "Spara ändringar"}
        </Button>
      </div>
    </div>
  </div>
{/if}

<Dialog.Root
  open={pendingConfirm !== null}
  onOpenChange={(o) => {
    if (!o) pendingConfirm = null;
  }}
>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>Bekräfta ändring</Dialog.Title>
      <Dialog.Description>
        Följande får direkt effekt för alla användare i organisationen:
      </Dialog.Description>
    </Dialog.Header>
    <ul class="list-disc space-y-1 pl-6 text-sm">
      {#each pendingConfirm?.messages ?? [] as msg (msg)}
        <li>{msg}</li>
      {/each}
    </ul>
    <Dialog.Footer>
      <Button variant="outline" onclick={() => (pendingConfirm = null)} disabled={saving}>
        Avbryt
      </Button>
      <Button onclick={() => pendingConfirm?.submit()} disabled={saving} aria-busy={saving}>
        {saving ? "Sparar…" : "Bekräfta och spara"}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
