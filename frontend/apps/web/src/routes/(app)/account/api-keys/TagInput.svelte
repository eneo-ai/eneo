<script lang="ts">
  import { X, Plus, Globe, Server, AlertCircle } from "lucide-svelte";
  import { fly, scale } from "svelte/transition";
  import { flip } from "svelte/animate";
  import { m } from "$lib/paraglide/messages";

  type TagType = "origin" | "ip";

  let {
    type = "origin",
    value = $bindable<string[]>([]),
    label = "",
    description = "",
    placeholder = "",
    required = false,
    disabled = false
  } = $props<{
    type?: TagType;
    value?: string[];
    label?: string;
    description?: string;
    placeholder?: string;
    required?: boolean;
    disabled?: boolean;
  }>();

  let inputValue = $state("");
  let inputElement: HTMLInputElement;
  let validationError = $state<string | null>(null);

  // Quick-add patterns for origins (using getter for translations)
  const getOriginQuickAdd = () => [
    { label: m.api_keys_tag_localhost(), pattern: "http://localhost:*" },
    { label: m.api_keys_tag_https_wildcard(), pattern: "https://*" }
  ];

  // Quick-add patterns for IPs (using getter for translations)
  const getIpQuickAdd = () => [
    { label: m.api_keys_tag_private_10(), pattern: "10.0.0.0/8" },
    { label: m.api_keys_tag_private_192(), pattern: "192.168.0.0/16" }
  ];

  const quickAddOptions = $derived(type === "origin" ? getOriginQuickAdd() : getIpQuickAdd());

  // Validate origin URL pattern
  function validateOrigin(val: string): string | null {
    // Allow wildcard patterns
    if (val.includes("*")) {
      // Check if it's a valid wildcard pattern
      if (!/^https?:\/\/(\*|[\w.-]+\*?|\*\.[\w.-]+)(:\d+|:\*)?$/.test(val)) {
        return m.api_keys_tag_invalid_wildcard();
      }
      return null;
    }

    // Check if it's a valid URL
    try {
      new URL(val);
      return null;
    } catch {
      return m.api_keys_tag_invalid_origin();
    }
  }

  // Validate CIDR notation
  function validateCidr(val: string): string | null {
    // IPv4 CIDR pattern
    const ipv4CidrPattern = /^(\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/;
    // IPv4 without CIDR (single IP)
    const ipv4Pattern = /^(\d{1,3}\.){3}\d{1,3}$/;
    // IPv6 patterns
    const ipv6CidrPattern = /^([0-9a-fA-F:]+)\/\d{1,3}$/;

    if (ipv4CidrPattern.test(val) || ipv4Pattern.test(val) || ipv6CidrPattern.test(val)) {
      // Additional validation for IPv4 octets
      if (ipv4CidrPattern.test(val) || ipv4Pattern.test(val)) {
        const [ip, cidr] = val.split("/");
        const octets = ip.split(".").map(Number);
        if (octets.some((o) => o < 0 || o > 255)) {
          return m.api_keys_tag_invalid_octet();
        }
        if (cidr && (Number(cidr) < 0 || Number(cidr) > 32)) {
          return m.api_keys_tag_invalid_cidr();
        }
      }
      return null;
    }

    return m.api_keys_tag_invalid_ip();
  }

  // Validate input based on type
  function validate(val: string): string | null {
    if (!val.trim()) return null;
    return type === "origin" ? validateOrigin(val.trim()) : validateCidr(val.trim());
  }

  // Add tag from input
  function addTag() {
    const trimmed = inputValue.trim();
    if (!trimmed) return;

    const error = validate(trimmed);
    if (error) {
      validationError = error;
      return;
    }

    if (value.includes(trimmed)) {
      validationError = m.api_keys_tag_already_added();
      return;
    }

    value = [...value, trimmed];
    inputValue = "";
    validationError = null;
  }

  // Add quick-add pattern
  function addQuickPattern(pattern: string) {
    if (!value.includes(pattern)) {
      value = [...value, pattern];
    }
  }

  // Remove tag
  function removeTag(tagToRemove: string) {
    value = value.filter((t: string) => t !== tagToRemove);
  }

  // Handle keyboard input
  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      addTag();
    } else if (e.key === "Backspace" && !inputValue && value.length > 0) {
      // Remove last tag on backspace when input is empty
      value = value.slice(0, -1);
    } else if (validationError) {
      // Clear error on typing
      validationError = null;
    }
  }

  const Icon = $derived(type === "origin" ? Globe : Server);
</script>

<div class="space-y-2">
  <!-- Label and description -->
  {#if label}
    <span id="tag-input-label" class="text-default block text-sm font-medium">
      {label}
      {#if required}
        <span class="text-negative">*</span>
      {/if}
    </span>
  {/if}
  {#if description}
    <p class="text-muted text-xs">{description}</p>
  {/if}

  <!-- Tags container -->
  <div
    class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 min-h-[2.75rem] rounded-lg
           border p-2 transition-all
           duration-150 ease-out focus-within:ring-2
           {disabled ? 'cursor-not-allowed opacity-50' : ''}
           {validationError
      ? 'border-negative focus-within:border-negative focus-within:ring-negative/20'
      : ''}"
  >
    <div class="flex flex-wrap items-center gap-1.5">
      <!-- Existing tags -->
      {#each value as tag (tag)}
        <div
          class="group bg-subtle hover:border-dimmer hover:bg-hover-subtle inline-flex items-center gap-1.5 rounded-md
                 border border-transparent px-2.5 py-1
                 transition-all duration-150 ease-out"
          animate:flip={{ duration: 200 }}
          in:scale={{ duration: 150 }}
          out:scale={{ duration: 150 }}
        >
          <Icon class="text-muted h-3 w-3" />
          <span class="text-default max-w-[200px] truncate font-mono text-sm" title={tag}>
            {tag}
          </span>
          {#if !disabled}
            <button
              type="button"
              onclick={() => removeTag(tag)}
              class="text-muted hover:bg-negative/10 hover:text-negative rounded p-0.5
                     opacity-0 transition-all
                     duration-150 ease-out group-hover:opacity-100"
              aria-label="Remove {tag}"
            >
              <X class="h-3 w-3" />
            </button>
          {/if}
        </div>
      {/each}

      <!-- Input field -->
      <div class="min-w-[150px] flex-1">
        <input
          bind:this={inputElement}
          bind:value={inputValue}
          onkeydown={handleKeydown}
          onblur={() => {
            if (inputValue.trim()) addTag();
          }}
          {placeholder}
          {disabled}
          class="text-default placeholder:text-muted w-full bg-transparent text-sm
                 focus:outline-none disabled:cursor-not-allowed"
        />
      </div>

      <!-- Add button -->
      {#if inputValue.trim()}
        <button
          type="button"
          onclick={addTag}
          class="text-muted hover:bg-accent-default/10 hover:text-accent-default rounded-md p-1.5 transition-colors"
          aria-label="Add tag"
        >
          <Plus class="h-4 w-4" />
        </button>
      {/if}
    </div>
  </div>

  <!-- Validation error -->
  {#if validationError}
    <p
      class="text-negative flex items-center gap-1.5 text-xs"
      transition:fly={{ y: -4, duration: 150 }}
    >
      <AlertCircle class="h-3.5 w-3.5 flex-shrink-0" />
      <span>{validationError}</span>
    </p>
  {/if}

  <!-- Quick-add buttons -->
  {#if !disabled && quickAddOptions.length > 0}
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-muted text-xs">{m.api_keys_tag_quick_add()}</span>
      {#each quickAddOptions as opt (opt.pattern)}
        <button
          type="button"
          onclick={() => addQuickPattern(opt.pattern)}
          disabled={value.includes(opt.pattern)}
          class="border-dimmer text-muted hover:border-accent-default/60 hover:bg-accent-default/5 hover:text-accent-default inline-flex items-center
                 gap-1 rounded-md border border-dashed
                 px-2 py-1 text-xs
                 transition-all duration-150 ease-out
                 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
        >
          <Plus class="h-3 w-3" />
          {opt.label}
        </button>
      {/each}
    </div>
  {/if}
</div>
