<script lang="ts">
  import { Button, Dropdown } from "@intric/ui";
  import SwedishFlag from "./SwedishFlag.svelte";
  import { IconChevronUpDown } from "@intric/icons/chevron-up-down";
  import { m } from "$lib/paraglide/messages";

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
      alert(`Language ${lang} is not available.`);
    }
    selectedLanguage = lang as Language;
  }
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <Button
      is={trigger}
      disabled={false}
      padding="icon"
      unstyled
      class="border-default hover:bg-hover-default flex items-center  gap-1 rounded-lg p-2 pr-1"
    >
      <svelte:component this={availableLanguages[selectedLanguage].flag}></svelte:component>
      <IconChevronUpDown></IconChevronUpDown>
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    {#each Object.entries(availableLanguages) as [language, { flag, label }] (language)}
      <Button
        is={item}
        on:click={() => {
          setLanguage(language);
        }}
        class="flex justify-between gap-2"
      >
        {label}

        <svelte:component this={flag}></svelte:component>
      </Button>
    {/each}
  </Dropdown.Menu>
</Dropdown.Root>
