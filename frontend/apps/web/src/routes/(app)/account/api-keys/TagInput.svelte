<script lang="ts">
  import { X, Plus, Globe, Server, AlertCircle } from "lucide-svelte";
  import { fly, scale } from "svelte/transition";
  import { flip } from "svelte/animate";

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

  // Quick-add patterns for origins
  const originQuickAdd = [
    { label: "localhost", pattern: "http://localhost:*" },
    { label: "HTTPS wildcard", pattern: "https://*" }
  ];

  // Quick-add patterns for IPs
  const ipQuickAdd = [
    { label: "Private (10.x)", pattern: "10.0.0.0/8" },
    { label: "Private (192.168.x)", pattern: "192.168.0.0/16" }
  ];

  const quickAddOptions = $derived(type === "origin" ? originQuickAdd : ipQuickAdd);

  // Validate origin URL pattern
  function validateOrigin(val: string): string | null {
    // Allow wildcard patterns
    if (val.includes("*")) {
      // Check if it's a valid wildcard pattern
      if (!/^https?:\/\/(\*|[\w.-]+\*?|\*\.[\w.-]+)(:\d+|\:\*)?$/.test(val)) {
        return "Invalid wildcard pattern. Use format: https://*.example.com or http://localhost:*";
      }
      return null;
    }

    // Check if it's a valid URL
    try {
      new URL(val);
      return null;
    } catch {
      return "Invalid URL format. Include protocol (e.g., https://example.com)";
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
          return "Invalid IP address: octets must be 0-255";
        }
        if (cidr && (Number(cidr) < 0 || Number(cidr) > 32)) {
          return "Invalid CIDR: must be 0-32 for IPv4";
        }
      }
      return null;
    }

    return "Invalid format. Use CIDR notation (e.g., 192.168.1.0/24) or single IP";
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
      validationError = "This value is already added";
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
    value = value.filter((t) => t !== tagToRemove);
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
    <label class="block text-sm font-medium text-default">
      {label}
      {#if required}
        <span class="text-negative">*</span>
      {/if}
    </label>
  {/if}
  {#if description}
    <p class="text-xs text-muted">{description}</p>
  {/if}

  <!-- Tags container -->
  <div
    class="min-h-[2.75rem] rounded-lg border border-default bg-primary p-2
           transition-all duration-150 ease-out
           focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20
           {disabled ? 'opacity-50 cursor-not-allowed' : ''}
           {validationError ? 'border-negative focus-within:border-negative focus-within:ring-negative/20' : ''}"
  >
    <div class="flex flex-wrap items-center gap-1.5">
      <!-- Existing tags -->
      {#each value as tag (tag)}
        <div
          class="group inline-flex items-center gap-1.5 rounded-md bg-subtle px-2.5 py-1
                 border border-transparent hover:border-dimmer hover:bg-hover-subtle
                 transition-all duration-150 ease-out"
          animate:flip={{ duration: 200 }}
          in:scale={{ duration: 150 }}
          out:scale={{ duration: 150 }}
        >
          <svelte:component this={Icon} class="h-3 w-3 text-muted" />
          <span class="text-sm font-mono text-default max-w-[200px] truncate" title={tag}>
            {tag}
          </span>
          {#if !disabled}
            <button
              type="button"
              onclick={() => removeTag(tag)}
              class="rounded p-0.5 text-muted opacity-0 group-hover:opacity-100
                     hover:bg-negative/10 hover:text-negative
                     transition-all duration-150 ease-out"
              aria-label="Remove {tag}"
            >
              <X class="h-3 w-3" />
            </button>
          {/if}
        </div>
      {/each}

      <!-- Input field -->
      <div class="flex-1 min-w-[150px]">
        <input
          bind:this={inputElement}
          bind:value={inputValue}
          onkeydown={handleKeydown}
          onblur={() => {
            if (inputValue.trim()) addTag();
          }}
          {placeholder}
          {disabled}
          class="w-full bg-transparent text-sm text-default placeholder:text-muted
                 focus:outline-none disabled:cursor-not-allowed"
        />
      </div>

      <!-- Add button -->
      {#if inputValue.trim()}
        <button
          type="button"
          onclick={addTag}
          class="rounded-md p-1.5 text-muted hover:bg-accent-default/10 hover:text-accent-default transition-colors"
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
      class="flex items-center gap-1.5 text-xs text-negative"
      transition:fly={{ y: -4, duration: 150 }}
    >
      <AlertCircle class="h-3.5 w-3.5 flex-shrink-0" />
      <span>{validationError}</span>
    </p>
  {/if}

  <!-- Quick-add buttons -->
  {#if !disabled && quickAddOptions.length > 0}
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-xs text-muted">Quick add:</span>
      {#each quickAddOptions as opt}
        <button
          type="button"
          onclick={() => addQuickPattern(opt.pattern)}
          disabled={value.includes(opt.pattern)}
          class="inline-flex items-center gap-1 rounded-md border border-dashed border-dimmer
                 px-2 py-1 text-xs text-muted
                 hover:border-accent-default/60 hover:bg-accent-default/5 hover:text-accent-default
                 transition-all duration-150 ease-out
                 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
        >
          <Plus class="h-3 w-3" />
          {opt.label}
        </button>
      {/each}
    </div>
  {/if}
</div>
