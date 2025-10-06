<script lang="ts">
  import { Select } from "@intric/ui";
  import { availableLanguages, type Language } from "../core/language";
  import { getLanguageStore } from "../core/language";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  
  const currentLanguage = getLanguageStore();
  
  // Language display names
  const languageLabels: Record<Language, string> = {
    sv: m.swedish(),
    en: m.english()
  };
  
  const selected = writable<{ label: string; value: Language }>({
    label: languageLabels[$currentLanguage],
    value: $currentLanguage
  });
  
  $: $currentLanguage = $selected.value;
</script>

<Select.Root customStore={selected}>
  <div class="sr-only">
    <Select.Label>{m.language()}</Select.Label>
  </div>
  <Select.Trigger placeholder={m.language()}></Select.Trigger>
  <Select.Options>
    {#each availableLanguages as language (language)}
      <Select.Item value={language} label={languageLabels[language]}></Select.Item>
    {/each}
  </Select.Options>
</Select.Root>