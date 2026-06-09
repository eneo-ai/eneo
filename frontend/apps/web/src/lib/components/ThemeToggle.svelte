<script lang="ts">
  import { Monitor, Sun, Moon } from "lucide-svelte";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { cn } from "$lib/utils";
  import { getThemeStore, type Theme } from "$lib/core/theme";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    menu?: boolean;
  }

  const { menu = false }: Props = $props();
  const theme = getThemeStore();

  const options: { value: Theme; label: string; Icon: typeof Monitor }[] = [
    { value: "system", label: m.system(), Icon: Monitor },
    { value: "light", label: m.light(), Icon: Sun },
    { value: "dark", label: m.dark(), Icon: Moon }
  ];
</script>

{#if menu}
  <DropdownMenu.RadioGroup
    value={$theme}
    onValueChange={(value) => theme.set(value as Theme)}
    aria-label={m.select_colour_scheme()}
    class="bg-muted inline-flex items-center gap-0.5 rounded-lg p-0.5"
  >
    {#each options as { value, label, Icon } (value)}
      <DropdownMenu.RadioItem
        {value}
        closeOnSelect={false}
        aria-label={label}
        title={label}
        class={cn(
          "text-muted-foreground hover:text-foreground inline-flex size-7 cursor-pointer items-center justify-center rounded-md p-0 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-current [&_[data-slot=dropdown-menu-radio-item-indicator]]:hidden [&_svg]:size-4",
          $theme === value && "bg-background text-foreground shadow-sm"
        )}
      >
        <Icon aria-hidden="true" />
      </DropdownMenu.RadioItem>
    {/each}
  </DropdownMenu.RadioGroup>
{:else}
  <div
    role="radiogroup"
    aria-label={m.select_colour_scheme()}
    class="bg-muted inline-flex items-center gap-0.5 rounded-lg p-0.5"
  >
    {#each options as { value, label, Icon } (value)}
      <button
        type="button"
        role="radio"
        aria-checked={$theme === value}
        aria-label={label}
        title={label}
        onclick={() => theme.set(value)}
        class={cn(
          "text-muted-foreground hover:text-foreground inline-flex size-7 items-center justify-center rounded-md transition-colors outline-none focus-visible:ring-2 focus-visible:ring-current [&_svg]:size-4",
          $theme === value && "bg-background text-foreground shadow-sm"
        )}
      >
        <Icon aria-hidden="true" />
      </button>
    {/each}
  </div>
{/if}
