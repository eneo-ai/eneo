<script lang="ts">
  import { Button, Input, Select } from "@eneo/ui";
  import * as m from "$lib/paraglide/messages";
  import { Shield, ArrowRight } from "lucide-svelte";
  import { slide, fade, fly } from "svelte/transition";
  import { writable } from "svelte/store";
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { onMount } from "svelte";

  // Animation state for staggered entrance
  let mounted = $state(false);

  onMount(() => {
    mounted = true;
  });

  // Props
  interface Props {
    onSubmit: (justification: { category: string; description: string }) => Promise<void>;
  }

  let { onSubmit }: Props = $props();

  // State
  const categoryStore = writable<{ value: string; label: string }>({ value: "", label: "" });
  let description = $state("");
  let isSubmitting = $state(false);
  let categoryError = $state<string | null>(null);
  let _descriptionError = $state<string | null>(null);

  // Access reason options
  const accessReasonOptions = [
    { value: "compliance_review", label: m.audit_reason_compliance_review() },
    { value: "security_investigation", label: m.audit_reason_security_investigation() },
    { value: "user_support", label: m.audit_reason_user_support() },
    { value: "gdpr_request", label: m.audit_reason_gdpr_request() },
    { value: "audit_review", label: m.audit_reason_audit_review() },
    { value: "troubleshooting", label: m.audit_reason_troubleshooting() },
    { value: "management_review", label: m.audit_reason_management_review() },
    { value: "legal_request", label: m.audit_reason_legal_request() },
    { value: "other", label: m.audit_reason_other() }
  ];

  // Form validation
  const isFormValid = $derived(
    $categoryStore?.value && description.trim().length >= 10 && description.length <= 500
  );

  // Character counter
  const charCount = $derived(description.length);
  const minChars = 10;
  const charsNeeded = $derived(Math.max(0, minChars - description.trim().length));

  // Validate category
  function validateCategory() {
    if (!$categoryStore?.value) {
      categoryError = "Please select an access reason";
      return false;
    }
    categoryError = null;
    return true;
  }

  // Validate description
  function validateDescription() {
    const trimmed = description.trim();
    if (trimmed.length === 0) {
      _descriptionError = m.audit_access_description_required();
      return false;
    }
    if (trimmed.length < 10) {
      _descriptionError = m.audit_access_description_required();
      return false;
    }
    if (description.length > 500) {
      _descriptionError = "Justification exceeds maximum length (500 characters)";
      return false;
    }
    _descriptionError = null;
    return true;
  }

  // Handle submit
  async function submitJustification() {
    // Validate both fields
    const categoryValid = validateCategory();
    const descriptionValid = validateDescription();

    if (!categoryValid || !descriptionValid) {
      return;
    }

    if (!$categoryStore?.value) return;

    isSubmitting = true;
    try {
      await onSubmit({
        category: $categoryStore.value,
        description: description.trim()
      });
    } catch (error) {
      console.error("Failed to submit justification:", error);
      // Reset errors on failure
      categoryError = "Failed to submit justification. Please try again.";
    } finally {
      isSubmitting = false;
    }
  }

  // Handle cancel - go back to audit logs without filters
  function handleCancel() {
    goto(resolve("/admin/audit-logs"), { replaceState: true });
  }

  // Handle keyboard shortcuts
  function handleKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && isFormValid) {
      submitJustification();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="flex min-h-[60vh] items-center justify-center px-4 sm:px-6 lg:px-8">
  {#if mounted}
    <div class="w-full max-w-xl py-12" in:fade={{ duration: 300 }}>
      <div
        class="border-default bg-primary relative overflow-hidden rounded-2xl border p-8 shadow-lg ring-1 ring-black/5 transition-all duration-300 hover:shadow-xl dark:ring-white/5"
      >
        <!-- Subtle security pattern overlay -->
        <div
          class="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,_currentColor_1px,_transparent_0)] bg-[length:24px_24px] opacity-[0.02] dark:opacity-[0.03]"
        ></div>

        <!-- Header -->
        <div
          class="relative mb-6 flex items-start gap-4"
          in:fly={{ y: -10, duration: 400, delay: 100 }}
        >
          <div class="relative">
            <!-- Glow ring behind shield -->
            <div
              class="bg-accent-default/20 absolute inset-0 animate-[pulse_3s_ease-in-out_infinite] rounded-lg blur-md"
            ></div>
            <div
              class="bg-accent-default/15 ring-accent-default/20 relative rounded-lg p-2.5 ring-1"
            >
              <Shield class="text-accent-default h-6 w-6" />
            </div>
          </div>
          <div class="flex-1">
            <h3 class="text-default mb-2 text-lg font-semibold tracking-tight">
              {m.audit_access_required_title()}
            </h3>
            <p class="text-muted text-sm leading-relaxed">
              {m.audit_access_required_description()}
            </p>
          </div>
        </div>

        <!-- Form -->
        <form
          onsubmit={(e) => {
            e.preventDefault();
            submitJustification();
          }}
          class="relative space-y-5"
        >
          <!-- Category Select -->
          <div in:fly={{ y: 10, duration: 400, delay: 200 }}>
            <!-- svelte-ignore a11y_label_has_associated_control -->
            <label class="text-default mb-2 block text-sm font-semibold">
              {m.audit_access_reason_label()} <span class="text-red-600 dark:text-red-400">*</span>
            </label>
            <!-- @ts-ignore customStore type mismatch -->
            <Select.Root
              customStore={categoryStore}
              required
              {...{ onSelectedChange: validateCategory }}
            >
              <Select.Trigger
                {...{
                  class: "w-full",
                  "aria-label": m.audit_access_reason_label(),
                  "aria-required": "true"
                }}
                placeholder={m.audit_access_reason_placeholder()}
              />
              <Select.Options>
                {#each accessReasonOptions as option (option.value)}
                  <Select.Item value={option.value} label={option.label} />
                {/each}
              </Select.Options>
            </Select.Root>
            {#if categoryError}
              <div
                transition:slide={{ duration: 150 }}
                class="mt-2 flex items-start gap-2 text-xs text-red-600 dark:text-red-400"
                role="alert"
              >
                <span>{categoryError}</span>
              </div>
            {/if}
          </div>

          <!-- Description TextArea -->
          <div in:fly={{ y: 10, duration: 400, delay: 300 }}>
            <label for="description-field" class="text-default mb-2 block text-sm font-semibold">
              {m.audit_access_description_label()}
              <span class="text-red-600 dark:text-red-400">*</span>
            </label>
            <Input.TextArea
              id="description-field"
              bind:value={description}
              rows={4}
              required
              placeholder={m.audit_access_description_placeholder()}
              maxlength={500}
              onblur={validateDescription}
              aria-label={m.audit_access_description_label()}
              aria-required="true"
              aria-describedby="char-counter"
              class="w-full"
            />
            <div class="mt-2 flex items-center justify-between">
              <span
                id="char-counter"
                class={`text-sm transition-colors duration-200 ${
                  charsNeeded > 0
                    ? "text-muted"
                    : charCount > 450
                      ? "font-medium text-amber-600 dark:text-amber-400"
                      : charCount > 400
                        ? "text-amber-500 dark:text-amber-500"
                        : "text-muted"
                }`}
                aria-live="polite"
              >
                {#if charsNeeded > 0}
                  <span class="text-accent-default font-semibold"
                    >{m.audit_access_chars_needed({ count: charsNeeded })}</span
                  >
                  <span class="text-muted/60 ml-1.5">({charCount}/500)</span>
                {:else}
                  {m.audit_access_char_limit({ current: charCount, max: 500 })}
                {/if}
              </span>
            </div>
          </div>

          <!-- Action Buttons -->
          <div
            class="flex flex-col items-center justify-between gap-3 pt-4 sm:flex-row"
            in:fly={{ y: 10, duration: 400, delay: 400 }}
          >
            <!-- Keyboard shortcut hint -->
            <span class="text-muted hidden items-center gap-1.5 text-xs sm:inline-flex">
              <kbd
                class="bg-subtle border-default rounded-md border px-2 py-1 font-mono text-xs shadow-sm"
                >Ctrl</kbd
              >
              <span class="text-muted/60">+</span>
              <kbd
                class="bg-subtle border-default rounded-md border px-2 py-1 font-mono text-xs shadow-sm"
                >Enter</kbd
              >
              <span class="text-muted/80 ml-1">{m.audit_keyboard_to_submit()}</span>
            </span>
            <div class="flex items-center gap-3">
              <Button
                type="button"
                variant="simple"
                onclick={handleCancel}
                class="w-full transition-all duration-150 hover:scale-[1.02] active:scale-[0.98] sm:w-auto"
              >
                {m.audit_access_cancel()}
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={!isFormValid || isSubmitting}
                class="w-full min-w-[160px] transition-transform duration-150 hover:scale-[1.02] active:scale-[0.98] sm:w-auto"
              >
                {#if isSubmitting}
                  <div
                    class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
                  ></div>
                  <span class="ml-2">{m.audit_config_saving()}</span>
                {:else}
                  <span>{m.audit_access_submit()}</span>
                  <ArrowRight class="ml-2 h-4 w-4" />
                {/if}
              </Button>
            </div>
          </div>
        </form>
      </div>
    </div>
  {/if}
</div>
