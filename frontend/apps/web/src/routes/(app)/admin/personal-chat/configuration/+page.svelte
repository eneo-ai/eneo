<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page, Settings } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";

  let { data } = $props();

  const allModels = $derived(data.models.completionModels);
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

  const allMcpServers = $derived((data.mcpSettings?.items ?? []).filter((s) => s.is_available));
  let mcpEnabled = $state(getInitialMcpEnabled());
  const mcpSelections = new SvelteSet<string>(getInitialMcpSelections());

  const promptOptions = $derived(data.promptLibrary.items);
  let promptEnabled = $state(getInitialPromptEnabled());
  let selectedPromptId = $state<string | null>(getInitialSelectedPromptId());

  let saving = $state(false);
  let saveError = $state<string | null>(null);
  let pendingConfirm = $state<{ messages: string[]; submit: () => Promise<void> } | null>(null);

  const selectedModels = $derived(
    Array.from(modelSelections.entries())
      .filter(([, v]) => v.selected)
      .map(([id, v]) => ({ completion_model_id: id, is_default: v.isDefault }))
  );

  $effect(() => {
    modelsEnabled = getInitialModelsEnabled();
    modelSelections.clear();
    for (const [modelId, selection] of getInitialModelSelections()) {
      modelSelections.set(modelId, selection);
    }

    mcpEnabled = getInitialMcpEnabled();
    mcpSelections.clear();
    for (const serverId of getInitialMcpSelections()) {
      mcpSelections.add(serverId);
    }

    promptEnabled = getInitialPromptEnabled();
    selectedPromptId = getInitialSelectedPromptId();
  });

  function setSingleDefault(id: string) {
    for (const [k, v] of modelSelections) {
      modelSelections.set(k, { ...v, isDefault: k === id });
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

  function buildConfirmations(): string[] {
    const out: string[] = [];
    const initial = data.policy;
    if (
      modelsEnabled &&
      selectedModels.length === 1 &&
      (!initial.models_restriction.enabled || initial.models_restriction.models.length !== 1)
    ) {
      out.push("Detta döljer modellväljaren för alla användares personliga chatt.");
    }
    if (
      mcpEnabled &&
      mcpSelections.size === 0 &&
      (!initial.mcp_restriction.enabled || initial.mcp_restriction.server_ids.length !== 0)
    ) {
      out.push("Detta inaktiverar alla MCP-servrar på alla personliga chattar.");
    }
    if (promptEnabled && !initial.prompt_enforcement.enabled) {
      out.push("Alla användares egna prompts döljs och den valda prompten används istället.");
    }
    return out;
  }

  async function doSave() {
    saving = true;
    saveError = null;
    try {
      await data.intric.personalChatPolicy.update({
        models_restriction: { enabled: modelsEnabled, models: selectedModels },
        mcp_restriction: {
          enabled: mcpEnabled,
          server_ids: Array.from(mcpSelections)
        },
        prompt_enforcement: {
          enabled: promptEnabled,
          prompt_library_id: promptEnabled ? selectedPromptId : null
        }
      });
      await invalidate("admin:personal-chat-policy");
      pendingConfirm = null;
    } catch (e) {
      const err = e as { message?: string };
      saveError = err.message ?? "Kunde inte spara policy.";
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

  const canSave = $derived(
    (!modelsEnabled || selectedModels.length > 0) && (!promptEnabled || selectedPromptId !== null)
  );
</script>

<svelte:head>
  <title>Eneo.ai – Admin – Personlig chatt</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title="Personlig chatt – konfiguration"></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Card.Root>
        <Card.Header>
          <Card.Title>Modeller</Card.Title>
          <Card.Description>
            Begränsa vilka completion-modeller användarens personliga chatt får använda. Om exakt en
            modell väljs döljs modellväljaren för slutanvändaren.
          </Card.Description>
        </Card.Header>
        <Card.Content class="space-y-4">
          <div class="flex items-center gap-3">
            <Switch id="models-enabled" bind:checked={modelsEnabled} />
            <Label for="models-enabled">Begränsa modellval i personlig chatt</Label>
          </div>
          {#if modelsEnabled}
            <div class="border-default rounded-lg border">
              <table class="w-full text-sm">
                <thead class="border-default border-b text-left">
                  <tr>
                    <th class="px-4 py-2">Tillåt</th>
                    <th class="px-4 py-2">Modell</th>
                    <th class="px-4 py-2">Förvald</th>
                  </tr>
                </thead>
                <tbody>
                  {#each allModels as model (model.id)}
                    {@const sel = modelSelections.get(model.id)}
                    <tr class="border-default border-b last:border-b-0">
                      <td class="px-4 py-2">
                        <Checkbox
                          checked={sel?.selected ?? false}
                          onCheckedChange={(v) => toggleModelSelected(model.id, !!v)}
                        />
                      </td>
                      <td class="px-4 py-2">{model.nickname ?? model.name}</td>
                      <td class="px-4 py-2">
                        <input
                          type="radio"
                          name="default-model"
                          disabled={!sel?.selected}
                          checked={sel?.isDefault}
                          onchange={() => setSingleDefault(model.id)}
                        />
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
            {#if selectedModels.length === 0}
              <p class="text-destructive text-sm">Minst en modell måste vara vald.</p>
            {/if}
          {:else}
            <p class="text-muted text-sm">
              Ingen modellbegränsning är aktiv. Personlig chatt kan använda tenantens tillgängliga
              completion-modeller.
            </p>
          {/if}
        </Card.Content>
      </Card.Root>

      <Card.Root>
        <Card.Header>
          <Card.Title>MCP-servrar</Card.Title>
          <Card.Description>
            Begränsa vilka MCP-servrar som är tillgängliga i personlig chatt. Användare kan själva
            toggla av/på dessa i sin egen chatt. Tom lista innebär att inga MCP-servrar tillåts.
          </Card.Description>
        </Card.Header>
        <Card.Content class="space-y-4">
          <div class="flex items-center gap-3">
            <Switch id="mcp-enabled" bind:checked={mcpEnabled} />
            <Label for="mcp-enabled">Begränsa MCP-servrar i personlig chatt</Label>
          </div>
          {#if mcpEnabled}
            {#if allMcpServers.length === 0}
              <p class="text-muted text-sm">Inga MCP-servrar är aktiverade för tenanten.</p>
            {:else}
              <div class="border-default space-y-2 rounded-lg border p-4">
                {#each allMcpServers as server (server.id)}
                  <label class="flex items-center gap-3">
                    <Checkbox
                      checked={mcpSelections.has(server.id)}
                      onCheckedChange={(v) => toggleMcp(server.id, !!v)}
                    />
                    <span>{server.name}</span>
                  </label>
                {/each}
              </div>
            {/if}
          {:else}
            <p class="text-muted text-sm">
              Ingen MCP-begränsning är aktiv. Personlig chatt följer användarens och tenantens
              vanliga MCP-tillgänglighet.
            </p>
          {/if}
        </Card.Content>
      </Card.Root>

      <Card.Root>
        <Card.Header>
          <Card.Title>Default-prompt</Card.Title>
          <Card.Description>
            Tvinga en gemensam system-prompt på alla användares personliga chatt. Användarnas egna
            prompts döljs så länge denna policy är aktiv.
          </Card.Description>
        </Card.Header>
        <Card.Content class="space-y-4">
          <div class="flex items-center gap-3">
            <Switch id="prompt-enabled" bind:checked={promptEnabled} />
            <Label for="prompt-enabled">Tvinga gemensam prompt</Label>
          </div>
          {#if promptEnabled}
            {#if promptOptions.length === 0}
              <p class="text-muted text-sm">
                Inga prompts finns i biblioteket.
                <a class="underline" href={resolve("/admin/personal-chat/prompts")}>
                  Skapa en prompt först →
                </a>
              </p>
            {:else}
              <RadioGroup.Root
                bind:value={() => selectedPromptId ?? "", (v) => (selectedPromptId = v)}
              >
                <div class="space-y-2">
                  {#each promptOptions as p (p.id)}
                    <label class="border-default flex items-start gap-3 rounded-lg border p-3">
                      <RadioGroup.Item value={p.id} id={`p-${p.id}`} />
                      <div class="flex-1">
                        <div class="font-medium">{p.name}</div>
                        {#if p.description}
                          <div class="text-muted text-xs">{p.description}</div>
                        {/if}
                      </div>
                    </label>
                  {/each}
                </div>
              </RadioGroup.Root>
            {/if}
            {#if !selectedPromptId}
              <p class="text-destructive text-sm">En prompt måste väljas.</p>
            {/if}
          {:else}
            <p class="text-muted text-sm">
              Ingen gemensam prompt tvingas. Användarnas egna personliga chatprompts är synliga och
              används som vanligt.
            </p>
          {/if}
        </Card.Content>
      </Card.Root>

      {#if saveError}
        <p class="text-destructive text-sm">{saveError}</p>
      {/if}

      <div class="flex justify-end">
        <Button onclick={save} disabled={!canSave || saving}>
          {saving ? "Sparar..." : "Spara"}
        </Button>
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>

<Dialog.Root
  open={pendingConfirm !== null}
  onOpenChange={(o) => {
    if (!o) pendingConfirm = null;
  }}
>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>Bekräfta ändring</Dialog.Title>
      <Dialog.Description>Vill du verkligen göra följande ändringar?</Dialog.Description>
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
      <Button onclick={() => pendingConfirm?.submit()} disabled={saving}>
        {saving ? "Sparar..." : "Bekräfta"}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
