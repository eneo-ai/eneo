<script lang="ts">
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import SwedishFlag from "./SwedishFlag.svelte";
  import { IconChevronUpDown } from "@eneo/icons/chevron-up-down";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";

  const availableLanguages = {
    sv: {
      flag: SwedishFlag,
      label: m.swedish()
    }
  } as const;

  type Language = keyof typeof availableLanguages;
  let selectedLanguage: Language = "sv";
  function setLanguage(lang: string) {
    if (!Object.hasOwn(availableLanguages, lang)) {
      toast.warning(`Language ${lang} is not available.`);
    }
    selectedLanguage = lang as Language;
  }
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        type="button"
        aria-label={m.language()}
        class="border-default hover:bg-hover-default flex cursor-pointer items-center gap-1 rounded-lg p-2 pr-1"
      >
        <svelte:component this={availableLanguages[selectedLanguage].flag}></svelte:component>
        <IconChevronUpDown></IconChevronUpDown>
      </button>
    {/snippet}
  </DropdownMenu.Trigger>
  <DropdownMenu.Content align="end">
    {#each Object.entries(availableLanguages) as [language, { flag, label }] (language)}
      <DropdownMenu.Item
        onSelect={() => {
          setLanguage(language);
        }}
        class="justify-between gap-2"
      >
        {label}

        <svelte:component this={flag}></svelte:component>
      </DropdownMenu.Item>
    {/each}
  </DropdownMenu.Content>
</DropdownMenu.Root>
