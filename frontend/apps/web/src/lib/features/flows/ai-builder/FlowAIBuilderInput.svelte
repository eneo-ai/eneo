<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";

  const service = getAIBuilderService();

  let inputValue = $state("");
  let textareaEl: HTMLTextAreaElement;
  let activePlaceholder = $state<string | null>(null);

  const currentPlaceholder = $derived(activePlaceholder ?? m.ai_builder_input_placeholder());

  export function focus(options?: string | { placeholder?: string; prefill?: string }) {
    // Support both old string signature and new options object
    if (typeof options === "string") {
      // Legacy: treat as placeholder (not prefill)
      activePlaceholder = options;
    } else if (options) {
      if (options.prefill) inputValue = options.prefill;
      if (options.placeholder) activePlaceholder = options.placeholder;
    }
    requestAnimationFrame(() => {
      textareaEl?.focus();
      handleInput();
    });
  }

  export function clearActivePlaceholder() {
    activePlaceholder = null;
  }

  async function handleSubmit() {
    const trimmed = inputValue.trim();
    if (!trimmed || !service.canSendMessage) return;
    inputValue = "";
    activePlaceholder = null;
    resetTextareaHeight();
    await service.sendMessage(trimmed);
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  function handleInput() {
    if (textareaEl) {
      textareaEl.style.height = "auto";
      textareaEl.style.height = Math.min(textareaEl.scrollHeight, 300) + "px";
    }
  }

  function resetTextareaHeight() {
    if (textareaEl) {
      textareaEl.style.height = "auto";
    }
  }

  const selectedModelName = $derived(
    service.availableModels.find((m) => m.id === service.selectedModelId)?.name ?? null
  );
</script>

<div class="mx-auto w-full max-w-[71ch]">
  <div class="input-container">
    <textarea
      bind:this={textareaEl}
      bind:value={inputValue}
      onkeydown={handleKeydown}
      oninput={handleInput}
      placeholder={currentPlaceholder}
      disabled={!service.canSendMessage}
      rows="1"
      class="text-primary placeholder:text-muted min-h-12 w-full resize-none bg-transparent px-4 pt-3.5 text-base leading-relaxed outline-none disabled:opacity-50"
      class:pb-3={!service.modelsLoaded || service.availableModels.length <= 1}
      class:pb-1={service.modelsLoaded && service.availableModels.length > 1}
    ></textarea>

    <!-- Bottom toolbar: model selector (left) + send button (right) -->
    <div class="flex items-end justify-between px-2 pb-2">
      <!-- Model selector — only shown when multiple models are available -->
      <div class="flex items-center">
        {#if service.modelsLoaded && service.availableModels.length > 1}
          <DropdownMenu.Root>
            <DropdownMenu.Trigger>
              {#snippet child({ props })}
                <button {...props} class="model-pill">
                  <span class="model-pill-name"
                    >{selectedModelName ?? m.ai_builder_model_label()}</span
                  >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 16 16"
                    fill="currentColor"
                    class="model-pill-chevron"
                  >
                    <path
                      fill-rule="evenodd"
                      d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"
                      clip-rule="evenodd"
                    />
                  </svg>
                </button>
              {/snippet}
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="start">
              {#each service.availableModels as model (model.id)}
                <DropdownMenu.Item
                  onmousedown={() => {
                    service.selectModel(model.id);
                  }}
                  class="!justify-start !gap-2 !px-3 !py-2 !text-[0.8125rem]"
                >
                  <span class="flex-1 text-left">{model.name}</span>
                  {#if model.id === service.selectedModelId}
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 16 16"
                      fill="currentColor"
                      class="model-menu-check"
                    >
                      <path
                        fill-rule="evenodd"
                        d="M12.416 3.376a.75.75 0 0 1 .208 1.04l-5 7.5a.75.75 0 0 1-1.154.114l-3-3a.75.75 0 0 1 1.06-1.06l2.353 2.353 4.493-6.74a.75.75 0 0 1 1.04-.207Z"
                        clip-rule="evenodd"
                      />
                    </svg>
                  {/if}
                </DropdownMenu.Item>
              {/each}
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        {/if}
      </div>

      <!-- Send button -->
      <button
        onclick={handleSubmit}
        disabled={!inputValue.trim() || !service.canSendMessage}
        class="send-button"
        aria-label={m.ai_builder_send()}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          class="size-3.5"
        >
          <path
            d="M3.105 2.288a.75.75 0 0 0-.826.95l1.414 4.926A1.5 1.5 0 0 0 5.135 9.25h6.115a.75.75 0 0 1 0 1.5H5.135a1.5 1.5 0 0 0-1.442 1.086l-1.414 4.926a.75.75 0 0 0 .826.95 28.897 28.897 0 0 0 15.293-7.155.75.75 0 0 0 0-1.114A28.897 28.897 0 0 0 3.105 2.288Z"
          />
        </svg>
      </button>
    </div>
  </div>
</div>

<style lang="postcss">
  .input-container {
    position: relative;
    border-radius: 1.25rem;
    border: 1px solid oklch(from var(--border-default) l c h / 1.5);
    background: var(--bg-primary);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.15),
      0 8px 30px -4px rgba(0, 0, 0, 0.06),
      0 4px 6px -2px rgba(0, 0, 0, 0.03);
    transition:
      border-color 0.2s cubic-bezier(0.16, 1, 0.3, 1),
      box-shadow 0.2s cubic-bezier(0.16, 1, 0.3, 1),
      transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  }

  .input-container:focus-within {
    border-color: var(--accent-default);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.15),
      0 0 0 1px var(--accent-default),
      0 12px 40px -4px rgba(0, 0, 0, 0.08),
      0 0 16px 2px oklch(from var(--accent-default) l c h / 0.15);
    transform: translateY(-1px);
  }

  /* --- Send button --- */

  .send-button {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2.25rem;
    height: 2.25rem;
    flex-shrink: 0;
    border-radius: 50%;
    background: var(--accent-default);
    color: var(--text-on-fill);
    cursor: pointer;
    box-shadow: 0 2px 8px -2px oklch(from var(--accent-default) l c h / 0.4);
    transition:
      background 0.2s ease,
      opacity 0.2s ease,
      transform 0.15s cubic-bezier(0.16, 1, 0.3, 1),
      box-shadow 0.2s ease;
  }

  .send-button:not(:disabled):hover {
    background: var(--accent-stronger);
    transform: scale(1.05);
    box-shadow: 0 4px 12px -2px oklch(from var(--accent-default) l c h / 0.5);
  }

  .send-button:not(:disabled):active {
    transform: scale(0.95);
  }

  .send-button:disabled {
    opacity: 0.3;
    cursor: default;
    box-shadow: none;
  }

  /* --- Model pill --- */

  .model-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.25rem 0.625rem;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    line-height: 1.3;
    color: var(--text-secondary);
    background: var(--bg-secondary);
    border: none;
    cursor: pointer;
    transition:
      color 0.12s ease,
      background 0.12s ease;
  }

  .model-pill:hover {
    color: var(--text-primary);
    background: var(--bg-hover-stronger);
  }

  .model-pill-name {
    white-space: nowrap;
  }

  .model-pill-chevron {
    width: 0.625rem;
    height: 0.625rem;
    flex-shrink: 0;
    opacity: 0.45;
    transition:
      transform 0.15s ease,
      opacity 0.15s ease;
  }

  .model-menu-check {
    width: 0.875rem;
    height: 0.875rem;
    flex-shrink: 0;
    color: var(--accent-default);
  }
</style>
