<script lang="ts">
  import { Monitor, Sun, Moon } from "lucide-svelte";
  import { cn } from "$lib/utils";
  import { getThemeStore, type Theme } from "$lib/core/theme";
  import { m } from "$lib/paraglide/messages";

  const theme = getThemeStore();

  const options: { value: Theme; label: string; Icon: typeof Monitor }[] = [
    { value: "system", label: m.system(), Icon: Monitor },
    { value: "light", label: m.light(), Icon: Sun },
    { value: "dark", label: m.dark(), Icon: Moon }
  ];
</script>

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
        "text-muted-foreground hover:text-foreground inline-flex size-7 items-center justify-center rounded-md transition-colors [&_svg]:size-4",
        $theme === value && "bg-background text-foreground shadow-sm"
      )}
    >
      <Icon aria-hidden="true" />
    </button>
  {/each}
</div>
